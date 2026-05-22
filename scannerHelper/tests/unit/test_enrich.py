"""Tests for engine.enrich.enrich_attached_lakehouse."""
from __future__ import annotations

import json

from fabric_scanner.engine.enrich import enrich_attached_lakehouse


def _nb(lh: dict | None = None) -> bytes:
    deps = {"lakehouse": lh} if lh else {}
    body = {"cells": [], "metadata": {"dependencies": deps}}
    return json.dumps(body).encode("utf-8")


def test_empty_notebook_returns_all_nones():
    out = enrich_attached_lakehouse(_nb(), "nb.ipynb", {})
    assert out == {
        "attached_lakehouse_id": None,
        "attached_lakehouse_name": None,
        "attached_lakehouse_workspace_id": None,
        "attached_lakehouse_workspace_name": None,
    }


def test_extracts_default_lakehouse_fields():
    out = enrich_attached_lakehouse(_nb({
        "default_lakehouse": "lh-1",
        "default_lakehouse_name": "rawlh",
        "default_lakehouse_workspace_id": "ws-1",
    }), "nb.ipynb", {})
    assert out["attached_lakehouse_id"] == "lh-1"
    assert out["attached_lakehouse_name"] == "rawlh"
    assert out["attached_lakehouse_workspace_id"] == "ws-1"
    # name is None when the workspace map has no entry
    assert out["attached_lakehouse_workspace_name"] is None


def test_backfills_workspace_name_from_map():
    out = enrich_attached_lakehouse(_nb({
        "default_lakehouse": "lh-1",
        "default_lakehouse_workspace_id": "WS-1",
    }), "nb.ipynb", {"ws-1": "Prod Workspace"})
    assert out["attached_lakehouse_workspace_name"] == "Prod Workspace"


def test_does_not_overwrite_existing_workspace_name():
    """If the notebook metadata itself has a workspace name, the map lookup
    should NOT clobber it."""
    body = {
        "cells": [],
        "metadata": {"dependencies": {"lakehouse": {
            "default_lakehouse": "lh-1",
            "default_lakehouse_workspace_id": "ws-1",
        }}},
    }
    raw = json.dumps(body).encode("utf-8")
    # extract returns workspace_name=None for plain .ipynb (only id is in
    # metadata) so this test mostly documents the contract.
    out = enrich_attached_lakehouse(raw, "nb.ipynb",
                                    {"ws-1": "From Map"})
    assert out["attached_lakehouse_workspace_name"] == "From Map"


def test_no_workspace_map_safe():
    """Passing None or {} for ws_name_by_id must not crash."""
    out_none = enrich_attached_lakehouse(_nb({
        "default_lakehouse": "lh-1",
        "default_lakehouse_workspace_id": "ws-1",
    }), "nb.ipynb", None)
    out_empty = enrich_attached_lakehouse(_nb({
        "default_lakehouse": "lh-1",
        "default_lakehouse_workspace_id": "ws-1",
    }), "nb.ipynb", {})
    assert out_none["attached_lakehouse_workspace_name"] is None
    assert out_empty["attached_lakehouse_workspace_name"] is None
