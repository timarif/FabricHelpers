"""Generate the thin Fabric Scanner orchestration notebooks (v2 + ai).

Cells live in this script for readability; the actual nbformat-write
mechanics are delegated to ``fabric_core.build_notebook``. The two
target notebooks are:

* ``fabric_scanner_v2.ipynb`` -- the rule-based scanner orchestrator
* ``fabric_scanner_ai_v1.ipynb`` -- the AI auditor orchestrator

Both pin the same ``fabric-scanner`` wheel version, read from
``src/fabric_scanner/_version.py`` (overridable via ``--version``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from fabric_core.build_notebook import (
    NotebookBuildSpec,
    _code as _core_code,
    _load_version,
    _md as _core_md,
    write_notebook,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_V2 = REPO_ROOT / "notebooks" / "fabric_scanner_v2.ipynb"
DEFAULT_OUT_AI = REPO_ROOT / "notebooks" / "fabric_scanner_ai_v1.ipynb"
VERSION_FILE = REPO_ROOT / "src" / "fabric_scanner" / "_version.py"

_SYNAPSE_KERNEL = {
    "display_name": "Synapse PySpark",
    "language": "Python",
    "name": "synapse_pyspark",
}


def _md(*lines: str) -> dict:
    return _core_md("\n".join(lines))


def _code(*lines: str) -> dict:
    return _core_code("\n".join(lines))


def _v2_cells(version: str) -> list[dict]:
    return [
        _md(
            "# Fabric Notebook Scanner v2",
            "",
            f"_Thin orchestrator over `fabric-scanner=={version}`._",
            "",
            "Five cells:",
            "1. **Install** the scanner wheel.",
            "2. **Configure** the scan (the only cell most users touch).",
            "3. **Probe** the source \u2014 sanity-check paths or endpoints.",
            "4. **Run** the scan \u2014 produces the inventory and findings Delta tables.",
            "5. **Explore** the findings \u2014 display the top rollups.",
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
            "`ScannerConfig` is a frozen dataclass \u2014 every knob has a sensible",
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
            "## 2. Diagnostics \u2014 probe paths / endpoints",
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
            "Each rollup is a regular Spark DataFrame \u2014 display, filter, or",
            "join as you like. See `fabric_scanner.persist.SummaryReport`",
            "for the full list.",
        ),
        _code("display(result.summary.by_severity)"),
        _code("display(result.summary.review_queue)"),
        _code("display(result.summary.cross_workspace_flows)"),
        _code("display(result.summary.sample_critical)"),
    ]


def _ai_cells(version: str) -> list[dict]:
    return [
        _md(
            "# Fabric Notebook AI Auditor v1",
            "",
            f"_Thin orchestrator over `fabric-scanner=={version}`._",
            "",
            "Runs Fabric AI Functions over every notebook in a lakehouse",
            "export folder and scores each for **external-resource access**",
            "and **data-exfiltration risk**.",
            "",
            "**\u26a0 Privacy boundary.** Notebook content is sent to Fabric AI",
            "Functions for evaluation. Only run on notebook corpora that are",
            "already permitted to flow to the Fabric AI model endpoint",
            "configured for your workspace.",
            "",
            "Five cells:",
            "1. **Install** the scanner wheel.",
            "2. **Configure** the scan + AI options (the only cells most users touch).",
            "3. **Probe** the source \u2014 sanity-check paths.",
            "4. **Run** the AI audit \u2014 writes the chunks + results Delta tables.",
            "5. **Explore** the results \u2014 top risk + cross-table JOIN with",
            "   the rule-based findings table.",
            "",
            "All scanner + AI logic lives in the installable wheel. Edits to",
            "the AI prompt, response schema, or aggregation happen there \u2014",
            "not in this notebook. `PROMPT_VERSION` is stamped on every",
            "output row so you can correlate scores back to the prompt that",
            "produced them.",
        ),
        _code(
            "# Install the scanner wheel (re-run when you bump the version).",
            f"%pip install -q fabric-scanner=={version}",
        ),
        _md(
            "## 1. Configuration",
            "",
            "`ScannerConfig` controls source/target resolution (same as the",
            "rule-based scanner); `AIAuditOptions` controls chunk size,",
            "per-notebook caps, and the optional hard budget.",
        ),
        _code(
            "from fabric_scanner import ScannerConfig",
            "from fabric_scanner.ai import AIAuditOptions, PROMPT_VERSION",
            "",
            "cfg = ScannerConfig(",
            "    # --- Where to read notebooks from (lakehouse-only in v1) ---",
            "    source_mode      = \"lakehouse\",",
            "    source_layout    = \"ws_dated\",   # or \"flat\"",
            "    source_subpath   = \"Files/notebook_exports\",",
            "    source_file_glob = \"*.ipynb\",",
            "    # Leave source_lakehouse_* blank to auto-detect the mounted",
            "    # default lakehouse (recommended).",
            "    # source_lakehouse_workspace_id = \"<ws-guid>\",",
            "    # source_lakehouse_id           = \"<lh-guid>\",",
            "",
            "    # --- Where to write outputs ---",
            "    write_to_default_lakehouse = True,",
            "    inventory_table = \"v2_inventory\",",
            "    output_table    = \"v2_findings\",  # unused by the AI auditor",
            "",
            "    # --- Behavior ---",
            "    max_notebooks         = 0,    # 0 = no cap (start small for cost!)",
            "    target_partition_size = 200,",
            ")",
            "",
            "opts = AIAuditOptions(",
            "    ai_output_table = \"notebook_ai_audit_results\",",
            "    ai_chunks_table = \"notebook_ai_audit_chunks\",",
            "    # Per-notebook chunk size + caps. Lower these if you're",
            "    # rate-limited or want a cheaper smoke run.",
            "    ai_max_content_chars       = 14_000,",
            "    ai_max_chunks_per_notebook = 50,",
            "    # Hard budget across the whole run. None = unlimited (risky).",
            "    # ai_max_total_chunks      = 500,",
            "    write_chunks_table = True,",
            ")",
            "print(f\"Prompt version : {PROMPT_VERSION}\")",
            "print(f\"Run id         : {opts.run_id}\")",
        ),
        _md(
            "## 2. Diagnostics \u2014 probe paths",
            "",
            "Prints a one-screen summary of what the AI auditor *will* read.",
            "Safe to run before kicking off the actual AI calls.",
        ),
        _code(
            "from fabric_scanner import resolve_paths, probe",
            "",
            "resolved = resolve_paths(cfg)",
            "probe(cfg, resolved)",
        ),
        _md(
            "## 3. Run the AI audit",
            "",
            "Builds the inventory, chunks each notebook, calls",
            "`df.ai.generate_response` on every chunk, defensively parses",
            "the JSON, and aggregates to one row per notebook.",
            "",
            "`run_ai_audit` raises `BudgetExceededError` if the planned chunk",
            "count exceeds `opts.ai_max_total_chunks` (when set). It also",
            "raises a friendly error if Fabric AI Functions aren't available",
            "in the current runtime.",
        ),
        _code(
            "from fabric_scanner.ai import run_ai_audit",
            "",
            "result = run_ai_audit(cfg, opts, spark)",
            "",
            "print(f\"Notebooks audited : {result.notebooks_count:,}\")",
            "print(f\"Chunks total      : {result.chunks_total:,}\")",
            "print(f\"Chunks parsed     : {result.chunks_parsed:,}\")",
            "print(f\"Chunks errored    : {result.chunks_errored:,}\")",
            "print(f\"Results table     : {result.results_table}\")",
            "print(f\"Chunks table      : {result.chunks_table}\")",
            "print(f\"Run id            : {result.run_id}\")",
        ),
        _md(
            "## 4. Explore the results",
            "",
            "`result.results_df` is one row per notebook with max scores",
            "across all chunks. `result.chunks_df` is the underlying",
            "per-chunk detail \u2014 useful when investigating a specific",
            "high-risk score.",
        ),
        _code(
            "# Highest-risk notebooks first.",
            "from pyspark.sql import functions as F",
            "display(result.results_df.orderBy(",
            "    F.col(\"exfiltration_risk_score\").desc_nulls_last(),",
            "    F.col(\"external_resource_access_score\").desc_nulls_last(),",
            "))",
        ),
        _code(
            "# Drill into the chunks for the top notebook.",
            "top_id = (result.results_df",
            "          .orderBy(F.col(\"exfiltration_risk_score\").desc_nulls_last())",
            "          .limit(1).select(\"notebook_id\").collect()[0][\"notebook_id\"])",
            "display(result.chunks_df",
            "        .filter(F.col(\"notebook_id\") == top_id)",
            "        .orderBy(\"chunk_index\"))",
        ),
        _md(
            "## 5. JOIN with the rule-based findings",
            "",
            "Both tables share `(workspace_id, source_dated_partition,",
            "display_name)` as a stable join key, plus `content_hash` for",
            "extra precision when display_names collide across exports.",
        ),
        _code(
            "ai = spark.table(opts.ai_output_table)",
            "findings = spark.table(cfg.output_table)",
            "",
            "joined = (findings.alias(\"r\")",
            "    .join(ai.alias(\"a\"),",
            "        (F.col(\"r.workspace_id\")           == F.col(\"a.workspace_id\")) &",
            "        (F.col(\"r.source_dated_partition\") == F.col(\"a.source_dated_partition\")) &",
            "        (F.col(\"r.display_name\")           == F.col(\"a.display_name\")),",
            "        how=\"left\")",
            "    .select(",
            "        \"r.workspace_id\", \"r.display_name\", \"r.severity\",",
            "        \"r.finding_type\", \"r.pattern_label\",",
            "        F.col(\"a.exfiltration_risk_score\").alias(\"exfil\"),",
            "        F.col(\"a.external_resource_access_score\").alias(\"ext_access\"),",
            "        F.col(\"a.top_rationale\").alias(\"rationale\"),",
            "    ))",
            "display(joined.orderBy(F.col(\"exfil\").desc_nulls_last()))",
        ),
    ]


def _build_one(label: str, builder: Callable[[str], list[dict]], out_path: Path, version: str) -> None:
    spec = NotebookBuildSpec(
        package_name="fabric-scanner",
        version=version,
        cells=builder(version),
        output_path=out_path,
        kernel_name="synapse_pyspark",
        language_name="python",
        metadata={"kernelspec": _SYNAPSE_KERNEL},
    )
    written = write_notebook(spec)
    print(f"Wrote {written}  (pinned fabric-scanner=={version})  [{label}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output .ipynb path (only valid with a single --target; "
             "default: both notebooks under notebooks/)",
    )
    parser.add_argument(
        "--version", default=None,
        help="override the pinned scanner version (default: read from _version.py)",
    )
    parser.add_argument(
        "--target", choices=("v2", "ai", "all"), default="all",
        help="which notebook(s) to build (default: all)",
    )
    args = parser.parse_args(argv)

    if args.out is not None and args.target == "all":
        parser.error("--out can only be set when --target is 'v2' or 'ai'")

    version = args.version or _load_version(VERSION_FILE)

    targets: list[tuple[str, Callable[[str], list[dict]], Path]] = []
    if args.target in ("v2", "all"):
        targets.append((
            "v2", _v2_cells,
            args.out if args.target == "v2" else DEFAULT_OUT_V2,
        ))
    if args.target in ("ai", "all"):
        targets.append((
            "ai", _ai_cells,
            args.out if args.target == "ai" else DEFAULT_OUT_AI,
        ))

    for label, builder, out_path in targets:
        _build_one(label, builder, out_path, version)

    return 0


if __name__ == "__main__":
    sys.exit(main())
