"""Diagnostics for downloader write targets and Fabric REST endpoints."""
from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial
from typing import Any, TextIO

import fabric_core.diagnostics as core_diag
from fabric_core.diagnostics import ProbeResult

from .config import DownloaderConfig
from .paths import ResolvedPaths, list_dir

_LABELS = {
    "pbi_admin_groups": "PBI admin /myorg/admin/groups",
    "fabric_admin_workspaces": "Fabric admin /v1/admin/workspaces",
    "fabric_admin_workspaces_items": "Fabric admin /v1/admin/items",
    "fabric_user_workspaces": "Fabric user /v1/workspaces",
}


def _print(stream: TextIO | None, *args: Any) -> None:
    print(*args, file=stream if stream is not None else sys.stdout)


def probe(
    config: DownloaderConfig,
    resolved: ResolvedPaths,
    *,
    token: str | None = None,
    ls: Callable[[str], list] | None = None,
    http_get: Callable[[str, dict, dict], Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Pretty-print a diagnostic banner for the current downloader config."""
    p = partial(_print, stream)

    p("=== Resolved write target ===")
    p(f"   lakehouse mount     : {resolved.lakehouse_mount}")
    p(f"   abfss Files prefix  : {resolved.abfss_files_prefix}")
    p(f"   manifest target     : {resolved.manifest_target}")
    p(f"   output sub-folder   : {resolved.output_root}/{resolved.run_label}")
    p(f"   write workspace id  : {resolved.write_workspace_id or '(?)'} ")
    p(f"   write lakehouse id  : {resolved.write_lakehouse_id or '(?)'} ")

    if resolved.lakehouse_mount is None and resolved.abfss_files_prefix:
        try:
            entries = list_dir(resolved.abfss_files_prefix, ls=ls)
            files = [e for e in entries if not getattr(e, "isDir", False)]
            dirs = [e for e in entries if getattr(e, "isDir", False)]
            p(f"   Top-level entries   : {len(entries)}  "
              f"({len(files)} files, {len(dirs)} folders)")
        except Exception as e:
            p(f"   [WARN] Could not list {resolved.abfss_files_prefix}: "
              f"{type(e).__name__}: {e}")

    p("\n=== Item types to download ===")
    for item_type in config.item_types:
        mode = config.export_mode_for(item_type)
        fmt = config.format_for(item_type) or "(default / parts)"
        p(f"   {item_type:20s}  export_mode={mode:6s}  format={fmt}")

    if token is None:
        p("\n(Pass token=... to probe Fabric enumeration endpoints.)")
        return

    _probe_api(config, token, http_get=http_get, stream=stream)


def _probe_api(
    config: DownloaderConfig,
    token: str,
    *,
    http_get: Callable[[str, dict, dict], Any] | None = None,
    stream: TextIO | None = None,
) -> None:
    p = partial(_print, stream)
    p("\n=== Probing endpoints with current identity ===")

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
        p(f"  [{result.status}] {label:34s}  {_sample(result)}")
    p("Done. 200 = accessible; 401/403 = role mismatch; 404 = wrong path.")


def _sample(result: ProbeResult) -> str:
    if result.count is not None:
        return f"value[]: {result.count} rows"
    keys = result.detail.get("json_keys") if isinstance(result.detail, dict) else None
    if keys:
        return ", ".join(keys[:6])
    if result.error:
        return str(result.error)[:120]
    return ""
