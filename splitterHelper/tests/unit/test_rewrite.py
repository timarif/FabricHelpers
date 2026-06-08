"""Unit tests for :mod:`fabric_splitter.rewrite`."""
from __future__ import annotations

import base64
import json

import pytest

from fabric_splitter.rewrite import (
    REWRITE_CANDIDATES,
    _patch_part,
    _replace_workspace_id,
    rewrite_references,
)


# ---------------------------------------------------------------------------
# _replace_workspace_id — pure recursive substitution
# ---------------------------------------------------------------------------


def test_replace_string_simple():
    assert _replace_workspace_id("old-ws", "old-ws", "new-ws") == "new-ws"


def test_replace_string_substring():
    s = "workspaceId=old-ws&other=x"
    assert _replace_workspace_id(s, "old-ws", "new-ws") == "workspaceId=new-ws&other=x"


def test_replace_no_match():
    assert _replace_workspace_id("no-change", "old-ws", "new-ws") == "no-change"


def test_replace_in_dict():
    obj = {"workspaceId": "old-ws", "other": "keep"}
    result = _replace_workspace_id(obj, "old-ws", "new-ws")
    assert result == {"workspaceId": "new-ws", "other": "keep"}


def test_replace_in_list():
    obj = ["old-ws", "keep", "old-ws"]
    result = _replace_workspace_id(obj, "old-ws", "new-ws")
    assert result == ["new-ws", "keep", "new-ws"]


def test_replace_nested():
    obj = {"sources": [{"workspaceId": "old-ws"}], "name": "keep"}
    result = _replace_workspace_id(obj, "old-ws", "new-ws")
    assert result["sources"][0]["workspaceId"] == "new-ws"
    assert result["name"] == "keep"


def test_replace_non_string_scalar_unchanged():
    assert _replace_workspace_id(42, "x", "y") == 42
    assert _replace_workspace_id(None, "x", "y") is None
    assert _replace_workspace_id(3.14, "x", "y") == 3.14


# ---------------------------------------------------------------------------
# _patch_part
# ---------------------------------------------------------------------------


def _make_part(content: dict) -> dict:
    payload = base64.b64encode(json.dumps(content).encode()).decode()
    return {"path": "definition.json", "payload": payload}


def test_patch_part_replaces_workspace_id():
    content = {"workspaceId": "old-ws", "name": "keep"}
    part = _make_part(content)
    new_part, changed = _patch_part(part, {"old-ws": "new-ws"}, workspace_id="new-ws")
    assert changed is True
    decoded = json.loads(base64.b64decode(new_part["payload"]))
    assert decoded["workspaceId"] == "new-ws"
    assert decoded["name"] == "keep"


def test_patch_part_no_change():
    content = {"workspaceId": "other", "name": "keep"}
    part = _make_part(content)
    new_part, changed = _patch_part(part, {"old-ws": "new-ws"}, workspace_id="new-ws")
    assert changed is False
    assert new_part is part


def test_patch_part_no_payload():
    part = {"path": "README.md"}
    new_part, changed = _patch_part(part, {"old-ws": "new-ws"}, workspace_id="new-ws")
    assert changed is False
    assert new_part is part


def test_patch_part_non_json_payload_is_left_unchanged():
    part = {
        "path": "binary.bin",
        "payload": base64.b64encode(b"\x00\x01\x02\x03").decode(),
    }
    new_part, changed = _patch_part(part, {"old-ws": "new-ws"}, workspace_id="new-ws")
    assert changed is False


def test_patch_part_multiple_id_substitutions():
    content = {"wsA": "ws-old-a", "wsB": "ws-old-b"}
    part = _make_part(content)
    new_part, changed = _patch_part(
        part,
        {"ws-old-a": "ws-new-a", "ws-old-b": "ws-new-b"},
        workspace_id="ws-new-a",
    )
    assert changed is True
    decoded = json.loads(base64.b64decode(new_part["payload"]))
    assert decoded["wsA"] == "ws-new-a"
    assert decoded["wsB"] == "ws-new-b"


# ---------------------------------------------------------------------------
# REWRITE_CANDIDATES constant
# ---------------------------------------------------------------------------


def test_rewrite_candidates_includes_expected_types():
    for t in ("SemanticModel", "Report", "DataPipeline"):
        assert t in REWRITE_CANDIDATES


# ---------------------------------------------------------------------------
# rewrite_references — with mocked HTTP
# ---------------------------------------------------------------------------


def _b64_json(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _make_definition(parts: list[dict]) -> dict:
    return {"definition": {"format": "PBIDP", "parts": parts}}


def test_rewrite_references_returns_false_for_non_candidate_type(monkeypatch):
    item = {"id": "nb1", "type": "Notebook"}
    result = rewrite_references(item, "ws-id", {"old": "new"}, "token")
    assert result is False


def test_rewrite_references_makes_no_call_for_non_candidate(monkeypatch):
    calls = []

    def fake_request(method, url, token, body=None, **kw):
        calls.append((method, url))
        return None

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)
    item = {"id": "nb1", "type": "Notebook"}
    result = rewrite_references(item, "ws-id", {"old": "new"}, "token")
    assert result is False
    assert calls == []


def test_rewrite_references_patches_and_pushes(monkeypatch):
    content = {"workspaceId": "old-ws", "keep": "value"}
    definition = _make_definition([{"path": "model.json", "payload": _b64_json(content)}])

    call_log: list[tuple] = []

    def fake_request(method, url, token, body=None, **kw):
        call_log.append((method, url))
        if "getDefinition" in url:
            return definition
        # updateDefinition
        return {}

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)

    item = {"id": "sm1", "type": "SemanticModel"}
    changed = rewrite_references(item, "ws-target", {"old-ws": "new-ws"}, "token")
    assert changed is True
    assert any("updateDefinition" in url for _, url in call_log)


def test_rewrite_references_returns_false_when_no_change_needed(monkeypatch):
    content = {"workspaceId": "current-ws"}
    definition = _make_definition([{"path": "m.json", "payload": _b64_json(content)}])

    def fake_request(method, url, token, body=None, **kw):
        if "getDefinition" in url:
            return definition
        return {}

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)

    item = {"id": "sm1", "type": "SemanticModel"}
    # id_map doesn't match "current-ws" → no change
    changed = rewrite_references(item, "ws-target", {"old-ws": "new-ws"}, "token")
    assert changed is False


def test_rewrite_references_returns_false_when_get_definition_fails(monkeypatch):
    import urllib.error

    def fake_request(method, url, token, body=None, **kw):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)

    item = {"id": "sm1", "type": "SemanticModel"}
    result = rewrite_references(item, "ws-id", {"old": "new"}, "token")
    assert result is False


def test_rewrite_references_handles_empty_definition(monkeypatch):
    def fake_request(method, url, token, body=None, **kw):
        return {"definition": None}

    monkeypatch.setattr("fabric_splitter.rewrite._request", fake_request)

    item = {"id": "sm1", "type": "SemanticModel"}
    result = rewrite_references(item, "ws-id", {"old": "new"}, "token")
    assert result is False
