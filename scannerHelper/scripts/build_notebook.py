"""Generate the thin v2 orchestration notebook.

Pulls `__version__` from the installed `fabric_scanner` (or the dev
source tree) and emits ``notebooks/fabric_scanner_v2.ipynb`` with the
exact pin baked into the `%pip install` cell.

Why a build script? Two reasons:

  * Keeps the pinned version single-sourced: ``_version.py`` is the
    source of truth, every wheel + every notebook references the same
    string.
  * Notebook JSON is fiddly. Writing nbformat by hand invites stray
    commas, missing IDs, and wrong nbformat_minor values that some
    editors silently round-trip. Doing it through ``nbformat`` (a
    dependency we already pin in ``[dev]``) gives us a validator on
    the way out.

Run from anywhere::

    python scripts/build_notebook.py
    # -> writes scannerHelper/notebooks/fabric_scanner_v2.ipynb

Set ``--out`` to redirect; set ``--version`` to override the pin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = ROOT / "notebooks" / "fabric_scanner_v2.ipynb"


def _load_version() -> str:
    """Read `__version__` straight from the source tree (no install)."""
    src = ROOT / "src" / "fabric_scanner" / "_version.py"
    ns: dict = {}
    exec(src.read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def _md(*lines: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": "\n".join(lines),
    }


def _code(*lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": "\n".join(lines),
    }


def build_notebook(version: str) -> dict:
    """Return an nbformat-4.5 document for the thin v2 notebook."""
    install_cell_src = (
        f"# Install the scanner wheel (re-run when you bump the version).\n"
        f"%pip install -q fabric-scanner=={version}"
    )

    cells = [
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
        _code(install_cell_src),
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
        _code(
            "from fabric_scanner import resolve_paths, probe",
            "",
            "resolved = resolve_paths(cfg)",
            "probe(cfg, resolved)",
        ),
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
        _code(
            "display(result.summary.by_severity)",
        ),
        _code(
            "display(result.summary.review_queue)",
        ),
        _code(
            "display(result.summary.cross_workspace_flows)",
        ),
        _code(
            "display(result.summary.sample_critical)",
        ),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Synapse PySpark",
                "language":     "Python",
                "name":         "synapse_pyspark",
            },
            "language_info": {"name": "python"},
            "fabric_scanner_version": version,
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _slug(text: str) -> str:
    """nbformat 4.5 cell-id: deterministic short hash of the source."""
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"output .ipynb path (default: {DEFAULT_OUT})")
    p.add_argument("--version", type=str, default=None,
                   help="override the pinned scanner version (default: read "
                        "from src/fabric_scanner/_version.py)")
    args = p.parse_args(argv)

    version = args.version or _load_version()

    try:
        import nbformat
    except ImportError:
        nbformat = None  # type: ignore[assignment]

    nb = build_notebook(version)
    for cell in nb["cells"]:
        cell.setdefault("id", _slug(cell["source"]))

    if nbformat is not None:
        nbnode = nbformat.from_dict(nb)
        nbformat.validate(nbnode)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(nbnode, str(args.out))
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(nb, indent=1), encoding="utf-8")

    print(f"Wrote {args.out}  (pinned fabric-scanner=={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
