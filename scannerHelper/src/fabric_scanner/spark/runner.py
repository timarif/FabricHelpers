"""Top-level orchestration: `run(config, spark) -> ScannerResult`.

Glues together every layer:

  api.auth.get_token        ─┐
                             ├─► enumerate (API)   ─┐
  paths.resolve_paths       ─┘                     │
                                                   ├─► build_inventory_*
                                                   ├─► mapPartitions
                                                   ├─► createDataFrame
                                                   ├─► persist.write_findings
                                                   └─► persist.summarize

Everything else in the package is reachable as a building block; the
runner is what the thin notebook calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..api.auth import get_token
from ..api.enumerate import run_enumeration_sync
from ..config import ScannerConfig
from ..paths import ResolvedPaths, resolve_paths
from .. import persist as _persist
from .context import PartitionContext, build_partition_context
from .inventory import (
    build_inventory_api,
    build_inventory_lakehouse,
    repartition_for_scan,
    write_snapshot,
)
from .partition import fetch_partition, scan_partition_lakehouse
from .schema import result_schema


@dataclass
class ScannerResult:
    """Return value of `run(config, spark)`."""
    inventory_df:    Any
    findings_df:     Any
    inventory_table: str
    findings_table:  str
    notebook_count:  int
    findings_count:  int
    by_severity:     dict[str, int]
    by_category:     dict[str, int]
    dated_index:     dict[str, str]
    resolved:        ResolvedPaths
    summary:         "_persist.SummaryReport | None" = None
    started_at:      datetime = field(default_factory=lambda:
                                      datetime.now(timezone.utc))
    finished_at:     datetime | None = None


def run(
    config: ScannerConfig,
    spark: Any,
    *,
    token: str | None = None,
    notebooks: list[dict] | None = None,
    compute_summary: bool = True,
) -> ScannerResult:
    """Execute one end-to-end scan.

    Parameters
    ----------
    config :
        Frozen ScannerConfig describing source mode, output targets, etc.
    spark :
        A live `pyspark.sql.SparkSession`. Caller-owned.
    token :
        Optional pre-fetched bearer token (API mode). When omitted the
        runner pulls one via `api.auth.get_token(config.token_audience)`.
    notebooks :
        Optional pre-enumerated notebook list (API mode). When omitted the
        runner calls `api.enumerate.run_enumeration_sync` itself.
    compute_summary :
        If True (default), also runs the 10 rollup queries and attaches
        them to `ScannerResult.summary`. Set False to skip the extra job
        when the caller doesn't care.
    """
    started = datetime.now(timezone.utc)

    resolved = resolve_paths(config)

    # --- Enumeration / token (API mode only) --------------------------------
    workspaces: list[dict] = []
    if config.source_mode == "api":
        if token is None:
            token = get_token(config.token_audience)
        if notebooks is None:
            notebooks = run_enumeration_sync(config, token)
        # Best-effort: reuse enumerate's workspace data for the WS map.
        # The notebooks already have workspaceName stamped on by enumerate,
        # so we can rebuild the lookup from them.
        seen = set()
        for n in notebooks:
            wid = (n.get("workspaceId") or "").lower()
            if wid and wid not in seen:
                workspaces.append({
                    "id": n["workspaceId"],
                    "name": n.get("workspaceName") or n["workspaceId"],
                })
                seen.add(wid)

    # --- Inventory ----------------------------------------------------------
    if config.source_mode == "lakehouse":
        scan_df, snapshot_df, n_total = build_inventory_lakehouse(
            config, resolved, spark)
    else:
        scan_df, snapshot_df, n_total = build_inventory_api(
            notebooks or [], spark)

    write_snapshot(snapshot_df, resolved.inventory_target,
                   config.write_to_default_lakehouse)
    scan_df = repartition_for_scan(scan_df, n_total, config.target_partition_size)

    # --- Partition context (driver-side) ------------------------------------
    ctx = build_partition_context(
        config, resolved,
        workspaces=workspaces,
        fallback_token=token if config.source_mode == "api" else None,
    )

    # --- mapPartitions ------------------------------------------------------
    if config.source_mode == "lakehouse":
        partition_fn = lambda rows: scan_partition_lakehouse(rows, ctx)
    else:
        partition_fn = lambda rows: fetch_partition(rows, ctx)

    findings_rdd = scan_df.rdd.mapPartitions(partition_fn)
    findings_df = spark.createDataFrame(findings_rdd,
                                        schema=result_schema()).cache()
    findings_count = findings_df.count()

    # --- Persist ------------------------------------------------------------
    _persist.write_findings(findings_df, resolved.output_target,
                            config.write_to_default_lakehouse)

    # --- Rollups (optional) -------------------------------------------------
    summary = _persist.summarize(findings_df, spark) if compute_summary else None

    # --- Build summary counts for the result dataclass ---------------------
    by_severity = _collect_count(findings_df, "severity")
    by_category = _collect_count(findings_df, "category")

    return ScannerResult(
        inventory_df=snapshot_df,
        findings_df=findings_df,
        inventory_table=resolved.inventory_target,
        findings_table=resolved.output_target,
        notebook_count=n_total,
        findings_count=findings_count,
        by_severity=by_severity,
        by_category=by_category,
        dated_index=resolved.dated_index,
        resolved=resolved,
        summary=summary,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )


def _collect_count(df: Any, col: str) -> dict[str, int]:
    """Return {value: count} for `col`, ignoring NULLs."""
    rows = (df.where(f"{col} IS NOT NULL")
              .groupBy(col).count().collect())
    return {r[col]: int(r["count"]) for r in rows}
