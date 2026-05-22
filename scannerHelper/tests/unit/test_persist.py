"""Tests for `fabric_scanner.persist` — SummaryReport shape + SQL strings.

Live Spark execution of the queries is deferred to integration tests.
Here we just guard against typos in the SQL templates (e.g. wrong view
name, missing columns) by string-checking each query.
"""
from __future__ import annotations

import pytest

from fabric_scanner.persist import SummaryReport, _FINDINGS_VIEW, _QUERIES


def test_summary_report_has_ten_fields():
    """The user-facing dataclass must expose all 10 rollups."""
    from dataclasses import fields
    names = {f.name for f in fields(SummaryReport)}
    expected = {
        "by_severity", "by_category_severity", "top_notebooks",
        "url_directions", "cross_workspace_flows", "by_attached_lakehouse",
        "cross_workspace_lh", "needs_update", "review_queue",
        "sample_critical",
    }
    assert names == expected


def test_queries_dict_matches_report_fields():
    from dataclasses import fields
    report_fields = {f.name for f in fields(SummaryReport)}
    assert set(_QUERIES.keys()) == report_fields


@pytest.mark.parametrize("name,sql", list(_QUERIES.items()))
def test_each_query_references_the_findings_view(name, sql):
    assert _FINDINGS_VIEW in sql, (
        f"Query '{name}' does not reference {_FINDINGS_VIEW}")


@pytest.mark.parametrize("name,sql", list(_QUERIES.items()))
def test_each_query_starts_with_select(name, sql):
    assert sql.strip().upper().startswith("SELECT"), (
        f"Query '{name}' should start with SELECT")


def test_review_queue_includes_all_status_labels():
    """Catch dropped status labels in the long CASE expression."""
    sql = _QUERIES["review_queue"]
    for status in (
        "critical_review", "cross_workspace_write", "dynamic_exec_review",
        "high_entropy_review", "flag_for_review", "needs_update_review",
        "url_writes_only", "informational", "clean",
    ):
        assert status in sql, f"review_queue missing status '{status}'"
