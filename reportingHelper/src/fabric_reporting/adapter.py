"""ReportingAdapter — write canonical rows into a shared Delta lakehouse.

The adapter is the single integration point between any Fabric helper and
the shared reporting lakehouse.  Usage::

    adapter = ReportingAdapter(spark, "abfss://ws@onelake.dfs.fabric.microsoft.com/lh.Lakehouse/Tables")
    adapter.ensure_tables()
    n = adapter.write_facts("fact_scan_findings", rows)

Design notes
------------
* **Opt-in only.** Every call site guards the adapter behind a user-supplied
  configuration flag.  If the flag is absent / empty, the adapter is never
  instantiated — zero overhead for existing workflows.
* **Schema enforcement.** ``write_facts`` validates every row through the
  Pydantic model for the target table before converting to a Spark DataFrame.
  Malformed rows raise ``pydantic.ValidationError`` on the driver, not as a
  corrupt Delta commit.
* **MERGE semantics.** Facts are upserted on the table's primary key so that
  re-running a scan / download does not create duplicate rows.
* **Idempotent table creation.** ``ensure_tables`` uses ``mode("ignore")`` —
  it is safe to call on every run.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import TABLE_REGISTRY, validate_rows

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spark StructType definitions (built lazily to avoid import cost on
# engine-only installs)
# ---------------------------------------------------------------------------

def _build_spark_schemas() -> "dict[str, Any]":
    from pyspark.sql.types import (
        IntegerType, StringType, StructField, StructType, TimestampType,
    )

    def _s(*fields):
        return StructType(list(fields))

    def _f(name, dtype, nullable=True):
        return StructField(name, dtype(), nullable)

    _str  = StringType
    _int  = IntegerType
    _ts   = TimestampType

    return {
        "fact_scan_findings": _s(
            _f("finding_id",             _str, False),
            _f("scan_run_id",            _str),
            _f("workspace_id",           _str),
            _f("source_dated_partition", _str),
            _f("notebook_id",            _str),
            _f("severity",               _str),
            _f("kind",                   _str),
            _f("redacted_snippet",       _str),
            _f("url",                    _str),
            _f("detected_at",            _ts),
        ),
        "fact_downloads": _s(
            _f("download_id",   _str, False),
            _f("run_id",        _str),
            _f("workspace_id",  _str),
            _f("item_id",       _str),
            _f("item_type",     _str),
            _f("format",        _str),
            _f("downloaded_at", _ts),
            _f("bytes",         _int),
            _f("sha256",        _str),
        ),
        "fact_mpe_lifecycle": _s(
            _f("event_id",          _str, False),
            _f("workspace_id",      _str),
            _f("mpe_id",            _str),
            _f("target_resource_id", _str),
            _f("action",            _str),
            _f("actor",             _str),
            _f("timestamp",         _ts),
        ),
        "dim_workspace": _s(
            _f("workspace_id",   _str, False),
            _f("workspace_name", _str),
            _f("capacity_id",    _str),
            _f("last_seen",      _ts),
        ),
        "dim_item_type": _s(
            _f("item_type", _str, False),
            _f("family",    _str),
        ),
        "dim_severity": _s(
            _f("severity", _str, False),
            _f("ordinal",  _int, False),
            _f("color",    _str),
        ),
    }


_SPARK_SCHEMAS: "dict[str, Any] | None" = None


def _get_spark_schemas() -> "dict[str, Any]":
    global _SPARK_SCHEMAS
    if _SPARK_SCHEMAS is None:
        _SPARK_SCHEMAS = _build_spark_schemas()
    return _SPARK_SCHEMAS


# ---------------------------------------------------------------------------
# ReportingAdapter
# ---------------------------------------------------------------------------

class ReportingAdapter:
    """Write canonical reporting rows to a shared Delta lakehouse.

    Parameters
    ----------
    spark:
        A live ``pyspark.sql.SparkSession``.  Caller-owned; the adapter
        never stops or creates sessions.
    lakehouse_path:
        Root path for the reporting tables.  Every table is written to
        ``<lakehouse_path>/<table_name>``.

        Examples::

            # OneLake ABFSS
            "abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>.Lakehouse/Tables"
            # Local test path
            "/tmp/reporting_lh"
    """

    def __init__(self, spark: Any, lakehouse_path: str) -> None:
        if not lakehouse_path:
            raise ValueError("lakehouse_path must not be empty")
        # Reject backtick characters — they are used as identifiers in the
        # MERGE SQL statement and cannot be safely escaped.
        if "`" in lakehouse_path:
            raise ValueError(
                "lakehouse_path must not contain backtick characters ('`'); "
                f"got: {lakehouse_path!r}"
            )
        self._spark = spark
        self._path = lakehouse_path.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_tables(self) -> None:
        """Idempotently create all six canonical Delta tables.

        Uses ``mode("ignore")`` so existing tables are left untouched.
        Safe to call on every run.
        """
        schemas = _get_spark_schemas()
        for table_name, schema in schemas.items():
            table_path = self._table_path(table_name)
            empty_df = self._spark.createDataFrame([], schema)
            (empty_df.write
             .format("delta")
             .mode("ignore")
             .save(table_path))
            _LOG.debug("ensure_tables: %s → %s", table_name, table_path)

    def write_facts(self, table_name: str, rows: list[dict]) -> int:
        """Validate *rows* and upsert them into *table_name*.

        Parameters
        ----------
        table_name:
            One of the six canonical table names (e.g.
            ``"fact_scan_findings"``).
        rows:
            Plain dicts conforming to the Pydantic model for *table_name*.
            An empty list is a no-op.

        Returns
        -------
        int
            Number of rows written (same as ``len(rows)``).

        Raises
        ------
        KeyError
            If *table_name* is unknown.
        pydantic.ValidationError
            If any row fails Pydantic schema validation.
        """
        if not rows:
            return 0

        if table_name not in TABLE_REGISTRY:
            raise KeyError(
                f"Unknown table '{table_name}'. "
                f"Expected one of: {sorted(TABLE_REGISTRY)}"
            )

        # --- Pydantic validation -----------------------------------------
        validated = validate_rows(table_name, rows)

        # --- Convert to plain dicts (serializable by Spark) ---------------
        plain_rows = [m.model_dump() for m in validated]

        # --- Build Spark DataFrame ----------------------------------------
        schema = _get_spark_schemas()[table_name]
        new_df = self._spark.createDataFrame(plain_rows, schema=schema)

        table_path = self._table_path(table_name)
        _, pk = TABLE_REGISTRY[table_name]

        # --- MERGE into Delta table ---------------------------------------
        # Register as a temp view so the MERGE SQL stays readable.
        tmp_view = f"_rpt_{table_name}_new"
        new_df.createOrReplaceTempView(tmp_view)
        self._spark.sql(f"""
            MERGE INTO delta.`{table_path}` t
            USING {tmp_view} s
            ON t.{pk} = s.{pk}
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
        """)
        self._spark.catalog.dropTempView(tmp_view)

        _LOG.info("write_facts: %d rows → %s (%s)", len(rows), table_name, table_path)
        return len(rows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _table_path(self, table_name: str) -> str:
        return f"{self._path}/{table_name}"
