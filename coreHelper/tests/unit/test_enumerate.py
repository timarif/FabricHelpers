import asyncio
import importlib
import re
import sys
from pathlib import Path

import aiohttp
from aioresponses import aioresponses

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

enum_mod = importlib.import_module("fabric_core.enumerate")

PBI_BASE = "https://pbi.test"
FABRIC_BASE = "https://fabric.test"
TOKEN = "token"


def run(coro):
    return asyncio.run(coro)


def pbi_admin_url():
    return re.compile(rf"^{re.escape(PBI_BASE)}/v1\.0/myorg/admin/groups.*")


def enum_kwargs(**overrides):
    kwargs = {
        "token": TOKEN,
        "pbi_base": PBI_BASE,
        "fabric_base": FABRIC_BASE,
        "timeout": 10.0,
        "workspace_concurrency": 4,
    }
    kwargs.update(overrides)
    return kwargs


async def call_with_session(fn):
    async with aiohttp.ClientSession() as session:
        return await fn(session)


def mock_admin_failures(mocked):
    mocked.get(pbi_admin_url(), status=403, payload={"error": "forbidden"})
    mocked.get(f"{FABRIC_BASE}/v1/admin/workspaces", status=403, payload={"error": "forbidden"})


def test_http_json_returns_json_and_headers():
    with aioresponses() as mocked:
        mocked.get("https://example.test/ok", status=200, payload={"ok": True}, headers={"X-Test": "yes"})

        async def scenario(session):
            return await enum_mod._http_json(session, "GET", "https://example.test/ok")

        status, body, headers = run(call_with_session(scenario))

    assert status == 200
    assert body == {"ok": True}
    assert headers["X-Test"] == "yes"


def test_http_json_returns_text_for_non_json_failure():
    with aioresponses() as mocked:
        mocked.get("https://example.test/fail", status=503, body="unavailable")

        async def scenario(session):
            return await enum_mod._http_json(session, "GET", "https://example.test/fail")

        status, body, _headers = run(call_with_session(scenario))

    assert status == 503
    assert body == "unavailable"


def test_list_pbi_admin_workspaces_returns_value():
    workspaces = [{"id": "w1", "name": "PBI Workspace"}]
    with aioresponses() as mocked:
        mocked.get(pbi_admin_url(), status=200, payload={"value": workspaces})

        async def scenario(session):
            return await enum_mod._list_pbi_admin_workspaces(session, PBI_BASE)

        result = run(call_with_session(scenario))

    assert result == workspaces


def test_list_fabric_admin_workspaces_returns_value():
    workspaces = [{"id": "w2", "displayName": "Fabric Workspace"}]
    with aioresponses() as mocked:
        mocked.get(f"{FABRIC_BASE}/v1/admin/workspaces", status=200, payload={"value": workspaces})

        async def scenario(session):
            return await enum_mod._list_fabric_admin_workspaces(session, FABRIC_BASE)

        result = run(call_with_session(scenario))

    assert result == workspaces


def test_list_user_workspaces_returns_value():
    workspaces = [{"id": "w3", "displayName": "User Workspace"}]
    with aioresponses() as mocked:
        mocked.get(f"{FABRIC_BASE}/v1/workspaces", status=200, payload={"value": workspaces})

        async def scenario(session):
            return await enum_mod._list_user_workspaces(session, FABRIC_BASE)

        result = run(call_with_session(scenario))

    assert result == workspaces


def test_fabric_workspace_listing_follows_continuation_uri():
    first_url = f"{FABRIC_BASE}/v1/admin/workspaces"
    next_url = f"{FABRIC_BASE}/v1/admin/workspaces?continuationToken=abc"
    with aioresponses() as mocked:
        mocked.get(first_url, status=200, payload={"value": [{"id": "w1"}], "continuationUri": next_url})
        mocked.get(next_url, status=200, payload={"value": [{"id": "w2"}]})

        async def scenario(session):
            return await enum_mod._list_fabric_admin_workspaces(session, FABRIC_BASE)

        result = run(call_with_session(scenario))

    assert result == [{"id": "w1"}, {"id": "w2"}]


def test_pbi_admin_403_falls_back_to_fabric_admin_workspaces():
    with aioresponses() as mocked:
        mocked.get(pbi_admin_url(), status=403, payload={"error": "forbidden"})
        mocked.get(
            f"{FABRIC_BASE}/v1/admin/workspaces",
            status=200,
            payload={"value": [{"id": "w2", "displayName": "Fabric Workspace"}]},
        )
        mocked.get(
            f"{FABRIC_BASE}/v1/admin/items",
            status=200,
            payload={"itemEntities": [{"id": "i2", "type": "Notebook", "displayName": "Notebook", "workspaceId": "w2"}]},
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs()))

    assert result == [
        {
            "id": "i2",
            "type": "Notebook",
            "displayName": "Notebook",
            "workspaceId": "w2",
            "name": "Notebook",
            "workspaceName": "Fabric Workspace",
        }
    ]


def test_pbi_admin_200_uses_pbi_list_without_workspace_fallback():
    with aioresponses() as mocked:
        mocked.get(
            pbi_admin_url(),
            status=200,
            payload={"value": [{"id": "w1", "name": "PBI Workspace"}]},
        )
        mocked.get(
            f"{FABRIC_BASE}/v1/admin/items",
            status=200,
            payload={"itemEntities": [{"id": "i1", "itemType": "Lakehouse", "name": "Lake", "workspaceId": "w1"}]},
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs()))

    assert len(result) == 1
    assert result[0]["workspaceId"] == "w1"
    assert result[0]["workspaceName"] == "PBI Workspace"
    assert result[0]["type"] == "Lakehouse"


def test_pbi_and_fabric_admin_failures_fall_back_to_user_workspaces():
    with aioresponses() as mocked:
        mock_admin_failures(mocked)
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces",
            status=200,
            payload={"value": [{"id": "w3", "displayName": "User Workspace"}]},
        )
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces/w3/items",
            status=200,
            payload={"value": [{"id": "i3", "type": "DataPipeline", "displayName": "Pipe"}]},
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs()))

    assert len(result) == 1
    assert result[0]["workspaceId"] == "w3"
    assert result[0]["workspaceName"] == "User Workspace"
    assert result[0]["name"] == "Pipe"


def test_all_workspace_listing_failures_return_empty_list():
    with aioresponses() as mocked:
        mocked.get(pbi_admin_url(), status=403, payload={"error": "forbidden"})
        mocked.get(f"{FABRIC_BASE}/v1/admin/workspaces", status=500, payload={"error": "boom"})
        mocked.get(f"{FABRIC_BASE}/v1/workspaces", status=401, payload={"error": "unauthorized"})

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs()))

    assert result == []


def test_item_filter_none_returns_all_items():
    with aioresponses() as mocked:
        mock_admin_failures(mocked)
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces",
            status=200,
            payload={"value": [{"id": "w1", "displayName": "Workspace"}]},
        )
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces/w1/items",
            status=200,
            payload={
                "value": [
                    {"id": "n1", "type": "Notebook", "displayName": "Notebook"},
                    {"id": "p1", "type": "DataPipeline", "displayName": "Pipe"},
                ]
            },
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs(item_filter=None)))

    assert [item["id"] for item in result] == ["n1", "p1"]


def test_item_filter_callable_only_includes_truthy_results():
    seen = []

    def only_notebooks(item, workspace):
        seen.append((item["id"], workspace["id"]))
        return item.get("type") == "Notebook"

    with aioresponses() as mocked:
        mock_admin_failures(mocked)
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces",
            status=200,
            payload={"value": [{"id": "w1", "displayName": "Workspace"}]},
        )
        mocked.get(
            f"{FABRIC_BASE}/v1/workspaces/w1/items",
            status=200,
            payload={
                "value": [
                    {"id": "n1", "type": "Notebook", "displayName": "Notebook"},
                    {"id": "p1", "type": "DataPipeline", "displayName": "Pipe"},
                ]
            },
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs(item_filter=only_notebooks)))

    assert [item["id"] for item in result] == ["n1"]
    assert seen == [("n1", "w1"), ("p1", "w1")]


def test_admin_tenant_items_failure_falls_back_to_per_workspace_items():
    with aioresponses() as mocked:
        mocked.get(
            pbi_admin_url(),
            status=200,
            payload={"value": [{"id": "w1", "name": "PBI Workspace"}]},
        )
        mocked.get(f"{FABRIC_BASE}/v1/admin/items", status=500, payload={"error": "boom"})
        mocked.get(
            f"{FABRIC_BASE}/v1/admin/items?workspaceId=w1",
            status=200,
            payload={"itemEntities": [{"id": "i1", "type": "Notebook", "displayName": "Notebook"}]},
        )

        result = run(enum_mod.enumerate_workspaces_items(**enum_kwargs()))

    assert len(result) == 1
    assert result[0]["workspaceId"] == "w1"
    assert result[0]["workspaceName"] == "PBI Workspace"


def test_run_enumeration_sync_fresh_interpreter(monkeypatch):
    async def fake_enumeration(**kwargs):
        assert kwargs["token"] == TOKEN
        return [{"id": "fresh"}]

    monkeypatch.setattr(enum_mod, "enumerate_workspaces_items", fake_enumeration)

    result = enum_mod.run_enumeration_sync(**enum_kwargs())

    assert result == [{"id": "fresh"}]


def test_run_enumeration_sync_inside_running_event_loop(monkeypatch):
    async def fake_enumeration(**_kwargs):
        await asyncio.sleep(0)
        return [{"id": "running"}]

    monkeypatch.setattr(enum_mod, "enumerate_workspaces_items", fake_enumeration)

    async def scenario():
        return enum_mod.run_enumeration_sync(**enum_kwargs())

    result = asyncio.run(scenario())

    assert result == [{"id": "running"}]
