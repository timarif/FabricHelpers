from __future__ import annotations

from dataclasses import fields
from unittest.mock import patch

import requests

from fabric_core.diagnostics import ProbeResult, probe_api


class MockResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object | None = None,
        text: str = "",
        reason: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = reason

    def json(self) -> object:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def _call_probe_api(*responses: MockResponse | BaseException, timeout: float = 30.0):
    calls = []

    def fake_get(url, *, headers, params, timeout):
        calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        response = responses[len(calls) - 1]
        if isinstance(response, BaseException):
            raise response
        return response

    with patch.object(requests, "get", side_effect=fake_get):
        results = probe_api(
            token="token-123",
            pbi_base="https://api.powerbi.com/",
            fabric_base="https://api.fabric.microsoft.com/",
            timeout=timeout,
        )
    return results, calls


def test_probe_result_dataclass_fields_and_defaults() -> None:
    field_names = [field.name for field in fields(ProbeResult)]

    assert field_names == ["name", "url", "status", "ok", "count", "elapsed_ms", "error", "detail"]
    result = ProbeResult("name", "url", 200, True, 3, 12)
    assert result.error is None
    assert result.detail == {}


def test_probe_result_detail_default_is_not_shared() -> None:
    first = ProbeResult("first", "url", 200, True, None, 1)
    second = ProbeResult("second", "url", 200, True, None, 1)

    first.detail["changed"] = True

    assert second.detail == {}


def test_probe_api_happy_path_returns_four_results_in_order() -> None:
    results, _ = _call_probe_api(
        MockResponse(payload={"value": [1]}),
        MockResponse(payload={"value": [1, 2]}),
        MockResponse(payload={"value": [1, 2, 3]}),
        MockResponse(payload={"value": []}),
    )

    assert [result.name for result in results] == [
        "pbi_admin_groups",
        "fabric_admin_workspaces",
        "fabric_admin_workspaces_items",
        "fabric_user_workspaces",
    ]
    assert len(results) == 4
    assert all(result.ok for result in results)


def test_probe_api_calls_expected_urls_without_item_type_filter() -> None:
    _, calls = _call_probe_api(
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
    )

    assert [call["url"] for call in calls] == [
        "https://api.powerbi.com/v1.0/myorg/admin/groups",
        "https://api.fabric.microsoft.com/v1/admin/workspaces",
        "https://api.fabric.microsoft.com/v1/admin/items",
        "https://api.fabric.microsoft.com/v1/workspaces",
    ]
    assert calls[2]["params"] == {}


def test_probe_api_sends_authorization_header_timeout_and_paging() -> None:
    _, calls = _call_probe_api(
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        timeout=9.5,
    )

    assert all(call["headers"]["Authorization"] == "Bearer token-123" for call in calls)
    assert all(call["timeout"] == 9.5 for call in calls)
    assert calls[0]["params"] == {"$top": 1}


def test_probe_api_unauthorized_endpoint_sets_error_and_continues() -> None:
    results, calls = _call_probe_api(
        MockResponse(payload={"value": [1]}),
        MockResponse(status_code=401, payload={"error": {"message": "unauthorized"}}),
        MockResponse(payload={"value": [1, 2]}),
        MockResponse(payload={"value": [1, 2, 3]}),
    )

    assert len(calls) == 4
    assert results[1].status == 401
    assert results[1].ok is False
    assert results[1].error == "unauthorized"
    assert [result.ok for result in results] == [True, False, True, True]


def test_probe_api_all_endpoints_timeout_return_status_zero() -> None:
    timeout = requests.Timeout("timed out")

    results, calls = _call_probe_api(timeout, timeout, timeout, timeout)

    assert len(calls) == 4
    assert len(results) == 4
    assert all(result.status == 0 for result in results)
    assert all(result.ok is False for result in results)
    assert all(result.count is None for result in results)
    assert all("Timeout" in (result.error or "") for result in results)


def test_probe_api_extracts_counts_from_value_arrays() -> None:
    results, _ = _call_probe_api(
        MockResponse(payload={"value": ["group-a", "group-b"]}),
        MockResponse(payload={"value": ["workspace-a"]}),
        MockResponse(payload={"value": ["item-a", "item-b", "item-c"]}),
        MockResponse(payload={"value": []}),
    )

    assert [result.count for result in results] == [2, 1, 3, 0]


def test_probe_api_count_is_none_when_value_is_missing_or_not_list() -> None:
    results, _ = _call_probe_api(
        MockResponse(payload={"value": {"not": "a-list"}}),
        MockResponse(payload={"other": []}),
        MockResponse(payload=["not-a-dict"]),
        MockResponse(payload=ValueError("not json"), text="plain text"),
    )

    assert [result.count for result in results] == [None, None, None, None]


def test_probe_api_non_json_error_uses_response_text() -> None:
    results, _ = _call_probe_api(
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(status_code=403, payload=ValueError("not json"), text="forbidden"),
        MockResponse(payload={"value": []}),
    )

    assert results[2].ok is False
    assert results[2].error == "forbidden"


def test_probe_api_elapsed_ms_is_non_negative_integer() -> None:
    results, _ = _call_probe_api(
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
        MockResponse(payload={"value": []}),
    )

    assert all(isinstance(result.elapsed_ms, int) for result in results)
    assert all(result.elapsed_ms >= 0 for result in results)
