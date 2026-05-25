"""Lakehouse item handler — metadata only.

Lakehouses do not expose a ``getDefinition`` endpoint that returns Delta
data.  This handler saves the item metadata (id, displayName, description,
and any properties) as a single ``lakehouse_metadata.json`` file so the
lakehouse is represented in the backup manifest without attempting to
copy Delta tables.
"""
from __future__ import annotations

import json

from ..item_types import ItemHandler, register


@register
class LakehouseHandler(ItemHandler):
    """Handler for Fabric Lakehouse items (metadata-only snapshot)."""

    item_type = "Lakehouse"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        """Serialize the item metadata dict to ``lakehouse_metadata.json``.

        The ``definition`` argument is ignored — Lakehouses do not have a
        useful ``getDefinition`` payload.  Instead we persist the item
        metadata that came from the enumeration response.
        """
        payload = {
            "id":          item.get("id", ""),
            "displayName": item.get("displayName") or item.get("name", ""),
            "description": item.get("description", ""),
            "workspaceId": item.get("workspaceId", ""),
            "type":        item.get("type", "Lakehouse"),
            "properties":  item.get("properties") or {},
        }
        return {
            "lakehouse_metadata.json": json.dumps(payload, indent=2).encode("utf-8"),
        }
