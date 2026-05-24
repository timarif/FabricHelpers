"""Tests for ai.runner — argument validation, options, friendly errors.

End-to-end SparkSession exercise is intentionally NOT done here (requires
the Fabric runtime / a working local Spark). The pure-Python validation
paths and the friendly errors are what we test.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from fabric_scanner.ai.runner import (
    AIAuditOptions,
    BudgetExceededError,
    ensure_ai_functions_available,
    run_ai_audit,
)
from fabric_scanner.config import ScannerConfig

# --- AIAuditOptions defaults + validation ---------------------------------

def test_default_options_values():
    o = AIAuditOptions()
    assert o.ai_output_table == "notebook_ai_audit_results"
    assert o.ai_chunks_table == "notebook_ai_audit_chunks"
    assert o.ai_max_content_chars == 14000
    assert o.ai_min_chunk_chars == 0
    assert o.ai_max_chunks_per_notebook == 50
    assert o.ai_max_total_chunks is None
    assert o.ai_fail_on_error is False
    assert o.write_chunks_table is True
    assert isinstance(o.run_id, str) and len(o.run_id) > 0


def test_each_new_options_gets_distinct_run_id():
    a = AIAuditOptions()
    b = AIAuditOptions()
    assert a.run_id != b.run_id


def test_max_content_chars_must_be_positive():
    with pytest.raises(ValueError, match="ai_max_content_chars"):
        AIAuditOptions(ai_max_content_chars=0)
    with pytest.raises(ValueError, match="ai_max_content_chars"):
        AIAuditOptions(ai_max_content_chars=-1)


def test_max_chunks_per_notebook_must_be_at_least_one():
    with pytest.raises(ValueError, match="ai_max_chunks_per_notebook"):
        AIAuditOptions(ai_max_chunks_per_notebook=0)


def test_max_total_chunks_when_set_must_be_at_least_one():
    with pytest.raises(ValueError, match="ai_max_total_chunks"):
        AIAuditOptions(ai_max_total_chunks=0)
    # None is allowed
    AIAuditOptions(ai_max_total_chunks=None)


def test_options_is_frozen():
    import dataclasses
    o = AIAuditOptions()
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.ai_max_content_chars = 9999  # type: ignore[misc]


# --- run_ai_audit early-rejects api source_mode ---------------------------

def test_api_mode_raises_immediately():
    cfg = ScannerConfig(source_mode="api")
    opts = AIAuditOptions()
    spark = MagicMock()
    with pytest.raises(RuntimeError, match="lakehouse"):
        run_ai_audit(cfg, opts, spark)


# --- ensure_ai_functions_available friendly error -------------------------

def test_ensure_ai_functions_friendly_error(monkeypatch):
    # Force the import to fail by inserting a stub that raises.
    fake_synapse = type(sys)("synapse")
    fake_ml = type(sys)("synapse.ml")
    fake_spark = type(sys)("synapse.ml.spark")
    monkeypatch.setitem(sys.modules, "synapse", fake_synapse)
    monkeypatch.setitem(sys.modules, "synapse.ml", fake_ml)
    monkeypatch.setitem(sys.modules, "synapse.ml.spark", fake_spark)
    # synapse.ml.spark exists but `aifunc` attribute missing → ImportError
    # from `from synapse.ml.spark import aifunc`
    with pytest.raises(RuntimeError, match="AI functions"):
        ensure_ai_functions_available()


# --- BudgetExceededError is a RuntimeError --------------------------------

def test_budget_exceeded_is_runtime_error():
    assert issubclass(BudgetExceededError, RuntimeError)


# --- AIAuditOptions can be passed run_id explicitly -----------------------

def test_explicit_run_id_preserved():
    o = AIAuditOptions(run_id="custom-run-123")
    assert o.run_id == "custom-run-123"


# --- _ctx_fn_for_rows (regression test for the `workspace_id` crash) -----

class _FakeRow:
    """Mimics `pyspark.sql.Row.__getitem__` semantics: a missing str key
    raises `ValueError` (Row internally calls `__fields__.index(key)`,
    which is `list.index`'s native exception)."""

    def __init__(self, **fields):
        self._fields = fields

    def __getitem__(self, key):
        try:
            return self._fields[key]
        except KeyError:
            raise ValueError(f"{key!r} is not in list")

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError as e:
            raise AttributeError(name) from e


def _resolved_stub(**overrides):
    """Build a minimal `ResolvedPaths`-shaped object for `_ctx_fn_for_rows`."""
    from types import SimpleNamespace
    base = dict(
        source_lakehouse_id="lh-1",
        source_lakehouse_name="LH-1",
        source_workspace_id="ws-resolved",
        source_workspace_name="WS-Resolved",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_ctx_fn_for_row_missing_workspace_id_falls_back_to_resolved():
    """The exact failure mode that crashed step 3 of the AI auditor notebook:
    binaryFile reader rows have no `workspace_id` column, and Row[str]
    raises ValueError when the field is missing. The context extractor
    must absorb that and use `resolved.source_workspace_id` instead."""
    from fabric_scanner.ai.runner import _ctx_fn_for_rows
    ctx_fn = _ctx_fn_for_rows(_resolved_stub(), {"ws-resolved": "WS-Resolved"})
    row = _FakeRow(path="/lake/Files/exports/x.ipynb", content=b"...")
    ctx = ctx_fn(row)
    assert ctx["workspace_id"] == "ws-resolved"
    assert ctx["workspace_name"] == "WS-Resolved"
    assert ctx["source_dated_partition"] is None
    assert ctx["source_lakehouse_id"] == "lh-1"


def test_ctx_fn_for_row_with_workspace_id_uses_it():
    from fabric_scanner.ai.runner import _ctx_fn_for_rows
    ctx_fn = _ctx_fn_for_rows(_resolved_stub(), {"ws-from-path": "WS-FromPath"})
    row = _FakeRow(
        path="/lake/Files/exports/ws-from-path/20260522/n.ipynb",
        content=b"...",
        workspace_id="ws-from-path",
        source_dated_partition="20260522",
    )
    ctx = ctx_fn(row)
    assert ctx["workspace_id"] == "ws-from-path"
    assert ctx["workspace_name"] == "WS-FromPath"
    assert ctx["source_dated_partition"] == "20260522"


def test_ctx_fn_for_row_with_real_pyspark_row_missing_workspace_id():
    """Smoke test against the actual pyspark.sql.Row class, which is the
    source of the ValueError we're defending against."""
    pyspark = pytest.importorskip("pyspark")  # noqa: F841
    from pyspark.sql import Row
    from fabric_scanner.ai.runner import _ctx_fn_for_rows
    ctx_fn = _ctx_fn_for_rows(_resolved_stub(), {})
    row = Row(path="/x/y.ipynb", content=b"...")
    ctx = ctx_fn(row)
    assert ctx["workspace_id"] == "ws-resolved"
