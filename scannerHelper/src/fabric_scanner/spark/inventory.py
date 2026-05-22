"""Inventory DataFrame construction (one row per scanned notebook).

Two flavors:
  * Lakehouse — read the file listing via Spark `binaryFile` reader so
    every file gets a `(path, content)` pair that the partition scanner
    can chew on directly. The same DataFrame is the *scan input*; a
    projection without `content` is written to the inventory table.
  * API — start from a `[notebook_descriptor, ...]` list (from
    `api.enumerate.enumerate_notebooks`); the partition function later
    fetches the actual bytes.

Returns `(scan_df, snapshot_df, n_total)`:
  - `scan_df`: the wide DataFrame mapPartitions will iterate over.
  - `snapshot_df`: the narrow DataFrame written to the inventory table.
  - `n_total`: row count used to choose partition count.
"""
from __future__ import annotations

import re
from typing import Any

from ..paths import PATH_GUID_DATE_RE_STR


def build_inventory_lakehouse(
    config,
    resolved,
    spark: Any,
) -> tuple[Any, Any, int]:
    """Build the lakehouse-mode inventory by listing all matching files
    under `resolved.source_paths`.

    Raises RuntimeError when no files are matched (more useful than the
    legacy `SystemExit`).
    """
    from pyspark.sql import functions as F

    if not resolved.source_paths:
        raise RuntimeError(
            "build_inventory_lakehouse: no source paths to scan (did "
            "resolve_paths() return empty?)")

    file_df = (spark.read.format("binaryFile")
                 .option("recursiveFileLookup", "true")
                 .option("pathGlobFilter", config.source_file_glob)
                 .load(list(resolved.source_paths)))
    n_total = file_df.count()
    if n_total == 0:
        raise RuntimeError(
            f"No files matched glob '{config.source_file_glob}' under "
            f"{list(resolved.source_paths)}.")

    if config.max_notebooks:
        file_df = file_df.limit(config.max_notebooks)
        n_total = min(n_total, config.max_notebooks)

    src_lh_id   = resolved.source_lakehouse_id   or ""
    src_lh_name = resolved.source_lakehouse_name or src_lh_id or ""
    src_ws_id   = resolved.source_workspace_id   or ""
    src_ws_name = resolved.source_workspace_name or src_ws_id or ""

    # Try the more specific ws_dated_base anchor first (only when the
    # caller actually opted into that layout). Then fall back to the
    # universal '<anywhere>/<guid>/<datestamp>/' pattern so the
    # workspace_id and source_dated_partition columns come out right
    # for the common 'notebook_exports/<guid>/<date>/<file>' shape
    # even under the default flat layout.
    if config.source_layout == "ws_dated" and resolved.source_uri:
        base = (resolved.source_uri or "").rstrip("/")
        base_pat = re.escape(base) + r"/([^/]+)/([^/]+)/"
        base_id = F.regexp_extract(F.col("path"), base_pat, 1)
        base_dt = F.regexp_extract(F.col("path"), base_pat, 2)
    else:
        base_id = F.lit("")
        base_dt = F.lit("")

    uni_id = F.regexp_extract(F.col("path"), PATH_GUID_DATE_RE_STR, 1)
    uni_dt = F.regexp_extract(F.col("path"), PATH_GUID_DATE_RE_STR, 2)

    extracted_ws_id = (F.when(base_id != "", base_id)
                       .otherwise(F.when(uni_id != "", uni_id)
                                  .otherwise(F.lit(""))))
    extracted_ws_dt = (F.when(base_dt != "", base_dt)
                       .otherwise(F.when(uni_dt != "", uni_dt)
                                  .otherwise(F.lit(""))))

    # Final columns: extracted GUID when present, else fall back to
    # the source lakehouse's workspace. workspace_name mirrors the GUID
    # (since lakehouse mode has no friendly-name lookup).
    ws_id_col   = F.when(extracted_ws_id != "", extracted_ws_id) \
                   .otherwise(F.lit(src_ws_id))
    ws_name_col = F.when(extracted_ws_id != "", extracted_ws_id) \
                   .otherwise(F.lit(src_ws_name))
    dt_col      = F.when(extracted_ws_dt != "", extracted_ws_dt) \
                   .otherwise(F.lit(None).cast("string"))

    snapshot = file_df.select(
        ws_id_col.alias("workspace_id"),
        ws_name_col.alias("workspace_name"),
        F.lit(src_lh_id).alias("source_lakehouse_id"),
        F.lit(src_lh_name).alias("source_lakehouse_name"),
        dt_col.alias("source_dated_partition"),
        F.col("path").alias("notebook_id"),
        F.regexp_extract(F.col("path"), "([^/]+)$", 1).alias("display_name"),
    )

    return file_df, snapshot, n_total


def build_inventory_api(
    notebooks: list[dict],
    spark: Any,
) -> tuple[Any, Any, int]:
    """Build the API-mode inventory from an enumeration result.

    Both `scan_df` and `snapshot_df` are the same shape here — the
    partition function fetches the bytes lazily on the executor.
    """
    from pyspark.sql import Row

    if not notebooks:
        raise RuntimeError(
            "build_inventory_api: no notebooks to scan (enumeration "
            "returned an empty list)")

    rows = [
        Row(workspace_id=n.get("workspaceId") or "",
            workspace_name=(n.get("workspaceName")
                            or n.get("workspaceId") or ""),
            source_lakehouse_id=None,
            source_lakehouse_name=None,
            source_dated_partition=None,
            notebook_id=n.get("id") or "",
            display_name=(n.get("displayName") or ""))
        for n in notebooks
    ]
    inv = spark.createDataFrame(rows)
    n_total = len(rows)
    return inv, inv, n_total


def write_snapshot(
    snapshot_df: Any,
    target: str,
    write_to_default_lakehouse: bool,
) -> None:
    """Write the inventory snapshot to `target` (either a saveAsTable
    name or an ABFSS Delta path)."""
    if write_to_default_lakehouse:
        snapshot_df.write.mode("overwrite").option(
            "overwriteSchema", "true").saveAsTable(target)
    else:
        (snapshot_df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .save(target))


def repartition_for_scan(
    scan_df: Any, n_total: int, target_partition_size: int,
) -> Any:
    """Repartition so each partition has roughly `target_partition_size`
    notebooks. mapPartitions sees this shape."""
    n_parts = max(1, (n_total + target_partition_size - 1)
                       // target_partition_size)
    return scan_df.repartition(n_parts)
