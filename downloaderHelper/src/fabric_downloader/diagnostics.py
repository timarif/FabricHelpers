"""Diagnostics — probe the resolved write target + (optionally) the Fabric
REST endpoints used by the downloader.

Used by the thin orchestration notebook to give the user a one-cell sanity
check before kicking off a full run.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, TextIO

from .config import DownloaderConfig
from .paths  import ResolvedPaths, list_dir


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
    """Pretty-print a diagnostic banner for the current downloader config.

    Always reports the resolved write target. When `token` is provided,
    also probes the Fabric enumeration endpoints with the current
    identity.
    """
    p = lambda *a: _print(stream, *a)

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
            dirs  = [e for e in entries if     getattr(e, "isDir", False)]
            p(f"   Top-level entries   : {len(entries)}  "
              f"({len(files)} files, {len(dirs)} folders)")
        except Exception as e:
            p(f"   [WARN] Could not list {resolved.abfss_files_prefix}: "
              f"{type(e).__name__}: {e}")

    p("\n=== Item types to download ===")
    for t in config.item_types:
        mode = config.export_mode_for(t)
        fmt = config.format_for(t) or "(default / parts)"
        p(f"   {t:20s}  export_mode={mode:6s}  format={fmt}")

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
    p = lambda *a: _print(stream, *a)
    if http_get is None:
        import requests

        def http_get(url, headers, params):
            return requests.get(url, headers=headers, params=params,
                                timeout=30)

    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}

    def _probe(label: str, url: str, params: dict | None = None) -> int | None:
        try:
            r = http_get(url, headers, params or {})
            sample = ""
            try:
                j = r.json()
                if isinstance(j, dict):
                    if "value" in j and isinstance(j["value"], list):
                        sample = f"value[]: {len(j['value'])} rows"
                    else:
                        sample = ", ".join(list(j.keys())[:6])
                else:
                    sample = str(j)[:120]
            except Exception:
                sample = (getattr(r, "text", "") or "")[:120]
            p(f"  [{r.status_code}] {label:34s}  {sample}")
            return r.status_code
        except Exception as e:
            p(f"  [ERR] {label:34s}  {type(e).__name__}: {e}")
            return None

    p("\n=== Probing endpoints with current identity ===")
    _probe("PBI admin /myorg/admin/groups",
           f"{config.pbi_base}/v1.0/myorg/admin/groups", {"$top": 1})
    _probe("Fabric admin /v1/admin/workspaces",
           f"{config.fabric_base}/v1/admin/workspaces")
    _probe("Fabric admin /v1/admin/items",
           f"{config.fabric_base}/v1/admin/items")
    _probe("Fabric user /v1/workspaces",
           f"{config.fabric_base}/v1/workspaces")
    p("Done. 200 = accessible; 401/403 = role mismatch; 404 = wrong path.")
