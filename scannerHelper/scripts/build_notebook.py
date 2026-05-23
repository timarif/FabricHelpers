"""Generate the thin v2 Fabric Scanner orchestration notebook."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from fabric_core.build_notebook import (
    NotebookBuildSpec,
    _load_version,
    write_notebook,
)
from fabric_core.build_notebook import (
    _code as _core_code,
)
from fabric_core.build_notebook import (
    _md as _core_md,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "notebooks" / "fabric_scanner_v2.ipynb"
__version__ = _load_version(REPO_ROOT / "src" / "fabric_scanner" / "_version.py")


def _md(*lines: str) -> dict[str, str]:
    return _core_md("\n".join(lines))


def _code(*lines: str) -> dict[str, str]:
    return _core_code("\n".join(lines))


def cells(version: str) -> list[dict[str, str]]:
    return [
        _md(
            "# Fabric Notebook Scanner v2",
            "",
            f"_Thin orchestrator over `fabric-scanner=={version}`._",
            "",
            "Five cells:",
            "1. **Install** the scanner wheel.",
            "2. **Configure** the scan (the only cell most users touch).",
            "3. **Probe** the source — sanity-check paths or endpoints.",
            "4. **Run** the scan — produces the inventory and findings Delta tables.",
            "5. **Explore** the findings — display the top rollups.",
            "",
            "All scanner logic lives in the installable wheel; edits to detection",
            "patterns or schema happen there, not in this notebook.",
        ),
        _code(
            "# Install the scanner wheel (re-run when you bump the version).",
            f"%pip install -q fabric-scanner=={version}",
        ),
        _md(
            "## 1. Configuration",
            "",
            "`ScannerConfig` is a frozen dataclass — every knob has a sensible",
            "default. The most common edits are commented inline below.",
        ),
        _code(
            "from fabric_scanner import ScannerConfig",
            "",
            "cfg = ScannerConfig(",
            "    # --- Where to read notebooks from ---",
            "    source_mode      = \"lakehouse\",   # or \"api\" for tenant scan",
            "    source_layout    = \"flat\",        # or \"ws_dated\"",
            "    source_subpath   = \"Files/notebooks\",",
            "    source_file_glob = \"*.ipynb\",",
            "    # Leave source_lakehouse_* blank to auto-detect the mounted",
            "    # default lakehouse (recommended). Set explicitly to scan a",
            "    # different LH the notebook isn't attached to.",
            "    # source_lakehouse_workspace_id = \"<ws-guid>\",",
            "    # source_lakehouse_id           = \"<lh-guid>\",",
            "",
            "    # --- Where to write outputs ---",
            "    write_to_default_lakehouse = True,   # saveAsTable on attached LH",
            "    # write_workspace_id = \"<ws-guid>\",",
            "    # write_lakehouse_id = \"<lh-guid>\",",
            "    inventory_table = \"v2_inventory\",",
            "    output_table    = \"v2_findings\",",
            "",
            "    # --- Behavior ---",
            "    min_severity              = \"low\",",
            "    scan_markdown_and_outputs = True,",
            "    target_partition_size     = 200,",
            ")",
            "cfg",
        ),
        _md(
            "## 2. Diagnostics — probe paths / endpoints",
            "",
            "Prints a one-screen summary of what the scanner *will* read.",
            "Safe to run before kicking off the actual scan.",
        ),
        _code("from fabric_scanner import resolve_paths, probe", "", "resolved = resolve_paths(cfg)", "probe(cfg, resolved)"),
        _md(
            "## 3. Run the scan",
            "",
            "Builds the inventory, fans out the partition scanners, writes",
            "the inventory + findings Delta tables, and returns a",
            "`ScannerResult` with summary stats and the 10 rollup DataFrames.",
        ),
        _code(
            "from fabric_scanner.spark import run",
            "",
            "result = run(cfg, spark)",
            "",
            "print(f\"Notebooks scanned : {result.notebook_count:,}\")",
            "print(f\"Findings rows     : {result.findings_count:,}\")",
            "print(f\"Inventory table   : {result.inventory_table}\")",
            "print(f\"Findings table    : {result.findings_table}\")",
            "print()",
            "print(\"By severity:\")",
            "for sev, n in sorted(result.by_severity.items()):",
            "    print(f\"  {sev:10s}  {n:>6,}\")",
        ),
        _md(
            "## 4. Explore the findings",
            "",
            "Each rollup is a regular Spark DataFrame — display, filter, or",
            "join as you like. See `fabric_scanner.persist.SummaryReport`",
            "for the full list.",
        ),
        _code("display(result.summary.by_severity)"),
        _code("display(result.summary.review_queue)"),
        _code("display(result.summary.cross_workspace_flows)"),
        _code("display(result.summary.sample_critical)"),
    ]


def _source_text(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def _cell_id(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


def _normalize_for_stable_diff(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    ordered_cells = []
    for cell in notebook["cells"]:
        source = _source_text(cell)
        if cell["cell_type"] == "markdown":
            ordered_cells.append({
                "cell_type": "markdown", "metadata": {}, "source": source, "id": _cell_id(source)
            })
        else:
            ordered_cells.append({
                "cell_type": "code", "metadata": {}, "execution_count": None,
                "outputs": [], "source": source, "id": _cell_id(source)
            })
    stable = {
        "cells": ordered_cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Synapse PySpark",
                "language": "Python",
                "name": "synapse_pyspark",
            },
            "language_info": {"name": "python"},
            "fabric_scanner_version": notebook["metadata"]["fabric_scanner_version"],
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(stable, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--version", default=None, help="override the pinned scanner version")
    parser.add_argument("--target", choices=("v2", "all"), default="v2")
    args = parser.parse_args(argv)

    version = args.version or __version__
    out = write_notebook(NotebookBuildSpec(
        package_name="fabric-scanner",
        version=version,
        cells=cells(version),
        output_path=args.out,
        kernel_name="synapse_pyspark",
        language_name="python",
        metadata={"kernelspec": {
            "display_name": "Synapse PySpark",
            "language": "Python",
            "name": "synapse_pyspark",
        }},
    ))
    _normalize_for_stable_diff(out)
    print(f"Wrote {out}  (pinned fabric-scanner=={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
