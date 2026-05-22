"""The Spark `StructType` for the unified v2 findings table.

Field order + types here are the contract between `partition.scan_row` /
`partition.fetch_row` (which emit dicts with these exact keys) and the
DataFrame that `runner.run` finally writes. Adding a column means
touching: this file, `partition.scan_row`, the `_empty_row_dict` helper,
and at least one unit test.
"""
from __future__ import annotations


def _build_schema():
    # Lazy import so `import fabric_scanner.spark.schema` doesn't blow up
    # on an engine-only install (used by tests that just check field
    # names against the row dict).
    from pyspark.sql.types import (
        BooleanType, IntegerType, StringType, StructField, StructType,
        TimestampType,
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
        StructField("part_path",                         StringType(),   True),
        StructField("source_kind",                       StringType(),   True),
        StructField("cell_index",                        IntegerType(),  True),
        StructField("line_number",                       IntegerType(),  True),
        StructField("finding_type",                      StringType(),   True),
        StructField("category",                          StringType(),   True),
        StructField("severity",                          StringType(),   True),
        StructField("message",                           StringType(),   True),
        StructField("code_snippet",                      StringType(),   True),
        StructField("url",                               StringType(),   True),
        StructField("direction",                         StringType(),   True),
        StructField("dest_workspace_id",                 StringType(),   True),
        StructField("dest_workspace_name",               StringType(),   True),
        StructField("cross_workspace",                   BooleanType(),  True),
        StructField("error",                             StringType(),   True),
        StructField("scanned_at",                        TimestampType(), True),
    ])


# Public column list — keep in sync with `_build_schema`. Used by row
# builders to ensure every emitted dict has the same keys regardless of
# whether a value is present.
RESULT_COLUMNS: tuple[str, ...] = (
    "workspace_id", "workspace_name",
    "source_lakehouse_id", "source_lakehouse_name", "source_dated_partition",
    "notebook_id", "display_name",
    "attached_lakehouse_id", "attached_lakehouse_name",
    "attached_lakehouse_workspace_id", "attached_lakehouse_workspace_name",
    "part_path", "source_kind",
    "cell_index", "line_number",
    "finding_type", "category", "severity", "message", "code_snippet",
    "url", "direction",
    "dest_workspace_id", "dest_workspace_name", "cross_workspace",
    "error", "scanned_at",
)


def result_schema():
    """Return the v2 findings StructType. Cached on first call."""
    global _CACHED
    try:
        return _CACHED
    except NameError:
        _CACHED = _build_schema()
        return _CACHED
