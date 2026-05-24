"""Environment item handler.

Uses ``POST /v1/workspaces/{ws}/environments/{id}/getDefinition`` to
retrieve the Fabric Environment definition.  Parts typically include
``environment.yml`` (library specs) and ``.platform``.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class EnvironmentHandler(ItemHandler):
    """Handler for Fabric Environment items."""

    item_type = "Environment"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
