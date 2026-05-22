"""Tests for ai.schema."""
from __future__ import annotations

import pytest

pyspark = pytest.importorskip("pyspark")

from fabric_scanner.ai.schema import (  # noqa: E402
    AI_CHUNK_COLUMNS,
    AI_CHUNK_PRE_AI_COLUMNS,
    AI_RESULT_COLUMNS,
    ai_chunk_pre_ai_schema,
    ai_chunk_schema,
    ai_result_schema,
)


def test_column_lists_match_schema_fields():
    chunk_fields = [f.name for f in ai_chunk_schema().fields]
    assert chunk_fields == list(AI_CHUNK_COLUMNS)

    result_fields = [f.name for f in ai_result_schema().fields]
    assert result_fields == list(AI_RESULT_COLUMNS)

    pre_ai_fields = [f.name for f in ai_chunk_pre_ai_schema().fields]
    assert pre_ai_fields == list(AI_CHUNK_PRE_AI_COLUMNS)


def test_enrichment_columns_match_findings_table():
    """The 11 enrichment columns + their types must match the rule-based
    findings table so the two tables can JOIN cleanly."""
    from fabric_scanner.spark.schema import result_schema as findings_schema

    # Pull the relevant subset of fields by name, in declared order.
    enrichment_cols = [
        "workspace_id", "workspace_name",
        "source_lakehouse_id", "source_lakehouse_name",
        "source_dated_partition",
        "notebook_id", "display_name",
        "attached_lakehouse_id", "attached_lakehouse_name",
        "attached_lakehouse_workspace_id",
        "attached_lakehouse_workspace_name",
    ]
    findings_by_name = {f.name: f for f in findings_schema().fields}
    ai_by_name = {f.name: f for f in ai_result_schema().fields}

    for col in enrichment_cols:
        assert col in findings_by_name, f"missing in findings: {col}"
        assert col in ai_by_name, f"missing in ai_result: {col}"
        # Same type
        assert findings_by_name[col].dataType == ai_by_name[col].dataType, (
            f"type mismatch for {col}")


def test_chunk_has_score_columns():
    cols = [f.name for f in ai_chunk_schema().fields]
    assert "external_resource_access_score" in cols
    assert "exfiltration_risk_score" in cols
    assert "sources" in cols
    assert "destinations" in cols
    assert "rationale" in cols


def test_result_has_aggregate_columns():
    cols = [f.name for f in ai_result_schema().fields]
    assert "chunks_parsed" in cols
    assert "chunks_errored" in cols
    assert "top_rationale" in cols


def test_provenance_columns_present():
    for s in (ai_chunk_schema(), ai_result_schema()):
        cols = [f.name for f in s.fields]
        assert "auditor_version" in cols
        assert "prompt_version" in cols
        assert "run_id" in cols
        assert "assessed_at" in cols


def test_schemas_cached():
    s1 = ai_chunk_schema()
    s2 = ai_chunk_schema()
    assert s1 is s2
    r1 = ai_result_schema()
    r2 = ai_result_schema()
    assert r1 is r2
