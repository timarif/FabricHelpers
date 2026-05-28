from __future__ import annotations

import json
import urllib.error

from fabric_downloader.handlers.lakehouse import fetch_lakehouse_tables


class _Resp:
    def __init__(self, body: dict) -> None:
        self._body = body

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_fetch_lakehouse_tables_happy_path(monkeypatch):
    def fake_urlopen(req, timeout):
        assert timeout == 120
        assert req.full_url.endswith("/v1/workspaces/ws-1/lakehouses/lh-1/tables")
        return _Resp({"value": [{"name": "t1"}]})

    monkeypatch.setattr("fabric_downloader.handlers.lakehouse.urllib.request.urlopen", fake_urlopen)

    out = fetch_lakehouse_tables(
        workspace_id="ws-1",
        lakehouse_id="lh-1",
        token="tok",
        fabric_base="https://api.fabric.microsoft.com",
    )
    assert out == {"value": [{"name": "t1"}]}


def test_fetch_lakehouse_tables_pagination(monkeypatch):
    seen_urls: list[str] = []

    def fake_urlopen(req, timeout):
        del timeout
        seen_urls.append(req.full_url)
        if len(seen_urls) == 1:
            return _Resp(
                {
                    "value": [{"name": "t1"}],
                    "continuationToken": "next page token",
                }
            )
        return _Resp({"value": [{"name": "t2"}]})

    monkeypatch.setattr("fabric_downloader.handlers.lakehouse.urllib.request.urlopen", fake_urlopen)

    out = fetch_lakehouse_tables(
        workspace_id="ws-1",
        lakehouse_id="lh-1",
        token="tok",
        fabric_base="https://api.fabric.microsoft.com",
    )
    assert out == {"value": [{"name": "t1"}, {"name": "t2"}]}
    assert "continuationToken=next+page+token" in seen_urls[1]


def test_fetch_lakehouse_tables_404_returns_empty(monkeypatch):
    def fake_urlopen(req, timeout):
        del req, timeout
        raise urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)

    monkeypatch.setattr("fabric_downloader.handlers.lakehouse.urllib.request.urlopen", fake_urlopen)

    out = fetch_lakehouse_tables(
        workspace_id="ws-1",
        lakehouse_id="lh-1",
        token="tok",
        fabric_base="https://api.fabric.microsoft.com",
    )
    assert out == {"value": []}


def test_fetch_lakehouse_tables_403_returns_forbidden_and_warns(monkeypatch, caplog):
    def fake_urlopen(req, timeout):
        del req, timeout
        raise urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)

    monkeypatch.setattr("fabric_downloader.handlers.lakehouse.urllib.request.urlopen", fake_urlopen)

    out = fetch_lakehouse_tables(
        workspace_id="ws-1",
        lakehouse_id="lh-1",
        token="tok",
        fabric_base="https://api.fabric.microsoft.com",
    )
    assert out == {"error": "forbidden"}
    assert "forbidden" in caplog.text.lower()
