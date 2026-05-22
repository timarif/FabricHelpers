"""Per-row notebook enrichment shared by rule-based and AI scanners.

`enrich_attached_lakehouse(content, path, ws_name_by_id)` runs
`extract_attached_lakehouse` then back-fills the workspace name from a
caller-provided id→name map. Both the rule-based partition function
(`spark.partition.scan_row`) and the AI partition function
(`ai.partition.build_chunk_rows`) call this so the four
`attached_lakehouse_*` columns stay identical across the two output
tables (which is what makes them JOIN-able).
"""
from __future__ import annotations

from collections.abc import Mapping

from .extract import extract_attached_lakehouse


def enrich_attached_lakehouse(
    content: bytes | str,
    file_label: str,
    ws_name_by_id: Mapping[str, str] | None = None,
) -> dict:
    """Return the four `attached_lakehouse_*` columns for one notebook.

    Identical contract to `extract_attached_lakehouse` but additionally
    back-fills `attached_lakehouse_workspace_name` from `ws_name_by_id`
    (which the caller usually already has from the API workspace map).
    Missing values come back as `None`.
    """
    lh = extract_attached_lakehouse(content or b"", file_label or "")
    lh_wsid = lh.get("attached_lakehouse_workspace_id")
    lh_wsname = lh.get("attached_lakehouse_workspace_name")
    if lh_wsid and not lh_wsname and ws_name_by_id:
        lh_wsname = ws_name_by_id.get((lh_wsid or "").lower())
        if lh_wsname:
            lh["attached_lakehouse_workspace_name"] = lh_wsname
    return lh
