"""Top-level orchestration: `run(config, spark) -> DownloaderResult`.

Glues together every layer:

  api.auth.get_token        ─┐
                             ├─► enumerate_items    ─┐
  paths.resolve_paths       ─┘                       │
                                                     ├─► build_inventory
                                                     ├─► mapPartitions
                                                     ├─► createDataFrame
                                                     ├─► persist.write_manifest
                                                     └─► persist.summarize

The user-facing thin notebook calls only `run(cfg, spark)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..api.auth import get_token
from ..api.enumerate import run_enumeration_sync
from ..config import DownloaderConfig
from ..paths import ResolvedPaths, resolve_paths
from .. import persist as _persist
from .context import DownloadContext, build_download_context
from .inventory import build_inventory, repartition_for_download
from .partition import download_partition
from .schema import manifest_schema


@dataclass
class DownloaderResult:
    """Return value of `run(config, spark)`."""
    manifest_df:     Any
    manifest_table:  str
    item_count:      int
    by_status:       dict[str, int]
    by_type:         dict[str, int]
    resolved:        ResolvedPaths
    summary:         "_persist.SummaryReport | None" = None
    started_at:      datetime = field(default_factory=lambda:
                                      datetime.now(timezone.utc))
    finished_at:     datetime | None = None


def run(
    config: DownloaderConfig,
    spark: Any,
    *,
    token: str | None = None,
    items: list[dict] | None = None,
    compute_summary: bool = True,
) -> DownloaderResult:
    """Execute one end-to-end download run.

    Parameters
    ----------
    config :
        Frozen DownloaderConfig describing what to download and where to
        write outputs.
    spark :
        A live `pyspark.sql.SparkSession`. Caller-owned.
    token :
        Optional pre-fetched bearer token. When omitted the runner pulls
        one via `api.auth.get_token(config.token_audience)`.
    items :
        Optional pre-enumerated item list (skips the enumerate step).
        Each dict needs at least `workspaceId`, `id`, `type`,
        `displayName`. When omitted the runner calls
        `api.enumerate.run_enumeration_sync` itself.
    compute_summary :
        If True (default), also runs the rollup queries and attaches them
        to `DownloaderResult.summary`. Set False to skip the extra job.
    """
    started = datetime.now(timezone.utc)
    resolved = resolve_paths(config)

    if token is None:
        token = get_token(config.token_audience)
    if items is None:
        items = run_enumeration_sync(config, token)
    if config.max_items:
        items = items[:config.max_items]

    inv_df, n_total = build_inventory(items, spark)
    inv_df = repartition_for_download(
        inv_df, n_total, config.num_partitions,
        spark.sparkContext.defaultParallelism)

    ctx = build_download_context(config, resolved, fallback_token=token)

    manifest_rdd = inv_df.rdd.mapPartitions(
        lambda rs: download_partition(rs, ctx))
    manifest_df = spark.createDataFrame(
        manifest_rdd, schema=manifest_schema()).cache()
    _ = manifest_df.count()  # materialize before persist + summary

    _persist.write_manifest(manifest_df, resolved.manifest_target,
                            config.write_to_default_lakehouse)

    summary = (_persist.summarize(manifest_df, spark)
               if compute_summary else None)

    by_status = _collect_count(manifest_df, "status")
    by_type   = _collect_count(manifest_df, "item_type")

    return DownloaderResult(
        manifest_df=manifest_df,
        manifest_table=resolved.manifest_target,
        item_count=n_total,
        by_status=by_status,
        by_type=by_type,
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
