"""Unit tests for ``fabric_scanner.reporting`` — the bridge to fabric-reporting.

Tests run without pyspark *and* without fabric-reporting installed:
- The conversion logic (``_findings_df_to_rows``) is tested with a simple
  mock Row.
- The ``write_scan_findings`` ImportError path is tested by temporarily
  hiding the ``fabric_reporting`` module from sys.modules.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fabric_scanner.reporting import _findings_df_to_rows, _get, write_scan_findings
from fabric_scanner.config import ScannerConfig


# ---------------------------------------------------------------------------
# _get helper
# ---------------------------------------------------------------------------

def test_get_existing_field():
    row = SimpleNamespace(foo="bar")
    assert _get(row, "foo") == "bar"


def test_get_missing_field_returns_none():
    row = SimpleNamespace()
    assert _get(row, "missing") is None


# ---------------------------------------------------------------------------
# _findings_df_to_rows
# ---------------------------------------------------------------------------

def _make_row(**kwargs):
    """Build a mock Spark Row with the given fields."""
    return SimpleNamespace(**kwargs)


def test_empty_df_returns_empty_list():
    df = MagicMock()
    df.collect.return_value = []
    assert _findings_df_to_rows(df, "run-001") == []


def test_row_mapping():
    row = _make_row(
        workspace_id="ws-001",
        source_dated_partition="2024-01-15",
        notebook_id="nb-001",
        severity="high",
        finding_type="entropy",
        code_snippet="tok='***'",
        url=None,
        scanned_at=None,
    )
    df = MagicMock()
    df.collect.return_value = [row]

    rows = _findings_df_to_rows(df, "run-001")

    assert len(rows) == 1
    r = rows[0]
    assert r["scan_run_id"] == "run-001"
    assert r["workspace_id"] == "ws-001"
    assert r["severity"] == "high"
    assert r["kind"] == "entropy"
    assert r["redacted_snippet"] == "tok='***'"
    assert r["url"] is None
    # finding_id must be a non-empty string (UUID4)
    assert r["finding_id"]


def test_each_row_gets_unique_finding_id():
    row = _make_row(workspace_id="ws", notebook_id="nb", severity="low",
                    finding_type="url", code_snippet="", url=None, scanned_at=None,
                    source_dated_partition=None)
    df = MagicMock()
    df.collect.return_value = [row, row]
    rows = _findings_df_to_rows(df, "run-x")
    assert rows[0]["finding_id"] != rows[1]["finding_id"]


# ---------------------------------------------------------------------------
# write_scan_findings — fabric_reporting not installed
# ---------------------------------------------------------------------------

def test_write_scan_findings_raises_when_reporting_not_installed():
    """If fabric_reporting is missing, a clear RuntimeError must be raised."""
    cfg = ScannerConfig(reporting_lakehouse="/tmp/rpt")
    spark = MagicMock()
    findings_df = MagicMock()
    findings_df.collect.return_value = [
        _make_row(workspace_id="ws", notebook_id="nb", severity="low",
                  finding_type="url", code_snippet="", url=None,
                  scanned_at=None, source_dated_partition=None)
    ]

    # Force the import of fabric_reporting.adapter to fail by setting the
    # module entry to None in sys.modules (Python's "blocked import" sentinel).
    blocked = {"fabric_reporting": None, "fabric_reporting.adapter": None}
    with patch.dict(sys.modules, blocked):
        with pytest.raises(RuntimeError, match="reporting_lakehouse is set but"):
            write_scan_findings(cfg, spark, findings_df, "run-001")


# ---------------------------------------------------------------------------
# ScannerConfig — reporting_lakehouse field
# ---------------------------------------------------------------------------

def test_reporting_lakehouse_defaults_to_empty():
    cfg = ScannerConfig()
    assert cfg.reporting_lakehouse == ""


def test_reporting_lakehouse_round_trip():
    cfg = ScannerConfig(reporting_lakehouse="/tmp/rpt")
    assert cfg.to_dict()["reporting_lakehouse"] == "/tmp/rpt"
    cfg2 = ScannerConfig.from_dict(cfg.to_dict())
    assert cfg2 == cfg
