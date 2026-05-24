"""Retrying urllib JSON client for synchronous Fabric / ARM REST calls.

This is the small synchronous companion to :mod:`fabric_core.enumerate`'s
async aiohttp loops. It exists for callers — like the MPE manager and any
notebook-friendly CLI — that issue a handful of GET/POST/PUT/DELETE calls
and would rather not pull in :mod:`aiohttp`.

Behavior:

* Returns ``(status, parsed_body)`` from :func:`request_json` — never raises
  on HTTP errors. Network / DNS failures raise after exhausting retries.
* Retries 429 (honouring ``Retry-After``) and 5xx with exponential backoff
  capped at 30 seconds, up to ``max_retries`` attempts.
* Walks the three pagination shapes Fabric / Power BI / ARM use:
  ``continuationToken``, ``continuationUri``, and ``nextLink`` — via
  :func:`paged_get`.

Body parsing falls back to ``{"raw": <text>}`` when the response is not
valid JSON, so callers can always inspect ``body`` without a second try.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 5
_RETRY_BACKOFF_CAP = 30.0


def _build_headers(token: str | None, has_body: bool) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if has_body:
        headers["Content-Type"] = "application/json"
    return headers


def _parse_body(raw: str) -> Any:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _retry_after_seconds(headers: Any, attempt: int) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return min(2 ** attempt, _RETRY_BACKOFF_CAP)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return min(2 ** attempt, _RETRY_BACKOFF_CAP)


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep: Any = time.sleep,
    opener: Any = None,
) -> tuple[int, Any]:
    """Issue a single JSON HTTP request with retry/backoff.

    Returns ``(status_code, parsed_body)``. ``parsed_body`` is the decoded
    JSON object for success and error responses alike, or ``{"raw": text}``
    when the body is not valid JSON. ``status`` is ``0`` if the request
    fails with a non-HTTP error after exhausting retries (rare; usually
    the original :class:`URLError` is re-raised instead).

    The ``sleep`` and ``opener`` hooks exist for tests.
    """
    method = method.upper()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    merged_headers = _build_headers(token, body is not None)
    if headers:
        merged_headers.update(headers)

    open_func = opener.open if opener is not None else urllib.request.urlopen

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=data, method=method, headers=merged_headers)
        try:
            with open_func(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return int(response.status), _parse_body(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = _retry_after_seconds(exc.headers, attempt)
                sleep(wait)
                continue
            if 500 <= exc.code < 600 and attempt + 1 < max_retries:
                sleep(min(2 ** attempt, _RETRY_BACKOFF_CAP))
                continue
            err_body = exc.read().decode("utf-8", errors="replace")
            return int(exc.code), _parse_body(err_body)
        except urllib.error.URLError:
            if attempt + 1 < max_retries:
                sleep(min(2 ** attempt, _RETRY_BACKOFF_CAP))
                continue
            raise

    return 0, {"error": "exhausted retries"}


def _next_url(base_url: str, payload: Any) -> str | None:
    """Pick the next page URL from a Fabric / Power BI / ARM response.

    Recognized shapes (first match wins):

    * ``nextLink`` — absolute URL (ARM convention).
    * ``continuationUri`` — absolute URL (Fabric admin convention).
    * ``continuationToken`` — token appended to ``base_url`` as a query
      parameter (Fabric user-scope convention).
    """
    if not isinstance(payload, dict):
        return None
    next_link = payload.get("nextLink")
    if isinstance(next_link, str) and next_link:
        return next_link
    continuation_uri = payload.get("continuationUri")
    if isinstance(continuation_uri, str) and continuation_uri:
        return continuation_uri
    token = payload.get("continuationToken")
    if isinstance(token, str) and token:
        joiner = "&" if "?" in base_url else "?"
        return f"{base_url}{joiner}continuationToken={urllib.parse.quote(token)}"
    return None


def paged_get(
    url: str,
    *,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    value_key: str = "value",
    sleep: Any = time.sleep,
    opener: Any = None,
) -> Iterator[tuple[int, Any]]:
    """Iterate over a paginated REST endpoint.

    Yields ``(status, payload)`` for every page. Stops on the first
    non-200 response (yielding it once so the caller can react), and
    stops cleanly when the payload exposes no continuation pointer.

    ``value_key`` is only used to determine emptiness — it's not used to
    filter the payload, so callers can always inspect ``payload[value_key]``
    themselves.
    """
    current: str | None = url
    while current:
        status, payload = request_json(
            "GET",
            current,
            token=token,
            headers=headers,
            timeout=timeout,
            max_retries=max_retries,
            sleep=sleep,
            opener=opener,
        )
        yield status, payload
        if status != 200:
            return
        current = _next_url(current, payload)
        if isinstance(payload, dict) and value_key in payload and not payload.get(value_key):
            # Empty page with no continuation also terminates cleanly.
            if current is None:
                return


def collect_paged(
    url: str,
    *,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    value_key: str = "value",
    sleep: Any = time.sleep,
    opener: Any = None,
) -> tuple[list[Any], int, Any]:
    """Drain :func:`paged_get` and return ``(items, last_status, last_body)``.

    ``items`` is the flattened concatenation of ``page[value_key]`` across
    successful pages. On the first non-200, ``items`` contains rows
    collected up to that point and ``last_status`` / ``last_body`` reflect
    the failing page so the caller can decide how to surface the error.
    """
    items: list[Any] = []
    last_status = 0
    last_body: Any = None
    for status, payload in paged_get(
        url,
        token=token,
        headers=headers,
        timeout=timeout,
        max_retries=max_retries,
        value_key=value_key,
        sleep=sleep,
        opener=opener,
    ):
        last_status, last_body = status, payload
        if status != 200:
            return items, status, payload
        if isinstance(payload, dict):
            page = payload.get(value_key) or []
            if isinstance(page, list):
                items.extend(page)
    return items, last_status, last_body
