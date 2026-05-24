"""SparkJobDefinition item handler.

Uses ``POST /v1/workspaces/{ws}/sparkJobDefinitions/{id}/getDefinition``
to retrieve the Spark job definition.  Parts typically include
``SparkJobDefinitionV1.json`` and ``.platform``.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class SparkJobDefinitionHandler(ItemHandler):
    """Handler for Fabric SparkJobDefinition items."""

    item_type = "SparkJobDefinition"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
