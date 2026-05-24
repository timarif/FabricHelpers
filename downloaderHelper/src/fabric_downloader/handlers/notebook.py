"""Notebook item handler.

Supports all four download modes that the existing ``process_definition_body``
layer supports:

- ``"py"``    — save the notebook source as ``<name>__<id>.<lang>``
- ``"txt"``   — save the notebook source as ``<name>__<id>.txt``
- ``"ipynb"`` — save the full Jupyter notebook as ``<name>__<id>.ipynb``
- ``"parts"`` — write every definition part as a separate file
"""
from __future__ import annotations

from ..item_types import (
    ItemHandler,
    _decode_part,
    _parts_from_body,
    generic_parts_to_files,
    register,
)

_NOTEBOOK_SOURCE_EXTS = ("py", "scala", "sql", "r")


@register
class NotebookHandler(ItemHandler):
    """Handler for Fabric Notebook items."""

    item_type = "Notebook"
    default_format = "py"

    def to_files(
        self,
        item: dict,
        definition: dict,
        *,
        notebook_format: str = "py",
    ) -> dict[str, bytes]:
        """Convert a Notebook getDefinition response to saveable files.

        Parameters
        ----------
        notebook_format:
            One of ``"py"``, ``"txt"``, ``"ipynb"``, ``"parts"``.
        """
        parts = _parts_from_body(definition)
        if not parts:
            return {}

        if notebook_format == "ipynb":
            return _ipynb_files(parts)
        if notebook_format in ("py", "txt"):
            return _source_files(parts, notebook_format)
        # "parts" mode — generic fallback
        return generic_parts_to_files(definition)


def _ipynb_files(parts: list[dict]) -> dict[str, bytes]:
    for p in parts:
        ppath = (p.get("path") or "").lower()
        if ppath.endswith(".ipynb"):
            data = _decode_part(p)
            if data:
                return {ppath: data}
    return {}


def _source_files(parts: list[dict], mode: str) -> dict[str, bytes]:
    for p in parts:
        raw = (p.get("path") or "").strip("/")
        basename = raw.rsplit("/", 1)[-1].lower()
        if not basename.startswith("notebook-content."):
            continue
        ext = basename[len("notebook-content."):]
        if not ext or "." in ext or ext not in _NOTEBOOK_SOURCE_EXTS:
            continue
        data = _decode_part(p)
        if not data:
            continue
        out_ext = ext if mode == "py" else "txt"
        return {f"notebook-content.{out_ext}": data}
    return {}
