"""SemanticModel item handler.

Uses ``POST /v1/workspaces/{ws}/semanticModels/{id}/getDefinition`` to
retrieve the model definition.  The API returns a parts array with files
such as ``model.bim`` (TMSL) or TMDL source files.
"""
from __future__ import annotations

from ..item_types import ItemHandler, generic_parts_to_files, register


@register
class SemanticModelHandler(ItemHandler):
    """Handler for Fabric / Power BI SemanticModel (dataset) items."""

    item_type = "SemanticModel"

    def to_files(self, item: dict, definition: dict) -> dict[str, bytes]:
        return generic_parts_to_files(definition)
