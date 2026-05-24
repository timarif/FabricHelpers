"""Source-side diagnostics for fabric-mpe.

Prints the standard four-endpoint banner from
:func:`fabric_core.diagnostics.probe_api` (so MPE users get the same
visible feedback as scanner/downloader users) and adds one MPE-specific
check: a list-MPEs call against the first visible workspace.
"""
from __future__ import annotations

import sys
from typing import Any, TextIO

from fabric_core.diagnostics import probe_api

from . import api
from .auth import get_fabric_token
from .config import MpeConfig

_LABELS = {
    "pbi_admin_groups": "PBI admin /myorg/admin/groups",
    "fabric_admin_workspaces": "Fabric admin /v1/admin/workspaces",
    "fabric_admin_workspaces_items": "Fabric admin /v1/admin/items",
    "fabric_user_workspaces": "Fabric user /v1/workspaces",
}


def _print(stream: TextIO | None, *args: Any) -> None:
    print(*args, file=stream if stream is not None else sys.stdout)


def _sample(result: Any) -> str:
    if result.count is not None:
        return f"value[]: {result.count} rows"
    keys = result.detail.get("json_keys") if isinstance(result.detail, dict) else None
    if keys:
        return ", ".join(keys[:6])
    if result.error:
        return str(result.error)[:120]
    return ""


def probe(
    cfg: MpeConfig,
    *,
    token: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Print a one-screen banner summarizing what fabric-mpe can see."""
    bearer = token or get_fabric_token(cfg)

    _print(stream, "Probing endpoints with current identity ...")
    results = probe_api(
        token=bearer,
        pbi_base=cfg.pbi_base,
        fabric_base=cfg.fabric_base,
        timeout=cfg.request_timeout,
    )
    for r in results:
        label = _LABELS.get(r.name, r.name)
        if r.status == 0:
            _print(stream, f"  [ERR] {label:34s}  {r.error or 'request failed'}")
        else:
            _print(stream, f"  [{r.status}] {label:34s}  {_sample(r)}")

    # MPE-specific probe: list MPEs on the first visible workspace.
    _print(stream, "MPE probe: list /managedPrivateEndpoints on first visible workspace ...")
    try:
        workspaces = api.list_workspaces(cfg, bearer)
    except Exception as exc:  # noqa: BLE001 — diagnostic banner, swallow + log
        _print(stream, f"  [ERR] Could not list workspaces: {type(exc).__name__}: {exc}")
        return

    if not workspaces:
        _print(stream, "  (no visible workspaces — nothing to probe)")
        return

    ws = workspaces[0]
    ws_id = ws.get("id") or ""
    ws_name = ws.get("displayName") or "(unnamed)"
    eps, err = api.list_mpes(cfg, ws_id, bearer)
    if err is None:
        _print(stream, f"  [200] {ws_name}  ({ws_id})  {len(eps)} MPE(s)")
    else:
        _print(
            stream,
            f"  [{err['status']}] {ws_name}  ({ws_id})  {str(err['body'])[:120]}",
        )
    _print(
        stream,
        "Done. 200 = accessible; 401/403 = role mismatch; 404 = wrong path.",
    )


__all__ = ["probe"]
