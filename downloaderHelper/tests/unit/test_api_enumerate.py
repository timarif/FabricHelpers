"""Unit tests for `api.enumerate` — exercise the multi-type filter,
admin-vs-user fallback chain, and read_workspace_ids client-side filter
using a fake aiohttp session.

We never make real HTTP calls. `aiohttp.ClientSession` is monkeypatched
with a recorder that returns scripted responses keyed by URL.
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

# These tests import optional [api] deps (aiohttp). Skip if missing.
pytest.importorskip("aiohttp")

from fabric_downloader import DownloaderConfig                    # noqa: E402
from fabric_downloader.api import enumerate as enum_mod           # noqa: E402


# --------------------------------------------------------------------
# Tiny scripted aiohttp.ClientSession double
# --------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, body: Any,
                 headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return str(self._body)


class _FakeSession:
    """Records requests + returns scripted responses by URL prefix."""

    def __init__(self, routes: dict[str, _FakeResponse]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    @asynccontextmanager
    async def request(self, method, url, **kw):
        self.calls.append((method, url))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                yield resp
                return
        raise AssertionError(f"unscripted URL: {method} {url}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def fake_aiohttp(monkeypatch):
    """Patch `aiohttp.ClientSession` in the enumerate module so calling
    code receives our scripted double."""
    holder: dict[str, _FakeSession] = {}

    def install(routes: dict[str, _FakeResponse]) -> _FakeSession:
        session = _FakeSession(routes)
        holder["session"] = session

        def factory(*a, **kw):
            return session

        monkeypatch.setattr(enum_mod.aiohttp, "ClientSession", factory)
        return session

    return install


# --------------------------------------------------------------------
# _normalize / item_to_descriptor
# --------------------------------------------------------------------


def test_normalize_is_lowercase_trimmed():
    assert enum_mod._normalize("  Notebook ") == "notebook"
    assert enum_mod._normalize(None) == ""


def test_item_to_descriptor_filters_by_allowed_types():
    raw = {"id": "i1", "type": "DataPipeline", "displayName": "P"}
    out = enum_mod._item_to_descriptor(raw, "w1", {"notebook"})
    assert out is None
    out = enum_mod._item_to_descriptor(raw, "w1", {"datapipeline"})
    assert out == {"workspaceId": "w1", "id": "i1",
                   "type": "DataPipeline", "displayName": "P"}


def test_item_to_descriptor_extracts_workspace_from_payload():
    raw = {"id": "i", "type": "Notebook", "workspaceId": "embedded-ws"}
    out = enum_mod._item_to_descriptor(raw, "", {"notebook"})
    assert out["workspaceId"] == "embedded-ws"


# --------------------------------------------------------------------
# enumerate_items — full async paths
# --------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_admin_chain_uses_tenant_wide_items(fake_aiohttp):
    cfg = DownloaderConfig(
        item_types=("Notebook", "DataPipeline"),
        admin_mode=True,
    )
    fake_aiohttp({
        "https://api.powerbi.com/v1.0/myorg/admin/groups": _FakeResponse(
            200, {"value": [{"id": "ws-A", "name": "Alpha"},
                            {"id": "ws-B", "name": "Beta"}]}),
        "https://api.fabric.microsoft.com/v1/admin/items": _FakeResponse(
            200, {"itemEntities": [
                {"id": "n1", "type": "Notebook",
                 "displayName": "NB-1", "workspaceId": "ws-A"},
                {"id": "p1", "type": "DataPipeline",
                 "displayName": "Pipe-1", "workspaceId": "ws-B"},
                {"id": "r1", "type": "Report",
                 "displayName": "R-1", "workspaceId": "ws-B"},
            ]}),
    })
    items = _run(enum_mod.enumerate_items(cfg, token="x"))
    assert len(items) == 2
    ids = {n["id"] for n in items}
    assert ids == {"n1", "p1"}
    assert {n["workspaceName"] for n in items} == {"Alpha", "Beta"}


def test_user_mode_uses_user_workspace_endpoint(fake_aiohttp):
    cfg = DownloaderConfig(
        item_types=("Notebook",),
        admin_mode=False,
    )
    session = fake_aiohttp({
        "https://api.fabric.microsoft.com/v1/workspaces/ws-1/items":
            _FakeResponse(200, {"value": [
                {"id": "n", "type": "Notebook", "displayName": "N"},
                {"id": "p", "type": "DataPipeline", "displayName": "P"},
            ]}),
        "https://api.fabric.microsoft.com/v1/workspaces": _FakeResponse(
            200, {"value": [{"id": "ws-1", "displayName": "Mine"}]}),
    })
    items = _run(enum_mod.enumerate_items(cfg, token="x"))
    assert len(items) == 1
    assert items[0]["id"] == "n"
    # Admin endpoints must NOT be probed in user mode
    assert not any("admin" in u for _, u in session.calls)


def test_read_workspace_ids_filters_admin_tenant_results(fake_aiohttp):
    cfg = DownloaderConfig(
        item_types=("Notebook",),
        admin_mode=True,
        read_workspace_ids=("ws-A",),
    )
    fake_aiohttp({
        "https://api.powerbi.com/v1.0/myorg/admin/groups": _FakeResponse(
            200, {"value": [
                {"id": "ws-A", "name": "Keep"},
                {"id": "ws-B", "name": "Drop"},
            ]}),
        "https://api.fabric.microsoft.com/v1/admin/items": _FakeResponse(
            200, {"itemEntities": [
                {"id": "a", "type": "Notebook", "displayName": "A",
                 "workspaceId": "ws-A"},
                {"id": "b", "type": "Notebook", "displayName": "B",
                 "workspaceId": "ws-B"},
            ]}),
    })
    items = _run(enum_mod.enumerate_items(cfg, token="x"))
    assert [n["id"] for n in items] == ["a"]


def test_admin_falls_back_to_user_when_admin_endpoints_fail(fake_aiohttp):
    cfg = DownloaderConfig(item_types=("Notebook",), admin_mode=True)
    fake_aiohttp({
        # admin endpoints return 401 -> chain advances to user /workspaces
        "https://api.powerbi.com/v1.0/myorg/admin/groups": _FakeResponse(
            401, "forbidden"),
        "https://api.fabric.microsoft.com/v1/admin/workspaces": _FakeResponse(
            403, "forbidden"),
        "https://api.fabric.microsoft.com/v1/workspaces/ws-U/items":
            _FakeResponse(200, {"value": [
                {"id": "u1", "type": "Notebook", "displayName": "U"},
            ]}),
        "https://api.fabric.microsoft.com/v1/workspaces": _FakeResponse(
            200, {"value": [{"id": "ws-U", "displayName": "User WS"}]}),
    })
    items = _run(enum_mod.enumerate_items(cfg, token="x"))
    assert [n["id"] for n in items] == ["u1"]
    assert items[0]["workspaceName"] == "User WS"


def test_enumerate_returns_empty_when_no_workspaces(fake_aiohttp):
    cfg = DownloaderConfig(item_types=("Notebook",), admin_mode=False)
    fake_aiohttp({
        "https://api.fabric.microsoft.com/v1/workspaces": _FakeResponse(
            200, {"value": []}),
    })
    items = _run(enum_mod.enumerate_items(cfg, token="x"))
    assert items == []


# --------------------------------------------------------------------
# run_enumeration_sync
# --------------------------------------------------------------------


def test_run_enumeration_sync_no_running_loop(monkeypatch):
    """When no event loop is running, the sync wrapper should just
    call asyncio.run on the coroutine."""
    called: list[Any] = []

    async def fake_enumerate(cfg, token, **kw):
        called.append((cfg, token))
        return [{"id": "x"}]

    monkeypatch.setattr(enum_mod, "enumerate_items", fake_enumerate)
    cfg = DownloaderConfig()
    out = enum_mod.run_enumeration_sync(cfg, token="t")
    assert out == [{"id": "x"}]
    assert called == [(cfg, "t")]
