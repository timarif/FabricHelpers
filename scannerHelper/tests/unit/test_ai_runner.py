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
