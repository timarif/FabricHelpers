"""Unit tests for `persist.py`. We exercise the SQL templates and the
write-mode plumbing without spinning up Spark — fake DataFrame /
SparkSession doubles record what would have been called."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from fabric_downloader import persist


# --------------------------------------------------------------------
# write_manifest — mode + path routing
# --------------------------------------------------------------------


class _FakeWriter:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []

    def _record(self, name, value=None):
        self.calls.append((name, value))
        return self

    def mode(self, m):                 return self._record("mode", m)
    def format(self, f):               return self._record("format", f)
    def option(self, k, v):            return self._record(("option", k), v)

    def saveAsTable(self, name):       return self._record("saveAsTable", name)
    def save(self, path):              return self._record("save", path)


class _FakeDF:
    def __init__(self):
        self.write = _FakeWriter()
        self._temp_view: str | None = None

    def createOrReplaceTempView(self, name):
        self._temp_view = name


def test_write_manifest_default_lakehouse_uses_saveAsTable():
    df = _FakeDF()
    persist.write_manifest(df, "my_table", write_to_default_lakehouse=True)
    calls = df.write.calls
    assert ("mode", "append") in calls
    assert ("saveAsTable", "my_table") in calls
    # Must NOT also call save()
    assert not any(name == "save" for name, _ in calls)


def test_write_manifest_external_path_uses_delta_save():
    df = _FakeDF()
    persist.write_manifest(df, "abfss://ws@host/lh/Tables/t",
                           write_to_default_lakehouse=False)
    calls = df.write.calls
    assert ("format", "delta") in calls
    assert ("mode", "append") in calls
    assert ("save", "abfss://ws@host/lh/Tables/t") in calls


def test_write_manifest_always_appends_never_overwrites():
    """The downloader explicitly accumulates runs — overwrite would be a
    silent data-loss bug. Guard against regressions."""
    df = _FakeDF()
    persist.write_manifest(df, "t", write_to_default_lakehouse=True)
    modes = [v for name, v in df.write.calls if name == "mode"]
    assert modes == ["append"]


def test_write_manifest_merges_schema_for_forward_compat():
    df = _FakeDF()
    persist.write_manifest(df, "t", write_to_default_lakehouse=True)
    opts = {k[1]: v for k, v in df.write.calls if isinstance(k, tuple)
            and k[0] == "option"}
    assert opts.get("mergeSchema") == "true"


# --------------------------------------------------------------------
# summarize — temp view + rollup SQL
# --------------------------------------------------------------------


class _FakeSpark:
    def __init__(self):
        self.queries: list[str] = []

    def sql(self, q: str):
        self.queries.append(q)
        # Return a placeholder DataFrame stand-in; tests only check identity
        return SimpleNamespace(_sql=q)


def test_summarize_registers_temp_view_and_runs_six_rollups():
    df = _FakeDF()
    spark = _FakeSpark()
    report = persist.summarize(df, spark)

    # Temp view registered with the expected (stable) name
    assert df._temp_view == "fabric_downloader_manifest_v"

    # 6 rollup queries were issued
    assert len(spark.queries) == 6

    # Every report attribute is a non-None DataFrame stand-in
    for name in ("by_status", "by_type", "by_workspace", "errors",
                 "balance_check", "run_summary"):
        v = getattr(report, name)
        assert v is not None
        assert v._sql.startswith("SELECT")


def test_rollups_reference_the_temp_view():
    df = _FakeDF()
    spark = _FakeSpark()
    persist.summarize(df, spark)
    for q in spark.queries:
        assert "fabric_downloader_manifest_v" in q


@pytest.mark.parametrize("rollup,must_contain", [
    ("by_status",     ["GROUP BY status", "total_mb"]),
    ("by_type",       ["GROUP BY item_type", "downloaded", "errors"]),
    ("by_workspace",  ["workspace_name", "GROUP BY workspace_name"]),
    ("errors",        ["status = 'error'", "http_status"]),
    ("balance_check", ["has_content_part", "parts_saved"]),
    ("run_summary",   ["GROUP BY run_label", "items_attempted",
                       "total_token_refreshes"]),
])
def test_rollup_sql_shape(rollup, must_contain):
    """Cheap schema/intent assertions on each rollup query so refactors
    don't silently change manifest semantics."""
    q = persist._QUERIES[rollup]
    for needle in must_contain:
        assert needle in q, (
            f"rollup '{rollup}' missing expected substring '{needle}' in:\n{q}")


def test_summary_report_dataclass_fields_are_explicit():
    """SummaryReport must declare every rollup as an explicit field —
    keeps `display(result.summary.X)` IDE-completable and protects
    notebook code from typos."""
    from dataclasses import fields
    names = {f.name for f in fields(persist.SummaryReport)}
    assert names == {"by_status", "by_type", "by_workspace",
                     "errors", "balance_check", "run_summary"}
