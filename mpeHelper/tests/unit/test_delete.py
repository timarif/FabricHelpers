"""Tests for ``fabric_mpe.delete`` (dry-run + commit safety + audit shape)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from fabric_mpe import MpeConfig, delete


def _row(**overrides):
    base = {
        "workspace_id": "ws-a",
        "workspace_name": "A",
        "mpe_id": "m1",
        "mpe_name": "blob-1",
        "target_resource_id": "rid-1",
        "target_subresource_type": "blob",
        "provisioning_state": "Succeeded",
        "connection_status": "Approved",
    }
    base.update(overrides)
    return base


def test_dry_run_filters_match_name_and_target():
    rows = [_row(), _row(mpe_id="m2", mpe_name="sql-1", target_resource_id="rid-2")]
    cfg = MpeConfig(name_filter="^blob-")
    assert [r["mpe_id"] for r in delete.dry_run(cfg, rows=rows)] == ["m1"]

    cfg = MpeConfig(id_filter=("m2",))
    assert [r["mpe_id"] for r in delete.dry_run(cfg, rows=rows)] == ["m2"]


def test_dry_run_requires_rows_or_spark():
    with pytest.raises(RuntimeError, match="Spark"):
        delete.dry_run(MpeConfig())


def test_commit_skips_when_commit_flag_false():
    rows = [_row()]
    cfg = MpeConfig()  # commit=False
    with patch("fabric_mpe.delete.api.delete_mpe") as dm:
        result = delete.commit(cfg, rows=rows, token="tok")
    dm.assert_not_called()
    assert result.committed is False
    assert result.audit_rows == []
    assert [r["mpe_id"] for r in result.targets] == ["m1"]


def test_commit_aborts_when_targets_exceed_cap():
    rows = [_row(mpe_id=f"m{i}") for i in range(3)]
    cfg = MpeConfig(commit=True, max_deletes=2)
    with pytest.raises(RuntimeError, match="ABORT"):
        delete.commit(cfg, rows=rows, token="tok")


def test_commit_calls_delete_and_records_audit_for_each_target():
    rows = [_row(mpe_id="m1"), _row(mpe_id="m2", mpe_name="blob-2")]
    cfg = MpeConfig(commit=True)

    with patch(
        "fabric_mpe.delete.api.delete_mpe",
        side_effect=[(204, {}), (500, {"error": "boom"})],
    ) as dm:
        result = delete.commit(cfg, rows=rows, token="tok")

    assert dm.call_count == 2
    assert result.committed is True
    assert result.succeeded == 1
    assert result.failed == 1
    assert [r["mpe_id"] for r in result.audit_rows] == ["m1", "m2"]
    assert result.audit_rows[0]["delete_status"] == 204
    assert result.audit_rows[1]["delete_status"] == 500
    assert "error" in result.audit_rows[1]["delete_response"]


def test_commit_does_not_call_spark_when_no_spark_supplied():
    """Even with rows= provided, commit must tolerate spark=None."""
    rows = [_row()]
    cfg = MpeConfig(commit=True)
    with patch("fabric_mpe.delete.api.delete_mpe", return_value=(204, {})):
        result = delete.commit(cfg, spark=None, rows=rows, token="tok")
    assert result.committed is True
    assert result.audit_rows[0]["mpe_id"] == "m1"
