"""Tests for `fabric_scanner.api.enumerate` — async workspace + notebook
listing, with HTTP mocked via aioresponses."""
from __future__ import annotations

import asyncio

import pytest
from aioresponses import aioresponses

from fabric_scanner import ScannerConfig
from fabric_scanner.api.enumerate import (
    enumerate_notebooks,
    run_enumeration_sync,
)


FABRIC = "https://api.fabric.microsoft.com"
PBI    = "https://api.powerbi.com"


def _await(coro):
    """Convenience runner — every test creates and tears down its own loop."""
    return asyncio.run(coro)


# --- User mode --------------------------------------------------------------

def test_user_mode_lists_workspaces_and_notebooks():
    cfg = ScannerConfig(source_mode="api", admin_mode=False)
    with aioresponses() as m:
        m.get(f"{FABRIC}/v1/workspaces", payload={"value": [
            {"id": "ws-a", "displayName": "Alpha"},
            {"id": "ws-b", "displayName": "Beta"},
        ]})
        m.get(f"{FABRIC}/v1/workspaces/ws-a/items", payload={"value": [
            {"id": "nb-1", "type": "Notebook", "displayName": "First"},
            {"id": "rep-1", "type": "Report",  "displayName": "Skip me"},
        ]})
        m.get(f"{FABRIC}/v1/workspaces/ws-b/items", payload={"value": [
            {"id": "nb-2", "type": "Notebook", "displayName": "Second"},
        ]})

        result = _await(enumerate_notebooks(cfg, "TOKEN"))

    assert len(result) == 2
    by_id = {n["id"]: n for n in result}
    assert by_id["nb-1"]["workspaceName"] == "Alpha"
    assert by_id["nb-2"]["workspaceName"] == "Beta"


def test_user_mode_returns_empty_when_no_workspaces():
    cfg = ScannerConfig(source_mode="api", admin_mode=False)
    with aioresponses() as m:
        m.get(f"{FABRIC}/v1/workspaces", payload={"value": []})
        assert _await(enumerate_notebooks(cfg, "T")) == []


def test_allowlist_filters_results():
    cfg = ScannerConfig(
        source_mode="api", admin_mode=False,
        read_workspace_ids=("ws-a",),
    )
    with aioresponses() as m:
        m.get(f"{FABRIC}/v1/workspaces", payload={"value": [
            {"id": "ws-a", "displayName": "Alpha"},
            {"id": "ws-b", "displayName": "Beta"},
        ]})
        m.get(f"{FABRIC}/v1/workspaces/ws-a/items", payload={"value": [
            {"id": "nb-1", "type": "Notebook", "displayName": "x"},
        ]})

        result = _await(enumerate_notebooks(cfg, "T"))

    assert [n["id"] for n in result] == ["nb-1"]


# --- Admin mode -------------------------------------------------------------

def test_admin_mode_uses_pbi_groups_then_tenant_items():
    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    with aioresponses() as m:
        # Step 1: workspace listing via PBI admin/groups (single page).
        m.get(
            f"{PBI}/v1.0/myorg/admin/groups?%24top=5000&%24skip=0",
            payload={"value": [
                {"id": "ws-a", "name": "Alpha"},
                {"id": "ws-b", "name": "Beta"},
            ]},
        )
        # Step 2: tenant-wide /v1/admin/items returns notebooks for both.
        m.get(f"{FABRIC}/v1/admin/items", payload={
            "itemEntities": [
                {"id": "nb-1", "type": "Notebook", "workspaceId": "ws-a",
                 "displayName": "First"},
                {"id": "nb-2", "type": "Notebook", "workspaceId": "ws-b",
                 "displayName": "Second"},
                {"id": "rep-1", "type": "Report", "workspaceId": "ws-a",
                 "displayName": "Skip"},
            ],
        })

        result = _await(enumerate_notebooks(cfg, "T"))

    assert {n["id"] for n in result} == {"nb-1", "nb-2"}
    by_id = {n["id"]: n for n in result}
    assert by_id["nb-1"]["workspaceName"] == "Alpha"


def test_admin_mode_falls_back_when_pbi_groups_fails():
    """If PBI admin/groups returns 403 the chain falls through to the
    Fabric admin endpoint."""
    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    with aioresponses() as m:
        m.get(
            f"{PBI}/v1.0/myorg/admin/groups?%24top=5000&%24skip=0",
            status=403, payload={"error": "denied"},
        )
        m.get(f"{FABRIC}/v1/admin/workspaces", payload={"value": [
            {"id": "ws-a", "displayName": "Alpha"},
        ]})
        m.get(f"{FABRIC}/v1/admin/items", payload={
            "itemEntities": [
                {"id": "nb-1", "type": "Notebook", "workspaceId": "ws-a",
                 "displayName": "n"},
            ],
        })
        result = _await(enumerate_notebooks(cfg, "T"))

    assert [n["id"] for n in result] == ["nb-1"]


def test_admin_tenant_failure_falls_back_to_per_workspace():
    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    with aioresponses() as m:
        m.get(
            f"{PBI}/v1.0/myorg/admin/groups?%24top=5000&%24skip=0",
            payload={"value": [{"id": "ws-a", "name": "Alpha"}]},
        )
        # tenant-wide items errors out
        m.get(f"{FABRIC}/v1/admin/items", status=500, payload={})
        # per-workspace fallback succeeds
        m.get(
            f"{FABRIC}/v1/admin/items?workspaceId=ws-a",
            payload={"itemEntities": [
                {"id": "nb-1", "type": "Notebook", "displayName": "x"},
            ]},
        )

        result = _await(enumerate_notebooks(cfg, "T"))

    assert [n["id"] for n in result] == ["nb-1"]
    assert result[0]["workspaceId"] == "ws-a"


# --- Sync wrapper -----------------------------------------------------------

def test_run_enumeration_sync_outside_running_loop():
    cfg = ScannerConfig(source_mode="api", admin_mode=False)
    with aioresponses() as m:
        m.get(f"{FABRIC}/v1/workspaces", payload={"value": [
            {"id": "ws-a", "displayName": "Alpha"},
        ]})
        m.get(f"{FABRIC}/v1/workspaces/ws-a/items", payload={"value": [
            {"id": "nb-1", "type": "Notebook", "displayName": "x"},
        ]})
        result = run_enumeration_sync(cfg, "T")

    assert [n["id"] for n in result] == ["nb-1"]


def test_run_enumeration_sync_inside_running_loop():
    """When called from inside a running loop the sync helper must spin up
    a worker thread + its own loop. We simulate Jupyter by running the
    sync call from a coroutine."""
    cfg = ScannerConfig(source_mode="api", admin_mode=False)

    async def driver():
        # aioresponses must be entered inside the calling loop so the
        # patches are active when the worker thread reuses them; using a
        # synchronous with-block here means the same mock is visible to
        # the worker thread too.
        with aioresponses() as m:
            m.get(f"{FABRIC}/v1/workspaces", payload={"value": [
                {"id": "ws-a", "displayName": "Alpha"},
            ]})
            m.get(f"{FABRIC}/v1/workspaces/ws-a/items", payload={"value": [
                {"id": "nb-1", "type": "Notebook", "displayName": "x"},
            ]})
            return run_enumeration_sync(cfg, "T")

    result = asyncio.run(driver())
    assert [n["id"] for n in result] == ["nb-1"]
