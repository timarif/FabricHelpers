"""Top-level scanner: combines patterns + ast + entropy + write-call detection
over the blocks produced by `extract_blocks`.

The public entry point `scan_notebook_bytes` is the single API consumed by
the thin notebook and by the Spark map-partition partition function. It
takes a `ScannerConfig` so callers can configure severity threshold,
markdown/output inclusion, and snippet size without touching globals.
"""
from __future__ import annotations

import ast
import re

from ..config import ScannerConfig
from .extract import extract_blocks, extract_attached_lakehouse
from .patterns import (
    PATTERNS,
    URL_RE,
    TRAILING_CHARS,
    BENIGN_URL_PATTERNS,
    READ_CONTEXT_RE,
    WRITE_CONTEXT_RE,
    WRITE_CALL_RE,
)
from .utils import (
    ast_scan,
    meets_severity,
    redact,
    shannon_entropy,
    trim_snippet,
)


def _scan_one_block(
    text: str,
    cell_idx: int,
    source_kind: str,
    *,
    min_severity: str,
    max_snippet_bytes: int,
) -> list[dict]:
    findings: list[dict] = []
    if not text or not text.strip():
        return findings
    lines = text.splitlines()
    is_code = (source_kind == "code")

    if is_code:
        for pattern, category, severity, message in PATTERNS:
            if not meets_severity(severity, min_severity):
                continue
            for m in pattern.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                snippet_line = (lines[line_no - 1]
                                if line_no <= len(lines) else "").strip()
                snippet = trim_snippet(snippet_line, max_snippet_bytes)
                if category == "credential_access":
                    snippet = redact(snippet, keep=4)
                findings.append({
                    "finding_type": "pattern",
                    "category": category, "severity": severity,
                    "message": message, "line": line_no,
                    "code_snippet": snippet,
                    "url": None, "direction": None,
                })

    if is_code:
        for f in ast_scan(text):
            if meets_severity(f["severity"], min_severity):
                line = f.get("line", 0)
                snippet_line = (lines[line - 1]
                                if 0 < line <= len(lines) else "").strip()
                f["code_snippet"] = trim_snippet(snippet_line, max_snippet_bytes)
                f["url"] = None
                f["direction"] = None
                findings.append(f)

    seen_urls: set[str] = set()
    url_severity = "medium" if is_code else "low"
    if meets_severity(url_severity, min_severity):
        for m in URL_RE.finditer(text):
            url = m.group("url")
            while url and url[-1] in TRAILING_CHARS:
                url = url[:-1]
            if not url:
                continue
            ul = url.lower().rstrip("/")
            if ul in seen_urls:
                continue
            if any(bp.search(url) for bp in BENIGN_URL_PATTERNS):
                continue
            seen_urls.add(ul)
            if is_code:
                ctx_start = max(0, m.start() - 300)
                ctx = text[ctx_start: m.start()]
                has_read = READ_CONTEXT_RE.search(ctx)
                has_write = WRITE_CONTEXT_RE.search(ctx)
                if has_read and has_write:
                    direction = "read_write"
                elif has_write:
                    direction = "write"
                elif has_read:
                    direction = "read"
                else:
                    direction = "unknown"
            else:
                direction = "reference"
            line_no = text[: m.start()].count("\n") + 1
            snippet_line = (lines[line_no - 1]
                            if line_no <= len(lines) else "").strip()
            findings.append({
                "finding_type": "url",
                "category": "external_url_reference",
                "severity": url_severity,
                "message": (f"External URL/URI [direction: {direction}]: "
                            f"{url[:100]}"),
                "line": line_no,
                "code_snippet": trim_snippet(snippet_line, max_snippet_bytes),
                "url": url, "direction": direction,
            })

    if is_code and meets_severity("high", min_severity):
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    s = node.value
                    if len(s) > 40:
                        ent = shannon_entropy(s)
                        if ent > 4.5 and not s.lstrip().upper().startswith(
                                ("SELECT", "INSERT", "CREATE", "ALTER",
                                 "UPDATE", "DELETE", "MERGE", "WITH")):
                            line = getattr(node, "lineno", 0)
                            findings.append({
                                "finding_type": "entropy",
                                "category": "encoding_obfuscation",
                                "severity": "high",
                                "message": (
                                    f"High-entropy string literal "
                                    f"(entropy={ent:.2f}, len={len(s)})"),
                                "line": line,
                                "code_snippet": trim_snippet(s, max_snippet_bytes),
                                "url": None, "direction": None,
                            })
        except SyntaxError:
            pass

    if is_code and meets_severity("medium", min_severity):
        seen_pw: set[tuple[int, str]] = set()
        for m in WRITE_CALL_RE.finditer(text):
            sig = m.group(0)
            line_no = text[: m.start()].count("\n") + 1
            snippet_line = (lines[line_no - 1]
                            if line_no <= len(lines) else "").strip()
            key = (line_no, sig.strip())
            if key in seen_pw:
                continue
            seen_pw.add(key)
            findings.append({
                "finding_type": "potential_write",
                "category": "potential_write",
                "severity": "medium",
                "message": f"Write-API call detected: {sig.strip()[:60]}",
                "line": line_no,
                "code_snippet": trim_snippet(snippet_line, max_snippet_bytes),
                "url": None, "direction": "potential_write",
            })

    return findings


def scan_notebook_bytes(
    content_bytes: bytes | str,
    file_label: str,
    config: ScannerConfig | None = None,
) -> list[dict]:
    """Top-level driver scan. Returns a list of finding dicts, each annotated
    with cell_index, source_kind, part_path, and attached_lakehouse_*.

    URL findings carry no dest_workspace at this layer (the Spark executor
    adds those via the broadcast workspace map). Same for
    attached_lakehouse_workspace_name.
    """
    cfg = config or ScannerConfig()
    out: list[dict] = []
    lh = extract_attached_lakehouse(content_bytes, file_label)
    for text, cell_idx, source_kind, part_path in extract_blocks(
            content_bytes, file_label, cfg.scan_markdown_and_outputs):
        for f in _scan_one_block(
            text, cell_idx, source_kind,
            min_severity=cfg.min_severity,
            max_snippet_bytes=cfg.max_snippet_bytes,
        ):
            f["cell_index"] = int(cell_idx)
            f["source_kind"] = source_kind
            f["part_path"] = part_path or ""
            f.update(lh)
            out.append(f)
    return out
