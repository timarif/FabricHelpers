"""Tests for ``fabric_core.http`` retrying urllib client + pagination."""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fabric_core import http


class _FakeResponse:
    """Minimal stand-in for the context manager returned by urlopen."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _ok(payload: dict, status: int = 200) -> _FakeResponse:
    return _FakeResponse(status, json.dumps(payload).encode("utf-8"))


def _http_error(code: int, body: bytes = b"", retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError(
        url="http://x",
        code=code,
        msg="err",
        hdrs=headers,
        fp=io.BytesIO(body),
    )


def _opener(side_effects):
    """Build a fake urllib opener whose .open(...) returns/raises each side effect in turn."""
    opener = SimpleNamespace()
    opener._calls = []
    iterator = iter(side_effects)

    def fake_open(request, timeout=None):
        opener._calls.append((request.get_method(), request.full_url, dict(request.headers), request.data))
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    opener.open = fake_open
    return opener


def test_request_json_success_returns_status_and_parsed_body():
    opener = _opener([_ok({"value": [{"id": "a"}]})])
    sleeps: list[float] = []

    status, body = http.request_json(
        "GET",
        "https://api.test/v1/items",
        token="tok",
        sleep=sleeps.append,
        opener=opener,
    )

    assert status == 200
    assert body == {"value": [{"id": "a"}]}
    method, url, headers, data = opener._calls[0]
    assert method == "GET"
    assert url == "https://api.test/v1/items"
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept"] == "application/json"
    assert "Content-Type" not in headers  # GET, no body
    assert data is None
    assert sleeps == []


def test_request_json_sends_json_body_and_content_type():
    opener = _opener([_ok({"id": "new"}, status=201)])

    status, body = http.request_json(
        "POST",
        "https://api.test/v1/items",
        token="tok",
        body={"name": "x"},
        sleep=lambda _s: None,
        opener=opener,
    )

    assert status == 201
    assert body == {"id": "new"}
    method, _url, headers, data = opener._calls[0]
    assert method == "POST"
    # urllib capitalizes only the first letter of header names.
    assert headers.get("Content-type") == "application/json"
    assert json.loads(data) == {"name": "x"}


def test_request_json_extra_headers_override_defaults():
    opener = _opener([_ok({})])
    http.request_json(
        "GET",
        "https://api.test",
        token="tok",
        headers={"Accept": "text/plain", "X-Run": "abc"},
        sleep=lambda _s: None,
        opener=opener,
    )
    _m, _u, headers, _d = opener._calls[0]
    # urllib capitalizes only the first letter of header names.
    assert headers.get("Accept") == "text/plain"
    assert headers.get("X-run") == "abc"
    assert headers.get("Authorization") == "Bearer tok"


def test_request_json_omits_authorization_when_no_token():
    opener = _opener([_ok({})])
    http.request_json("GET", "https://api.test", sleep=lambda _s: None, opener=opener)
    _m, _u, headers, _d = opener._calls[0]
    assert "Authorization" not in headers


def test_request_json_retries_429_and_honors_retry_after():
    opener = _opener([
        _http_error(429, retry_after="7"),
        _ok({"value": []}),
    ])
    sleeps: list[float] = []
    status, body = http.request_json(
        "GET",
        "https://api.test",
        sleep=sleeps.append,
        opener=opener,
    )
    assert status == 200
    assert body == {"value": []}
    assert sleeps == [7.0]


def test_request_json_429_without_retry_after_uses_exponential_backoff():
    opener = _opener([
        _http_error(429),
        _http_error(429),
        _ok({"ok": True}),
    ])
    sleeps: list[float] = []
    http.request_json("GET", "https://api.test", sleep=sleeps.append, opener=opener)
    assert sleeps == [1.0, 2.0]


def test_request_json_retries_5xx_and_returns_last_error_when_exhausted():
    opener = _opener([
        _http_error(503, body=b"down"),
        _http_error(503, body=b"down"),
        _http_error(503, body=b'{"error":"boom"}'),
    ])
    sleeps: list[float] = []
    status, body = http.request_json(
        "GET",
        "https://api.test",
        max_retries=3,
        sleep=sleeps.append,
        opener=opener,
    )
    assert status == 503
    assert body == {"error": "boom"}
    assert sleeps == [1.0, 2.0]  # backoff before retries 2 and 3


def test_request_json_returns_4xx_immediately_without_retry():
    opener = _opener([_http_error(404, body=b'{"error":"not found"}')])
    sleeps: list[float] = []
    status, body = http.request_json(
        "GET",
        "https://api.test",
        sleep=sleeps.append,
        opener=opener,
    )
    assert status == 404
    assert body == {"error": "not found"}
    assert sleeps == []


def test_request_json_4xx_body_falls_back_to_raw_when_not_json():
    opener = _opener([_http_error(400, body=b"plain text")])
    status, body = http.request_json(
        "GET",
        "https://api.test",
        sleep=lambda _s: None,
        opener=opener,
    )
    assert status == 400
    assert body == {"raw": "plain text"}


def test_request_json_url_error_raises_after_retries_exhausted():
    err = urllib.error.URLError("connection refused")
    opener = _opener([err, err, err])
    sleeps: list[float] = []
    with pytest.raises(urllib.error.URLError):
        http.request_json(
            "GET",
            "https://api.test",
            max_retries=3,
            sleep=sleeps.append,
            opener=opener,
        )
    assert sleeps == [1.0, 2.0]


def test_request_json_empty_body_decodes_as_empty_dict():
    opener = _opener([_FakeResponse(204, b"")])
    status, body = http.request_json(
        "DELETE",
        "https://api.test",
        sleep=lambda _s: None,
        opener=opener,
    )
    assert status == 204
    assert body == {}


def test_paged_get_walks_continuation_token():
    page1 = {"value": [{"id": 1}], "continuationToken": "tok=1"}
    page2 = {"value": [{"id": 2}]}
    opener = _opener([_ok(page1), _ok(page2)])
    pages = list(
        http.paged_get(
            "https://api.test/v1/items",
            sleep=lambda _s: None,
            opener=opener,
        )
    )
    assert [s for s, _b in pages] == [200, 200]
    second_url = opener._calls[1][1]
    assert "continuationToken=tok%3D1" in second_url


def test_paged_get_walks_continuation_uri():
    page1 = {
        "value": [{"id": 1}],
        "continuationUri": "https://api.test/v1/items?ct=xyz",
    }
    page2 = {"value": [{"id": 2}]}
    opener = _opener([_ok(page1), _ok(page2)])
    list(http.paged_get("https://api.test/v1/items", sleep=lambda _s: None, opener=opener))
    assert opener._calls[1][1] == "https://api.test/v1/items?ct=xyz"


def test_paged_get_walks_next_link_arm_shape():
    page1 = {"value": [{"id": 1}], "nextLink": "https://mgmt.test/page2"}
    page2 = {"value": [{"id": 2}]}
    opener = _opener([_ok(page1), _ok(page2)])
    list(http.paged_get("https://mgmt.test/page1", sleep=lambda _s: None, opener=opener))
    assert opener._calls[1][1] == "https://mgmt.test/page2"


def test_paged_get_stops_on_non_200():
    opener = _opener([_http_error(403, body=b'{"error":"forbidden"}')])
    pages = list(http.paged_get("https://api.test", sleep=lambda _s: None, opener=opener))
    assert pages == [(403, {"error": "forbidden"})]


def test_collect_paged_concatenates_value_keys():
    pages = [
        {"value": [{"id": 1}, {"id": 2}], "continuationToken": "n"},
        {"value": [{"id": 3}]},
    ]
    opener = _opener([_ok(pages[0]), _ok(pages[1])])
    items, status, body = http.collect_paged(
        "https://api.test",
        sleep=lambda _s: None,
        opener=opener,
    )
    assert items == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert status == 200
    assert body == pages[1]


def test_collect_paged_returns_partial_items_on_error():
    pages = [
        {"value": [{"id": 1}], "continuationToken": "n"},
    ]
    opener = _opener([_ok(pages[0]), _http_error(500, body=b'{"e":"boom"}')])
    items, status, body = http.collect_paged(
        "https://api.test",
        max_retries=1,
        sleep=lambda _s: None,
        opener=opener,
    )
    assert items == [{"id": 1}]
    assert status == 500
    assert body == {"e": "boom"}


def test_collect_paged_alternate_value_key():
    opener = _opener([_ok({"itemEntities": [{"id": "a"}, {"id": "b"}]})])
    items, status, _body = http.collect_paged(
        "https://api.test/v1/admin/items",
        value_key="itemEntities",
        sleep=lambda _s: None,
        opener=opener,
    )
    assert items == [{"id": "a"}, {"id": "b"}]
    assert status == 200


def test_request_json_default_sleep_is_time_sleep():
    """Ensure the default ``sleep`` parameter is ``time.sleep`` (smoke check)."""
    import time as _time

    # Keyword-only args land in __kwdefaults__.
    assert http.request_json.__kwdefaults__["sleep"] is _time.sleep
