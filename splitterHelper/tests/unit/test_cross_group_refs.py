"""Cross-group reference rewrite tests."""
from __future__ import annotations

import base64
import json

from fabric_splitter.rewrite import rewrite_references


SOURCE_WS = "ws-source"
WS_A = "ws-a"
WS_B = "ws-b"


def _b64_json(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _decode_payload(body: dict) -> dict:
    payload = body["definition"]["parts"][0]["payload"]
    return json.loads(base64.b64decode(payload))


def _rewrite_once(monkeypatch, *, content: dict, current_ws: str) -> tuple[bool, list[dict]]:
    definition = {"definition": {"parts": [{"path": "definition.json", "payload": _b64_json(content)}]}}
    updates: list[dict] = []

    def fake_request(method, url, token, body=None, **kw):
        if "getDefinition" in url:
            return definition
        updates.append(body)
        return {}

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)
    changed = rewrite_references(
        {"id": "item-under-test", "type": "SemanticModel"},
        current_ws,
        {SOURCE_WS: current_ws},
        "token",
        {"item-a": WS_A, "item-b": WS_B},
    )
    return changed, updates


def test_same_group_a_to_a_reference_keeps_target_workspace(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"ref": {"workspaceId": SOURCE_WS, "artifactId": "item-a"}},
        current_ws=WS_A,
    )
    assert changed is True
    decoded = _decode_payload(updates[0])
    assert decoded["ref"]["workspaceId"] == WS_A
    assert decoded["ref"]["artifactId"] == "item-a"


def test_cross_group_a_to_b_reference_routes_to_b_workspace(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"ref": {"workspaceId": SOURCE_WS, "artifactId": "item-b"}},
        current_ws=WS_A,
    )
    assert changed is True
    decoded = _decode_payload(updates[0])
    assert decoded["ref"]["workspaceId"] == WS_B
    assert decoded["ref"]["artifactId"] == "item-b"


def test_cross_group_b_to_a_reference_routes_to_a_workspace(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"ref": {"workspaceId": SOURCE_WS, "artifactId": "item-a"}},
        current_ws=WS_B,
    )
    assert changed is True
    decoded = _decode_payload(updates[0])
    assert decoded["ref"]["workspaceId"] == WS_A
    assert decoded["ref"]["artifactId"] == "item-a"


def test_url_shape_reference_rewrites_workspace_by_item_location(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"uri": f"workspaces/{SOURCE_WS}/lakehouses/item-b"},
        current_ws=WS_A,
    )
    assert changed is True
    decoded = _decode_payload(updates[0])
    assert decoded["uri"] == f"workspaces/{WS_B}/lakehouses/item-b"


def test_external_workspace_reference_is_left_unchanged(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"ref": {"workspaceId": "external-ws", "artifactId": "item-a"}},
        current_ws=WS_B,
    )
    assert changed is False
    assert updates == []


def test_unknown_item_id_keeps_rewriting_item_workspace(monkeypatch):
    changed, updates = _rewrite_once(
        monkeypatch,
        content={"ref": {"workspaceId": SOURCE_WS, "artifactId": "unknown-item"}},
        current_ws=WS_B,
    )
    assert changed is True
    decoded = _decode_payload(updates[0])
    assert decoded["ref"]["workspaceId"] == WS_B
    assert decoded["ref"]["artifactId"] == "unknown-item"
