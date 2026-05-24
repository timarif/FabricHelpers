"""Tests for ``fabric_mpe.persist``."""
from __future__ import annotations

import csv as _csv
import datetime as _dt
import json
import os
from unittest.mock import MagicMock

from fabric_mpe import MpeConfig
from fabric_mpe.persist import (
    INVENTORY_CSV_FIELDS,
    append_delta,
    encode_body,
    write_inventory_files,
)


def _row(**overrides):
    base = {
        "workspace_id": "ws1",
        "workspace_name": "ws-one",
        "mpe_id": "m1",
        "mpe_name": "blob-1",
        "target_resource_id": "rid",
        "target_subresource_type": "blob",
        "provisioning_state": "Succeeded",
        "connection_status": "Approved",
        "connection_description": "ok",
        "run_label": "r1",
        "collected_at": _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc),
    }
    base.update(overrides)
    return base


def test_write_inventory_files_writes_json_and_csv(tmp_path):
    rows = [_row(), _row(mpe_id="m2")]
    directory, json_path, csv_path = write_inventory_files(
        MpeConfig(),
        rows,
        run_label="r1",
        base_dir=str(tmp_path / "out"),
    )
    assert os.path.isdir(directory)
    assert json_path.endswith("inventory.json")
    assert csv_path.endswith("inventory.csv")

    with open(json_path) as fh:
        loaded = json.load(fh)
    assert len(loaded) == 2
    # datetime values must be stringified for JSON export.
    assert loaded[0]["collected_at"] == "2026-01-01T00:00:00+00:00"

    with open(csv_path) as fh:
        reader = _csv.DictReader(fh)
        csv_rows = list(reader)
    assert reader.fieldnames == list(INVENTORY_CSV_FIELDS)
    assert len(csv_rows) == 2
    assert csv_rows[0]["mpe_id"] == "m1"


def test_write_inventory_files_creates_well_formed_empty_files(tmp_path):
    _d, jp, cp = write_inventory_files(
        MpeConfig(), [], run_label="r1", base_dir=str(tmp_path / "out")
    )
    assert json.load(open(jp)) == []  # noqa: SIM115 — test, short-lived handle
    rows = list(_csv.DictReader(open(cp)))  # noqa: SIM115
    assert rows == []


def test_append_delta_no_op_on_empty():
    spark = MagicMock()
    assert append_delta(spark, [], "tbl") == 0
    spark.createDataFrame.assert_not_called()


def test_append_delta_writes_with_append_mode():
    spark = MagicMock()
    rows = [{"a": 1}, {"a": 2}]
    assert append_delta(spark, rows, "tbl") == 2

    spark.createDataFrame.assert_called_once_with(rows)
    df = spark.createDataFrame.return_value
    df.write.format.assert_called_once_with("delta")
    df.write.format.return_value.mode.assert_called_once_with("append")
    df.write.format.return_value.mode.return_value.saveAsTable.assert_called_once_with("tbl")


def test_encode_body_passthrough_for_string():
    assert encode_body("plain") == "plain"


def test_encode_body_json_dumps_for_other_types():
    assert encode_body({"k": "v"}) == '{"k": "v"}'
    assert encode_body([1, 2]) == "[1, 2]"
