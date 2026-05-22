"""Misc helpers used by the scanner: entropy scoring, redaction, snippet
trimming, AST-based suspicious-import + eval/exec detection."""
from __future__ import annotations

import ast
import math

from .patterns import SUSPICIOUS_IMPORTS, IMPORT_CATEGORIES


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((count / n) * math.log2(count / n) for count in freq.values())


def redact(s: str, keep: int = 4) -> str:
    """Mask the middle of a string, keeping `keep` chars at each end."""
    if not s:
        return s
    s = s.strip()
    if len(s) <= keep * 2 + 3:
        return "***"
    return s[:keep] + "*" * (len(s) - keep * 2) + s[-keep:]


def trim_snippet(text: str, max_bytes: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_bytes:
        return t
    return t[: max_bytes - 1] + "…"


def ast_scan(code_str: str) -> list[dict]:
    """Return findings for suspicious imports + eval/exec/compile calls in
    `code_str`. Empty list when the code doesn't parse or contains none."""
    findings: list[dict] = []
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                mods = [node.module] if node.module else []
            for mod in mods:
                if not mod:
                    continue
                top = mod.split(".")[0]
                matched = (mod if mod in SUSPICIOUS_IMPORTS
                           else (top if top in SUSPICIOUS_IMPORTS else None))
                if matched:
                    cat = IMPORT_CATEGORIES.get(matched, "suspicious_import")
                    findings.append({
                        "finding_type": "import",
                        "category": cat,
                        "severity": "high",
                        "message": f"Import of suspicious module: {mod}",
                        "line": getattr(node, "lineno", 0),
                    })
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Name)
                    and node.func.id in ("eval", "exec", "compile")):
                findings.append({
                    "finding_type": "dynamic_exec",
                    "category": "dynamic_code_execution",
                    "severity": "critical",
                    "message": f"{node.func.id}() call — dynamic code execution",
                    "line": node.lineno,
                })
    return findings


SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def meets_severity(sev: str, min_sev: str) -> bool:
    """True when `sev` is >= `min_sev` in the severity ordering."""
    try:
        min_idx = SEVERITY_ORDER.index(min_sev.lower())
    except ValueError:
        min_idx = 0
    try:
        return SEVERITY_ORDER.index(sev) >= min_idx
    except ValueError:
        return True
