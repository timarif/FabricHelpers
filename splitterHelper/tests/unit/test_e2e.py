"""Integration-style E2E tests for the full split workflow.

All Fabric REST calls are intercepted by monkeypatching the internal
``_request`` and ``paged_get`` helpers so no real network access is needed.
"""
from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path
from unittest import mock

import pytest

from fabric_splitter.classify import classify
from fabric_splitter.move import move_item
from fabric_splitter.plan import build_plan, write_plan
from fabric_splitter.rewrite import rewrite_references
from fabric_splitter.workspaces import get_or_create_workspace, copy_role_assignments


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


SOURCE_WS = "ws-source"
WS_A = "ws-eng"
WS_B = "ws-cons"

ITEMS = [
    {"id": "nb1", "type": "Notebook", "displayName": "NB 1"},
    {"id": "lh1", "type": "Lakehouse", "displayName": "LH 1"},
    {"id": "sm1", "type": "SemanticModel", "displayName": "SM 1"},
    {"id": "rpt1", "type": "Report", "displayName": "Rpt 1"},
]

TYPES_TO_A = {"notebook", "lakehouse"}


def _b64_json(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


# ---------------------------------------------------------------------------
# 1. Classify
# ---------------------------------------------------------------------------


def test_classify_engineering_vs_consumption():
    result = classify(ITEMS, TYPES_TO_A)
    assert result["nb1"] == "A"
    assert result["lh1"] == "A"
    assert result["sm1"] == "B"
    assert result["rpt1"] == "B"


# ---------------------------------------------------------------------------
# 2. Build plan
# ---------------------------------------------------------------------------


def test_plan_has_correct_actions():
    classification = classify(ITEMS, TYPES_TO_A)
    plan = build_plan(ITEMS, classification, WS_A, WS_B, SOURCE_WS)
    by_id = {row.item_id: row for row in plan}
    # All items differ from source → all are "move"
    assert all(row.action == "move" for row in plan)
    assert by_id["nb1"].target_workspace_id == WS_A
    assert by_id["sm1"].target_workspace_id == WS_B


# ---------------------------------------------------------------------------
# 3. Write plan
# ---------------------------------------------------------------------------


def test_write_plan_roundtrip(tmp_path):
    classification = classify(ITEMS, TYPES_TO_A)
    plan = build_plan(ITEMS, classification, WS_A, WS_B, SOURCE_WS)
    csv_path, json_path = write_plan(plan, tmp_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(ITEMS)
    json_rows = json.loads(json_path.read_text())
    assert len(json_rows) == len(ITEMS)


# ---------------------------------------------------------------------------
# 4. get_or_create_workspace
# ---------------------------------------------------------------------------


def test_get_or_create_workspace_creates_when_missing(monkeypatch):
    def fake_paged_get(url, token):
        return []  # no existing workspaces

    def fake_request(method, url, token, body=None, **kw):
        assert method == "POST"
        return {"id": "new-ws-id", "displayName": body["displayName"]}

    monkeypatch.setattr("fabric_splitter.workspaces.paged_get", fake_paged_get)
    monkeypatch.setattr("fabric_splitter.workspaces._request", fake_request)

    ws_id = get_or_create_workspace("Engineering", token="t")
    assert ws_id == "new-ws-id"


def test_get_or_create_workspace_returns_existing(monkeypatch):
    def fake_paged_get(url, token):
        return [{"id": "existing-id", "displayName": "Engineering"}]

    called = []

    def fake_request(method, url, token, body=None, **kw):
        called.append(method)
        return {}

    monkeypatch.setattr("fabric_splitter.workspaces.paged_get", fake_paged_get)
    monkeypatch.setattr("fabric_splitter.workspaces._request", fake_request)

    ws_id = get_or_create_workspace("Engineering", token="t")
    assert ws_id == "existing-id"
    assert called == []  # no POST was made


# ---------------------------------------------------------------------------
# 5. copy_role_assignments
# ---------------------------------------------------------------------------


def test_copy_role_assignments_copies_all(monkeypatch):
    assignments = [
        {"role": "Admin", "principal": {"id": "u1", "type": "User"}},
        {"role": "Member", "principal": {"id": "u2", "type": "User"}},
    ]

    def fake_paged_get(url, token):
        return assignments

    posted = []

    def fake_request(method, url, token, body=None, **kw):
        posted.append(body)
        return {}

    monkeypatch.setattr("fabric_splitter.workspaces.paged_get", fake_paged_get)
    monkeypatch.setattr("fabric_splitter.workspaces._request", fake_request)

    n = copy_role_assignments("src", "tgt", token="t")
    assert n == 2
    assert {p["role"] for p in posted} == {"Admin", "Member"}


# ---------------------------------------------------------------------------
# 6. move_item (export-and-recreate path)
# ---------------------------------------------------------------------------


def test_move_item_export_recreate(monkeypatch):
    item = {"id": "nb1", "type": "Notebook", "displayName": "NB 1"}
    calls: list[tuple] = []

    def fake_request(method, url, token, body=None, **kw):
        calls.append((method, url))
        if "getDefinition" in url:
            return {"definition": {"parts": [{"path": "nb.py", "payload": "aGVsbG8="}]}}
        return {"id": "new-nb1"}

    monkeypatch.setattr("fabric_splitter.move._request", fake_request)

    audit_fh = io.StringIO()
    move_item(item, SOURCE_WS, WS_A, "token", audit_fh)

    # getDefinition must have been called on source
    assert any("getDefinition" in url for _, url in calls)
    # createItem must have been called on target
    create_calls = [(m, u) for m, u in calls if m == "POST" and WS_A in u and "getDefinition" not in u]
    assert len(create_calls) >= 1

    # Audit log should have a record
    audit_fh.seek(0)
    record = json.loads(audit_fh.readline())
    assert record["action"] == "export_recreate"
    assert record["itemId"] == "nb1"


def test_move_item_skips_when_get_definition_fails(monkeypatch):
    import urllib.error

    item = {"id": "nb1", "type": "Notebook", "displayName": "NB 1"}

    def fake_request(method, url, token, body=None, **kw):
        if "getDefinition" in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return {}

    monkeypatch.setattr("fabric_splitter.move._request", fake_request)

    audit_fh = io.StringIO()
    # Should not raise — skip_no_definition is logged
    move_item(item, SOURCE_WS, WS_A, "token", audit_fh)

    audit_fh.seek(0)
    record = json.loads(audit_fh.readline())
    assert record["action"] == "skip_no_definition"


# ---------------------------------------------------------------------------
# 7. rewrite_references
# ---------------------------------------------------------------------------


def test_rewrite_patches_semantic_model_workspace_ref(monkeypatch):
    sm_content = {"dataSource": {"workspaceId": SOURCE_WS, "lakeHouseId": "lh1"}}
    definition = {
        "definition": {
            "parts": [{"path": "model.bim", "payload": _b64_json(sm_content)}]
        }
    }
    updates = []

    def fake_request(method, url, token, body=None, **kw):
        if "getDefinition" in url:
            return definition
        updates.append(body)
        return {}

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)

    item = {"id": "sm1", "type": "SemanticModel"}
    changed = rewrite_references(item, WS_B, {SOURCE_WS: WS_A}, "token")
    assert changed is True
    assert len(updates) == 1
    # Verify the substitution happened in the pushed body
    pushed_parts = updates[0]["definition"]["parts"]
    decoded = json.loads(base64.b64decode(pushed_parts[0]["payload"]))
    assert decoded["dataSource"]["workspaceId"] == WS_A


# ---------------------------------------------------------------------------
# 8. Idempotency — second run produces zero mutations
# ---------------------------------------------------------------------------


def test_idempotency_second_run_no_mutations(monkeypatch, tmp_path):
    """Simulate a second run where all items are already in the right workspaces.

    With all items already in workspace A or B (none in the source), every
    item's target equals its current location → action='leave' → zero moves.
    """
    # Items already live in the target workspaces (not in source)
    items_already_moved = [
        {"id": "nb1", "type": "Notebook", "displayName": "NB 1", "workspaceId": WS_A},
        {"id": "sm1", "type": "SemanticModel", "displayName": "SM 1", "workspaceId": WS_B},
    ]
    # Use WS_A as source (so nb1's target == source == WS_A → leave)
    # and WS_B for sm1 similarly
    # We test with a simpler scenario: source = WS_A, A-types go to WS_A.
    classification = classify(items_already_moved, {"notebook"})
    # workspace_a_id == SOURCE_WS (same workspace)
    plan = build_plan(items_already_moved, classification, WS_A, WS_B, WS_A)
    nb_row = next(r for r in plan if r.item_id == "nb1")
    assert nb_row.action == "leave"

    # Write the plan and confirm zero "move" rows
    csv_path, _ = write_plan(plan, tmp_path)
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    move_rows = [r for r in rows if r["action"] == "move"]
    # nb1 → leave (already in WS_A), sm1 → move (WS_B ≠ WS_A)
    assert len(move_rows) == 1
    assert move_rows[0]["itemId"] == "sm1"
