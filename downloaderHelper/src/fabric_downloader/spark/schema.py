"""The Spark `StructType` for the unified download manifest table.

Field order + types here are the contract between
`partition.download_partition` (which emits dicts with these exact keys)
and the DataFrame the runner finally writes.
"""
from __future__ import annotations


MANIFEST_COLUMNS: tuple[str, ...] = (
    "workspace_id", "workspace_name",
    "item_type",
    "item_id", "display_name",
    "rel_path", "primary_target", "item_json_target",
    "export_format",
    "part_count", "parts_saved",
    "has_content_part",
    "payload_bytes",
    "attempts", "token_refreshes",
    "http_status",
    "status", "error",
    "run_label", "downloaded_at",
)


def _build_schema():
    # Lazy import so `import fabric_downloader.spark.schema` doesn't blow
    # up on an engine-only install (used by tests that just check field
    # names against the row dict).
    from pyspark.sql.types import (
        BooleanType, IntegerType, LongType, StringType, StructField,
        StructType, TimestampType,
    )
    return StructType([
        StructField("workspace_id",     StringType(),   True),
        StructField("workspace_name",   StringType(),   True),
        StructField("item_type",        StringType(),   True),
        StructField("item_id",          StringType(),   True),
        StructField("display_name",     StringType(),   True),
        StructField("rel_path",         StringType(),   True),
        StructField("primary_target",   StringType(),   True),
        StructField("item_json_target", StringType(),   True),
        StructField("export_format",    StringType(),   True),
        StructField("part_count",       IntegerType(),  True),
        StructField("parts_saved",      IntegerType(),  True),
        StructField("has_content_part", BooleanType(),  True),
        StructField("payload_bytes",    LongType(),     True),
        StructField("attempts",         IntegerType(),  True),
        StructField("token_refreshes",  IntegerType(),  True),
        StructField("http_status",      IntegerType(),  True),
        StructField("status",           StringType(),   True),
        StructField("error",            StringType(),   True),
        StructField("run_label",        StringType(),   True),
        StructField("downloaded_at",    TimestampType(), True),
    ])


def manifest_schema():
    """Return the download manifest StructType. Cached on first call."""
    global _CACHED
    try:
        return _CACHED
    except NameError:
        _CACHED = _build_schema()
        return _CACHED
