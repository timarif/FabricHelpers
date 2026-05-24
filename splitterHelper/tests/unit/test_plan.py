"""Unit tests for :mod:`fabric_splitter.plan`."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fabric_splitter.plan import PlanRow, build_plan, write_plan


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


_ITEMS = [
    {"id": "nb1", "type": "Notebook", "displayName": "My Notebook"},
    {"id": "rpt1", "type": "Report", "displayName": "My Report"},
    {"id": "lh1", "type": "Lakehouse", "displayName": "My Lakehouse"},
]

_SRC = "ws-source"
_WS_A = "ws-a"
_WS_B = "ws-b"


def _classification(
    notebook="A", report="B", lakehouse="A"
) -> dict[str, str]:
    return {"nb1": notebook, "rpt1": report, "lh1": lakehouse}


def test_build_plan_returns_one_row_per_item():
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    assert len(plan) == 3


def test_build_plan_action_is_move_when_target_differs():
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    by_id = {row.item_id: row for row in plan}
    # nb1 → A (ws-a ≠ ws-source) → move
    assert by_id["nb1"].action == "move"
    # rpt1 → B (ws-b ≠ ws-source) → move
    assert by_id["rpt1"].action == "move"


def test_build_plan_action_is_leave_when_target_equals_source():
    # If workspace A IS the source workspace, items going to A should "leave"
    plan = build_plan(_ITEMS, _classification(), _SRC, _WS_B, _SRC)
    by_id = {row.item_id: row for row in plan}
    assert by_id["nb1"].action == "leave"
    assert by_id["rpt1"].action == "move"


def test_build_plan_sets_target_workspace_id_correctly():
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    by_id = {row.item_id: row for row in plan}
    assert by_id["nb1"].target_workspace_id == _WS_A
    assert by_id["rpt1"].target_workspace_id == _WS_B
    assert by_id["lh1"].target_workspace_id == _WS_A


def test_build_plan_skips_items_without_id():
    items_with_blank = [{"type": "Notebook"}] + _ITEMS
    plan = build_plan(items_with_blank, _classification(), _WS_A, _WS_B, _SRC)
    assert len(plan) == 3


def test_build_plan_uses_displayName_then_name_then_id():
    items = [
        {"id": "i1", "type": "Notebook", "displayName": "DName"},
        {"id": "i2", "type": "Notebook", "name": "NName"},
        {"id": "i3", "type": "Notebook"},
    ]
    plan = build_plan(items, {"i1": "A", "i2": "A", "i3": "A"}, _WS_A, _WS_B, _SRC)
    by_id = {row.item_id: row for row in plan}
    assert by_id["i1"].name == "DName"
    assert by_id["i2"].name == "NName"
    assert by_id["i3"].name == "i3"


def test_build_plan_defaults_missing_classification_to_b():
    items = [{"id": "unknown", "type": "Mystery"}]
    plan = build_plan(items, {}, _WS_A, _WS_B, _SRC)
    assert plan[0].target_workspace == "B"


# ---------------------------------------------------------------------------
# write_plan
# ---------------------------------------------------------------------------


def test_write_plan_creates_csv_and_json(tmp_path):
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    csv_path, json_path = write_plan(plan, tmp_path)

    assert csv_path.exists()
    assert json_path.exists()


def test_write_plan_csv_has_correct_headers(tmp_path):
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    csv_path, _ = write_plan(plan, tmp_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == [
            "itemId", "itemType", "name", "sourceWorkspaceId",
            "targetWorkspace", "targetWorkspaceId", "action",
        ]


def test_write_plan_csv_has_correct_row_count(tmp_path):
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    csv_path, _ = write_plan(plan, tmp_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3


def test_write_plan_json_is_valid(tmp_path):
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    _, json_path = write_plan(plan, tmp_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 3
    assert all("itemId" in row for row in data)


def test_write_plan_json_fields_match_csv(tmp_path):
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    csv_path, json_path = write_plan(plan, tmp_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        csv_rows = {row["itemId"]: row for row in csv.DictReader(fh)}
    json_rows = {row["itemId"]: row for row in json.loads(json_path.read_text())}

    for item_id in csv_rows:
        assert csv_rows[item_id]["action"] == json_rows[item_id]["action"]
        assert csv_rows[item_id]["targetWorkspace"] == json_rows[item_id]["targetWorkspace"]


def test_write_plan_creates_output_dir_if_missing(tmp_path):
    nested = tmp_path / "sub" / "dir"
    plan = build_plan(_ITEMS, _classification(), _WS_A, _WS_B, _SRC)
    write_plan(plan, nested)
    assert nested.exists()


def test_write_plan_empty_plan_writes_empty_files(tmp_path):
    csv_path, json_path = write_plan([], tmp_path)
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows == []
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data == []
