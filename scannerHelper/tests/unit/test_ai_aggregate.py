"""Tests for ai.aggregate.

Uses a real local SparkSession (via the `spark` fixture in conftest.py).
Skipped when pyspark is not installed.
"""
from __future__ import annotations

import json

import pytest

pyspark = pytest.importorskip("pyspark")

from fabric_scanner.ai.aggregate import (  # noqa: E402
    aggregate_chunks_to_notebooks,
    parse_ai_response_df,
)

# Small helper to build a chunk-level DataFrame matching the shape
# `parse_ai_response_df` expects (pre-AI columns + ai_response + ai_error).

def _make_audit_df(spark, rows):
    """rows is a list of dicts with keys:
       path, chunk_index, chunk_count, ai_response, ai_error,
       optionally workspace_id, display_name, source_dated_partition, etc.
    """
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
    base = [
        ("workspace_id",                      StringType()),
        ("workspace_name",                    StringType()),
        ("source_lakehouse_id",               StringType()),
        ("source_lakehouse_name",             StringType()),
        ("source_dated_partition",            StringType()),
        ("notebook_id",                       StringType()),
        ("display_name",                      StringType()),
        ("attached_lakehouse_id",             StringType()),
        ("attached_lakehouse_name",           StringType()),
        ("attached_lakehouse_workspace_id",   StringType()),
        ("attached_lakehouse_workspace_name", StringType()),
        ("content_length",                    LongType()),
        ("content_hash",                      StringType()),
        ("chunk_index",                       IntegerType()),
        ("chunk_count",                       IntegerType()),
        ("chunk_text",                        StringType()),
        ("ai_response",                       StringType()),
        ("ai_error",                          StringType()),
    ]
    schema = StructType([StructField(n, t, True) for n, t in base])
    canonical = []
    for r in rows:
        canonical.append({n: r.get(n) for n, _ in base})
    return spark.createDataFrame(canonical, schema=schema)


# --- parse_ai_response_df --------------------------------------------------

def test_parse_extracts_typed_fields(spark):
    response = json.dumps({
        "external_resource_access_score": 60,
        "exfiltration_risk_score": 30,
        "sources": [{"endpoint": "https://x.com", "type": "https",
                     "deterministic": True}],
        "destinations": [],
        "rationale": "uses requests.get to an external URL",
    })
    df = _make_audit_df(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": response, "ai_error": None,
    }])
    parsed = parse_ai_response_df(df).collect()
    assert len(parsed) == 1
    row = parsed[0]
    assert row["external_resource_access_score"] == 60
    assert row["exfiltration_risk_score"] == 30
    assert len(row["sources"]) == 1
    assert row["sources"][0]["endpoint"] == "https://x.com"
    assert row["destinations"] == []
    assert "external URL" in row["rationale"]
    assert row["ai_error"] is None


def test_parse_clamps_out_of_range_scores(spark):
    response = json.dumps({
        "external_resource_access_score": 500,   # > 100 → clamp to 100
        "exfiltration_risk_score": -20,          # < 0 → clamp to 0
        "sources": [],
        "destinations": [],
        "rationale": "weird scores",
    })
    df = _make_audit_df(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": response, "ai_error": None,
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["external_resource_access_score"] == 100
    assert row["exfiltration_risk_score"] == 0


def test_parse_malformed_json_marks_error(spark):
    df = _make_audit_df(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": "not json at all",
        "ai_error": None,
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["ai_error"] is not None
    assert "parse_error" in row["ai_error"]
    assert row["external_resource_access_score"] is None
    assert row["exfiltration_risk_score"] is None
    assert row["sources"] == []
    assert row["destinations"] == []
    assert row["rationale"] is None


def test_parse_passes_through_ai_error(spark):
    df = _make_audit_df(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": None,
        "ai_error": "rate_limited",
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["ai_error"] == "rate_limited"
    assert row["external_resource_access_score"] is None
    assert row["sources"] == []
    assert row["destinations"] == []


# --- regression: Fabric's df.ai.generate_response writes ai_error as a STRUCT,
# not a string. parse_ai_response_df must coerce it before the parse_error
# CASE WHEN mixes the column with a string literal, otherwise Spark raises
# `[DATATYPE_MISMATCH.DATA_DIFF_TYPES] Input to casewhen should all be the
# same type, but it's [STRING, STRUCT<...>]`. -----------------------------

def _make_audit_df_struct_error(spark, rows):
    """Like `_make_audit_df`, but `ai_error` is a STRUCT matching Fabric's
    HTTP envelope schema: STRUCT<response, status<protocolVersion, statusCode,
    reasonPhrase>>. Used to reproduce the AnalysisException seen in real
    Fabric notebook runs.
    """
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
    proto_t = StructType([
        StructField("protocol", StringType(),  True),
        StructField("major",    IntegerType(), True),
        StructField("minor",    IntegerType(), True),
    ])
    status_t = StructType([
        StructField("protocolVersion", proto_t,       True),
        StructField("statusCode",      IntegerType(), True),
        StructField("reasonPhrase",    StringType(),  True),
    ])
    err_t = StructType([
        StructField("response", StringType(), True),
        StructField("status",   status_t,     True),
    ])
    base = [
        ("workspace_id",                      StringType()),
        ("workspace_name",                    StringType()),
        ("source_lakehouse_id",               StringType()),
        ("source_lakehouse_name",             StringType()),
        ("source_dated_partition",            StringType()),
        ("notebook_id",                       StringType()),
        ("display_name",                      StringType()),
        ("attached_lakehouse_id",             StringType()),
        ("attached_lakehouse_name",           StringType()),
        ("attached_lakehouse_workspace_id",   StringType()),
        ("attached_lakehouse_workspace_name", StringType()),
        ("content_length",                    LongType()),
        ("content_hash",                      StringType()),
        ("chunk_index",                       IntegerType()),
        ("chunk_count",                       IntegerType()),
        ("chunk_text",                        StringType()),
        ("ai_response",                       StringType()),
    ]
    schema = StructType(
        [StructField(n, t, True) for n, t in base]
        + [StructField("ai_error", err_t, True)],
    )
    canonical = []
    for r in rows:
        d = {n: r.get(n) for n, _ in base}
        d["ai_error"] = r.get("ai_error")
        canonical.append(d)
    return spark.createDataFrame(canonical, schema=schema)


def test_parse_coerces_struct_ai_error_top_level_null(spark):
    """Top-level null struct (Fabric's normal success contract) is treated as
    'no error' — parsing proceeds and ai_error stays NULL."""
    response = json.dumps({
        "external_resource_access_score": 30,
        "exfiltration_risk_score": 20,
        "sources": [],
        "destinations": [],
        "rationale": "ok",
    })
    df = _make_audit_df_struct_error(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": response, "ai_error": None,
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["ai_error"] is None
    assert row["external_resource_access_score"] == 30
    assert row["exfiltration_risk_score"] == 20


def test_parse_coerces_struct_ai_error_populated_http_envelope(spark):
    """Populated struct error becomes a JSON string carrying the HTTP info;
    parsed score fields are NULL and downstream aggregation can count it as
    chunks_errored."""
    df = _make_audit_df_struct_error(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": None,
        "ai_error": {
            "response": "rate limit exceeded",
            "status": {
                "protocolVersion": {"protocol": "HTTP", "major": 1, "minor": 1},
                "statusCode": 429,
                "reasonPhrase": "Too Many Requests",
            },
        },
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["ai_error"] is not None
    assert isinstance(row["ai_error"], str)
    assert "429" in row["ai_error"]
    assert "Too Many Requests" in row["ai_error"]
    assert row["external_resource_access_score"] is None
    assert row["exfiltration_risk_score"] is None


def test_parse_coerces_struct_ai_error_all_null_leaves_treated_as_success(spark):
    """A non-null struct whose every leaf field is null (defensive against
    Spark/Fabric variants that materialize the struct envelope even on
    success) is treated as 'no error' so chunks_parsed stays accurate."""
    response = json.dumps({
        "external_resource_access_score": 40,
        "exfiltration_risk_score": 10,
        "sources": [],
        "destinations": [],
        "rationale": "ok",
    })
    df = _make_audit_df_struct_error(spark, [{
        "notebook_id": "nb1", "display_name": "nb1.ipynb",
        "chunk_index": 0, "chunk_count": 1,
        "ai_response": response,
        "ai_error": {
            "response": None,
            "status": {
                "protocolVersion": {"protocol": None, "major": None, "minor": None},
                "statusCode": None,
                "reasonPhrase": None,
            },
        },
    }])
    row = parse_ai_response_df(df).collect()[0]
    assert row["ai_error"] is None
    assert row["external_resource_access_score"] == 40


def test_parse_coerces_struct_ai_error_runs_under_aggregate(spark):
    """End-to-end: parse_ai_response_df → aggregate_chunks_to_notebooks
    composes cleanly when the inbound ai_error is a STRUCT — this is the
    exact pipeline shape from runner.run_ai_audit, and the original
    AnalysisException was raised during plan analysis of this combined
    pipeline."""
    response = json.dumps({
        "external_resource_access_score": 50,
        "exfiltration_risk_score": 60,
        "sources": [],
        "destinations": [],
        "rationale": "uses external requests.get",
    })
    df = _make_audit_df_struct_error(spark, [
        {
            "notebook_id": "nb1", "display_name": "nb1.ipynb",
            "chunk_index": 0, "chunk_count": 2,
            "ai_response": response, "ai_error": None,
        },
        {
            "notebook_id": "nb1", "display_name": "nb1.ipynb",
            "chunk_index": 1, "chunk_count": 2,
            "ai_response": None,
            "ai_error": {
                "response": "service unavailable",
                "status": {
                    "protocolVersion": {"protocol": "HTTP", "major": 1, "minor": 1},
                    "statusCode": 503,
                    "reasonPhrase": "Service Unavailable",
                },
            },
        },
    ])
    parsed = parse_ai_response_df(df)
    rolled = aggregate_chunks_to_notebooks(parsed).collect()
    assert len(rolled) == 1
    row = rolled[0]
    assert row["chunk_count"] == 2
    assert row["chunks_parsed"] == 1
    assert row["chunks_errored"] == 1
    assert row["exfiltration_risk_score"] == 60
    assert row["top_rationale"] == "uses external requests.get"


# --- aggregate_chunks_to_notebooks ----------------------------------------

def _parsed_row(notebook_id, display_name, chunk_index, chunk_count,
                ext_score, exfil_score, sources, dests, rationale,
                ai_error=None,
                workspace_id="ws-1", source_dated_partition="20260522"):
    return {
        "workspace_id": workspace_id,
        "workspace_name": "ws-1 name",
        "source_lakehouse_id": "lh-1",
        "source_lakehouse_name": "Source LH",
        "source_dated_partition": source_dated_partition,
        "notebook_id": notebook_id,
        "display_name": display_name,
        "attached_lakehouse_id": "alh-1",
        "attached_lakehouse_name": "ALH",
        "attached_lakehouse_workspace_id": "aws-1",
        "attached_lakehouse_workspace_name": "AWS-1",
        "content_length": 100,
        "content_hash": "abc",
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "external_resource_access_score": ext_score,
        "exfiltration_risk_score": exfil_score,
        "sources": sources,
        "destinations": dests,
        "rationale": rationale,
        "ai_error": ai_error,
    }


def _parsed_df(spark, rows):
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
    ep = StructType([
        StructField("endpoint",      StringType(),  True),
        StructField("type",          StringType(),  True),
        StructField("deterministic", BooleanType(), True),
    ])
    schema = StructType([
        StructField("workspace_id",                      StringType(),   True),
        StructField("workspace_name",                    StringType(),   True),
        StructField("source_lakehouse_id",               StringType(),   True),
        StructField("source_lakehouse_name",             StringType(),   True),
        StructField("source_dated_partition",            StringType(),   True),
        StructField("notebook_id",                       StringType(),   True),
        StructField("display_name",                      StringType(),   True),
        StructField("attached_lakehouse_id",             StringType(),   True),
        StructField("attached_lakehouse_name",           StringType(),   True),
        StructField("attached_lakehouse_workspace_id",   StringType(),   True),
        StructField("attached_lakehouse_workspace_name", StringType(),   True),
        StructField("content_length",                    LongType(),     True),
        StructField("content_hash",                      StringType(),   True),
        StructField("chunk_index",                       IntegerType(),  True),
        StructField("chunk_count",                       IntegerType(),  True),
        StructField("external_resource_access_score",    IntegerType(),  True),
        StructField("exfiltration_risk_score",           IntegerType(),  True),
        StructField("sources",                           ArrayType(ep),  True),
        StructField("destinations",                      ArrayType(ep),  True),
        StructField("rationale",                         StringType(),   True),
        StructField("ai_error",                          StringType(),   True),
    ])
    return spark.createDataFrame(rows, schema=schema)


def test_aggregate_max_scores_across_chunks(spark):
    rows = [
        _parsed_row("nb1", "nb1.ipynb", 0, 3, 20, 10, [], [], "first"),
        _parsed_row("nb1", "nb1.ipynb", 1, 3, 80, 40, [], [], "second"),
        _parsed_row("nb1", "nb1.ipynb", 2, 3, 50, 60, [], [], "third"),
    ]
    df = _parsed_df(spark, rows)
    result = aggregate_chunks_to_notebooks(df).collect()
    assert len(result) == 1
    row = result[0]
    assert row["external_resource_access_score"] == 80
    assert row["exfiltration_risk_score"] == 60
    assert row["chunk_count"] == 3
    assert row["chunks_parsed"] == 3
    assert row["chunks_errored"] == 0


def test_aggregate_top_rationale_is_from_max_exfil_chunk(spark):
    rows = [
        _parsed_row("nb1", "nb1.ipynb", 0, 3, 99, 10, [], [], "low risk"),
        _parsed_row("nb1", "nb1.ipynb", 1, 3, 20, 90, [], [], "HIGH RISK"),
        _parsed_row("nb1", "nb1.ipynb", 2, 3, 50, 50, [], [], "medium"),
    ]
    df = _parsed_df(spark, rows)
    row = aggregate_chunks_to_notebooks(df).collect()[0]
    assert row["top_rationale"] == "HIGH RISK"


def test_aggregate_distinct_flattens_sources(spark):
    s_a = [{"endpoint": "https://a.com", "type": "https", "deterministic": True}]
    s_b = [{"endpoint": "https://a.com", "type": "https", "deterministic": True},
           {"endpoint": "https://b.com", "type": "https", "deterministic": True}]
    rows = [
        _parsed_row("nb1", "nb1.ipynb", 0, 2, 10, 10, s_a, [], "first"),
        _parsed_row("nb1", "nb1.ipynb", 1, 2, 20, 20, s_b, [], "second"),
    ]
    df = _parsed_df(spark, rows)
    row = aggregate_chunks_to_notebooks(df).collect()[0]
    endpoints = sorted(s["endpoint"] for s in row["sources"])
    assert endpoints == ["https://a.com", "https://b.com"]


def test_aggregate_counts_errored_chunks(spark):
    rows = [
        _parsed_row("nb1", "nb1.ipynb", 0, 3, 50, 50, [], [], "ok"),
        _parsed_row("nb1", "nb1.ipynb", 1, 3, None, None, [], [], None,
                    ai_error="rate_limited"),
        _parsed_row("nb1", "nb1.ipynb", 2, 3, 30, 20, [], [], "ok2"),
    ]
    df = _parsed_df(spark, rows)
    row = aggregate_chunks_to_notebooks(df).collect()[0]
    assert row["chunks_parsed"] == 2
    assert row["chunks_errored"] == 1


def test_aggregate_groups_by_notebook(spark):
    rows = [
        _parsed_row("nb1", "nb1.ipynb", 0, 1, 10, 10, [], [], "first"),
        _parsed_row("nb2", "nb2.ipynb", 0, 1, 90, 80, [], [], "second"),
    ]
    df = _parsed_df(spark, rows)
    result = aggregate_chunks_to_notebooks(df).collect()
    assert len(result) == 2
    by_id = {r["notebook_id"]: r for r in result}
    assert by_id["nb1"]["exfiltration_risk_score"] == 10
    assert by_id["nb2"]["exfiltration_risk_score"] == 80
