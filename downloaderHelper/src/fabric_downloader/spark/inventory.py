"""Inventory DataFrame construction (one row per item to download)."""
from __future__ import annotations

from typing import Any


def build_inventory(items: list[dict], spark: Any) -> tuple[Any, int]:
    """Build the download inventory from an enumeration result.

    Returns `(inventory_df, n_total)`. The DataFrame columns match the
    fields the partition function reads off each row.
    """
    from pyspark.sql import Row

    if not items:
        raise RuntimeError(
            "build_inventory: no items to download (enumeration returned "
            "an empty list)")

    rows = [
        Row(
            workspace_id=(n.get("workspaceId") or ""),
            workspace_name=(n.get("workspaceName")
                            or n.get("workspaceId") or ""),
            item_type=(n.get("type") or "Notebook"),
            item_id=(n.get("id") or ""),
            display_name=(n.get("displayName") or n.get("id") or ""),
        )
        for n in items
    ]
    n_total = len(rows)
    return spark.createDataFrame(rows), n_total


def repartition_for_download(scan_df: Any, n_total: int,
                             num_partitions: int,
                             default_parallelism: int) -> Any:
    """Repartition the inventory across the cluster. Mirrors the seed
    notebook: `NUM_PARTITIONS or sc.defaultParallelism`, capped at the
    total row count."""
    target = num_partitions or default_parallelism
    target = max(1, min(target, n_total))
    return scan_df.repartition(target)
