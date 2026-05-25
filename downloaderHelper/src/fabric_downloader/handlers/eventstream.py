"""Eventstream item handler.

Uses ``POST /v1/workspaces/{ws}/eventstreams/{id}/getDefinition`` to
retrieve the Eventstream topology definition.  Parts typically include
the topology JSON and metadata files.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class EventstreamHandler(ItemHandler):
    """Handler for Fabric Eventstream items."""

    item_type = "Eventstream"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
