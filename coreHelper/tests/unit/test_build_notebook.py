from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

from fabric_core.build_notebook import (
    NotebookBuildSpec,
    _code,
    _load_version,
    _md,
    _slug,
    write_notebook,
)


def _read_notebook(path: Path):
    with path.open(encoding="utf-8") as fp:
        return nbformat.read(fp, as_version=4)


def test_md_builds_markdown_payload() -> None:
    assert _md("# Title") == {"kind": "md", "text": "# Title"}


def test_code_builds_code_payload() -> None:
    assert _code("print('hello')") == {"kind": "code", "text": "print('hello')"}


def test_slug_lowercases_words_and_numbers() -> None:
    assert _slug("Fabric Scanner v2") == "fabric-scanner-v2"


def test_slug_strips_special_characters() -> None:
    assert _slug(" Fabric! Scanner@#$ v2? ") == "fabric-scanner-v2"


def test_slug_collapses_hyphen_runs() -> None:
    assert _slug("Fabric---Scanner___v2") == "fabric-scanner-v2"


def test_load_version_reads_dunder_version(tmp_path: Path) -> None:
    version_file = tmp_path / "_version.py"
    version_file.write_text('__version__ = "1.2.3"\n', encoding="utf-8")

    assert _load_version(version_file) == "1.2.3"


def test_load_version_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_version(tmp_path / "missing_version.py")


def test_load_version_raises_for_missing_dunder_version(tmp_path: Path) -> None:
    version_file = tmp_path / "_version.py"
    version_file.write_text('VERSION = "1.2.3"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="__version__"):
        _load_version(version_file)


def test_notebook_build_spec_defaults() -> None:
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version="0.4.0",
        cells=[],
        output_path="scanner.ipynb",
    )

    assert spec.kernel_name == "python3"
    assert spec.language_name == "python"
    assert spec.metadata == {}


def test_notebook_build_spec_requires_fields() -> None:
    with pytest.raises(TypeError):
        NotebookBuildSpec()  # type: ignore[call-arg]


def test_write_notebook_creates_parent_directories(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "notebooks" / "fabric_scanner.ipynb"
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version="0.4.0",
        cells=[_md("# Fabric Scanner")],
        output_path=output_path,
    )

    result = write_notebook(spec)

    assert result == output_path
    assert output_path.exists()


def test_write_notebook_writes_valid_ipynb(tmp_path: Path) -> None:
    output_path = tmp_path / "fabric_scanner.ipynb"
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version="0.4.0",
        cells=[_md("# Fabric Scanner"), _code("print('scan')")],
        output_path=output_path,
    )

    write_notebook(spec)
    notebook = _read_notebook(output_path)

    nbformat.validate(notebook)
    assert notebook.nbformat == 4
    assert notebook.cells[0].cell_type == "markdown"
    assert notebook.cells[1].cell_type == "code"


def test_write_notebook_writes_expected_cell_content(tmp_path: Path) -> None:
    output_path = tmp_path / "fabric_downloader.ipynb"
    spec = NotebookBuildSpec(
        package_name="fabric-downloader",
        version="0.2.0",
        cells=[_md("# Fabric Downloader"), _code("from fabric_downloader import run")],
        output_path=output_path,
    )

    write_notebook(spec)
    notebook = _read_notebook(output_path)

    assert notebook.cells[0].source == "# Fabric Downloader"
    assert notebook.cells[1].source == "from fabric_downloader import run"
    assert notebook.cells[1].execution_count is None
    assert notebook.cells[1].outputs == []


def test_write_notebook_writes_kernel_and_version_metadata(tmp_path: Path) -> None:
    output_path = tmp_path / "fabric_scanner.ipynb"
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version="0.4.0",
        cells=[],
        output_path=output_path,
        kernel_name="synapse_pyspark",
        language_name="Python",
    )

    write_notebook(spec)
    notebook = _read_notebook(output_path)

    assert notebook.metadata.kernelspec.name == "synapse_pyspark"
    assert notebook.metadata.kernelspec.display_name == "synapse_pyspark"
    assert notebook.metadata.kernelspec.language == "Python"
    assert notebook.metadata.language_info.name == "Python"
    assert notebook.metadata.fabric_scanner_version == "0.4.0"


def test_write_notebook_preserves_extra_metadata(tmp_path: Path) -> None:
    output_path = tmp_path / "fabric_scanner.ipynb"
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version="0.4.0",
        cells=[],
        output_path=output_path,
        metadata={"fabric": {"workspace": "demo"}},
    )

    write_notebook(spec)
    notebook = _read_notebook(output_path)

    assert notebook.metadata.fabric == {"workspace": "demo"}
