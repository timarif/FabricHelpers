"""KQLDatabase item handler.

Uses ``POST /v1/workspaces/{ws}/kqlDatabases/{id}/getDefinition`` to
retrieve the KQL database definition.  Parts typically include the
database schema and configuration files.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class KQLDatabaseHandler(ItemHandler):
    """Handler for Fabric KQLDatabase (Eventhouse database) items."""

    item_type = "KQLDatabase"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
