"""Reporting adapter bridge for ``fabric_scanner``.

This module is the thin glue between ``fabric_scanner``'s native findings
schema and the shared ``fabric_reporting`` lakehouse schema.  It is imported
**lazily** from ``spark/runner.py`` — only when the user has set
``ScannerConfig.reporting_lakehouse``.

If ``fabric-reporting`` is not installed, a ``RuntimeError`` is raised so
the user gets a clear, actionable message instead of a bare ``ImportError``.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import ScannerConfig


def write_scan_findings(
    config: "ScannerConfig",
    spark: Any,
    findings_df: Any,
    scan_run_id: str,
) -> int:
    """Convert *findings_df* rows to ``fact_scan_findings`` and upsert them.

    Parameters
    ----------
    config:
        The active ``ScannerConfig``.  ``config.reporting_lakehouse`` must be
        non-empty (the caller is responsible for guarding the call).
    spark:
        The live ``SparkSession`` used by the scanner run.
    findings_df:
        The scanner findings ``DataFrame`` produced by ``runner.run``.
    scan_run_id:
        Stable identifier for this scan run (ISO-8601 UTC timestamp
        recommended).

    Returns
    -------
    int
        Number of rows written (0 when *findings_df* is empty).
    """
    try:
        from fabric_reporting.adapter import ReportingAdapter
    except ImportError as exc:
        raise RuntimeError(
            "reporting_lakehouse is set but 'fabric-reporting' is not installed. "
            "Install it with: pip install fabric-reporting"
        ) from exc

    rows = _findings_df_to_rows(findings_df, scan_run_id)
    if not rows:
        return 0

    adapter = ReportingAdapter(spark, config.reporting_lakehouse)
    adapter.ensure_tables()
    return adapter.write_facts("fact_scan_findings", rows)


def _findings_df_to_rows(findings_df: Any, scan_run_id: str) -> list[dict]:
    """Map a scanner findings ``DataFrame`` to ``fact_scan_findings`` dicts."""
    collected = findings_df.collect()
    rows: list[dict] = []
    for row in collected:
        rows.append({
            "finding_id":             str(uuid.uuid4()),
            "scan_run_id":            scan_run_id,
            "workspace_id":           _get(row, "workspace_id"),
            "source_dated_partition": _get(row, "source_dated_partition"),
            "notebook_id":            _get(row, "notebook_id"),
            "severity":               _get(row, "severity"),
            "kind":                   _get(row, "finding_type"),
            "redacted_snippet":       _get(row, "code_snippet"),
            "url":                    _get(row, "url"),
            "detected_at":            _get(row, "scanned_at"),
        })
    return rows


def _get(row: Any, field: str) -> Any:
    """Safe field access on a Spark Row — returns None if missing."""
    try:
        return getattr(row, field)
    except AttributeError:
        return None
