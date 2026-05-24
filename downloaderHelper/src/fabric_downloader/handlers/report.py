"""Report item handler.

Uses ``POST /v1/workspaces/{ws}/reports/{id}/getDefinition`` to retrieve
the PBIP report definition.  The API returns parts including
``report.json``, ``definition.pbir``, and related resource files.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class ReportHandler(ItemHandler):
    """Handler for Fabric / Power BI Report items (PBIP format)."""

    item_type = "Report"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
