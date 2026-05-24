"""Generate the thin v1 orchestration notebook for fabric-downloader."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import nbformat
from fabric_core.build_notebook import (
    NotebookBuildSpec, _code as _core_code, _load_version, _md as _core_md,
    write_notebook,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = ROOT / "notebooks" / "fabric_downloader_v1.ipynb"
__version__ = _load_version(ROOT / "src" / "fabric_downloader" / "_version.py")


def _md(*lines: str) -> dict[str, str]:
    return _core_md("\n".join(lines))


def _code(*lines: str) -> dict[str, str]:
    return _core_code("\n".join(lines))


def cells(version: str) -> list[dict[str, str]]:
    return [
        _md(
            "# Fabric Item Downloader v1",
            "",
            f"_Thin orchestrator over `fabric-downloader=={version}`._",
            "",
            "Five cells:",
            "1. **Install** the downloader wheel.",
            "2. **Configure** the run (the only cell most users touch).",
            "3. **Probe** the resolved write target + (optionally) the API endpoints.",
            "4. **Run** the download \u2014 produces files under `Files/<output_root>/<run_label>/`",
            "   and appends one row per item to the manifest Delta table.",
            "5. **Explore** the manifest \u2014 display the five rollups.",
            "",
            "All downloader logic lives in the installable wheel; edits to fetch",
            "behavior, schema, or rollups happen there, not in this notebook.",
        ),
        _code(
            "# Install the downloader wheel (re-run when you bump the version).",
            f"%pip install -q fabric-downloader=={version}",
        ),
        _md(
            "## 1. Configuration",
            "",
            "`DownloaderConfig` is a frozen dataclass \u2014 every knob has a",
            "sensible default. The most common edits are commented inline.",
            "",
            "**Multi-type runs**: list every Fabric item type you want backed",
            "up in `item_types`. `notebook_format` controls how Notebooks are",
            "saved \u2014 the default `\"py\"` writes one native-source file per",
            "notebook (`.py` for PySpark/Python, `.scala`/`.sql`/`.r` for the",
            "other Spark languages). Use `\"txt\"` to flatten the source to a",
            "single `.txt`, `\"ipynb\"` for a single self-contained Jupyter",
            "file, or `\"parts\"` to write every definition part (same shape",
            "the other item types get). Non-notebook types use",
            "`format_by_type` for per-type `?format=` overrides; missing keys",
            "fall back to parts mode.",
        ),
        _code(
            "from fabric_downloader import DownloaderConfig",
            "",
            "cfg = DownloaderConfig(",
            "    # --- What to download ---",
            "    item_types     = (\"Notebook\", \"DataPipeline\", \"Dataflow\"),",
            "    notebook_format = \"py\",   # \"py\" | \"txt\" | \"ipynb\" | \"parts\"",
            "    # format_by_type = {\"Report\": \"pbix\"},  # per-type override (non-Notebook)",
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
            "## 2. Diagnostics \u2014 probe the resolved target",
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
            "Each rollup is a regular Spark DataFrame \u2014 display, filter, or",
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


def _source_text(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def _cell_id(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


def _normalize_for_stable_diff(path: Path) -> None:
    notebook = nbformat.read(str(path), as_version=4)
    for cell in notebook.cells:
        cell["id"] = _cell_id(_source_text(cell))
    nbformat.write(notebook, str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"output .ipynb path (default: {DEFAULT_OUT})")
    parser.add_argument("--version", type=str, default=None,
                        help="override the pinned downloader version")
    args = parser.parse_args(argv)

    version = args.version or __version__
    out = write_notebook(NotebookBuildSpec(
        package_name="fabric-downloader",
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
    print(f"Wrote {out}  (pinned fabric-downloader=={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
