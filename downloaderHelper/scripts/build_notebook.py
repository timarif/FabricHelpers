"""Generate the thin v1 orchestration notebook for fabric-downloader.

Pulls `__version__` from the source tree and emits
``notebooks/fabric_downloader_v1.ipynb`` with the exact pin baked into
the `%pip install` cell. Mirrors `scannerHelper/scripts/build_notebook.py`.

Run from anywhere::

    python scripts/build_notebook.py
    # -> writes downloaderHelper/notebooks/fabric_downloader_v1.ipynb
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = ROOT / "notebooks" / "fabric_downloader_v1.ipynb"


def _load_version() -> str:
    """Read `__version__` straight from the source tree (no install)."""
    src = ROOT / "src" / "fabric_downloader" / "_version.py"
    ns: dict = {}
    exec(src.read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def _md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": "\n".join(lines)}


def _code(*lines: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": "\n".join(lines)}


def build_notebook(version: str) -> dict:
    """Return an nbformat-4.5 document for the thin v1 notebook."""
    install_cell_src = (
        f"# Install the downloader wheel (re-run when you bump the version).\n"
        f"%pip install -q fabric-downloader=={version}"
    )

    cells = [
        _md(
            "# Fabric Item Downloader v1",
            "",
            f"_Thin orchestrator over `fabric-downloader=={version}`._",
            "",
            "Five cells:",
            "1. **Install** the downloader wheel.",
            "2. **Configure** the run (the only cell most users touch).",
            "3. **Probe** the resolved write target + (optionally) the API endpoints.",
            "4. **Run** the download — produces files under `Files/<output_root>/<run_label>/`",
            "   and appends one row per item to the manifest Delta table.",
            "5. **Explore** the manifest — display the five rollups.",
            "",
            "All downloader logic lives in the installable wheel; edits to fetch",
            "behavior, schema, or rollups happen there, not in this notebook.",
        ),
        _code(install_cell_src),
        _md(
            "## 1. Configuration",
            "",
            "`DownloaderConfig` is a frozen dataclass — every knob has a",
            "sensible default. The most common edits are commented inline.",
            "",
            "**Multi-type runs**: list every Fabric item type you want backed",
            "up in `item_types`. Default `format_by_type` maps `Notebook` ->",
            "`ipynb` (one self-contained file per notebook); every other type",
            "falls back to parts mode (the API returns every definition part",
            "as a separate file — `.platform`, `pipeline-content.json`,",
            "`mashup.pq`, etc.). Override per-type with `format_by_type` if",
            "you want parts mode for notebooks too.",
        ),
        _code(
            "from fabric_downloader import DownloaderConfig",
            "",
            "cfg = DownloaderConfig(",
            "    # --- What to download ---",
            "    item_types     = (\"Notebook\", \"DataPipeline\", \"Dataflow\"),",
            "    # format_by_type = {\"Notebook\": \"ipynb\"},  # uncomment to override",
            "",
            "    # --- Enumeration scope ---",
            "    admin_mode         = True,   # tenant admin APIs when available",
            "    read_workspace_ids = (),     # () = all visible workspaces",
            "    max_items          = 0,      # 0 = no cap (set to 5 for dry-run)",
            "",
            "    # --- Output ---",
            "    output_root    = \"fabric_item_backups\",",
            "    run_label      = \"\",        # \"\" -> auto yyyy-mm-dd_HH-MM-SS UTC",
            "    manifest_table = \"fabric_download_manifest\",",
            "    skip_existing  = True,       # restart-safe re-runs",
            "    group_by_type  = True,       # subfolder per item type",
            "    include_raw_definition = False,  # also save the .item.json envelope",
            "",
            "    # --- Write target ---",
            "    write_to_default_lakehouse = True,",
            "    # write_workspace_id = \"<ws-guid>\",",
            "    # write_lakehouse_id = \"<lh-guid>\",",
            "",
            "    # --- Spark distribution ---",
            "    num_partitions       = 0,    # 0 -> sc.defaultParallelism",
            "    executor_concurrency = 30,",
            "    max_retries          = 4,",
            ")",
            "cfg",
        ),
        _md(
            "## 2. Diagnostics — probe the resolved target",
            "",
            "Prints the resolved write paths + the planned export mode per",
            "item type. Pass a token to also probe Fabric REST endpoints.",
        ),
        _code(
            "from fabric_downloader import resolve_paths, probe",
            "",
            "resolved = resolve_paths(cfg)",
            "probe(cfg, resolved)   # add token=<bearer> to probe APIs",
        ),
        _md(
            "## 3. Run the download",
            "",
            "Enumerates items, distributes them across the Spark cluster, and",
            "downloads them in parallel. Files land under",
            "`Files/<output_root>/<run_label>/<wsName>__<wsId>/<Type>/`, and",
            "the manifest is **appended** to the Delta table so you can",
            "accumulate multiple runs over time (filter by `run_label`).",
        ),
        _code(
            "from fabric_downloader.spark import run",
            "",
            "result = run(cfg, spark)",
            "",
            "print(f\"Items attempted   : {result.item_count:,}\")",
            "print(f\"Manifest table    : {result.manifest_table}\")",
            "print()",
            "print(\"By status:\")",
            "for k, n in sorted(result.by_status.items()):",
            "    print(f\"  {k:18s}  {n:>6,}\")",
            "print()",
            "print(\"By item type:\")",
            "for k, n in sorted(result.by_type.items()):",
            "    print(f\"  {k:18s}  {n:>6,}\")",
        ),
        _md(
            "## 4. Explore the manifest",
            "",
            "Each rollup is a regular Spark DataFrame — display, filter, or",
            "join as you like. See `fabric_downloader.persist.SummaryReport`",
            "for the full list.",
        ),
        _code("display(result.summary.by_status)"),
        _code("display(result.summary.by_type)"),
        _code("display(result.summary.by_workspace)"),
        _code("display(result.summary.errors)"),
        _code("display(result.summary.balance_check)"),
        _code("display(result.summary.run_summary)"),
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
            "fabric_downloader_version": version,
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
                   help="override the pinned downloader version (default: "
                        "read from src/fabric_downloader/_version.py)")
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

    print(f"Wrote {args.out}  (pinned fabric-downloader=={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
