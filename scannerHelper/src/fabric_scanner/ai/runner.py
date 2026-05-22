"""Top-level entry point for the AI auditor.

`run_ai_audit(config, options, spark) -> AIAuditResult`

Wires together:

  paths.resolve_paths          (multi-workspace ws_dated source resolution)
  spark.inventory.build_inventory_lakehouse
                              (reads notebook files, adds workspace_id +
                               source_dated_partition columns at the DF
                               level via regexp_extract)
  ai.partition.build_chunk_rows
                              (mapPartitions: extract cells, enrich
                               attached LH, chunk text)
  df.ai.generate_response     (Fabric AI functions)
  ai.aggregate.parse_ai_response_df + aggregate_chunks_to_notebooks
                              (defensive parse + per-notebook rollup)
  persist.write_findings      (generic Delta write helper)

Lakehouse-only in v1. `source_mode='api'` raises immediately with a
friendly pointer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .. import persist as _persist
from .._version import __version__
from ..config import ScannerConfig
from ..paths import ResolvedPaths, resolve_paths, table_path
from ..spark.inventory import (
    build_inventory_lakehouse,
    repartition_for_scan,
    write_snapshot,
)
from .aggregate import aggregate_chunks_to_notebooks, parse_ai_response_df
from .partition import build_chunk_rows
from .prompt import AI_AUDIT_PROMPT, AI_AUDIT_RESPONSE_FORMAT, PROMPT_VERSION
from .schema import ai_chunk_pre_ai_schema


class BudgetExceededError(RuntimeError):
    """Raised when the planned AI call count exceeds `ai_max_total_chunks`."""


@dataclass(frozen=True)
class AIAuditOptions:
    """AI-specific knobs that don't belong in ScannerConfig.

    `ScannerConfig` controls source/target resolution; `AIAuditOptions`
    controls AI call shape and budget.
    """
    ai_output_table:   str = "notebook_ai_audit_results"
    ai_chunks_table:   str = "notebook_ai_audit_chunks"
    ai_max_content_chars: int = 14000
    ai_min_chunk_chars:   int = 0
    ai_max_chunks_per_notebook: int = 50
    ai_max_total_chunks:        int | None = None  # opt-in hard cap
    ai_fail_on_error: bool = False
    write_chunks_table: bool = True
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if self.ai_max_content_chars <= 0:
            raise ValueError("ai_max_content_chars must be > 0")
        if self.ai_max_chunks_per_notebook < 1:
            raise ValueError("ai_max_chunks_per_notebook must be >= 1")
        if (self.ai_max_total_chunks is not None
                and self.ai_max_total_chunks < 1):
            raise ValueError("ai_max_total_chunks must be >= 1 when set")


@dataclass
class AIAuditResult:
    """Return value of `run_ai_audit`."""
    notebooks_count: int
    chunks_total:    int
    chunks_parsed:   int
    chunks_errored:  int
    chunks_df:       Any
    results_df:      Any
    snapshot_df:     Any
    results_table:   str
    chunks_table:    str | None
    resolved:        ResolvedPaths
    run_id:          str
    started_at:      datetime
    finished_at:     datetime | None = None


def ensure_ai_functions_available() -> None:
    """Friendly error when running outside Fabric (or before AI Functions
    are enabled on the workspace)."""
    try:
        from synapse.ml.spark import aifunc  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "AI audit requires Microsoft Fabric runtime with "
            "`synapse.ml.spark.aifunc` available. Enable AI functions on "
            "your Fabric workspace and run this notebook inside a Fabric "
            "Spark session."
        ) from e


def _resolve_ai_targets(
    config: ScannerConfig,
    options: AIAuditOptions,
    resolved: ResolvedPaths,
) -> tuple[str, str]:
    """Compute the chunks-table and results-table write targets.

    Mirrors the logic in `paths.resolve_paths` for `inventory_target` /
    `output_target`: default-LH writes use the bare table name;
    cross-workspace writes use a full ABFSS path under
    `(config.write_workspace_id, config.write_lakehouse_id, config.write_schema)`.
    """
    if config.write_to_default_lakehouse:
        return options.ai_chunks_table, options.ai_output_table
    chunks = table_path(config.write_workspace_id,
                        config.write_lakehouse_id,
                        options.ai_chunks_table,
                        config.write_schema)
    results = table_path(config.write_workspace_id,
                         config.write_lakehouse_id,
                         options.ai_output_table,
                         config.write_schema)
    return chunks, results


def _ctx_fn_for_rows(resolved: ResolvedPaths,
                     ws_name_by_id: dict[str, str]):
    """Build a per-row ctx extractor for `build_chunk_rows`.

    `build_inventory_lakehouse` already attached `workspace_id` and
    `source_dated_partition` columns to `scan_df` via `regexp_extract`.
    We just forward them, falling back to the resolved-paths defaults
    when the per-row regex didn't fire.
    """
    src_lh_id    = resolved.source_lakehouse_id or ""
    src_lh_name  = resolved.source_lakehouse_name or src_lh_id or ""
    src_ws_id    = resolved.source_workspace_id or ""
    src_ws_name  = resolved.source_workspace_name or src_ws_id or ""

    def _ctx(row) -> dict:
        try:
            wid = row["workspace_id"] or src_ws_id
        except (TypeError, KeyError, IndexError):
            wid = getattr(row, "workspace_id", "") or src_ws_id
        try:
            dated = row["source_dated_partition"]
        except (TypeError, KeyError, IndexError):
            dated = getattr(row, "source_dated_partition", None)
        wname = ws_name_by_id.get((wid or "").lower(), wid) or src_ws_name
        return {
            "workspace_id":           wid,
            "workspace_name":         wname,
            "source_lakehouse_id":    src_lh_id,
            "source_lakehouse_name":  src_lh_name,
            "source_dated_partition": dated,
            "ws_name_by_id":          ws_name_by_id,
        }
    return _ctx


def run_ai_audit(
    config: ScannerConfig,
    options: AIAuditOptions,
    spark: Any,
    *,
    ws_name_by_id: dict[str, str] | None = None,
) -> AIAuditResult:
    """Execute one end-to-end AI audit pass over the notebooks in
    `config.source_*` and write per-chunk + per-notebook tables.

    Parameters
    ----------
    config :
        ScannerConfig with `source_mode='lakehouse'`. API mode is not
        supported in v1 — raises RuntimeError early.
    options :
        AIAuditOptions controlling chunk size, budget caps, and table names.
    spark :
        A live `pyspark.sql.SparkSession`. Caller-owned.
    ws_name_by_id :
        Optional workspace-id → workspace-name lookup, used to backfill
        `workspace_name` and `attached_lakehouse_workspace_name`. Empty
        when None.

    Raises
    ------
    RuntimeError
        When `source_mode='api'` (v2 feature).
    BudgetExceededError
        When the planned chunk count exceeds `options.ai_max_total_chunks`.
    """
    from pyspark.sql import functions as F

    if config.source_mode != "lakehouse":
        raise RuntimeError(
            "run_ai_audit currently only supports source_mode='lakehouse'. "
            "API-mode AI audit is a roadmap item; set "
            "config.source_mode='lakehouse' and point source_subpath at "
            "your notebook exports.")

    started = datetime.now(timezone.utc)
    ws_name_by_id = {(k or "").lower(): v
                     for k, v in (ws_name_by_id or {}).items()}

    # --- Inventory ----------------------------------------------------------
    resolved = resolve_paths(config)
    scan_df, snapshot_df, n_total = build_inventory_lakehouse(
        config, resolved, spark)
    scan_df = repartition_for_scan(scan_df, n_total,
                                   config.target_partition_size)

    # --- Chunk rows via mapPartitions ---------------------------------------
    ctx_fn = _ctx_fn_for_rows(resolved, ws_name_by_id)
    max_chars = options.ai_max_content_chars
    min_chunk = options.ai_min_chunk_chars

    def _partition_fn(rows):
        return build_chunk_rows(rows, ctx_fn,
                                max_chars=max_chars,
                                min_chunk_chars=min_chunk)

    chunk_rdd = scan_df.rdd.mapPartitions(_partition_fn)
    chunks_df = spark.createDataFrame(
        chunk_rdd, schema=ai_chunk_pre_ai_schema())

    # --- Per-notebook chunk cap ---------------------------------------------
    # We've already let the chunker emit as many chunks as needed; clip the
    # tail per notebook so a single huge notebook doesn't blow our budget.
    cap = options.ai_max_chunks_per_notebook
    if cap is not None and cap > 0:
        chunks_df = chunks_df.filter(F.col("chunk_index") < F.lit(cap))

    # --- Materialize before AI (critical: prevents Spark retries from
    # doubling AI cost) -----------------------------------------------------
    chunks_df = chunks_df.persist()
    chunks_total = chunks_df.count()

    if chunks_total == 0:
        finished = datetime.now(timezone.utc)
        empty_results = spark.createDataFrame([], chunks_df.schema)
        return AIAuditResult(
            notebooks_count=0, chunks_total=0,
            chunks_parsed=0, chunks_errored=0,
            chunks_df=chunks_df, results_df=empty_results,
            snapshot_df=snapshot_df,
            results_table="", chunks_table=None,
            resolved=resolved, run_id=options.run_id,
            started_at=started, finished_at=finished,
        )

    if (options.ai_max_total_chunks is not None
            and chunks_total > options.ai_max_total_chunks):
        chunks_df.unpersist()
        raise BudgetExceededError(
            f"AI audit would run {chunks_total} chunks, but "
            f"ai_max_total_chunks={options.ai_max_total_chunks}. "
            f"Lower max_notebooks, raise ai_max_total_chunks, or lower "
            f"ai_max_chunks_per_notebook.")

    # --- AI generate_response -----------------------------------------------
    ensure_ai_functions_available()

    # Prompt template uses {file_name}, {chunk_number}, {chunk_count},
    # {chunk_text}. Spark's ai.generate_response substitutes by column name.
    prompt_df = (chunks_df
        .withColumn("chunk_number", F.col("chunk_index") + F.lit(1))
        .withColumn("file_name", F.col("display_name")))

    audit_df = prompt_df.ai.generate_response(
        prompt=AI_AUDIT_PROMPT,
        is_prompt_template=True,
        output_col="ai_response",
        error_col="ai_error",
        response_format=AI_AUDIT_RESPONSE_FORMAT,
    )

    # --- Defensive parse + provenance --------------------------------------
    parsed_df = parse_ai_response_df(audit_df)
    now_lit = F.current_timestamp()
    parsed_df = (parsed_df
        .withColumn("auditor_version", F.lit(__version__))
        .withColumn("prompt_version",  F.lit(PROMPT_VERSION))
        .withColumn("run_id",          F.lit(options.run_id))
        .withColumn("assessed_at",     now_lit))

    chunks_target, results_target = _resolve_ai_targets(
        config, options, resolved)

    if options.write_chunks_table:
        # Project to chunk-table column order before writing.
        from .schema import AI_CHUNK_COLUMNS
        chunks_out = parsed_df.select(*[F.col(c) for c in AI_CHUNK_COLUMNS])
        _persist.write_findings(chunks_out, chunks_target,
                                config.write_to_default_lakehouse)

    chunks_parsed = parsed_df.filter(F.col("ai_error").isNull()).count()
    chunks_errored = chunks_total - chunks_parsed

    if options.ai_fail_on_error and chunks_errored > 0:
        chunks_df.unpersist()
        raise RuntimeError(
            f"AI audit had {chunks_errored} errored chunks (of {chunks_total}) "
            f"and ai_fail_on_error=True.")

    # --- Aggregate to notebook level ---------------------------------------
    results_df = aggregate_chunks_to_notebooks(parsed_df)
    results_df = (results_df
        .withColumn("auditor_version", F.lit(__version__))
        .withColumn("prompt_version",  F.lit(PROMPT_VERSION))
        .withColumn("run_id",          F.lit(options.run_id))
        .withColumn("assessed_at",     F.current_timestamp()))

    from .schema import AI_RESULT_COLUMNS
    results_out = results_df.select(*[F.col(c) for c in AI_RESULT_COLUMNS])

    _persist.write_findings(results_out, results_target,
                            config.write_to_default_lakehouse)

    # Snapshot of the inventory (one row per scanned notebook).
    write_snapshot(snapshot_df, resolved.inventory_target,
                   config.write_to_default_lakehouse)

    notebooks_count = (parsed_df
        .select("notebook_id").distinct().count())

    finished = datetime.now(timezone.utc)
    return AIAuditResult(
        notebooks_count=notebooks_count,
        chunks_total=chunks_total,
        chunks_parsed=chunks_parsed,
        chunks_errored=chunks_errored,
        chunks_df=parsed_df,
        results_df=results_out,
        snapshot_df=snapshot_df,
        results_table=results_target,
        chunks_table=(chunks_target if options.write_chunks_table else None),
        resolved=resolved,
        run_id=options.run_id,
        started_at=started,
        finished_at=finished,
    )
