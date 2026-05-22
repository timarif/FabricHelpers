"""Notebook content extraction.

Two public entry points:
    extract_blocks(content_bytes, file_path, include_md_and_outputs=True)
        -> list of (text, cell_index, source_kind, part_path)
    extract_attached_lakehouse(content_bytes, file_label)
        -> dict with the four attached_lakehouse_* keys (any may be None)

Handles plain `.py` / `.md` / `.ipynb`, Fabric Item JSON with
`definition.parts` (base64-encoded payloads), Fabric Item JSON with
`properties.cells` / `properties.metadata`, and the Fabric notebook
source-export `.py` format with `# META { ... # META }` blocks and
`# CELL ********************` / `# MARKDOWN ********************`
separators.
"""
from __future__ import annotations

import base64
import json
from typing import Iterable


_FABRIC_PY_HEADER     = "# Fabric notebook source"
_FABRIC_PY_META_LINE  = "# META"           # may be followed by space + JSON
_FABRIC_PY_METADATA   = "# METADATA ****"
_FABRIC_PY_CELL       = "# CELL ****"
_FABRIC_PY_MARKDOWN   = "# MARKDOWN ****"


def _is_fabric_py_source(text: str) -> bool:
    """Detect the Fabric notebook source-export format.

    Heuristic: file begins with the Fabric header, OR contains both
    a '# METADATA ****' separator and at least one '# META {' line.
    """
    if not text:
        return False
    head = text.lstrip()
    if head.startswith(_FABRIC_PY_HEADER):
        return True
    if _FABRIC_PY_METADATA in text and "# META {" in text:
        return True
    return False


def _decode_meta_block(lines: list[str], start: int) -> tuple[dict | None, int]:
    """Starting at lines[start], consume consecutive '# META' lines and
    decode their stripped contents as a JSON object.

    Returns (parsed dict or None, index just past the last consumed line).
    Non-'# META' lines and JSON parse failures both return None.
    """
    collected: list[str] = []
    i = start
    while i < len(lines):
        s = lines[i]
        # Match '# META ' (with payload) or bare '# META' (blank line in JSON).
        if s.startswith(_FABRIC_PY_META_LINE + " "):
            collected.append(s[len(_FABRIC_PY_META_LINE) + 1:])
        elif s.rstrip() == _FABRIC_PY_META_LINE:
            collected.append("")
        else:
            break
        i += 1
    joined = "\n".join(collected).strip()
    if not joined:
        return None, i
    try:
        obj = json.loads(joined)
    except (json.JSONDecodeError, ValueError):
        return None, i
    return (obj if isinstance(obj, dict) else None), i


def _parse_fabric_py_source(
    text: str,
) -> tuple[dict | None, list[tuple[str, int, str]]]:
    """Parse the Fabric notebook source-export format.

    Returns (notebook_metadata, cells) where each cell is
    (cell_text, cell_index, source_kind). source_kind is 'code' for
    '# CELL ****' blocks and 'markdown' for '# MARKDOWN ****' blocks
    (with leading '# ' line comments stripped from markdown cells).

    Per-cell '# META ...' trailers are consumed and not included in
    the cell text.
    """
    notebook_meta: dict | None = None
    cells: list[tuple[str, int, str]] = []
    lines = text.splitlines()
    n = len(lines)
    i = 0
    cur_lines: list[str] = []
    cur_kind: str | None = None     # 'code' | 'markdown' | None
    cell_idx = -1

    def _flush_cell() -> None:
        nonlocal cur_lines, cur_kind
        if cur_kind is None:
            return
        body = "\n".join(cur_lines).strip("\n")
        if cur_kind == "markdown":
            # Strip the leading "# " comment prefix Fabric adds to
            # each markdown line. Lines that are exactly "#" become blank.
            md_lines = []
            for ln in body.splitlines():
                if ln.startswith("# "):
                    md_lines.append(ln[2:])
                elif ln == "#":
                    md_lines.append("")
                else:
                    md_lines.append(ln)
            body = "\n".join(md_lines)
        cells.append((body, cell_idx, cur_kind))
        cur_lines = []
        cur_kind = None

    while i < n:
        s = lines[i]
        if s.startswith(_FABRIC_PY_METADATA):
            _flush_cell()
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            meta, i = _decode_meta_block(lines, i)
            # First metadata block (before any cell) is the notebook-level meta.
            if notebook_meta is None and not cells and cur_kind is None:
                notebook_meta = meta
            continue
        if s.startswith(_FABRIC_PY_CELL):
            _flush_cell()
            cell_idx += 1
            cur_kind = "code"
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            continue
        if s.startswith(_FABRIC_PY_MARKDOWN):
            _flush_cell()
            cell_idx += 1
            cur_kind = "markdown"
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            continue
        if cur_kind is not None:
            cur_lines.append(s)
        i += 1
    _flush_cell()

    return notebook_meta, cells


def extract_blocks(
    content_bytes: bytes | str,
    file_path: str,
    include_md_and_outputs: bool = True,
) -> list[tuple[str, int, str, str]]:
    """Yield blocks of (text, cell_index, source_kind, part_path).

    source_kind ∈ {"code", "markdown", "output", "raw"}.
    part_path is "" for plain .ipynb / .py inputs; for Fabric Item JSON it is
    the path of the part inside `definition.parts`
    (e.g. "notebook-content.py").
    """
    try:
        if isinstance(content_bytes, (bytes, bytearray)):
            text = content_bytes.decode("utf-8", errors="ignore")
        else:
            text = str(content_bytes)
    except Exception:
        return []

    fp = (file_path or "").lower()
    if fp.endswith(".py"):
        if _is_fabric_py_source(text):
            _, cells = _parse_fabric_py_source(text)
            if cells:
                blocks = []
                for body, idx, kind in cells:
                    if kind == "markdown" and not include_md_and_outputs:
                        continue
                    blocks.append((body, idx, kind, ""))
                return blocks
        return [(text, 0, "code", "")]
    if fp.endswith(".md"):
        return [(text, 0, "markdown", "")]

    if fp.endswith(".ipynb") or fp.endswith(".json") or text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return [(text, 0, "raw", "")]
        if not isinstance(data, dict):
            return [(text, 0, "raw", "")]

        blocks: list[tuple[str, int, str, str]] = []

        if "cells" in data and isinstance(data["cells"], list):
            for i, cell in enumerate(data["cells"]):
                ct = cell.get("cell_type")
                src = cell.get("source", [])
                txt = "".join(src) if isinstance(src, list) else str(src)
                if ct == "code":
                    blocks.append((txt, i, "code", ""))
                elif ct == "markdown" and include_md_and_outputs:
                    blocks.append((txt, i, "markdown", ""))
                if include_md_and_outputs:
                    for out in cell.get("outputs", []) or []:
                        if not isinstance(out, dict):
                            continue
                        t = out.get("text", "")
                        if t:
                            ot = "".join(t) if isinstance(t, list) else str(t)
                            blocks.append((ot, i, "output", ""))
                        data_field = out.get("data") or {}
                        for key, val in data_field.items():
                            if "text" in key.lower():
                                vt = "".join(val) if isinstance(val, list) else str(val)
                                blocks.append((vt, i, "output", ""))
            return blocks

        parts = (data.get("definition") or {}).get("parts") or []
        if parts:
            for i, part in enumerate(parts):
                path = part.get("path", "") or ""
                payload = part.get("payload", "") or ""
                if not payload:
                    continue
                try:
                    decoded = base64.b64decode(payload).decode(
                        "utf-8", errors="ignore")
                except Exception:
                    continue
                if path.endswith(".ipynb"):
                    try:
                        sub = json.loads(decoded)
                    except (json.JSONDecodeError, ValueError):
                        blocks.append((decoded, i, "raw", path))
                        continue
                    for j, cell in enumerate(sub.get("cells", []) or []):
                        ct = cell.get("cell_type")
                        src = cell.get("source", [])
                        txt = "".join(src) if isinstance(src, list) else str(src)
                        if ct == "code":
                            blocks.append((txt, j, "code", path))
                        elif ct == "markdown" and include_md_and_outputs:
                            blocks.append((txt, j, "markdown", path))
                        if include_md_and_outputs:
                            for out in cell.get("outputs", []) or []:
                                if not isinstance(out, dict):
                                    continue
                                t = out.get("text", "")
                                if t:
                                    ot = "".join(t) if isinstance(t, list) else str(t)
                                    blocks.append((ot, j, "output", path))
                elif path.endswith(".py"):
                    if _is_fabric_py_source(decoded):
                        _, sub_cells = _parse_fabric_py_source(decoded)
                        if sub_cells:
                            for body, idx, kind in sub_cells:
                                if kind == "markdown" and not include_md_and_outputs:
                                    continue
                                blocks.append((body, idx, kind, path))
                            continue
                    blocks.append((decoded, i, "code", path))
                elif path.endswith(".md"):
                    if include_md_and_outputs:
                        blocks.append((decoded, i, "markdown", path))
                else:
                    if include_md_and_outputs:
                        blocks.append((decoded, i, "raw", path))
            if blocks:
                return blocks

        cells = (data.get("properties") or {}).get("cells") or []
        if cells:
            for i, cell in enumerate(cells):
                ct = cell.get("cell_type")
                src = cell.get("source", [])
                txt = "".join(src) if isinstance(src, list) else str(src)
                if ct == "code":
                    blocks.append((txt, i, "code", ""))
                elif ct == "markdown" and include_md_and_outputs:
                    blocks.append((txt, i, "markdown", ""))
            return blocks

    return [(text, 0, "raw", "")]


def _from_meta(meta) -> dict | None:
    if not isinstance(meta, dict):
        return None
    deps = meta.get("dependencies")
    if not isinstance(deps, dict):
        return None
    lh = deps.get("lakehouse")
    if not isinstance(lh, dict):
        return None
    lh_id = lh.get("default_lakehouse") or lh.get("default_lakehouse_id")
    lh_name = lh.get("default_lakehouse_name")
    lh_wsid = lh.get("default_lakehouse_workspace_id")
    if not lh_id:
        known = lh.get("known_lakehouses") or []
        if isinstance(known, list) and known and isinstance(known[0], dict):
            lh_id = known[0].get("id") or known[0].get("lakehouse_id")
    if not (lh_id or lh_name or lh_wsid):
        return None
    return {
        "attached_lakehouse_id": lh_id or None,
        "attached_lakehouse_name": lh_name or None,
        "attached_lakehouse_workspace_id": lh_wsid or None,
        "attached_lakehouse_workspace_name": None,
    }


def extract_attached_lakehouse(
    content_bytes: bytes | str,
    file_label: str,
) -> dict:
    """Return the notebook's attached/default Lakehouse from metadata.

    Inspects `metadata.dependencies.lakehouse` for plain .ipynb, then
    Fabric Item JSON variants (definition.parts, properties.metadata).
    Keys that cannot be determined come back as None.
    """
    empty = {
        "attached_lakehouse_id": None,
        "attached_lakehouse_name": None,
        "attached_lakehouse_workspace_id": None,
        "attached_lakehouse_workspace_name": None,
    }
    try:
        if isinstance(content_bytes, (bytes, bytearray)):
            text = content_bytes.decode("utf-8", errors="ignore")
        else:
            text = str(content_bytes)
    except Exception:
        return dict(empty)

    fp = (file_label or "").lower()
    if fp.endswith(".md"):
        return dict(empty)
    if fp.endswith(".py") or (not fp.endswith(".ipynb") and not fp.endswith(".json")
                              and _is_fabric_py_source(text)):
        if _is_fabric_py_source(text):
            nb_meta, _ = _parse_fabric_py_source(text)
            result = _from_meta(nb_meta)
            if result:
                return result
        return dict(empty)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return dict(empty)
    if not isinstance(data, dict):
        return dict(empty)

    result = _from_meta(data.get("metadata"))
    if result:
        return result

    parts = (data.get("definition") or {}).get("parts") or []
    for part in parts:
        path = part.get("path", "") or ""
        payload = part.get("payload", "") or ""
        if not payload:
            continue
        try:
            decoded = base64.b64decode(payload).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if path.endswith(".ipynb"):
            try:
                sub = json.loads(decoded)
            except Exception:
                continue
            result = _from_meta(sub.get("metadata"))
            if result:
                return result
        elif path.endswith(".py") and _is_fabric_py_source(decoded):
            nb_meta, _ = _parse_fabric_py_source(decoded)
            result = _from_meta(nb_meta)
            if result:
                return result

    props = data.get("properties")
    if isinstance(props, dict):
        result = _from_meta(props.get("metadata"))
        if result:
            return result

    return dict(empty)
