"""Reusable helpers for building FabricHelpers orchestration notebooks."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import nbformat


def _deterministic_cell_id(source: str) -> str:
    """Return a stable 12-char SHA-1 prefix derived from the cell source.

    Using a content-based id keeps regenerated notebooks byte-clean against
    git, where nbformat's default random UUID ids would churn on every run.
    """
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]

Cell = dict[str, str]


def _md(text: str) -> Cell:
    """Build a markdown cell payload."""
    return {"kind": "md", "text": text}


def _code(text: str) -> Cell:
    """Build a code cell payload."""
    return {"kind": "code", "text": text}


def _slug(text: str) -> str:
    """Lowercase, alphanumeric + hyphen slug. Used for filename hints."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return re.sub(r"-+", "-", slug).strip("-")


def _load_version(version_file: Union[str, Path]) -> str:  # noqa: UP007
    """Read __version__ from a path to a _version.py file."""
    path = Path(version_file)
    namespace: dict[str, Any] = {}
    exec(path.read_text(encoding="utf-8"), namespace)

    version = namespace.get("__version__")
    if not isinstance(version, str):
        raise ValueError(f"{path} does not define a string __version__")
    return version


@dataclass
class NotebookBuildSpec:
    """All the inputs needed to write one notebook."""

    package_name: str
    version: str
    cells: list[Cell]
    output_path: Union[str, Path]  # noqa: UP007
    kernel_name: str = "python3"
    language_name: str = "python"
    metadata: dict[str, Any] = field(default_factory=dict)


def _version_metadata_key(package_name: str) -> str:
    package_key = _slug(package_name).replace("-", "_") or "package"
    return f"{package_key}_version"


def write_notebook(spec: NotebookBuildSpec) -> Path:
    """Build an nbformat notebook from the spec and write to spec.output_path.

    Returns the output path as a pathlib.Path. Creates parent directories if needed.
    Overwrites existing file.
    """
    cells = []
    for cell in spec.cells:
        kind = cell.get("kind")
        text = cell.get("text", "")
        if kind == "md":
            node = nbformat.v4.new_markdown_cell(text)
        elif kind == "code":
            node = nbformat.v4.new_code_cell(text)
        else:
            raise ValueError(f"Unsupported notebook cell kind: {kind!r}")
        node["id"] = _deterministic_cell_id(text)
        cells.append(node)

    metadata: dict[str, Any] = {
        "kernelspec": {
            "display_name": spec.kernel_name,
            "language": spec.language_name,
            "name": spec.kernel_name,
        },
        "language_info": {"name": spec.language_name},
        _version_metadata_key(spec.package_name): spec.version,
    }
    metadata.update(spec.metadata)

    notebook = nbformat.v4.new_notebook(cells=cells, metadata=metadata)
    nbformat.validate(notebook)

    output_path = Path(spec.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, str(output_path))
    return output_path
