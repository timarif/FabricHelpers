"""Unit tests for import_existing.py."""
from __future__ import annotations

import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

# Add the scripts directory to the path so we can import directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from import_existing import (  # noqa: E402
    _logical_key,
    _req,
    build_inventory,
    get_fabric_token,
    list_mpes,
    list_workspaces,
    write_imports_tf,
    write_tfvars_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(status: int, body: dict):
    """Return a mock urlopen context manager."""
    raw = json.dumps(body).encode()
    resp = mock.MagicMock()
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    resp.status = status
    resp.read.return_value = raw
    return resp


# ---------------------------------------------------------------------------
# get_fabric_token
# ---------------------------------------------------------------------------

class TestGetFabricToken:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("FABRIC_TOKEN", "my-token")
        assert get_fabric_token() == "my-token"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("FABRIC_TOKEN", "  spaced-token  ")
        assert get_fabric_token() == "spaced-token"

    def test_falls_back_to_az_cli(self, monkeypatch):
        monkeypatch.delenv("FABRIC_TOKEN", raising=False)
        with mock.patch(
            "import_existing.subprocess.check_output", return_value="cli-token\n"
        ):
            assert get_fabric_token() == "cli-token"

    def test_raises_on_empty_cli_token(self, monkeypatch):
        monkeypatch.delenv("FABRIC_TOKEN", raising=False)
        with mock.patch(
            "import_existing.subprocess.check_output", return_value="\n"
        ):
            with pytest.raises(RuntimeError, match="empty token"):
                get_fabric_token()

    def test_raises_when_az_cli_fails(self, monkeypatch):
        monkeypatch.delenv("FABRIC_TOKEN", raising=False)
        with mock.patch(
            "import_existing.subprocess.check_output",
            side_effect=FileNotFoundError("az not found"),
        ):
            with pytest.raises(RuntimeError, match="FABRIC_TOKEN"):
                get_fabric_token()


# ---------------------------------------------------------------------------
# _req
# ---------------------------------------------------------------------------

class TestReq:
    def test_get_200(self):
        body = {"value": [{"id": "abc"}]}
        resp = _make_http_response(200, body)
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            status, data = _req("GET", "https://example.com", "token")
        assert status == 200
        assert data == body

    def test_http_error_returned_as_status_and_body(self):
        err_body = json.dumps({"error": {"code": "Forbidden"}}).encode()
        exc = urllib.error.HTTPError(
            url="https://example.com",
            code=403,
            msg="Forbidden",
            hdrs=mock.MagicMock(get=lambda k, d: d),  # type: ignore
            fp=BytesIO(err_body),
        )
        with mock.patch(
            "import_existing.urllib.request.urlopen", side_effect=exc
        ):
            status, data = _req("GET", "https://example.com", "token")
        assert status == 403
        assert data == {"error": {"code": "Forbidden"}}

    def test_retries_429(self):
        err_429 = urllib.error.HTTPError(
            url="https://example.com",
            code=429,
            msg="Too Many Requests",
            hdrs=mock.MagicMock(get=lambda k, d: "0"),  # Retry-After=0
            fp=BytesIO(b"{}"),
        )
        ok_resp = _make_http_response(200, {"value": []})
        with mock.patch(
            "import_existing.urllib.request.urlopen",
            side_effect=[err_429, ok_resp],
        ):
            with mock.patch("import_existing.time.sleep") as mock_sleep:
                status, _ = _req("GET", "https://example.com", "token")
        assert status == 200
        mock_sleep.assert_called_once_with(0)  # Retry-After header returned "0"


# ---------------------------------------------------------------------------
# list_workspaces
# ---------------------------------------------------------------------------

class TestListWorkspaces:
    def test_returns_workspaces(self):
        body = {"value": [{"id": "ws1", "displayName": "Workspace 1"}]}
        resp = _make_http_response(200, body)
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            ws = list_workspaces("token", "https://api.fabric.microsoft.com")
        assert len(ws) == 1
        assert ws[0]["id"] == "ws1"

    def test_paginates(self):
        page1 = {
            "value": [{"id": "ws1"}],
            "continuationToken": "tok1",
        }
        page2 = {"value": [{"id": "ws2"}]}
        resp1 = _make_http_response(200, page1)
        resp2 = _make_http_response(200, page2)
        with mock.patch(
            "import_existing.urllib.request.urlopen",
            side_effect=[resp1, resp2],
        ):
            ws = list_workspaces("token", "https://api.fabric.microsoft.com")
        assert [w["id"] for w in ws] == ["ws1", "ws2"]

    def test_raises_on_non_200(self):
        resp = _make_http_response(403, {"error": {"code": "Forbidden"}})
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            with pytest.raises(RuntimeError, match="List workspaces failed"):
                list_workspaces("token", "https://api.fabric.microsoft.com")


# ---------------------------------------------------------------------------
# list_mpes
# ---------------------------------------------------------------------------

class TestListMpes:
    def test_returns_mpes(self):
        body = {
            "value": [
                {
                    "id": "mpe1",
                    "name": "myMPE",
                    "targetPrivateLinkResourceId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa",
                    "targetSubresourceType": "blob",
                }
            ]
        }
        resp = _make_http_response(200, body)
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            mpes = list_mpes("ws1", "token", "https://api.fabric.microsoft.com")
        assert len(mpes) == 1
        assert mpes[0]["id"] == "mpe1"

    def test_returns_empty_on_permission_error(self):
        resp = _make_http_response(403, {"error": "forbidden"})
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            mpes = list_mpes("ws1", "token", "https://api.fabric.microsoft.com")
        assert mpes == []


# ---------------------------------------------------------------------------
# build_inventory
# ---------------------------------------------------------------------------

class TestBuildInventory:
    def test_uses_explicit_workspace_ids(self):
        mpe_body = {
            "value": [
                {
                    "id": "mpe-id-1",
                    "name": "myMPE",
                    "targetPrivateLinkResourceId": "/subscriptions/s/rg/r/p/M.Storage/storageAccounts/sa",
                    "targetSubresourceType": "blob",
                    "requestMessage": "hello",
                    "provisioningState": "Succeeded",
                }
            ]
        }
        resp = _make_http_response(200, mpe_body)
        with mock.patch("import_existing.urllib.request.urlopen", return_value=resp):
            inv = build_inventory(
                ["ws-guid-1"], "token", "https://api.fabric.microsoft.com"
            )
        assert len(inv) == 1
        assert inv[0]["workspace_id"] == "ws-guid-1"
        assert inv[0]["mpe_id"] == "mpe-id-1"
        assert inv[0]["name"] == "myMPE"

    def test_no_workspace_ids_lists_all(self):
        ws_body = {"value": [{"id": "ws-a", "displayName": "WS A"}]}
        mpe_body = {"value": [{"id": "mpe-x", "name": "x", "targetPrivateLinkResourceId": "/s/rg/p/M.S/storageAccounts/sa"}]}
        resp_ws = _make_http_response(200, ws_body)
        resp_mpe = _make_http_response(200, mpe_body)
        with mock.patch(
            "import_existing.urllib.request.urlopen",
            side_effect=[resp_ws, resp_mpe],
        ):
            inv = build_inventory(None, "token", "https://api.fabric.microsoft.com")
        assert len(inv) == 1
        assert inv[0]["workspace_name"] == "WS A"


# ---------------------------------------------------------------------------
# _logical_key
# ---------------------------------------------------------------------------

class TestLogicalKey:
    def test_basic(self):
        key = _logical_key("aabbccdd-0000-0000-0000-000000000000", "my-mpe")
        assert key == "ws_aabbccdd_my_mpe"

    def test_spaces_replaced(self):
        key = _logical_key("aabbccdd-0000-0000-0000-000000000000", "My MPE Name")
        assert "My_MPE_Name" in key

    def test_different_workspaces_produce_different_keys(self):
        k1 = _logical_key("aaaaaaaa-0000-0000-0000-000000000000", "mpe")
        k2 = _logical_key("bbbbbbbb-0000-0000-0000-000000000000", "mpe")
        assert k1 != k2


# ---------------------------------------------------------------------------
# write_imports_tf
# ---------------------------------------------------------------------------

class TestWriteImportsTf:
    def test_creates_file(self, tmp_path):
        inventory = [
            {
                "workspace_id": "ws-guid-1",
                "mpe_id": "mpe-guid-1",
                "name": "myMPE",
                "target_resource_id": "/s/rg/p/M.S/storageAccounts/sa",
                "target_subresource_type": "blob",
                "request_message": "hello",
                "provisioning_state": "Succeeded",
            }
        ]
        out = write_imports_tf(inventory, tmp_path)
        assert out.exists()
        content = out.read_text()
        assert "import" in content
        assert "ws-guid-1/mpe-guid-1" in content
        assert "module.mpe" in content

    def test_empty_inventory_creates_file(self, tmp_path):
        out = write_imports_tf([], tmp_path)
        assert out.exists()
        content = out.read_text()
        assert "Auto-generated" in content


# ---------------------------------------------------------------------------
# write_tfvars_json
# ---------------------------------------------------------------------------

class TestWriteTfvarsJson:
    def test_creates_valid_json(self, tmp_path):
        inventory = [
            {
                "workspace_id": "ws-1",
                "mpe_id": "mpe-1",
                "name": "storageMPE",
                "target_resource_id": "/s/rg/p/M.Storage/storageAccounts/sa",
                "target_subresource_type": "blob",
                "request_message": "hello",
                "provisioning_state": "Succeeded",
            }
        ]
        out = write_tfvars_json(inventory, tmp_path)
        data = json.loads(out.read_text())
        assert "managed_private_endpoints" in data
        endpoints = data["managed_private_endpoints"]
        assert len(endpoints) == 1
        entry = next(iter(endpoints.values()))
        assert entry["workspace_id"] == "ws-1"
        assert entry["name"] == "storageMPE"
        assert entry["target_subresource_type"] == "blob"

    def test_omits_null_subresource_type(self, tmp_path):
        inventory = [
            {
                "workspace_id": "ws-1",
                "mpe_id": "mpe-1",
                "name": "noSubMPE",
                "target_resource_id": "/s/rg/p/M.Storage/storageAccounts/sa",
                "target_subresource_type": None,
                "request_message": "msg",
                "provisioning_state": "Succeeded",
            }
        ]
        out = write_tfvars_json(inventory, tmp_path)
        data = json.loads(out.read_text())
        entry = next(iter(data["managed_private_endpoints"].values()))
        assert "target_subresource_type" not in entry
