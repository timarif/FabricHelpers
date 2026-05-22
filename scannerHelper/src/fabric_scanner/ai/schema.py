"""StructTypes + column lists for the AI auditor output tables.

Two tables:

- ai_chunk_schema()   : `<chunks_table>`
    One row per (notebook, chunk_index). Operational/debug table.
    Holds the raw AI response, the chunk text we sent, and parsed
    per-chunk fields. This is the foundation for a future "resume
    from partial run" feature: we can re-run only chunks whose
    `(notebook_id, chunk_index, content_hash)` is missing.

- ai_result_schema()  : `<results_table>`
    One row per notebook (aggregated across all chunks). This is the
    table users JOIN against rule-based findings on
    `(workspace_id, source_dated_partition, display_name)`.

All four `attached_lakehouse_*` columns + `workspace_id`, `workspace_name`,
`source_lakehouse_id`, `source_lakehouse_name`, `source_dated_partition`,
`notebook_id`, `display_name` are present in BOTH the chunk and result
tables and use the same StringType columns as `spark.schema.result_schema`
so cross-table JOINs work without casts.
"""
from __future__ import annotations


def _endpoint_struct():
    """Sources/destinations element type — matches AI_AUDIT_RESPONSE_FORMAT."""
    from pyspark.sql.types import (
        BooleanType,
        StringType,
        StructField,
        StructType,
    )
    return StructType([
        StructField("endpoint",      StringType(),  True),
        StructField("type",          StringType(),  True),
        StructField("deterministic", BooleanType(), True),
    ])


def _build_chunk_schema():
    from pyspark.sql.types import (
        ArrayType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )
    ep = _endpoint_struct()
    return StructType([
        # --- Enrichment (same columns as the rule-based scanner) ----------
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
        # --- Chunk identity --------------------------------------------------
        StructField("content_length",                    LongType(),     True),
        StructField("content_hash",                      StringType(),   True),
        StructField("chunk_index",                       IntegerType(),  True),
        StructField("chunk_count",                       IntegerType(),  True),
        StructField("chunk_text",                        StringType(),   True),
        # --- AI response (populated by ai.generate_response) ----------------
        StructField("ai_response",                       StringType(),   True),
        StructField("ai_error",                          StringType(),   True),
        # --- Parsed fields (NULL when ai_error is set) ----------------------
        StructField("external_resource_access_score",    IntegerType(),  True),
        StructField("exfiltration_risk_score",           IntegerType(),  True),
        StructField("sources",                           ArrayType(ep),  True),
        StructField("destinations",                      ArrayType(ep),  True),
        StructField("rationale",                         StringType(),   True),
        # --- Provenance ------------------------------------------------------
        StructField("auditor_version",                   StringType(),   True),
        StructField("prompt_version",                    StringType(),   True),
        StructField("run_id",                            StringType(),   True),
        StructField("assessed_at",                       TimestampType(), True),
    ])


def _build_result_schema():
    from pyspark.sql.types import (
        ArrayType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )
    ep = _endpoint_struct()
    return StructType([
        # --- Enrichment ------------------------------------------------------
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
        # --- Notebook stats --------------------------------------------------
        StructField("content_length",                    LongType(),     True),
        StructField("content_hash",                      StringType(),   True),
        StructField("chunk_count",                       IntegerType(),  True),
        StructField("chunks_parsed",                     IntegerType(),  True),
        StructField("chunks_errored",                    IntegerType(),  True),
        # --- AI aggregate scores --------------------------------------------
        StructField("external_resource_access_score",    IntegerType(),  True),
        StructField("exfiltration_risk_score",           IntegerType(),  True),
        StructField("sources",                           ArrayType(ep),  True),
        StructField("destinations",                      ArrayType(ep),  True),
        StructField("top_rationale",                     StringType(),   True),
        # --- Provenance ------------------------------------------------------
        StructField("auditor_version",                   StringType(),   True),
        StructField("prompt_version",                    StringType(),   True),
        StructField("run_id",                            StringType(),   True),
        StructField("assessed_at",                       TimestampType(), True),
    ])


# Public column lists — used by row builders to ensure every emitted dict
# has the same keys regardless of whether a value is present.
AI_CHUNK_COLUMNS: tuple[str, ...] = (
    "workspace_id", "workspace_name",
    "source_lakehouse_id", "source_lakehouse_name", "source_dated_partition",
    "notebook_id", "display_name",
    "attached_lakehouse_id", "attached_lakehouse_name",
    "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
    "content_length", "content_hash",
    "chunk_index", "chunk_count", "chunk_text",
    "ai_response", "ai_error",
    "external_resource_access_score", "exfiltration_risk_score",
    "sources", "destinations", "rationale",
    "auditor_version", "prompt_version", "run_id", "assessed_at",
)

AI_RESULT_COLUMNS: tuple[str, ...] = (
    "workspace_id", "workspace_name",
    "source_lakehouse_id", "source_lakehouse_name", "source_dated_partition",
    "notebook_id", "display_name",
    "attached_lakehouse_id", "attached_lakehouse_name",
    "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
    "content_length", "content_hash",
    "chunk_count", "chunks_parsed", "chunks_errored",
    "external_resource_access_score", "exfiltration_risk_score",
    "sources", "destinations", "top_rationale",
    "auditor_version", "prompt_version", "run_id", "assessed_at",
)

# Pre-AI columns of the chunk schema — what `partition.build_chunk_rows`
# emits before `df.ai.generate_response` runs. Used by the partition row
# builder to pad fields the AI step will fill in later.
AI_CHUNK_PRE_AI_COLUMNS: tuple[str, ...] = (
    "workspace_id", "workspace_name",
    "source_lakehouse_id", "source_lakehouse_name", "source_dated_partition",
    "notebook_id", "display_name",
    "attached_lakehouse_id", "attached_lakehouse_name",
    "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
    "content_length", "content_hash",
    "chunk_index", "chunk_count", "chunk_text",
)


_CACHED_CHUNK = None
_CACHED_RESULT = None


def ai_chunk_schema():
    """Return the StructType for the per-chunk staging table."""
    global _CACHED_CHUNK
    if _CACHED_CHUNK is None:
        _CACHED_CHUNK = _build_chunk_schema()
    return _CACHED_CHUNK


def ai_result_schema():
    """Return the StructType for the per-notebook aggregate table."""
    global _CACHED_RESULT
    if _CACHED_RESULT is None:
        _CACHED_RESULT = _build_result_schema()
    return _CACHED_RESULT


def ai_chunk_pre_ai_schema():
    """Return just the columns emitted by `partition.build_chunk_rows`
    (before the AI generate_response step runs)."""
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
    return StructType([
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
        StructField("chunk_text",                        StringType(),   True),
    ])
