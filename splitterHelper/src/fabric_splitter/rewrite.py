"""Cross-workspace reference rewriter.

After items have been moved to different workspaces, certain references must
be patched so they still resolve.  The three canonical cases are:

- ``SemanticModel → Lakehouse``   — the PBISM / model.bim sources reference
  the lakehouse by workspace ID.
- ``Report → SemanticModel``      — the definition.pbir references the
  semantic model's workspace.
- ``DataPipeline → Notebook / Lakehouse`` — activity JSON references their
  workspace IDs.

The rewriter:
1. Fetches the item definition via ``POST /items/{id}/getDefinition``.
2. Base64-decodes each definition part and JSON-parses it.
3. Replaces all occurrences of the old workspace ID with the new one.
4. Re-encodes and pushes back via ``POST /items/{id}/updateDefinition``.

Parts that are not valid JSON are left untouched.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from ._http import FABRIC_BASE, _request

log = logging.getLogger(__name__)

# Item types whose definition parts may contain cross-workspace references.
# Add more types here as the Fabric API documentation expands.
REWRITE_CANDIDATES: frozenset[str] = frozenset(
    {"SemanticModel", "Report", "DataPipeline"}
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_workspace_id(obj: Any, old_id: str, new_id: str) -> Any:
    """Recursively replace *old_id* with *new_id* in any JSON-like structure."""
    if isinstance(obj, dict):
        return {k: _replace_workspace_id(v, old_id, new_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_workspace_id(v, old_id, new_id) for v in obj]
    if isinstance(obj, str):
        return obj.replace(old_id, new_id)
    return obj


_WORKSPACE_ITEM_PATH_RE = re.compile(
    r"(workspaces/)([^/]+)/([^/]+/)([^/?#\"']+)", re.IGNORECASE
)
_ITEM_REFERENCE_KEYS: frozenset[str] = frozenset(
    {
        "artifactId",
        "itemId",
        "lakehouseId",
        "notebookId",
        "semanticModelId",
        "reportId",
        "pipelineId",
    }
)


def _route_reference_targets(
    obj: Any,
    *,
    workspace_id: str,
    item_workspace_map: dict[str, str],
) -> tuple[Any, bool]:
    """Route workspace+item references to the referenced item's workspace."""
    if isinstance(obj, dict):
        changed = False
        routed: dict[str, Any] = {}
        for key, value in obj.items():
            new_value, value_changed = _route_reference_targets(
                value,
                workspace_id=workspace_id,
                item_workspace_map=item_workspace_map,
            )
            routed[key] = new_value
            changed = changed or value_changed

        workspace_value = routed.get("workspaceId")
        if isinstance(workspace_value, str):
            target_workspace = None
            for key in _ITEM_REFERENCE_KEYS:
                item_id = routed.get(key)
                if not isinstance(item_id, str):
                    continue
                candidate_workspace = item_workspace_map.get(item_id)
                if not candidate_workspace:
                    continue
                if target_workspace and target_workspace != candidate_workspace:
                    log.warning(
                        "rewrite: inconsistent workspace routing for workspaceId=%s in keys %s",
                        workspace_value,
                        ", ".join(sorted(_ITEM_REFERENCE_KEYS.intersection(routed))),
                    )
                    continue
                target_workspace = candidate_workspace

            if target_workspace and workspace_value == workspace_id and target_workspace != workspace_value:
                routed["workspaceId"] = target_workspace
                changed = True

        return routed, changed

    if isinstance(obj, list):
        changed = False
        routed_items: list[Any] = []
        for value in obj:
            new_value, value_changed = _route_reference_targets(
                value,
                workspace_id=workspace_id,
                item_workspace_map=item_workspace_map,
            )
            routed_items.append(new_value)
            changed = changed or value_changed
        return routed_items, changed

    if isinstance(obj, str):
        changed = False

        def _replace(match: re.Match[str]) -> str:
            nonlocal changed
            current_workspace = match.group(2)
            item_id = match.group(4)
            target_workspace = item_workspace_map.get(item_id)
            if (
                target_workspace
                and current_workspace == workspace_id
                and target_workspace != current_workspace
            ):
                changed = True
                return f"{match.group(1)}{target_workspace}/{match.group(3)}{item_id}"
            return match.group(0)

        return _WORKSPACE_ITEM_PATH_RE.sub(_replace, obj), changed

    return obj, False


def _patch_part(
    part: dict,
    id_map: dict[str, str],
    *,
    workspace_id: str,
    item_workspace_map: dict[str, str] | None = None,
) -> tuple[dict, bool]:
    """Return a (possibly updated part dict, changed flag)."""
    payload_b64 = part.get("payload")
    if not payload_b64:
        return part, False
    try:
        raw_bytes = base64.b64decode(payload_b64)
        content = json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        return part, False

    new_content = content
    for old_id, new_id in id_map.items():
        new_content = _replace_workspace_id(new_content, old_id, new_id)
    if item_workspace_map:
        new_content, routed_changed = _route_reference_targets(
            new_content,
            workspace_id=workspace_id,
            item_workspace_map=item_workspace_map,
        )
    else:
        routed_changed = False

    if new_content == content and not routed_changed:
        return part, False

    new_payload = base64.b64encode(
        json.dumps(new_content, separators=(",", ":")).encode("utf-8")
    ).decode()
    return {**part, "payload": new_payload}, True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rewrite_references(
    item: dict,
    workspace_id: str,
    id_map: dict[str, str],
    token: str,
    item_workspace_map: dict[str, str] | None = None,
    *,
    fabric_base: str = FABRIC_BASE,
) -> bool:
    """Patch cross-workspace references in *item*'s definition.

    Parameters
    ----------
    item:
        Item metadata dict (must contain ``id`` and ``type`` / ``itemType``).
    workspace_id:
        The workspace where the item currently lives (after the move).
    id_map:
        Mapping ``{old_workspace_id: new_workspace_id}`` for every
        workspace-pair involved in the split.
    token:
        Bearer token.
    fabric_base:
        Fabric REST API base URL (override for testing).

    Returns
    -------
    ``True`` if any definition part was changed and pushed back, else ``False``.
    """
    item_id = item.get("id", "")
    item_type = item.get("type") or item.get("itemType") or ""
    if item_type not in REWRITE_CANDIDATES:
        return False

    # Fetch definition
    try:
        def_resp = _request(
            "POST",
            f"{fabric_base}/v1/workspaces/{workspace_id}/items/{item_id}/getDefinition",
            token,
            body={},
        )
    except Exception as exc:
        log.warning("rewrite: getDefinition failed for %s: %s", item_id, exc)
        return False

    if not def_resp:
        return False
    definition = def_resp.get("definition")
    if not definition:
        return False

    parts: list[dict] = definition.get("parts") or []
    new_parts: list[dict] = []
    any_changed = False

    for part in parts:
        new_part, changed = _patch_part(
            part,
            id_map,
            workspace_id=workspace_id,
            item_workspace_map=item_workspace_map,
        )
        new_parts.append(new_part)
        any_changed = any_changed or changed

    if not any_changed:
        return False

    # Push updated definition
    try:
        _request(
            "POST",
            f"{fabric_base}/v1/workspaces/{workspace_id}"
            f"/items/{item_id}/updateDefinition",
            token,
            body={"definition": {**definition, "parts": new_parts}},
        )
        log.info("Rewrote references in %s (%s)", item_id, item_type)
        return True
    except Exception as exc:
        log.error("rewrite: updateDefinition failed for %s: %s", item_id, exc)
        return False
