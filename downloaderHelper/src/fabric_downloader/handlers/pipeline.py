"""DataPipeline item handler.

Uses ``POST /v1/workspaces/{ws}/dataPipelines/{id}/getDefinition`` to
retrieve the pipeline definition.  Parts typically include
``pipeline-content.json`` and ``.platform``.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class DataPipelineHandler(ItemHandler):
    """Handler for Fabric DataPipeline items."""

    item_type = "DataPipeline"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
