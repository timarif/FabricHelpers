"""Cross-workspace URL parsing + resolution.

`parse_dest_workspace` extracts a workspace id or name from any of the
ABFSS/Fabric/Power BI URL flavors. `resolve_dest_workspace` cross-references
that against the broadcast workspace-name maps to produce final (id, name,
cross_workspace) for each finding.
"""
from __future__ import annotations

import re

WORKSPACE_URL_RE = re.compile(
    r"(?:"
    r"abfss?://([^@/\s]+)@onelake\.dfs\.fabric\.microsoft\.com"
    r"|https?://[^/\s]*\.fabric\.microsoft\.com/(?:[^?\s]*?/)?(?:v1/)?workspaces/([0-9a-f-]{8,})"
    r"|https?://(?:app|api)\.powerbi\.com/(?:[^/\s]*/)*?groups/([0-9a-f-]{8,})"
    r")",
    re.IGNORECASE,
)
GUID_RE = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$",
    re.IGNORECASE,
)


def parse_dest_workspace(url: str | None) -> str | None:
    """Return the workspace identifier (id or name) referenced by `url`, or
    None when no Fabric/Power BI/ABFSS workspace can be parsed out."""
    if not url:
        return None
    m = WORKSPACE_URL_RE.search(url)
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def resolve_dest_workspace(
    url: str,
    src_ws_id: str,
    src_ws_name: str,
    ws_name_by_id: dict[str, str] | None = None,
    ws_id_by_name: dict[str, str] | None = None,
) -> tuple[str | None, str | None, bool | None]:
    """Map a URL to a destination workspace tuple.

    Returns (dest_workspace_id, dest_workspace_name, is_cross_workspace).
    Any element may be None when the URL doesn't identify a workspace, or
    when name/id resolution is ambiguous. `is_cross_workspace` is a
    tri-state — True/False when both sides are comparable, None when not.
    """
    raw = parse_dest_workspace(url)
    if not raw:
        return None, None, None
    name_map = ws_name_by_id or {}
    id_map = ws_id_by_name or {}
    if GUID_RE.match(raw):
        dest_id = raw.lower()
        dest_name = name_map.get(dest_id, "") or name_map.get(raw, "")
    else:
        dest_name = raw
        dest_id = id_map.get(raw.lower(), "")
    src_id_l = (src_ws_id or "").lower()
    src_name_l = (src_ws_name or "").lower()
    if dest_id and src_id_l and GUID_RE.match(src_id_l or ""):
        cross = (dest_id != src_id_l)
    elif dest_name and src_name_l:
        cross = (dest_name.lower() != src_name_l)
    else:
        cross = None
    return (dest_id or None), (dest_name or None), cross
