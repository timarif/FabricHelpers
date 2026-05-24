"""Minimal synchronous HTTP helper for the Fabric REST API.

Uses only stdlib (urllib) — no mandatory runtime deps beyond fabric-core.
Handles:
  - JSON request/response encoding
  - 429 / 5xx retries with exponential back-off
  - continuationUri / nextLink pagination
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

FABRIC_BASE = "https://api.fabric.microsoft.com"

# HTTP status codes that warrant a retry.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _request(
    method: str,
    url: str,
    token: str,
    body: dict | None = None,
    *,
    max_retries: int = 4,
    base_delay: float = 2.0,
) -> Any:
    """Make a synchronous JSON REST call with automatic retries.

    Parameters
    ----------
    method:
        HTTP verb (``"GET"``, ``"POST"``, ``"PATCH"``, …).
    url:
        Full URL to call.
    token:
        Bearer token (Authorization header value without the "Bearer " prefix).
    body:
        Optional request body; serialised to JSON when provided.
    max_retries:
        How many times to retry after a retryable HTTP error.
    base_delay:
        Initial retry delay in seconds (doubles on each retry unless the
        ``Retry-After`` response header specifies a longer wait).

    Returns
    -------
    Parsed JSON response body, or ``None`` when the response body is empty.

    Raises
    ------
    urllib.error.HTTPError
        When the server returns a non-retryable error status.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if attempt > max_retries or exc.code not in _RETRY_STATUSES:
                raise
            retry_after_hdr = exc.headers.get("Retry-After") if exc.headers else None
            try:
                wait = float(retry_after_hdr) if retry_after_hdr else base_delay * (2 ** (attempt - 1))
            except (TypeError, ValueError):
                wait = base_delay * (2 ** (attempt - 1))
            time.sleep(min(wait, 60.0))


def paged_get(url: str, token: str) -> list[dict]:
    """GET all pages of a Fabric collection.

    Follows ``continuationUri`` / ``nextLink`` pagination keys until exhausted.

    Parameters
    ----------
    url:
        Starting URL for the collection.
    token:
        Bearer token.

    Returns
    -------
    Flat list of all items across all pages.
    """
    results: list[dict] = []
    current_url: str | None = url
    while current_url:
        body = _request("GET", current_url, token)
        if body is None:
            break
        if isinstance(body, list):
            results.extend(body)
            break
        results.extend(body.get("value") or body.get("itemEntities") or [])
        current_url = body.get("continuationUri") or body.get("nextLink") or None
    return results
