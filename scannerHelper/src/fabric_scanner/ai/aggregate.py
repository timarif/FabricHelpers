"""Per-chunk → per-notebook aggregation for the AI auditor.

`parse_ai_response_df(audit_df)` projects raw AI responses into typed
columns (defensive parsing — clamps scores, defaults null arrays to
empty).

`aggregate_chunks_to_notebooks(parsed_df)` rolls up the chunk-level
table to one row per notebook. `top_rationale` is the rationale from
the chunk with the highest `exfiltration_risk_score` (ties broken by
`external_resource_access_score`, then by chunk_index). This is more
useful than concatenating all rationales.
"""
from __future__ import annotations

from typing import Any


def _parsed_struct_type():
    """Return the StructType matching AI_AUDIT_RESPONSE_FORMAT for
    `F.from_json` parsing of the raw `ai_response` string."""
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        IntegerType,
        StringType,
        StructField,
        StructType,
    )
    ep = StructType([
        StructField("endpoint",      StringType(),  True),
        StructField("type",          StringType(),  True),
        StructField("deterministic", BooleanType(), True),
    ])
    return StructType([
        StructField("external_resource_access_score", IntegerType(),  True),
        StructField("exfiltration_risk_score",        IntegerType(),  True),
        StructField("sources",                        ArrayType(ep),  True),
        StructField("destinations",                   ArrayType(ep),  True),
        StructField("rationale",                      StringType(),   True),
    ])


def _any_leaf_non_null(col: Any, dtype: Any) -> Any:
    """Build a Column expression that is True iff any leaf field of `col`
    (with declared type `dtype`) is non-null. Recursively walks nested
    StructTypes. Returns ``F.lit(False)`` for an empty struct.
    """
    from functools import reduce

    from pyspark.sql import functions as F
    from pyspark.sql.types import StructType

    if isinstance(dtype, StructType):
        if not dtype.fields:
            return F.lit(False)
        sub = [_any_leaf_non_null(col.getField(f.name), f.dataType)
               for f in dtype.fields]
        return reduce(lambda a, b: a | b, sub)
    return col.isNotNull()


def _normalize_ai_error_to_string(df: Any) -> Any:
    """Coerce the ``ai_error`` column to StringType.

    Background: Microsoft Fabric's ``df.ai.generate_response(...,
    error_col="ai_error")`` writes the error column as a STRUCT matching
    the underlying SynapseML HTTP envelope -- typically
    ``STRUCT<response: STRING, status: STRUCT<protocolVersion, statusCode,
    reasonPhrase>>``. The previous implementation of
    :func:`parse_ai_response_df` assumed StringType, which caused an
    ``AnalysisException`` ("Input to casewhen should all be the same type,
    but it's [STRING, STRUCT<...>]") when the downstream parse_error
    branch mixed a string literal with the struct column.

    Behavior:
      - If ``ai_error`` is already StringType (or absent), the DataFrame
        is returned unchanged (preserves the older string-based contract
        that unit tests rely on).
      - If ``ai_error`` is a StructType, rows where every leaf field is
        null are mapped to NULL (success), and rows with any populated
        leaf are mapped to ``to_json(ai_error)`` so downstream code sees
        a non-null string error message.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.types import StructType

    if "ai_error" not in df.columns:
        return df
    err_field = df.schema["ai_error"]
    if not isinstance(err_field.dataType, StructType):
        return df

    has_error = _any_leaf_non_null(F.col("ai_error"), err_field.dataType)
    return df.withColumn(
        "ai_error",
        F.when(has_error, F.to_json(F.col("ai_error")))
         .otherwise(F.lit(None).cast("string")),
    )


def parse_ai_response_df(audit_df: Any) -> Any:
    """Parse the `ai_response` JSON column into typed fields.

    Defensive:
      - the ``ai_error`` column is normalized to StringType when Fabric's
        ``df.ai.generate_response`` writes it as a STRUCT (HTTP envelope)
      - rows with `ai_error IS NOT NULL` get NULL parsed fields
      - scores outside [0, 100] are clamped
      - null arrays become empty arrays
      - parse failure leaves the row with NULL parsed fields AND a
        synthesized `ai_error` ('parse_error: <msg>') so the chunks
        table reflects the failure

    Returns a DataFrame matching `ai_chunk_schema()` column order.
    """
    from pyspark.sql import functions as F

    parsed_t = _parsed_struct_type()

    # Normalize ai_error first so the CASE WHEN below mixes only strings.
    audit_df = _normalize_ai_error_to_string(audit_df)

    # Parse — null when ai_response is null OR not valid JSON of the right shape.
    df = audit_df.withColumn(
        "_parsed", F.from_json(F.col("ai_response"), parsed_t))

    # Detect parse failures: ai_error is null AND ai_response is non-null AND
    # _parsed is null OR _parsed.external_resource_access_score is null (the
    # schema is strict so a successful parse must populate all required keys).
    parse_failed = (
        F.col("ai_error").isNull()
        & F.col("ai_response").isNotNull()
        & (F.col("_parsed").isNull()
           | F.col("_parsed.external_resource_access_score").isNull())
    )

    df = df.withColumn(
        "ai_error",
        F.when(parse_failed,
               F.lit("parse_error: response did not match expected schema"))
         .otherwise(F.col("ai_error")),
    )

    def _clamp(col, lo=0, hi=100):
        return F.when(col.isNull(), F.lit(None)) \
                .when(col < F.lit(lo), F.lit(lo)) \
                .when(col > F.lit(hi), F.lit(hi)) \
                .otherwise(col)

    empty_endpoints = F.array().cast("array<struct<endpoint:string,type:string,"
                                     "deterministic:boolean>>")

    df = df.withColumn(
        "external_resource_access_score",
        F.when(F.col("ai_error").isNotNull(), F.lit(None))
         .otherwise(_clamp(F.col("_parsed.external_resource_access_score"))),
    ).withColumn(
        "exfiltration_risk_score",
        F.when(F.col("ai_error").isNotNull(), F.lit(None))
         .otherwise(_clamp(F.col("_parsed.exfiltration_risk_score"))),
    ).withColumn(
        "sources",
        F.when(F.col("ai_error").isNotNull(), empty_endpoints)
         .otherwise(F.coalesce(F.col("_parsed.sources"), empty_endpoints)),
    ).withColumn(
        "destinations",
        F.when(F.col("ai_error").isNotNull(), empty_endpoints)
         .otherwise(F.coalesce(F.col("_parsed.destinations"), empty_endpoints)),
    ).withColumn(
        "rationale",
        F.when(F.col("ai_error").isNotNull(), F.lit(None))
         .otherwise(F.col("_parsed.rationale")),
    )

    # Drop the helper column. Caller is responsible for stamping
    # auditor_version/prompt_version/run_id/assessed_at columns before
    # this is written to the chunks table.
    return df.drop("_parsed")


def aggregate_chunks_to_notebooks(parsed_df: Any) -> Any:
    """Aggregate per-chunk rows into one row per notebook.

    Returns a DataFrame matching `ai_result_schema()` column order, minus
    the provenance columns (auditor_version, prompt_version, run_id,
    assessed_at) — the runner stamps those.

    Aggregation strategy:
      - `max(score)` across all chunks for both scores
      - `array_distinct(flatten(collect_list(sources)))` for sources/dests
      - `chunks_total = chunks_parsed + chunks_errored`
      - `chunks_parsed = COUNT(ai_error IS NULL)`
      - `chunks_errored = COUNT(ai_error IS NOT NULL)`
      - `top_rationale` = rationale from the chunk with the highest
        exfiltration_risk_score (ties → highest external_resource_access_score,
        ties → lowest chunk_index)
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    empty_endpoints = F.array().cast(
        "array<struct<endpoint:string,type:string,deterministic:boolean>>")

    # Rank chunks within each notebook to pick top_rationale.
    w = Window.partitionBy("notebook_id").orderBy(
        F.coalesce(F.col("exfiltration_risk_score"), F.lit(-1)).desc(),
        F.coalesce(F.col("external_resource_access_score"), F.lit(-1)).desc(),
        F.col("chunk_index").asc(),
    )
    ranked = parsed_df.withColumn("_rank", F.row_number().over(w))

    top_rationale_df = (ranked
        .filter(F.col("_rank") == 1)
        .select(F.col("notebook_id").alias("_n"),
                F.col("rationale").alias("top_rationale")))

    grouped = (parsed_df.groupBy(
            "workspace_id", "workspace_name",
            "source_lakehouse_id", "source_lakehouse_name",
            "source_dated_partition",
            "notebook_id", "display_name",
            "attached_lakehouse_id", "attached_lakehouse_name",
            "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
            "content_length", "content_hash",
        )
        .agg(
            F.max("chunk_count").alias("chunk_count"),
            F.sum(F.when(F.col("ai_error").isNull(), 1).otherwise(0))
             .cast("int").alias("chunks_parsed"),
            F.sum(F.when(F.col("ai_error").isNotNull(), 1).otherwise(0))
             .cast("int").alias("chunks_errored"),
            F.max("external_resource_access_score")
             .alias("external_resource_access_score"),
            F.max("exfiltration_risk_score")
             .alias("exfiltration_risk_score"),
            F.array_distinct(F.flatten(
                F.collect_list(F.coalesce(F.col("sources"), empty_endpoints))
            )).alias("sources"),
            F.array_distinct(F.flatten(
                F.collect_list(F.coalesce(F.col("destinations"),
                                           empty_endpoints))
            )).alias("destinations"),
        ))

    joined = grouped.join(top_rationale_df,
                          grouped.notebook_id == top_rationale_df._n,
                          how="left").drop("_n")

    return joined.select(
        "workspace_id", "workspace_name",
        "source_lakehouse_id", "source_lakehouse_name",
        "source_dated_partition",
        "notebook_id", "display_name",
        "attached_lakehouse_id", "attached_lakehouse_name",
        "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
        "content_length", "content_hash",
        "chunk_count", "chunks_parsed", "chunks_errored",
        "external_resource_access_score", "exfiltration_risk_score",
        "sources", "destinations", "top_rationale",
    )
