"""Delta + filesystem persistence helpers for fabric-mpe.

The Spark writes are wrapped here so the engine modules (``inventory``,
``delete``, ``recreate``, ``approve``) stay free of literal ``saveAsTable``
calls. File writes (JSON + CSV under ``Files/<files_subdir>/<run>/``) use
plain stdlib ``json`` and ``csv``.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
from collections.abc import Iterable
from typing import Any

from .config import MpeConfig

INVENTORY_CSV_FIELDS = (
    "workspace_id",
    "workspace_name",
    "mpe_id",
    "mpe_name",
    "target_resource_id",
    "target_subresource_type",
    "provisioning_state",
    "connection_status",
    "connection_description",
    "run_label",
    "collected_at",
)


def _isoformat(value: Any) -> Any:
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    return value


def _row_for_export(row: dict) -> dict:
    return {k: _isoformat(v) for k, v in row.items()}


def write_inventory_files(
    cfg: MpeConfig,
    rows: list[dict],
    *,
    run_label: str | None = None,
    base_dir: str | None = None,
) -> tuple[str, str, str]:
    """Write ``inventory.json`` + ``inventory.csv`` under the run's Files dir.

    Returns ``(directory, json_path, csv_path)``. Creates the directory if
    it doesn't already exist. Empty ``rows`` still produces well-formed
    empty files so downstream consumers can rely on their existence.
    """
    target_label = run_label or cfg.run_label
    directory = base_dir or cfg.files_dir(target_label)
    os.makedirs(directory, exist_ok=True)
    json_path = os.path.join(directory, "inventory.json")
    csv_path = os.path.join(directory, "inventory.csv")

    export_rows = [_row_for_export(r) for r in rows]
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(export_rows, fh, indent=2)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(INVENTORY_CSV_FIELDS))
        writer.writeheader()
        for row in export_rows:
            writer.writerow({k: row.get(k) for k in INVENTORY_CSV_FIELDS})
    return directory, json_path, csv_path


def append_delta(spark: Any, rows: Iterable[dict], target: str) -> int:
    """Append ``rows`` to ``target`` as Delta, returning the row count.

    No-op when ``rows`` is empty (and returns 0); doing the no-op here
    keeps every engine cell free of an ``if rows:`` ladder.
    """
    materialized = list(rows)
    if not materialized:
        return 0
    df = spark.createDataFrame(materialized)
    (
        df.write.format("delta")
        .mode("append")
        .saveAsTable(target)
    )
    return len(materialized)


def encode_body(body: Any) -> str:
    """Encode an API response body for storage in the audit Delta column."""
    if isinstance(body, str):
        return body
    return json.dumps(body)


__all__ = [
    "INVENTORY_CSV_FIELDS",
    "write_inventory_files",
    "append_delta",
    "encode_body",
]
