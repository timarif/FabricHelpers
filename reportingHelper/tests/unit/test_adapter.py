"""Unit tests for ``fabric_reporting.adapter.ReportingAdapter``.

Uses a ``MagicMock`` Spark session so these run without PySpark installed.
The mock captures the arguments passed to ``createDataFrame``, ``write``,
and ``sql`` so we can verify the adapter behaves correctly.

``_get_spark_schemas`` is also patched to return ``None``-keyed dicts because
real ``pyspark.sql.types`` are not available in the unit-test environment.
The mock SparkSession does not inspect the schema argument anyway.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from fabric_reporting.adapter import ReportingAdapter
from fabric_reporting.models import TABLE_REGISTRY

# Sentinel schema value — the mock SparkSession ignores the schema argument.
_MOCK_SCHEMA = object()
_MOCK_SCHEMAS = {name: _MOCK_SCHEMA for name in TABLE_REGISTRY}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spark() -> MagicMock:
    """Build a minimal mock SparkSession."""
    spark = MagicMock(name="SparkSession")
    # createDataFrame returns a mock DataFrame
    df_mock = MagicMock(name="DataFrame")
    df_mock.write.format.return_value.mode.return_value.save = MagicMock()
    spark.createDataFrame.return_value = df_mock
    return spark


def _make_adapter(path: str = "/tmp/test_lh") -> tuple[ReportingAdapter, MagicMock]:
    spark = _make_spark()
    return ReportingAdapter(spark, path), spark


@pytest.fixture(autouse=True)
def _patch_spark_schemas(monkeypatch):
    """Patch _get_spark_schemas so adapter tests run without PySpark."""
    monkeypatch.setattr(
        "fabric_reporting.adapter._get_spark_schemas",
        lambda: _MOCK_SCHEMAS,
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_empty_path_raises():
    spark = _make_spark()
    with pytest.raises(ValueError, match="lakehouse_path"):
        ReportingAdapter(spark, "")


def test_trailing_slash_stripped():
    adapter, _ = _make_adapter("/tmp/lh/")
    assert adapter._path == "/tmp/lh"


# ---------------------------------------------------------------------------
# _table_path
# ---------------------------------------------------------------------------

def test_table_path():
    adapter, _ = _make_adapter("/tmp/lh")
    assert adapter._table_path("fact_scan_findings") == "/tmp/lh/fact_scan_findings"


# ---------------------------------------------------------------------------
# ensure_tables
# ---------------------------------------------------------------------------

class TestEnsureTables:
    def test_creates_all_six_tables(self):
        adapter, spark = _make_adapter()
        adapter.ensure_tables()

        # One createDataFrame call per canonical table
        assert spark.createDataFrame.call_count == len(TABLE_REGISTRY)

        # Each was called with an empty list
        for c in spark.createDataFrame.call_args_list:
            rows_arg = c[0][0]
            assert rows_arg == [], f"Expected empty list, got {rows_arg!r}"

    def test_write_uses_ignore_mode(self):
        adapter, spark = _make_adapter()
        adapter.ensure_tables()

        df_mock = spark.createDataFrame.return_value
        mode_calls = [
            str(c) for c in df_mock.write.format.return_value.mode.call_args_list
        ]
        assert all("ignore" in c for c in mode_calls), (
            f"All ensure_tables writes should use mode('ignore'), got: {mode_calls}"
        )

    def test_write_uses_delta_format(self):
        adapter, spark = _make_adapter()
        adapter.ensure_tables()

        df_mock = spark.createDataFrame.return_value
        format_calls = [
            str(c) for c in df_mock.write.format.call_args_list
        ]
        assert all("delta" in c for c in format_calls), (
            f"All ensure_tables writes should use format('delta'), got: {format_calls}"
        )


# ---------------------------------------------------------------------------
# write_facts — empty list
# ---------------------------------------------------------------------------

def test_write_facts_empty_list_is_noop():
    adapter, spark = _make_adapter()
    n = adapter.write_facts("fact_scan_findings", [])
    assert n == 0
    spark.createDataFrame.assert_not_called()


# ---------------------------------------------------------------------------
# write_facts — unknown table
# ---------------------------------------------------------------------------

def test_write_facts_unknown_table_raises():
    adapter, _ = _make_adapter()
    with pytest.raises(KeyError, match="no_such_table"):
        adapter.write_facts("no_such_table", [{"finding_id": "x"}])


# ---------------------------------------------------------------------------
# write_facts — schema validation
# ---------------------------------------------------------------------------

def test_write_facts_invalid_row_raises_validation_error():
    adapter, _ = _make_adapter()
    with pytest.raises(ValidationError):
        adapter.write_facts("fact_scan_findings", [{"severity": "oops"}])


# ---------------------------------------------------------------------------
# write_facts — happy path
# ---------------------------------------------------------------------------

class TestWriteFacts:
    def _finding_row(self) -> dict:
        return {
            "finding_id": "f-001",
            "scan_run_id": "run-2024",
            "workspace_id": "ws-001",
            "severity": "high",
            "kind": "entropy",
        }

    def test_returns_row_count(self):
        adapter, spark = _make_adapter()
        rows = [self._finding_row(), {**self._finding_row(), "finding_id": "f-002"}]
        n = adapter.write_facts("fact_scan_findings", rows)
        assert n == 2

    def test_creates_dataframe_with_rows(self):
        adapter, spark = _make_adapter()
        row = self._finding_row()
        adapter.write_facts("fact_scan_findings", [row])
        # createDataFrame called once (write path only — ensure_tables not called here)
        spark.createDataFrame.assert_called_once()
        first_arg = spark.createDataFrame.call_args[0][0]
        assert isinstance(first_arg, list)
        assert len(first_arg) == 1
        assert first_arg[0]["finding_id"] == "f-001"

    def test_merge_sql_is_executed(self):
        adapter, spark = _make_adapter("/tmp/lh")
        adapter.write_facts("fact_scan_findings", [self._finding_row()])
        sql_calls = [str(c) for c in spark.sql.call_args_list]
        assert any("MERGE INTO" in c for c in sql_calls), (
            f"Expected a MERGE INTO call; got: {sql_calls}"
        )

    def test_merge_uses_primary_key(self):
        adapter, spark = _make_adapter("/tmp/lh")
        adapter.write_facts("fact_scan_findings", [self._finding_row()])
        sql_calls = " ".join(str(c) for c in spark.sql.call_args_list)
        assert "finding_id" in sql_calls, "MERGE should reference the PK column 'finding_id'"

    def test_temp_view_is_dropped_after_write(self):
        adapter, spark = _make_adapter()
        adapter.write_facts("fact_scan_findings", [self._finding_row()])
        assert spark.catalog.dropTempView.called

    def test_dim_severity_happy_path(self):
        adapter, spark = _make_adapter()
        rows = [{"severity": "critical", "ordinal": 0, "color": "#C00000"}]
        n = adapter.write_facts("dim_severity", rows)
        assert n == 1
