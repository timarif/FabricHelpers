"""Move items between Fabric workspaces.

Strategy (per item):
1. If the item type is in ``NATIVE_MOVE_SUPPORTED``, call the Fabric native
   ``POST /items/{id}/move`` endpoint.
2. Otherwise fall back to *export-and-recreate*:
   a. ``POST /items/{id}/getDefinition`` from source.
   b. ``POST /items`` in target with the fetched definition.

Every API mutation is appended to a JSON-lines audit log so the run is
fully auditable and a partial split can be manually resumed or rolled back.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import IO

from ._http import FABRIC_BASE, _request

log = logging.getLogger(__name__)

# Item types that support the Fabric native move endpoint.
# Intentionally empty at launch — Microsoft has not published a generic
# /move endpoint as of the initial release of this helper.  Add type
# strings here (exact case, e.g. "Notebook") as the API evolves.
NATIVE_MOVE_SUPPORTED: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _audit(action: str, item: dict, target_workspace_id: str, audit_fh: IO[str]) -> None:
    """Append a JSON-lines record to *audit_fh*."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "itemId": item.get("id"),
        "itemType": item.get("type") or item.get("itemType"),
        "itemName": item.get("displayName") or item.get("name"),
        "targetWorkspaceId": target_workspace_id,
    }
    audit_fh.write(json.dumps(record) + "\n")
    audit_fh.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def move_item(
    item: dict,
    source_workspace_id: str,
    target_workspace_id: str,
    token: str,
    audit_fh: IO[str],
    *,
    fabric_base: str = FABRIC_BASE,
) -> None:
    """Move *item* from *source_workspace_id* to *target_workspace_id*.

    Tries the native Fabric move endpoint first; falls back to
    ``getDefinition → createItem`` for types not yet supported by the
    native endpoint.

    Parameters
    ----------
    item:
        Item metadata dict (must contain ``id`` and ``type`` / ``itemType``).
    source_workspace_id:
        The workspace the item currently lives in.
    target_workspace_id:
        The workspace the item should be moved to.
    token:
        Bearer token.
    audit_fh:
        Open file-like object for the JSON-lines audit log.
    fabric_base:
        Fabric REST API base URL (override for testing).
    """
    item_type = item.get("type") or item.get("itemType") or ""
    if item_type in NATIVE_MOVE_SUPPORTED:
        _native_move(
            item, source_workspace_id, target_workspace_id, token, audit_fh,
            fabric_base=fabric_base,
        )
    else:
        _export_recreate(
            item, source_workspace_id, target_workspace_id, token, audit_fh,
            fabric_base=fabric_base,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _native_move(
    item: dict,
    source_workspace_id: str,
    target_workspace_id: str,
    token: str,
    audit_fh: IO[str],
    *,
    fabric_base: str = FABRIC_BASE,
) -> None:
    item_id = item["id"]
    _request(
        "POST",
        f"{fabric_base}/v1/workspaces/{source_workspace_id}/items/{item_id}/move",
        token,
        body={"targetWorkspaceId": target_workspace_id},
    )
    _audit("native_move", item, target_workspace_id, audit_fh)
    log.info("Moved (native) %s → %s", item_id, target_workspace_id)


def _export_recreate(
    item: dict,
    source_workspace_id: str,
    target_workspace_id: str,
    token: str,
    audit_fh: IO[str],
    *,
    fabric_base: str = FABRIC_BASE,
) -> None:
    """Export item definition from *source_workspace_id*; recreate in *target_workspace_id*."""
    item_id = item["id"]
    item_type = item.get("type") or item.get("itemType") or ""
    display_name = item.get("displayName") or item.get("name") or item_id

    # 1. Fetch definition from source
    try:
        definition_resp = _request(
            "POST",
            f"{fabric_base}/v1/workspaces/{source_workspace_id}"
            f"/items/{item_id}/getDefinition",
            token,
            body={},
        )
    except Exception as exc:
        log.warning(
            "getDefinition failed for %s (%s): %s — skipping", item_id, item_type, exc
        )
        _audit("skip_no_definition", item, target_workspace_id, audit_fh)
        return

    definition = (definition_resp or {}).get("definition") if definition_resp else None

    # 2. Create in target
    create_body: dict = {
        "displayName": display_name,
        "type": item_type,
    }
    if definition:
        create_body["definition"] = definition

    try:
        new_item = _request(
            "POST",
            f"{fabric_base}/v1/workspaces/{target_workspace_id}/items",
            token,
            body=create_body,
        )
        new_item_id = (new_item or {}).get("id", "?")
        _audit("export_recreate", item, target_workspace_id, audit_fh)
        log.info("Recreated %s as %s in %s", item_id, new_item_id, target_workspace_id)
    except Exception as exc:
        log.error("createItem failed for %s: %s", item_id, exc)
        _audit("error_recreate", item, target_workspace_id, audit_fh)
        raise
