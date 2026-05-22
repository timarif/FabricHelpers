"""Findings persistence + rollup SQL.

Splits the legacy `09_persist.py` cell into:
  * `write_findings` — single function, dispatches on
    `write_to_default_lakehouse`.
  * `summarize(findings_df, spark) -> SummaryReport` — returns the ten
    rollup DataFrames as fields. The notebook can `display(rep.X)` for
    each one without the wheel ever calling `display` itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def write_findings(
    findings_df: Any,
    target: str,
    write_to_default_lakehouse: bool,
) -> None:
    """Persist the findings DataFrame to `target` (Delta)."""
    if write_to_default_lakehouse:
        findings_df.write.mode("overwrite").option(
            "overwriteSchema", "true").saveAsTable(target)
    else:
        (findings_df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .save(target))


@dataclass
class SummaryReport:
    """Ten rollup DataFrames over the findings table. Each is computed
    eagerly via SQL on a temp view created in `summarize()`.

    The user does `display(report.by_severity)` etc.; the wheel itself
    never imports `display` so it stays Fabric-runtime-agnostic.
    """
    by_severity:               Any
    by_category_severity:      Any
    top_notebooks:             Any
    url_directions:            Any
    cross_workspace_flows:     Any
    by_attached_lakehouse:     Any
    cross_workspace_lh:        Any
    needs_update:              Any
    review_queue:              Any
    sample_critical:           Any


# Queries — keep these in sync with `09_persist.py`. The view name is
# stable so users can poke around with `spark.sql(...)` after `run()`
# returns.
_FINDINGS_VIEW = "fabric_scanner_findings_v"


_QUERIES = {
    "by_severity": (
        "SELECT COALESCE(severity, '(no findings)') AS severity, "
        "       COUNT(*) AS n "
        f"FROM {_FINDINGS_VIEW} "
        "GROUP BY severity "
        "ORDER BY CASE severity "
        "  WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "  WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END"
    ),
    "by_category_severity": (
        "SELECT category, severity, COUNT(*) AS n "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE finding_type IS NOT NULL "
        "GROUP BY category, severity "
        "ORDER BY category, severity"
    ),
    "top_notebooks": (
        "SELECT workspace_name, display_name, notebook_id, "
        "       SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) AS critical_n, "
        "       SUM(CASE WHEN severity='high'     THEN 1 ELSE 0 END) AS high_n, "
        "       SUM(CASE WHEN severity='medium'   THEN 1 ELSE 0 END) AS medium_n, "
        "       SUM(CASE WHEN severity='low'      THEN 1 ELSE 0 END) AS low_n "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE finding_type IS NOT NULL "
        "GROUP BY workspace_name, display_name, notebook_id "
        "HAVING critical_n + high_n > 0 "
        "ORDER BY critical_n DESC, high_n DESC LIMIT 50"
    ),
    "url_directions": (
        "SELECT direction, COUNT(*) AS n "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE finding_type = 'url' "
        "GROUP BY direction ORDER BY n DESC"
    ),
    "cross_workspace_flows": (
        "SELECT workspace_name AS src_ws, dest_workspace_name AS dest_ws, "
        "       direction, COUNT(*) AS n "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE cross_workspace = true "
        "GROUP BY workspace_name, dest_workspace_name, direction "
        "ORDER BY n DESC LIMIT 100"
    ),
    "by_attached_lakehouse": (
        "SELECT attached_lakehouse_workspace_name AS lh_ws, "
        "       attached_lakehouse_name AS lakehouse, "
        "       attached_lakehouse_id, "
        "       COUNT(DISTINCT notebook_id) AS notebooks, "
        "       COUNT(*) AS total_findings "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE attached_lakehouse_id IS NOT NULL "
        "GROUP BY attached_lakehouse_workspace_name, attached_lakehouse_name, "
        "         attached_lakehouse_id "
        "ORDER BY notebooks DESC, total_findings DESC LIMIT 200"
    ),
    "cross_workspace_lh": (
        "SELECT workspace_name AS notebook_ws, display_name AS notebook, "
        "       attached_lakehouse_workspace_name AS lakehouse_ws, "
        "       attached_lakehouse_name AS lakehouse, "
        "       COUNT(*) AS findings "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE attached_lakehouse_workspace_id IS NOT NULL "
        "  AND workspace_id IS NOT NULL "
        "  AND LOWER(attached_lakehouse_workspace_id) <> LOWER(workspace_id) "
        "GROUP BY workspace_name, display_name, "
        "         attached_lakehouse_workspace_name, attached_lakehouse_name "
        "ORDER BY findings DESC LIMIT 200"
    ),
    "needs_update": (
        "SELECT workspace_name, display_name, notebook_id, "
        "       attached_lakehouse_name, "
        "       COUNT(*) AS needs_update_findings, "
        "       MIN(cell_index) AS first_cell, "
        "       MIN(line_number) AS first_line, "
        "       FIRST(message) AS sample_message, "
        "       FIRST(code_snippet) AS sample_snippet "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE category = 'needs_update' "
        "GROUP BY workspace_name, display_name, notebook_id, attached_lakehouse_name "
        "ORDER BY needs_update_findings DESC, workspace_name, display_name LIMIT 500"
    ),
    "review_queue": f"""
        SELECT
          workspace_name, display_name, notebook_id,
          MAX(CASE WHEN severity='critical' THEN 1 ELSE 0 END)        AS has_critical,
          MAX(CASE WHEN severity='high'     THEN 1 ELSE 0 END)        AS has_high,
          MAX(CASE WHEN cross_workspace = true THEN 1 ELSE 0 END)      AS has_cross_ws,
          MAX(CASE WHEN finding_type='potential_write' THEN 1 ELSE 0 END) AS has_potential_write,
          MAX(CASE WHEN finding_type='dynamic_exec' THEN 1 ELSE 0 END)    AS has_dynamic_exec,
          MAX(CASE WHEN finding_type='entropy' THEN 1 ELSE 0 END)         AS has_entropy,
          MAX(CASE WHEN finding_type='url' AND direction='write' THEN 1 ELSE 0 END) AS has_url_write,
          MAX(CASE WHEN category='needs_update' THEN 1 ELSE 0 END)        AS has_needs_update,
          COUNT(*) AS total_findings,
          CASE
            WHEN MAX(CASE WHEN severity='critical' THEN 1 ELSE 0 END) = 1
              THEN 'critical_review'
            WHEN MAX(CASE WHEN cross_workspace = true THEN 1 ELSE 0 END) = 1
              THEN 'cross_workspace_write'
            WHEN MAX(CASE WHEN finding_type='dynamic_exec' THEN 1 ELSE 0 END) = 1
              THEN 'dynamic_exec_review'
            WHEN MAX(CASE WHEN finding_type='entropy' THEN 1 ELSE 0 END) = 1
              THEN 'high_entropy_review'
            WHEN MAX(CASE WHEN finding_type='potential_write' THEN 1 ELSE 0 END) = 1
                 AND MAX(CASE WHEN finding_type='url' AND direction='write' THEN 1 ELSE 0 END) = 0
              THEN 'flag_for_review'
            WHEN MAX(CASE WHEN category='needs_update' THEN 1 ELSE 0 END) = 1
              THEN 'needs_update_review'
            WHEN MAX(CASE WHEN finding_type='url' AND direction='write' THEN 1 ELSE 0 END) = 1
              THEN 'url_writes_only'
            WHEN MAX(CASE WHEN finding_type IS NOT NULL THEN 1 ELSE 0 END) = 1
              THEN 'informational'
            ELSE 'clean'
          END AS status
        FROM {_FINDINGS_VIEW}
        GROUP BY workspace_name, display_name, notebook_id
        ORDER BY has_critical DESC, has_high DESC, has_cross_ws DESC,
                 has_needs_update DESC, total_findings DESC
    """,
    "sample_critical": (
        "SELECT workspace_name, display_name, cell_index, line_number, "
        "       finding_type, category, severity, message, code_snippet "
        f"FROM {_FINDINGS_VIEW} "
        "WHERE severity IN ('critical', 'high') "
        "ORDER BY severity, workspace_name, display_name "
        "LIMIT 200"
    ),
}


def summarize(findings_df: Any, spark: Any) -> SummaryReport:
    """Register a temp view and compute the 10 rollup DataFrames."""
    findings_df.createOrReplaceTempView(_FINDINGS_VIEW)
    return SummaryReport(**{name: spark.sql(sql)
                            for name, sql in _QUERIES.items()})
