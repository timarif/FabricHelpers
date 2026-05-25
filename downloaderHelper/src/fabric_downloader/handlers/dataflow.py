"""Dataflow Gen2 item handler.

Uses ``POST /v1/workspaces/{ws}/dataflows/{id}/getDefinition`` to
retrieve the Power Query mashup definition.  Parts typically include
``mashup.pq``, ``queryGroups.json``, and ``.platform``.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class DataflowHandler(ItemHandler):
    """Handler for Fabric Dataflow (Gen2) items."""

    item_type = "Dataflow"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
