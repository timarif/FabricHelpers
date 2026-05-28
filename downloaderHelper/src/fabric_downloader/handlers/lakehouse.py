"""Lakehouse item handler — metadata only.

Lakehouses do not expose a ``getDefinition`` endpoint that returns Delta
data. This module captures metadata only:

- ``lakehouse_metadata.json`` with item envelope + table list summary
- ``tables.json`` with the full paged response merged into one ``value`` list

The tables API does not return column schemas, so schema-level metadata is
out of scope for this handler.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from ..item_types import ItemHandler, register

log = logging.getLogger(__name__)


def fetch_lakehouse_tables(
    *,
    workspace_id: str,
    lakehouse_id: str,
    token: str,
    fabric_base: str,
) -> dict:
    """Fetch and merge all Lakehouse table pages.

    Returns ``{"value": [...]}`` on success.
    Returns ``{"value": []}`` on 404.
    Returns ``{"error": "forbidden"}`` on 403 (with a warning log).
    """
    base_url = (
        f"{fabric_base}/v1/workspaces/{workspace_id}/lakehouses/{lakehouse_id}/tables"
    )
    next_url: str | None = base_url
    merged: list[dict] = []

    while next_url:
        req = urllib.request.Request(
            next_url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"value": []}
            if exc.code == 403:
                log.warning(
                    "Lakehouse tables forbidden for workspace=%s lakehouse=%s",
                    workspace_id,
                    lakehouse_id,
                )
                return {"error": "forbidden"}
            raise

        page = body if isinstance(body, dict) else {}
        merged.extend(page.get("value") or [])
        continuation_token = page.get("continuationToken")
        continuation_uri = page.get("continuationUri")

        if continuation_token:
            query = urllib.parse.urlencode({"continuationToken": continuation_token})
            next_url = f"{base_url}?{query}"
        elif continuation_uri:
            next_url = continuation_uri
        else:
            next_url = None

    return {"value": merged}


@register
class LakehouseHandler(ItemHandler):
    """Handler for Fabric Lakehouse items (metadata-only snapshot)."""

    item_type = "Lakehouse"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        """Serialize the item metadata dict to ``lakehouse_metadata.json``.

        ``definition`` carries tables metadata fetched from the Lakehouse
        tables REST endpoint (not ``getDefinition``).
        """
        tables_payload = (definition or {}).get("tables")
        if not isinstance(tables_payload, dict):
            tables_payload = {"value": []}
        tables = tables_payload.get("value")
        if not isinstance(tables, list):
            tables = []

        payload = {
            "id":          item.get("id", ""),
            "displayName": item.get("displayName") or item.get("name", ""),
            "description": item.get("description", ""),
            "workspaceId": item.get("workspaceId", ""),
            "type":        item.get("type", "Lakehouse"),
            "properties":  item.get("properties") or {},
            "tables":      tables,
        }
        return {
            "lakehouse_metadata.json": json.dumps(payload, indent=2).encode("utf-8"),
            "tables.json": json.dumps(tables_payload, indent=2).encode("utf-8"),
        }
