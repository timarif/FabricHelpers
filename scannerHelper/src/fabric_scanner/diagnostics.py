"""Source diagnostics for scanner paths and Fabric REST endpoints."""
from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial
from typing import Any, TextIO

from .config import ScannerConfig
from .paths import ResolvedPaths, fs_ls

_LABELS = {
    "pbi_admin_groups": "PBI admin /myorg/admin/groups",
    "fabric_admin_workspaces": "Fabric admin /v1/admin/workspaces",
    "fabric_admin_workspaces_items": "Fabric admin /v1/admin/items",
    "fabric_user_workspaces": "Fabric user /v1/workspaces",
}


def _print(stream: TextIO | None, *args: Any) -> None:
    print(*args, file=stream if stream is not None else sys.stdout)


def probe(
    config: ScannerConfig,
    resolved: ResolvedPaths,
    *,
    token: str | None = None,
    ls: Callable[[str], list] | None = None,
    http_get: Callable[[str, dict, dict], Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Pretty-print a diagnostic banner for the current scanner config."""
    if config.source_mode == "lakehouse":
        _probe_lakehouse(config, resolved, ls=ls, stream=stream)
        return
    if not token:
        raise ValueError(
            "API-mode probe requires a token (call fabric_scanner.api.get_token() first)."
        )
    _probe_api(config, token, http_get=http_get, stream=stream)


def _probe_lakehouse(
    config: ScannerConfig,
    resolved: ResolvedPaths,
    *,
    ls: Callable[[str], list] | None = None,
    stream: TextIO | None = None,
) -> None:
    p = partial(_print, stream)
    p(f"[Lakehouse mode] Source: {resolved.source_uri}  (glob: {config.source_file_glob})")
    p(f"  Layout           : {config.source_layout}")
    if resolved.source_workspace_id or resolved.source_lakehouse_id:
        p(
            f"  Source workspace : {resolved.source_workspace_name or '(?)'}  "
            f"({resolved.source_workspace_id or '(?)'})"
        )
        p(
            f"  Source lakehouse : {resolved.source_lakehouse_name or '(?)'}  "
            f"({resolved.source_lakehouse_id or '(?)'})"
        )
        if resolved.runtime and resolved.source_lakehouse_id == resolved.runtime.get(
            "default_lakehouse_id"
        ):
            p(
                "    (auto-detected from notebookutils.runtime.context — this is the "
                "lakehouse currently mounted to the notebook)"
            )
    else:
        p(
            "  [WARN] No source workspace/lakehouse known. Output rows will have empty "
            "workspace_id / source_lakehouse_id columns."
        )
    if config.source_layout == "ws_dated":
        p(
            f"  ws_dated         : {len(resolved.source_paths)} workspace folders -> "
            "latest dated subdir per workspace"
        )
        if not resolved.dated_index:
            p("  [WARN] No workspace folders with dated subdirs found.")
        else:
            for ws_id, ts in list(resolved.dated_index.items())[:8]:
                p(f"    {ws_id}  -> {ts}")
            if len(resolved.dated_index) > 8:
                p(f"    ... and {len(resolved.dated_index) - 8} more")

    _ls = ls or fs_ls
    if not resolved.source_uri:
        return
    try:
        entries = _ls(resolved.source_uri)
    except Exception as e:
        p(f"  [ERR] Could not list {resolved.source_uri}: {type(e).__name__}: {e}")
        return
    files = [e for e in entries if not getattr(e, "isDir", False)]
    dirs = [e for e in entries if getattr(e, "isDir", False)]
    p(f"  Top-level entries: {len(entries)}  ({len(files)} files, {len(dirs)} folders)")
    for e in list(entries)[:5]:
        kind = "DIR " if getattr(e, "isDir", False) else "FILE"
        p(f"    {kind}  {getattr(e, 'name', e)}")


def _probe_api(
    config: ScannerConfig,
    token: str,
    *,
    http_get: Callable[[str, dict, dict], Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    import fabric_core.diagnostics as core_diag

    p = partial(_print, stream)
    p("Probing endpoints with current identity ...")

    original_get = core_diag.requests.get
    if http_get is not None:
        def patched_get(url: str, *, headers=None, params=None, **_kw: Any):
            return http_get(url, headers or {}, params or {})

        core_diag.requests.get = patched_get
    try:
        results = core_diag.probe_api(
            token=token,
            pbi_base=config.pbi_base,
            fabric_base=config.fabric_base,
            timeout=30.0,
        )
    finally:
        core_diag.requests.get = original_get

    for result in results:
        label = _LABELS.get(result.name, result.name)
        if result.status == 0:
            p(f"  [ERR] {label:34s}  {result.error or 'request failed'}")
            continue
        sample = _sample(result)
        p(f"  [{result.status}] {label:34s}  {sample}")
    p("Done. 200 = accessible; 401/403 = role mismatch; 404 = wrong path.")


def _sample(result: Any) -> str:
    if result.count is not None:
        return f"value[]: {result.count} rows"
    keys = result.detail.get("json_keys") if isinstance(result.detail, dict) else None
    if keys:
        return ", ".join(keys[:6])
    if result.error:
        return str(result.error)[:120]
    return ""
