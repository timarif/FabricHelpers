"""Tests for ``fabric_mpe.inventory.collect`` (no Spark required)."""
from __future__ import annotations

from unittest.mock import patch

from fabric_mpe import MpeConfig, inventory


def _ep(**overrides):
    base = {
        "id": "mpe-1",
        "name": "blob-1",
        "targetPrivateLinkResourceId": "rid",
        "targetSubresourceType": "blob",
        "provisioningState": "Succeeded",
        "connectionState": {"status": "Approved", "description": "ok"},
    }
    base.update(overrides)
    return base


def test_collect_visible_scope_uses_workspace_list_and_flattens_rows():
    cfg = MpeConfig(workspace_scope="visible", run_label="r1")
    workspaces = [
        {"id": "ws-a", "displayName": "A"},
        {"id": "ws-b", "displayName": "B"},
    ]
    mpes_by_ws = {
        "ws-a": ([_ep(id="m1"), _ep(id="m2", name="blob-2")], None),
        "ws-b": ([_ep(id="m3")], None),
    }

    with patch("fabric_mpe.inventory.api.list_workspaces", return_value=workspaces), patch(
        "fabric_mpe.inventory.api.list_mpes",
        side_effect=lambda c, wid, t: mpes_by_ws[wid],
    ):
        result = inventory.collect(cfg, token="tok")

    assert len(result.rows) == 3
    assert result.workspace_ids == ["ws-a", "ws-b"]
    assert result.workspace_names == {"ws-a": "A", "ws-b": "B"}
    first = result.rows[0]
    assert first["workspace_id"] == "ws-a"
    assert first["workspace_name"] == "A"
    assert first["mpe_id"] == "m1"
    assert first["connection_status"] == "Approved"
    assert first["run_label"] == "r1"


def test_collect_records_skipped_workspaces_on_list_error():
    cfg = MpeConfig(workspace_scope="visible")
    with patch(
        "fabric_mpe.inventory.api.list_workspaces",
        return_value=[{"id": "ws-a"}, {"id": "ws-b"}],
    ), patch(
        "fabric_mpe.inventory.api.list_mpes",
        side_effect=[
            ([_ep()], None),
            ([], {"status": 403, "body": "denied"}),
        ],
    ):
        result = inventory.collect(cfg, token="tok")

    assert len(result.rows) == 1
    assert result.skipped == [("ws-b", {"status": 403, "body": "denied"})]


def test_collect_list_scope_skips_workspace_listing():
    cfg = MpeConfig(workspace_scope="list", workspaces=("ws-a", "ws-b"))
    with patch("fabric_mpe.inventory.api.list_workspaces") as lw, patch(
        "fabric_mpe.inventory.api.list_mpes",
        return_value=([_ep()], None),
    ):
        result = inventory.collect(cfg, token="tok")
    lw.assert_not_called()
    assert result.workspace_ids == ["ws-a", "ws-b"]
    assert len(result.rows) == 2  # 1 ep per workspace


def test_collect_from_inventory_scope_requires_spark():
    cfg = MpeConfig(workspace_scope="from_inventory")
    try:
        inventory.collect(cfg, token="tok")
    except RuntimeError as exc:
        assert "Spark" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
