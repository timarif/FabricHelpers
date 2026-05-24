"""Tests for ``fabric_mpe.recreate``."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from fabric_mpe import MpeConfig, recreate


def _audit_row(**overrides):
    base = {
        "workspace_id": "ws-a",
        "workspace_name": "A",
        "mpe_id": "old-1",
        "mpe_name": "blob-1",
        "target_resource_id": "rid-1",
        "target_subresource_type": "blob",
    }
    base.update(overrides)
    return base


def test_run_preview_when_recreate_flag_false():
    rows = [_audit_row()]
    cfg = MpeConfig()  # recreate=False
    with patch("fabric_mpe.recreate.api.create_mpe") as cm:
        result = recreate.run(cfg, rows=rows, token="tok")
    cm.assert_not_called()
    assert result.committed is False
    assert [r["mpe_name"] for r in result.targets] == ["blob-1"]


def test_run_aborts_when_targets_exceed_cap():
    rows = [_audit_row(mpe_id=f"old-{i}", mpe_name=f"blob-{i}") for i in range(3)]
    cfg = MpeConfig(recreate=True, max_recreates=2)
    with pytest.raises(RuntimeError, match="ABORT"):
        recreate.run(cfg, rows=rows, token="tok")


def test_run_calls_create_with_run_marker_in_request_message():
    rows = [_audit_row()]
    cfg = MpeConfig(
        recreate=True,
        recreate_request_message="Restoring blobs",
        run_label="2026-01-01",
    )

    seen_bodies = []

    def fake_create(c, wid, body, token):
        seen_bodies.append(body)
        return 201, {"id": "new-1", "provisioningState": "Provisioning"}

    with patch("fabric_mpe.recreate.api.create_mpe", side_effect=fake_create):
        result = recreate.run(cfg, rows=rows, token="tok")

    assert result.committed is True
    assert result.succeeded == 1
    body = seen_bodies[0]
    assert body["name"] == "blob-1"
    assert body["targetPrivateLinkResourceId"] == "rid-1"
    assert body["targetSubresourceType"] == "blob"
    assert body["requestMessage"].startswith("[run=2026-01-01] ")
    assert "Restoring blobs" in body["requestMessage"]

    audit = result.audit_rows[0]
    assert audit["original_mpe_id"] == "old-1"
    assert audit["new_mpe_id"] == "new-1"
    assert audit["new_provisioning_state"] == "Provisioning"
    assert audit["create_status"] == 201
    assert audit["source"] == "audit"


def test_run_truncates_request_message_to_140_chars():
    long_msg = "x" * 200
    cfg = MpeConfig(recreate=True, recreate_request_message=long_msg)
    seen = []

    with patch(
        "fabric_mpe.recreate.api.create_mpe",
        side_effect=lambda c, w, b, t: seen.append(b) or (201, {"id": "n"}),
    ):
        recreate.run(cfg, rows=[_audit_row()], token="tok")
    assert len(seen[0]["requestMessage"]) <= 140


def test_run_records_failure_status_in_audit():
    cfg = MpeConfig(recreate=True)
    with patch(
        "fabric_mpe.recreate.api.create_mpe",
        return_value=(409, {"error": "conflict"}),
    ):
        result = recreate.run(cfg, rows=[_audit_row()], token="tok")
    assert result.failed == 1
    assert result.succeeded == 0
    assert result.audit_rows[0]["create_status"] == 409
    assert "conflict" in result.audit_rows[0]["create_response"]


def test_run_omits_targetSubresourceType_when_blank():
    rows = [_audit_row(target_subresource_type=None)]
    cfg = MpeConfig(recreate=True)
    seen = []
    with patch(
        "fabric_mpe.recreate.api.create_mpe",
        side_effect=lambda c, w, b, t: seen.append(b) or (201, {"id": "n"}),
    ):
        recreate.run(cfg, rows=rows, token="tok")
    assert "targetSubresourceType" not in seen[0]
