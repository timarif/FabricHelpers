"""Async `getDefinition` fetch for any Fabric item type, with LRO polling
and 401 token refresh hooks.

Each Fabric `POST /workspaces/{ws}/items/{id}/getDefinition[?format=...]`
returns one of:

    - HTTP 200 + body              -> definition immediately available
    - HTTP 202 + Location header   -> LRO; poll Location for status
                                       (or x-ms-operation-id fallback)
    - HTTP 401                     -> token expired; refresh + retry
    - HTTP 429 / 5xx + Retry-After -> backoff + retry up to `max_retries`
    - other                        -> permanent failure (return error)

`fetch_item_definition` returns `(body, http_status, attempts, error)`.
Exactly one of `body` / `error` is None on a successful or terminal call.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import aiohttp


log = logging.getLogger(__name__)

LRO_POLL_INTERVAL_SEC = 2.0
LRO_MAX_POLLS = 180
DEFAULT_MAX_RETRIES = 4


async def fetch_item_definition(
    session: aiohttp.ClientSession,
    fabric_base: str,
    workspace_id: str,
    item_id: str,
    *,
    format_hint: str | None = None,
    headers_provider: Callable[[], dict[str, str]] | None = None,
    on_unauthorized: Callable[[], Awaitable[bool]] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    lro_poll_interval: float = LRO_POLL_INTERVAL_SEC,
    lro_max_polls: int = LRO_MAX_POLLS,
) -> tuple[dict | None, int, int, str | None]:
    """Fetch a Fabric item's getDefinition payload.

    Parameters
    ----------
    format_hint :
        Value for the `?format=` query string (e.g. `"ipynb"` for
        notebooks). When None, no `format` query param is sent and the
        API returns every definition part separately.
    headers_provider :
        Callable returning the current request headers dict (so the
        partition function can swap in a refreshed bearer token without
        rebuilding the aiohttp session). When None, request headers come
        from the session.
    on_unauthorized :
        Async callable invoked when the API returns HTTP 401. Should
        refresh the token and return True if the retry can proceed. When
        None, 401 is treated as a terminal failure.

    Returns
    -------
    `(body, http_status, attempts, error)`:
        - On success: `(body_dict, 200, n_attempts, None)`
        - On terminal failure: `(None, last_status, n_attempts, error_str)`
    """
    suffix = f"?format={format_hint}" if format_hint else ""
    url = (f"{fabric_base}/v1/workspaces/{workspace_id}/items/{item_id}"
           f"/getDefinition{suffix}")

    def _hdrs() -> dict[str, str] | None:
        return headers_provider() if headers_provider else None

    attempt = 0
    last_status = 0
    poll_url: str | None = None

    while attempt <= max_retries:
        try:
            async with session.post(url, headers=_hdrs()) as r:
                last_status = r.status
                if r.status == 200:
                    return await r.json(), 200, attempt + 1, None
                if r.status == 401 and on_unauthorized is not None \
                        and attempt < max_retries:
                    refreshed = await on_unauthorized()
                    if refreshed:
                        attempt += 1
                        continue
                    return None, 401, attempt + 1, "401 (no refresh)"
                if r.status == 202:
                    poll_url = r.headers.get("Location")
                    if not poll_url:
                        op_id = r.headers.get("x-ms-operation-id")
                        if op_id:
                            poll_url = (f"{fabric_base}/v1/operations/"
                                        f"{op_id}")
                        else:
                            return (None, 202, attempt + 1,
                                    "202 without Location or operation id")
                elif r.status in (429, 500, 502, 503, 504):
                    hdr = r.headers.get("Retry-After")
                    try:
                        wait = int(hdr) if hdr else min(2 ** attempt, 60)
                    except ValueError:
                        wait = min(2 ** attempt, 60)
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
                else:
                    txt = await r.text()
                    return None, r.status, attempt + 1, txt[:300]

            assert poll_url is not None
            for _ in range(lro_max_polls):
                await asyncio.sleep(lro_poll_interval)
                async with session.get(poll_url, headers=_hdrs()) as p:
                    last_status = p.status
                    if p.status == 401 and on_unauthorized is not None:
                        await on_unauthorized()
                        continue
                    if p.status == 200:
                        pj = await p.json()
                        status = pj.get("status")
                        if status == "Succeeded":
                            async with session.get(
                                    poll_url + "/result",
                                    headers=_hdrs()) as res:
                                if res.status == 200:
                                    return (await res.json(), 200,
                                            attempt + 1, None)
                                return (None, res.status,
                                        attempt + 1,
                                        f"LRO result HTTP {res.status}")
                        if status == "Failed":
                            return (None, 0, attempt + 1,
                                    f"LRO failed: {pj}")
                    elif p.status == 429:
                        await asyncio.sleep(float(
                            p.headers.get("Retry-After", "5")))
            return None, last_status, attempt + 1, "LRO poll timeout"
        except Exception as e:
            if attempt == max_retries:
                return None, last_status, attempt + 1, \
                    f"{type(e).__name__}: {e}"
            await asyncio.sleep(min(2 ** attempt, 30))
            attempt += 1

    return None, last_status, attempt, "max retries exceeded"
