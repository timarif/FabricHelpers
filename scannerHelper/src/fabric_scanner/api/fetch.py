"""Async `getDefinition` fetch with long-running-operation polling.

Each Fabric `POST /workspaces/{ws}/items/{id}/getDefinition` returns one
of:

    - HTTP 200 + body              -> definition immediately available
    - HTTP 202 + Location header   -> LRO; poll Location for status
    - HTTP 429 / 5xx + Retry-After -> backoff + retry up to `max_retries`
    - other                        -> permanent failure (return error)

`fetch_notebook_definition` returns `(body, error)`. Exactly one is
None. The caller (Spark partition function in Phase 3) builds the row
from `body` or stamps the error into the result row.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp


log = logging.getLogger(__name__)

LRO_POLL_INTERVAL_SEC = 2.0
LRO_MAX_POLLS = 180
DEFAULT_MAX_RETRIES = 4


async def fetch_notebook_definition(
    session: aiohttp.ClientSession,
    fabric_base: str,
    workspace_id: str,
    item_id: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    lro_poll_interval: float = LRO_POLL_INTERVAL_SEC,
    lro_max_polls: int = LRO_MAX_POLLS,
) -> tuple[dict | None, str | None]:
    """Fetch the .ipynb definition for one notebook.

    Returns `(body, error)`. On success, `body` is the parsed JSON
    payload and `error` is None. On failure, `body` is None and `error`
    is a short diagnostic string.
    """
    url = (f"{fabric_base}/v1/workspaces/{workspace_id}/items/{item_id}"
           f"/getDefinition?format=ipynb")
    poll_url: str | None = None

    for attempt in range(max_retries + 1):
        try:
            async with session.post(url) as r:
                if r.status == 200:
                    return await r.json(), None
                if r.status == 202:
                    poll_url = r.headers.get("Location")
                    if not poll_url:
                        return None, "202 without Location header"
                elif r.status in (429, 500, 502, 503, 504):
                    backoff = float(r.headers.get(
                        "Retry-After", str(min(2 ** attempt, 60))))
                    await asyncio.sleep(backoff)
                    continue
                else:
                    txt = await r.text()
                    return None, f"HTTP {r.status}: {txt[:200]}"

            assert poll_url is not None
            for _ in range(lro_max_polls):
                await asyncio.sleep(lro_poll_interval)
                async with session.get(poll_url) as p:
                    if p.status == 200:
                        pj = await p.json()
                        status = pj.get("status")
                        if status == "Succeeded":
                            async with session.get(poll_url + "/result") as res:
                                if res.status == 200:
                                    return await res.json(), None
                                return None, (f"LRO result HTTP {res.status}")
                        if status == "Failed":
                            return None, f"LRO failed: {pj}"
                    elif p.status == 429:
                        await asyncio.sleep(float(
                            p.headers.get("Retry-After", "5")))
            return None, "LRO poll timeout"
        except Exception as e:
            if attempt == max_retries:
                return None, f"{type(e).__name__}: {e}"
            await asyncio.sleep(min(2 ** attempt, 30))

    return None, "exhausted retries without a response"
