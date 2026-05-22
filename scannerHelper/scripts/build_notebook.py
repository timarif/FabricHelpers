"""Generate the thin v2 orchestration notebooks (rule-based + AI auditor).

Pulls `__version__` from the installed `fabric_scanner` (or the dev
source tree) and emits TWO notebooks with the exact pin baked in:

  * ``notebooks/fabric_scanner_v2.ipynb``       — rule-based scanner
  * ``notebooks/fabric_scanner_ai_v1.ipynb``   — AI-based auditor

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
    # -> writes BOTH notebooks under scannerHelper/notebooks/

Use ``--target`` to build just one (`v2`, `ai`, or `all`); ``--out``
to redirect a single target; ``--version`` to override the pin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NOTEBOOKS_DIR = ROOT / "notebooks"
DEFAULT_OUT_V2 = NOTEBOOKS_DIR / "fabric_scanner_v2.ipynb"
DEFAULT_OUT_AI = NOTEBOOKS_DIR / "fabric_scanner_ai_v1.ipynb"


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
    """Return an nbformat-4.5 document for the thin v2 rule-based scanner notebook."""
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


def build_ai_notebook(version: str) -> dict:
    """Return an nbformat-4.5 document for the thin AI-auditor notebook."""
    install_cell_src = (
        f"# Install the scanner wheel (re-run when you bump the version).\n"
        f"%pip install -q fabric-scanner=={version}"
    )

    cells = [
        _md(
            "# Fabric Notebook AI Auditor v1",
            "",
            f"_Thin orchestrator over `fabric-scanner=={version}`._",
            "",
            "Runs Fabric AI Functions over every notebook in a lakehouse",
            "export folder and scores each for **external-resource access**",
            "and **data-exfiltration risk**.",
            "",
            "**⚠ Privacy boundary.** Notebook content is sent to Fabric AI",
            "Functions for evaluation. Only run on notebook corpora that are",
            "already permitted to flow to the Fabric AI model endpoint",
            "configured for your workspace.",
            "",
            "Five cells:",
            "1. **Install** the scanner wheel.",
            "2. **Configure** the scan + AI options (the only cells most users touch).",
            "3. **Probe** the source — sanity-check paths.",
            "4. **Run** the AI audit — writes the chunks + results Delta tables.",
            "5. **Explore** the results — top risk + cross-table JOIN with",
            "   the rule-based findings table.",
            "",
            "All scanner + AI logic lives in the installable wheel. Edits to",
            "the AI prompt, response schema, or aggregation happen there —",
            "not in this notebook. `PROMPT_VERSION` is stamped on every",
            "output row so you can correlate scores back to the prompt that",
            "produced them.",
        ),
        _code(install_cell_src),
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
            "## 2. Diagnostics — probe paths",
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
            "per-chunk detail — useful when investigating a specific",
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


def _write(nb: dict, out_path: Path, version: str) -> None:
    """Write `nb` to `out_path`, validating with nbformat when available."""
    try:
        import nbformat
    except ImportError:
        nbformat = None  # type: ignore[assignment]

    for cell in nb["cells"]:
        cell.setdefault("id", _slug(cell["source"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if nbformat is not None:
        nbnode = nbformat.from_dict(nb)
        nbformat.validate(nbnode)
        nbformat.write(nbnode, str(out_path))
    else:
        out_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"Wrote {out_path}  (pinned fabric-scanner=={version})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=None,
                   help="output .ipynb path (only valid with a single "
                        "--target; default: both notebooks under notebooks/)")
    p.add_argument("--version", type=str, default=None,
                   help="override the pinned scanner version (default: read "
                        "from src/fabric_scanner/_version.py)")
    p.add_argument("--target", choices=("v2", "ai", "all"), default="all",
                   help="which notebook(s) to build (default: all)")
    args = p.parse_args(argv)

    version = args.version or _load_version()

    if args.out is not None and args.target == "all":
        p.error("--out can only be set when --target is 'v2' or 'ai'")

    targets: list[tuple[str, callable, Path]] = []
    if args.target in ("v2", "all"):
        targets.append(("v2", build_notebook,
                        args.out if args.target == "v2" else DEFAULT_OUT_V2))
    if args.target in ("ai", "all"):
        targets.append(("ai", build_ai_notebook,
                        args.out if args.target == "ai" else DEFAULT_OUT_AI))

    for _label, builder, out_path in targets:
        nb = builder(version)
        _write(nb, out_path, version)

    return 0


if __name__ == "__main__":
    sys.exit(main())
