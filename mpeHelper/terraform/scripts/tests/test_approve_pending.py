"""Unit tests for approve_pending.py."""
from __future__ import annotations

import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

# Add the scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from approve_pending import (  # noqa: E402
    _pec_api_version,
    _pec_is_pending,
    _pec_matches_run_label,
    _req,
    _rp_from_resource_id,
    approve_pec,
    approve_pending_for_resources,
    get_arm_token,
    list_pecs,
    load_target_resource_ids,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(status: int, body: dict):
    raw = json.dumps(body).encode()
    resp = mock.MagicMock()
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    resp.status = status
    resp.read.return_value = raw
    return resp


def _sample_pec(
    name: str = "pec-1",
    status: str = "Pending",
    description: str = "",
) -> dict:
    return {
        "id": f"/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa/privateEndpointConnections/{name}",
        "name": name,
        "properties": {
            "privateLinkServiceConnectionState": {
                "status": status,
                "description": description,
            }
        },
    }


# ---------------------------------------------------------------------------
# _rp_from_resource_id
# ---------------------------------------------------------------------------

class TestRpFromResourceId:
    def test_storage(self):
        rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"
        assert _rp_from_resource_id(rid) == "Microsoft.Storage/storageAccounts"

    def test_keyvault(self):
        rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv"
        assert _rp_from_resource_id(rid) == "Microsoft.KeyVault/vaults"

    def test_returns_none_for_empty(self):
        assert _rp_from_resource_id("") is None

    def test_returns_none_for_no_providers_segment(self):
        assert _rp_from_resource_id("/subscriptions/sub/resourceGroups/rg") is None


# ---------------------------------------------------------------------------
# _pec_api_version
# ---------------------------------------------------------------------------

class TestPecApiVersion:
    def test_known_storage(self):
        rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"
        api, rp = _pec_api_version(rid)
        assert api == "2023-05-01"
        assert rp == "Microsoft.Storage/storageAccounts"

    def test_unknown_rp_falls_back_to_default(self):
        rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Unknown/things/x"
        api, _ = _pec_api_version(rid)
        assert api == "2023-09-01"


# ---------------------------------------------------------------------------
# _pec_is_pending
# ---------------------------------------------------------------------------

class TestPecIsPending:
    def test_pending(self):
        assert _pec_is_pending(_sample_pec(status="Pending")) is True

    def test_approved(self):
        assert _pec_is_pending(_sample_pec(status="Approved")) is False

    def test_case_insensitive(self):
        pec = _sample_pec()
        pec["properties"]["privateLinkServiceConnectionState"]["status"] = "PENDING"
        assert _pec_is_pending(pec) is True


# ---------------------------------------------------------------------------
# _pec_matches_run_label
# ---------------------------------------------------------------------------

class TestPecMatchesRunLabel:
    def test_no_label_always_matches(self):
        assert _pec_matches_run_label(_sample_pec(), "") is True

    def test_matching_label(self):
        pec = _sample_pec(description="[run=2026-01-15_10-00-00] Recreated")
        assert _pec_matches_run_label(pec, "2026-01-15_10-00-00") is True

    def test_different_label_does_not_match(self):
        pec = _sample_pec(description="[run=2026-01-15_10-00-00] Recreated")
        assert _pec_matches_run_label(pec, "2025-01-01_00-00-00") is False

    def test_no_marker_does_not_match_when_label_set(self):
        pec = _sample_pec(description="plain description")
        assert _pec_matches_run_label(pec, "2026-01-15_10-00-00") is False


# ---------------------------------------------------------------------------
# get_arm_token
# ---------------------------------------------------------------------------

class TestGetArmToken:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("ARM_TOKEN", "my-arm-token")
        assert get_arm_token() == "my-arm-token"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("ARM_TOKEN", "  spaced  ")
        assert get_arm_token() == "spaced"

    def test_uses_az_cli_when_no_env_and_no_azure_identity(self, monkeypatch):
        monkeypatch.delenv("ARM_TOKEN", raising=False)
        with mock.patch(
            "approve_pending.subprocess.check_output", return_value="cli-arm-token\n"
        ):
            # Make azure-identity unavailable
            with mock.patch.dict(sys.modules, {"azure.identity": None}):
                token = get_arm_token()
        assert token == "cli-arm-token"

    def test_raises_when_cli_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ARM_TOKEN", raising=False)
        with mock.patch(
            "approve_pending.subprocess.check_output", return_value="\n"
        ):
            with mock.patch.dict(sys.modules, {"azure.identity": None}):
                with pytest.raises(RuntimeError, match="empty token"):
                    get_arm_token()


# ---------------------------------------------------------------------------
# _req
# ---------------------------------------------------------------------------

class TestReqApprove:
    def test_200_success(self):
        body = {"id": "something"}
        resp = _make_http_response(200, body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ):
            status, data = _req("GET", "https://example.com", "tok")
        assert status == 200
        assert data == body

    def test_403_returns_error_tuple(self):
        err_body = json.dumps({"error": "Forbidden"}).encode()
        exc = urllib.error.HTTPError(
            url="https://example.com",
            code=403,
            msg="Forbidden",
            hdrs=mock.MagicMock(get=lambda k, d: d),
            fp=BytesIO(err_body),
        )
        with mock.patch(
            "approve_pending.urllib.request.urlopen", side_effect=exc
        ):
            status, data = _req("GET", "https://example.com", "tok")
        assert status == 403


# ---------------------------------------------------------------------------
# list_pecs
# ---------------------------------------------------------------------------

class TestListPecs:
    RID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"

    def test_returns_pec_list(self):
        pec = _sample_pec()
        body = {"value": [pec]}
        resp = _make_http_response(200, body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ):
            status, payload, rp, api = list_pecs(self.RID, "tok")
        assert status == 200
        assert isinstance(payload, list)
        assert len(payload) == 1

    def test_returns_error_on_403(self):
        body = {"error": "Forbidden"}
        resp = _make_http_response(403, body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ):
            status, payload, _, _ = list_pecs(self.RID, "tok")
        assert status == 403
        assert isinstance(payload, dict)

    def test_paginates_via_nextLink(self):
        page1 = {"value": [_sample_pec("pec-1")], "nextLink": "https://next.link"}
        page2 = {"value": [_sample_pec("pec-2")]}
        resp1 = _make_http_response(200, page1)
        resp2 = _make_http_response(200, page2)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", side_effect=[resp1, resp2]
        ):
            status, payload, _, _ = list_pecs(self.RID, "tok")
        assert status == 200
        assert len(payload) == 2


# ---------------------------------------------------------------------------
# approve_pec
# ---------------------------------------------------------------------------

class TestApprovePec:
    RID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"

    def test_sends_put(self):
        resp = _make_http_response(200, {"id": "approved"})
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ) as mock_open:
            status, _ = approve_pec(self.RID, "pec-1", "tok")
        assert status == 200
        req = mock_open.call_args[0][0]
        assert req.get_method() == "PUT"
        body = json.loads(req.data)
        assert body["properties"]["privateLinkServiceConnectionState"]["status"] == "Approved"


# ---------------------------------------------------------------------------
# approve_pending_for_resources
# ---------------------------------------------------------------------------

class TestApprovePendingForResources:
    RID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"

    def test_dry_run_does_not_call_put(self):
        list_body = {"value": [_sample_pec("p1", status="Pending")]}
        resp = _make_http_response(200, list_body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ) as mock_open:
            results = approve_pending_for_resources(
                [self.RID], "tok", dry_run=True
            )
        # Only one call (the LIST) — no PUT
        assert mock_open.call_count == 1
        assert results[0]["status"] == "dry-run"

    def test_approves_pending_pecs(self):
        list_body = {"value": [_sample_pec("p1", status="Pending")]}
        approve_body = {"id": "approved"}
        resp_list = _make_http_response(200, list_body)
        resp_approve = _make_http_response(200, approve_body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen",
            side_effect=[resp_list, resp_approve],
        ):
            results = approve_pending_for_resources([self.RID], "tok")
        assert results[0]["status"] == 200

    def test_skips_already_approved_pecs(self):
        list_body = {"value": [_sample_pec("p1", status="Approved")]}
        resp = _make_http_response(200, list_body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ) as mock_open:
            results = approve_pending_for_resources([self.RID], "tok")
        # Only LIST, no PUT
        assert mock_open.call_count == 1
        assert len(results) == 0

    def test_run_label_filters_pecs(self):
        pec_with_label = _sample_pec(
            "p-match", status="Pending", description="[run=run-123] recreated"
        )
        pec_without_label = _sample_pec("p-other", status="Pending", description="other")
        list_body = {"value": [pec_with_label, pec_without_label]}
        approve_body = {"id": "approved"}
        resp_list = _make_http_response(200, list_body)
        resp_approve = _make_http_response(200, approve_body)
        with mock.patch(
            "approve_pending.urllib.request.urlopen",
            side_effect=[resp_list, resp_approve],
        ):
            results = approve_pending_for_resources(
                [self.RID], "tok", run_label="run-123"
            )
        # Only p-match was approved
        assert len(results) == 1
        assert results[0]["pec_name"] == "p-match"

    def test_handles_list_error(self):
        resp = _make_http_response(403, {"error": "Forbidden"})
        with mock.patch(
            "approve_pending.urllib.request.urlopen", return_value=resp
        ):
            results = approve_pending_for_resources([self.RID], "tok")
        assert len(results) == 1
        assert results[0]["status"] == 403


# ---------------------------------------------------------------------------
# load_target_resource_ids
# ---------------------------------------------------------------------------

class TestLoadTargetResourceIds:
    def test_parses_tfvars_json(self, tmp_path):
        payload = {
            "managed_private_endpoints": {
                "key1": {
                    "workspace_id": "ws-1",
                    "name": "mpe1",
                    "target_resource_id": "/subscriptions/s/rg/rg/providers/Microsoft.Storage/storageAccounts/sa1",
                },
                "key2": {
                    "workspace_id": "ws-1",
                    "name": "mpe2",
                    "target_resource_id": "/subscriptions/s/rg/rg/providers/Microsoft.Storage/storageAccounts/sa1",
                },
                "key3": {
                    "workspace_id": "ws-2",
                    "name": "mpe3",
                    "target_resource_id": "/subscriptions/s/rg/rg/providers/Microsoft.KeyVault/vaults/kv1",
                },
            }
        }
        f = tmp_path / "terraform.tfvars.json"
        f.write_text(json.dumps(payload))
        ids = load_target_resource_ids(f)
        # sa1 and kv1 — deduped
        assert len(ids) == 2
        resource_types = [_rp_from_resource_id(r) for r in ids]
        assert "Microsoft.Storage/storageAccounts" in resource_types
        assert "Microsoft.KeyVault/vaults" in resource_types

    def test_empty_file(self, tmp_path):
        f = tmp_path / "terraform.tfvars.json"
        f.write_text("{}")
        ids = load_target_resource_ids(f)
        assert ids == []
