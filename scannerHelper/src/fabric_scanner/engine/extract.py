"""Notebook content extraction.

Two public entry points:
    extract_blocks(content_bytes, file_path, include_md_and_outputs=True)
        -> list of (text, cell_index, source_kind, part_path)
    extract_attached_lakehouse(content_bytes, file_label)
        -> dict with the four attached_lakehouse_* keys (any may be None)

Handles plain `.py` / `.md` / `.ipynb`, Fabric Item JSON with
`definition.parts` (base64-encoded payloads), and Fabric Item JSON with
`properties.cells` / `properties.metadata`.
"""
from __future__ import annotations

import base64
import json
from typing import Iterable


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
    if fp.endswith(".py") or fp.endswith(".md"):
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
        if not payload or not path.endswith(".ipynb"):
            continue
        try:
            decoded = base64.b64decode(payload).decode("utf-8", errors="ignore")
            sub = json.loads(decoded)
        except Exception:
            continue
        result = _from_meta(sub.get("metadata"))
        if result:
            return result

    props = data.get("properties")
    if isinstance(props, dict):
        result = _from_meta(props.get("metadata"))
        if result:
            return result

    return dict(empty)
