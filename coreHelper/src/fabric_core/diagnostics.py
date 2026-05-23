"""Shared API diagnostics probes for FabricHelpers packages."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


class _LazyRequests:
    def __getattr__(self, name: str) -> Any:
        import requests as real_requests

        return getattr(real_requests, name)


requests: Any = _LazyRequests()


@dataclass
class ProbeResult:
    name: str
    url: str
    status: int
    ok: bool
    count: Optional[int]  # noqa: UP045 - keep public contract spelling.
    elapsed_ms: int
    error: Optional[str] = None  # noqa: UP045 - keep public contract spelling.
    detail: dict = field(default_factory=dict)


def probe_api(
    *,
    token: str,
    pbi_base: str,
    fabric_base: str,
    timeout: float = 30.0,
) -> list[ProbeResult]:
    """Probe four canonical Fabric/PBI endpoints with the current identity.

    Returns results in this order: pbi_admin_groups,
    fabric_admin_workspaces, fabric_admin_workspaces_items, and
    fabric_user_workspaces. Each probe is independent; one failed request does
    not block the remaining probes.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    pbi_base = pbi_base.rstrip("/")
    fabric_base = fabric_base.rstrip("/")
    probes: list[tuple[str, str, dict[str, Any]]] = [
        (
            "pbi_admin_groups",
            f"{pbi_base}/v1.0/myorg/admin/groups",
            {"$top": 1},
        ),
        (
            "fabric_admin_workspaces",
            f"{fabric_base}/v1/admin/workspaces",
            {},
        ),
        (
            "fabric_admin_workspaces_items",
            f"{fabric_base}/v1/admin/items",
            {},
        ),
        (
            "fabric_user_workspaces",
            f"{fabric_base}/v1/workspaces",
            {},
        ),
    ]

    return [
        _probe_one(name, url, headers=headers, params=params, timeout=timeout)
        for name, url, params in probes
    ]


def _probe_one(
    name: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any],
    timeout: float,
) -> ProbeResult:
    started = time.perf_counter()
    detail: dict[str, Any] = {"params": dict(params)} if params else {}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
    except Exception as exc:
        return ProbeResult(
            name=name,
            url=url,
            status=0,
            ok=False,
            count=None,
            elapsed_ms=_elapsed_ms(started),
            error=f"{type(exc).__name__}: {exc}",
            detail=detail,
        )

    status = int(getattr(response, "status_code", 0) or 0)
    ok = 200 <= status < 300
    payload = _json_or_none(response)
    count = _extract_count(payload)
    if isinstance(payload, dict):
        detail["json_keys"] = list(payload.keys())[:10]
    error = None if ok else _response_error(response, payload, status)

    return ProbeResult(
        name=name,
        url=url,
        status=status,
        ok=ok,
        count=count,
        elapsed_ms=_elapsed_ms(started),
        error=error,
        detail=detail,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _json_or_none(response: Any) -> Any | None:
    try:
        return response.json()
    except Exception:
        return None


def _extract_count(payload: Any) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return len(payload["value"])
    return None


def _response_error(response: Any, payload: Any, status: int) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)
        elif error is not None:
            return str(error)
        message = payload.get("message")
        if message:
            return str(message)

    text = (getattr(response, "text", "") or "").strip()
    if text:
        return text[:500]
    reason = (getattr(response, "reason", "") or "").strip()
    if reason:
        return reason
    return f"HTTP {status}"
