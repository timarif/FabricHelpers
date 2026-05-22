"""Source diagnostics — probe paths or endpoints and print a human-readable
summary.

In lakehouse mode this lists the source URI (and dated subdirs when the
ws_dated layout is in use). In API mode it probes each enumeration
endpoint with the current token. Used by the thin orchestration notebook
to give the user a one-cell sanity check before kicking off a full scan.
"""
from __future__ import annotations

import json as _json
import sys
from typing import Any, Callable, TextIO

from .config import ScannerConfig
from .paths  import ResolvedPaths, fs_ls


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
    """Pretty-print a diagnostic banner for the current scanner config.

    `ls`, `http_get`, and `token` are injectable for tests:
        - `ls(path) -> list[entry]`  defaults to `paths.fs_ls`
        - `http_get(url, headers, params) -> response`  defaults to
          `requests.get(url, headers=headers, params=params, timeout=30)`
          — only used in API mode.
    """
    if config.source_mode == "lakehouse":
        _probe_lakehouse(config, resolved, ls=ls, stream=stream)
    else:
        if not token:
            raise ValueError(
                "API-mode probe requires a token (call "
                "fabric_scanner.api.get_token() first).")
        _probe_api(config, token, http_get=http_get, stream=stream)


def _probe_lakehouse(
    config: ScannerConfig,
    resolved: ResolvedPaths,
    *,
    ls: Callable[[str], list] | None = None,
    stream: TextIO | None = None,
) -> None:
    p = lambda *a: _print(stream, *a)
    p(f"[Lakehouse mode] Source: {resolved.source_uri}  "
      f"(glob: {config.source_file_glob})")
    p(f"  Layout           : {config.source_layout}")
    if resolved.source_workspace_id or resolved.source_lakehouse_id:
        p(f"  Source workspace : "
          f"{resolved.source_workspace_name or '(?)'}  "
          f"({resolved.source_workspace_id or '(?)'})")
        p(f"  Source lakehouse : "
          f"{resolved.source_lakehouse_name or '(?)'}  "
          f"({resolved.source_lakehouse_id or '(?)'})")
        if (resolved.runtime and resolved.source_lakehouse_id ==
                resolved.runtime.get("default_lakehouse_id")):
            p("    (auto-detected from notebookutils.runtime.context "
              "— this is the lakehouse currently mounted to the notebook)")
    else:
        p("  [WARN] No source workspace/lakehouse known. Output rows "
          "will have empty workspace_id / source_lakehouse_id columns.")
    if config.source_layout == "ws_dated":
        p(f"  ws_dated         : {len(resolved.source_paths)} workspace "
          f"folders -> latest dated subdir per workspace")
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
        p(f"  [ERR] Could not list {resolved.source_uri}: "
          f"{type(e).__name__}: {e}")
        return
    files = [e for e in entries if not getattr(e, "isDir", False)]
    dirs  = [e for e in entries if     getattr(e, "isDir", False)]
    p(f"  Top-level entries: {len(entries)}  "
      f"({len(files)} files, {len(dirs)} folders)")
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
                sample = r.text[:120]
            p(f"  [{r.status_code}] {label:34s}  {sample}")
            return r.status_code
        except Exception as e:
            p(f"  [ERR] {label:34s}  {type(e).__name__}: {e}")
            return None

    p("Probing endpoints with current identity ...")
    _probe("PBI admin /myorg/admin/groups",
           f"{config.pbi_base}/v1.0/myorg/admin/groups", {"$top": 1})
    _probe("Fabric admin /v1/admin/workspaces",
           f"{config.fabric_base}/v1/admin/workspaces")
    _probe("Fabric admin /v1/admin/items",
           f"{config.fabric_base}/v1/admin/items")
    _probe("Fabric user /v1/workspaces",
           f"{config.fabric_base}/v1/workspaces")
    p("Done. 200 = accessible; 401/403 = role mismatch; 404 = wrong path.")
