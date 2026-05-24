"""Tests for ``fabric_mpe.approve`` (queue building + approval pipeline)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from fabric_mpe import MpeConfig, approve

RID_A = "/subscriptions/x/providers/Microsoft.Storage/storageAccounts/acct-a"
RID_B = "/subscriptions/x/providers/Microsoft.Sql/servers/srv-b"


def _recreate_row(target=RID_A, mpe_name="blob-1", new_mpe_id="new-1"):
    return {
        "workspace_id": "ws-a",
        "workspace_name": "A",
        "original_mpe_id": "old-1",
        "new_mpe_id": new_mpe_id,
        "mpe_name": mpe_name,
        "target_resource_id": target,
        "request_message": "Recreated via fabric-mpe",
    }


def _pec(name, status, description):
    return {
        "name": name,
        "properties": {
            "privateLinkServiceConnectionState": {
                "status": status,
                "description": description,
            }
        },
    }


def test_run_preview_only_when_approve_flag_false():
    cfg = MpeConfig(run_label="2026-01-01")  # approve=False
    marker = "[run=2026-01-01]"
    rows = [_recreate_row()]

    list_pecs_payload = [
        _pec("pec1", "Pending", f"{marker} Recreated"),
        _pec("pec2", "Approved", f"{marker} Already approved"),
    ]
    with patch(
        "fabric_mpe.approve.api.list_pecs",
        return_value=(200, list_pecs_payload, "Microsoft.Storage/storageAccounts", "2023-05-01"),
    ), patch("fabric_mpe.approve.api.approve_pec") as ap:
        result = approve.run(cfg, rows=rows, token="arm-tok")

    ap.assert_not_called()
    assert result.committed is False
    # Only the Pending PEC with the marker should be queued.
    assert [q["pec_name"] for q in result.queue] == ["pec1"]


def test_run_skips_pecs_without_marker():
    cfg = MpeConfig(approve=True, run_label="2026-01-01")
    rows = [_recreate_row()]
    list_pecs_payload = [
        _pec("pec1", "Pending", "Some other thing"),
        _pec("pec2", "Pending", "[run=2026-01-01] Recreated"),
    ]
    with patch(
        "fabric_mpe.approve.api.list_pecs",
        return_value=(200, list_pecs_payload, "Microsoft.Storage/storageAccounts", "2023-05-01"),
    ), patch(
        "fabric_mpe.approve.api.approve_pec",
        return_value=(200, {"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}}),
    ) as ap:
        result = approve.run(cfg, rows=rows, token="arm-tok")

    assert ap.call_count == 1
    assert ap.call_args[0][2] == "pec2"  # pec_name positional arg
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.audit_rows[0]["new_connection_state"] == "Approved"


def test_run_aborts_when_queue_exceeds_cap():
    cfg = MpeConfig(approve=True, max_approves=1, run_label="2026-01-01")
    rows = [_recreate_row(), _recreate_row(mpe_name="blob-2", new_mpe_id="new-2")]
    marker = "[run=2026-01-01]"
    pecs = [
        _pec("pec1", "Pending", f"{marker} a"),
        _pec("pec2", "Pending", f"{marker} b"),
    ]
    with patch(
        "fabric_mpe.approve.api.list_pecs",
        return_value=(200, pecs, "Microsoft.Storage/storageAccounts", "2023-05-01"),
    ), pytest.raises(RuntimeError, match="ABORT"):
        approve.run(cfg, rows=rows, token="arm-tok")


def test_run_records_list_errors_with_status_in_audit():
    cfg = MpeConfig(approve=True, run_label="2026-01-01")
    marker = "[run=2026-01-01]"
    rows = [
        _recreate_row(),  # RID_A — list succeeds
        _recreate_row(target=RID_B, new_mpe_id="new-2"),  # RID_B — list fails
    ]

    def fake_list_pecs(_cfg, target, _token):
        if target == RID_A:
            return (
                200,
                [_pec("pec1", "Pending", f"{marker} ok")],
                "Microsoft.Storage/storageAccounts",
                "2023-05-01",
            )
        return 403, {"e": "forbidden"}, "Microsoft.Sql/servers", "2023-08-01-preview"

    with patch("fabric_mpe.approve.api.list_pecs", side_effect=fake_list_pecs), patch(
        "fabric_mpe.approve.api.approve_pec",
        return_value=(200, {}),
    ):
        result = approve.run(cfg, rows=rows, token="arm-tok")

    assert result.succeeded == 1
    assert len(result.list_errors) == 1
    # Audit must include one row for the approve PUT and one for the LIST error.
    statuses = sorted(r["approve_status"] for r in result.audit_rows)
    assert statuses == [200, 403]


def test_run_no_op_when_no_candidates_and_no_errors():
    cfg = MpeConfig(approve=True)
    with patch("fabric_mpe.approve.api.list_pecs") as lp:
        result = approve.run(cfg, rows=[], token="arm-tok")
    lp.assert_not_called()
    assert result.audit_rows == []
    assert result.committed is False
