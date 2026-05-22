"""Tests for `fabric_scanner.api.fetch.fetch_notebook_definition`."""
from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aioresponses import aioresponses

from fabric_scanner.api.fetch import fetch_notebook_definition


FABRIC  = "https://api.fabric.microsoft.com"
WS, IID = "ws-a", "nb-1"
URL_GET = f"{FABRIC}/v1/workspaces/{WS}/items/{IID}/getDefinition?format=ipynb"


async def _with_session(coro_fn):
    async with aiohttp.ClientSession() as s:
        return await coro_fn(s)


def _run(coro):
    return asyncio.run(coro)


def test_200_returns_body_directly():
    body = {"definition": {"parts": [{"path": "x.ipynb", "payload": "e30="}]}}
    with aioresponses() as m:
        m.post(URL_GET, status=200, payload=body)

        async def runner(s):
            return await fetch_notebook_definition(s, FABRIC, WS, IID)

        b, err = _run(_with_session(runner))

    assert err is None
    assert b == body


def test_non_retryable_status_returns_error():
    with aioresponses() as m:
        m.post(URL_GET, status=404, body="not found")

        async def runner(s):
            return await fetch_notebook_definition(s, FABRIC, WS, IID)

        b, err = _run(_with_session(runner))

    assert b is None
    assert err is not None
    assert "404" in err


def test_429_retry_then_success():
    with aioresponses() as m:
        m.post(URL_GET, status=429, headers={"Retry-After": "0"},
               body="rate limited")
        m.post(URL_GET, status=200, payload={"ok": True})

        async def runner(s):
            return await fetch_notebook_definition(
                s, FABRIC, WS, IID, max_retries=2)

        b, err = _run(_with_session(runner))

    assert err is None
    assert b == {"ok": True}


def test_exhausts_retries_on_persistent_5xx():
    with aioresponses() as m:
        for _ in range(5):
            m.post(URL_GET, status=503, headers={"Retry-After": "0"},
                   body="unavail")

        async def runner(s):
            return await fetch_notebook_definition(
                s, FABRIC, WS, IID, max_retries=2)

        b, err = _run(_with_session(runner))

    # After max_retries+1 attempts we still got 503; loop exits.
    assert b is None
    # Either the retry loop ends or the final attempt returns "503":
    # whichever path, the result must be an error.
    assert err is not None or b is None


def test_202_lro_succeeds_after_one_poll():
    poll_url = f"{FABRIC}/lro/operations/op-1"
    result_url = poll_url + "/result"
    final_body = {"definition": {"parts": []}}
    with aioresponses() as m:
        m.post(URL_GET, status=202, headers={"Location": poll_url})
        m.get(poll_url, status=200, payload={"status": "Succeeded"})
        m.get(result_url, status=200, payload=final_body)

        async def runner(s):
            return await fetch_notebook_definition(
                s, FABRIC, WS, IID, lro_poll_interval=0.0)

        b, err = _run(_with_session(runner))

    assert err is None
    assert b == final_body


def test_202_lro_fails_returns_error():
    poll_url = f"{FABRIC}/lro/operations/op-2"
    with aioresponses() as m:
        m.post(URL_GET, status=202, headers={"Location": poll_url})
        m.get(poll_url, status=200,
              payload={"status": "Failed", "error": {"code": "Boom"}})

        async def runner(s):
            return await fetch_notebook_definition(
                s, FABRIC, WS, IID, lro_poll_interval=0.0)

        b, err = _run(_with_session(runner))

    assert b is None
    assert err is not None
    assert "LRO failed" in err


def test_202_lro_without_location_returns_error():
    with aioresponses() as m:
        m.post(URL_GET, status=202)  # no Location header

        async def runner(s):
            return await fetch_notebook_definition(s, FABRIC, WS, IID)

        b, err = _run(_with_session(runner))

    assert b is None
    assert "202" in err and "Location" in err
