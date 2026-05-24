"""Tests for ``fabric_mpe.api`` (REST wrappers + filter helpers)."""
from __future__ import annotations

from unittest.mock import patch

from fabric_mpe import MpeConfig
from fabric_mpe.api import (
    apply_filters,
    approve_pec,
    create_mpe,
    delete_mpe,
    list_mpes,
    list_pecs,
    list_workspaces,
)

CFG = MpeConfig(fabric_base="https://fab.test", arm_base="https://mgmt.test")
TOKEN = "tok"


def test_apply_filters_no_filters_returns_input_unchanged():
    rows = [{"mpe_id": "a"}, {"mpe_id": "b"}]
    assert apply_filters(rows) == rows


def test_apply_filters_id_filter_keeps_matching():
    rows = [{"mpe_id": "a"}, {"mpe_id": "b"}, {"mpe_id": "c"}]
    assert apply_filters(rows, id_filter=["a", "c"]) == [{"mpe_id": "a"}, {"mpe_id": "c"}]
    assert apply_filters(rows, id_filter=("b",)) == [{"mpe_id": "b"}]


def test_apply_filters_id_filter_none_or_empty_is_noop():
    rows = [{"mpe_id": "a"}]
    assert apply_filters(rows, id_filter=None) == rows
    assert apply_filters(rows, id_filter=[]) == rows


def test_apply_filters_name_filter_uses_regex():
    rows = [
        {"mpe_id": "1", "mpe_name": "prod-blob"},
        {"mpe_id": "2", "mpe_name": "dev-blob"},
        {"mpe_id": "3", "mpe_name": "prod-sql"},
    ]
    assert [r["mpe_id"] for r in apply_filters(rows, name_filter=r"^prod-")] == ["1", "3"]


def test_apply_filters_target_filter_uses_regex():
    rows = [
        {"mpe_id": "1", "target_resource_id": "/.../storageAccounts/a"},
        {"mpe_id": "2", "target_resource_id": "/.../servers/b"},
    ]
    assert [r["mpe_id"] for r in apply_filters(rows, target_filter=r"storageAccounts")] == ["1"]


def test_apply_filters_missing_fields_treated_as_empty():
    rows = [{"mpe_id": "1"}, {"mpe_id": "2", "mpe_name": "x"}]
    # Filter on name when row has no name — must not raise.
    assert apply_filters(rows, name_filter="x") == [{"mpe_id": "2", "mpe_name": "x"}]


def test_apply_filters_chains_all_three_filters():
    rows = [
        {"mpe_id": "a", "mpe_name": "prod-1", "target_resource_id": "x/storageAccounts/n"},
        {"mpe_id": "b", "mpe_name": "prod-2", "target_resource_id": "x/storageAccounts/n"},
        {"mpe_id": "c", "mpe_name": "prod-1", "target_resource_id": "x/servers/n"},
    ]
    out = apply_filters(
        rows, id_filter=["a", "c"], name_filter="prod-", target_filter="storageAccounts"
    )
    assert [r["mpe_id"] for r in out] == ["a"]


# ---- REST wrappers (verify URL composition + delegation) ------------------


def test_list_workspaces_calls_collect_paged_with_user_endpoint():
    with patch("fabric_mpe.api.collect_paged", return_value=([{"id": "ws1"}], 200, {})) as cp:
        rows = list_workspaces(CFG, TOKEN)
    assert rows == [{"id": "ws1"}]
    cp.assert_called_once()
    args, kwargs = cp.call_args
    assert args[0] == "https://fab.test/v1/workspaces"
    assert kwargs["token"] == TOKEN


def test_list_workspaces_raises_on_non_200():
    with patch("fabric_mpe.api.collect_paged", return_value=([], 403, {"e": "denied"})):
        try:
            list_workspaces(CFG, TOKEN)
        except RuntimeError as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")


def test_list_mpes_returns_rows_on_success_and_error_on_failure():
    with patch("fabric_mpe.api.collect_paged", return_value=([{"id": "mpe1"}], 200, {})):
        rows, err = list_mpes(CFG, "ws1", TOKEN)
    assert rows == [{"id": "mpe1"}]
    assert err is None

    with patch("fabric_mpe.api.collect_paged", return_value=([], 403, {"e": "x"})):
        rows, err = list_mpes(CFG, "ws1", TOKEN)
    assert rows == []
    assert err == {"status": 403, "body": {"e": "x"}}


def test_delete_mpe_issues_delete_to_correct_url():
    with patch("fabric_mpe.api.request_json", return_value=(204, {})) as rj:
        status, body = delete_mpe(CFG, "ws1", "mpe1", TOKEN)
    assert (status, body) == (204, {})
    rj.assert_called_once()
    args, kwargs = rj.call_args
    assert args == ("DELETE", "https://fab.test/v1/workspaces/ws1/managedPrivateEndpoints/mpe1")
    assert kwargs["token"] == TOKEN


def test_create_mpe_posts_body_to_correct_url():
    body_in = {"name": "n", "targetPrivateLinkResourceId": "rid"}
    with patch("fabric_mpe.api.request_json", return_value=(201, {"id": "new"})) as rj:
        status, body = create_mpe(CFG, "ws1", body_in, TOKEN)
    assert (status, body) == (201, {"id": "new"})
    args, kwargs = rj.call_args
    assert args == ("POST", "https://fab.test/v1/workspaces/ws1/managedPrivateEndpoints")
    assert kwargs["body"] == body_in
    assert kwargs["token"] == TOKEN


def test_list_pecs_uses_arm_base_and_api_version_from_rp():
    rid = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/a"
    payload = [{"name": "pec1"}]
    with patch("fabric_mpe.api.collect_paged", return_value=(payload, 200, {})) as cp:
        status, items, rp, api_v = list_pecs(CFG, rid, TOKEN)
    assert status == 200
    assert items == payload
    assert rp == "Microsoft.Storage/storageAccounts"
    assert api_v  # known RP -> non-default version
    url = cp.call_args[0][0]
    assert url.startswith(f"https://mgmt.test{rid}/privateEndpointConnections?api-version=")


def test_list_pecs_returns_error_payload_on_non_200():
    rid = "/subscriptions/x/providers/Microsoft.Storage/storageAccounts/a"
    with patch("fabric_mpe.api.collect_paged", return_value=([], 403, {"e": "x"})):
        status, body, rp, api_v = list_pecs(CFG, rid, TOKEN)
    assert status == 403
    assert body == {"e": "x"}
    assert rp == "Microsoft.Storage/storageAccounts"


def test_approve_pec_puts_approved_with_description_and_explicit_api_version():
    rid = "/subscriptions/x/providers/Microsoft.Storage/storageAccounts/a"
    with patch("fabric_mpe.api.request_json", return_value=(200, {})) as rj:
        status, _body = approve_pec(
            CFG, rid, "pec1", TOKEN, description="OK", api_version="2099-01-01"
        )
    assert status == 200
    args, kwargs = rj.call_args
    assert args[0] == "PUT"
    assert args[1] == (
        f"https://mgmt.test{rid}/privateEndpointConnections/pec1"
        "?api-version=2099-01-01"
    )
    body = kwargs["body"]
    state = body["properties"]["privateLinkServiceConnectionState"]
    assert state == {"status": "Approved", "description": "OK"}


def test_approve_pec_derives_api_version_from_resource_id_when_omitted():
    rid = "/subscriptions/x/providers/Microsoft.Storage/storageAccounts/a"
    with patch("fabric_mpe.api.request_json", return_value=(200, {})) as rj:
        approve_pec(CFG, rid, "pec1", TOKEN)
    args, _kw = rj.call_args
    assert "api-version=" in args[1]
