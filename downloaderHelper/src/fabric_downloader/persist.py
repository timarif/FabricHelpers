"""Manifest persistence + rollup SQL.

`write_manifest` appends one row per item attempt to a Delta table (re-runs
accumulate; filter by `run_label` to slice). `summarize(...)` returns the
five canonical rollup DataFrames the orchestration notebook displays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def write_manifest(
    manifest_df: Any,
    target: str,
    write_to_default_lakehouse: bool,
) -> None:
    """Append the manifest DataFrame to `target` (Delta)."""
    if write_to_default_lakehouse:
        (manifest_df.write
            .mode("append")
            .option("mergeSchema", "true")
            .saveAsTable(target))
    else:
        (manifest_df.write
            .format("delta")
            .mode("append")
            .option("mergeSchema", "true")
            .save(target))


@dataclass
class SummaryReport:
    """Six rollup DataFrames over the manifest. Each is computed eagerly
    via SQL on a temp view created in `summarize()`. The notebook does
    `display(report.X)`; this module never imports `display` itself."""
    by_status:      Any
    by_type:        Any
    by_workspace:   Any
    errors:         Any
    balance_check:  Any
    run_summary:    Any


_MANIFEST_VIEW = "fabric_downloader_manifest_v"


_QUERIES = {
    "by_status": (
        "SELECT status, COUNT(*) AS n, "
        "       SUM(COALESCE(payload_bytes,0))/1048576.0 AS total_mb "
        f"FROM {_MANIFEST_VIEW} "
        "GROUP BY status "
        "ORDER BY n DESC"
    ),
    "by_type": (
        "SELECT item_type, "
        "       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)             AS downloaded, "
        "       SUM(CASE WHEN status='skipped_exists' THEN 1 ELSE 0 END) AS skipped, "
        "       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)          AS errors, "
        "       SUM(COALESCE(payload_bytes,0))/1048576.0                AS total_mb "
        f"FROM {_MANIFEST_VIEW} "
        "GROUP BY item_type "
        "ORDER BY downloaded DESC"
    ),
    "by_workspace": (
        "SELECT workspace_name, workspace_id, "
        "       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)             AS downloaded, "
        "       SUM(CASE WHEN status='skipped_exists' THEN 1 ELSE 0 END) AS skipped, "
        "       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)          AS errors, "
        "       SUM(COALESCE(payload_bytes,0))/1048576.0                AS total_mb "
        f"FROM {_MANIFEST_VIEW} "
        "GROUP BY workspace_name, workspace_id "
        "ORDER BY downloaded DESC LIMIT 500"
    ),
    "errors": (
        "SELECT workspace_name, item_type, display_name, item_id, "
        "       http_status, attempts, token_refreshes, error "
        f"FROM {_MANIFEST_VIEW} "
        "WHERE status = 'error' "
        "ORDER BY workspace_name, item_type, display_name LIMIT 500"
    ),
    "balance_check": (
        "SELECT workspace_name, item_type, display_name, item_id, "
        "       export_format, part_count, parts_saved, has_content_part, "
        "       status, error "
        f"FROM {_MANIFEST_VIEW} "
        "WHERE has_content_part = false OR has_content_part IS NULL "
        "   OR (parts_saved = 0 AND status <> 'skipped_exists') "
        "ORDER BY workspace_name, item_type, display_name LIMIT 500"
    ),
    "run_summary": (
        "SELECT run_label, "
        "       COUNT(*) AS items_attempted, "
        "       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)             AS ok, "
        "       SUM(CASE WHEN status='skipped_exists' THEN 1 ELSE 0 END) AS skipped, "
        "       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)          AS errors, "
        "       SUM(token_refreshes)                                     AS total_token_refreshes, "
        "       ROUND(SUM(COALESCE(payload_bytes,0))/1048576.0, 2)       AS total_mb, "
        "       MIN(downloaded_at) AS started_at, "
        "       MAX(downloaded_at) AS ended_at "
        f"FROM {_MANIFEST_VIEW} "
        "GROUP BY run_label"
    ),
}


def summarize(manifest_df: Any, spark: Any) -> SummaryReport:
    """Register a temp view and compute the rollup DataFrames."""
    manifest_df.createOrReplaceTempView(_MANIFEST_VIEW)
    return SummaryReport(**{name: spark.sql(sql)
                            for name, sql in _QUERIES.items()})
