"""Lakehouse path resolution + ws_dated layout enumeration.

The public surface here is intentionally pure-Python at the top level
(`table_path`, `files_path`, `resolve_paths`) — notebookutils is only
touched when the caller actually needs runtime detection or directory
listings (and even then it's a lazy import so the module loads cleanly
on any laptop).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .config import ScannerConfig


ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"


# Universal workspace-GUID-from-path pattern.
#
# A notebook path of the form
#     <anything>/<workspace-guid>/<datestamp>/<filename>
# is interpreted as "this notebook came from workspace <guid> and was
# exported under partition <datestamp>". The GUID portion is the
# standard 8-4-4-4-12 hex form (case-insensitive). The datestamp must
# begin with at least 8 digits (yyyymmdd) so plain folder names like
# 'Files' or 'notebook_exports' don't accidentally match.
#
# Used by:
#   - spark.partition.scan_row    (per-row fallback for findings)
#   - spark.inventory.build_inventory_lakehouse  (inventory snapshot)
#
# `PATH_GUID_DATE_RE_STR` is the *raw string* (so Spark's
# `regexp_extract` Java regex sees the same pattern); `PATH_GUID_DATE_RE`
# is the compiled Python version.
PATH_GUID_DATE_RE_STR = (
    r"/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"/(\d{8}[^/]*)/"
)
PATH_GUID_DATE_RE = re.compile(PATH_GUID_DATE_RE_STR)


def extract_workspace_from_path(path: str) -> tuple[str | None, str | None]:
    """Return `(workspace_guid, datestamp)` parsed from a notebook path
    of the form `<anywhere>/<guid>/<datestamp>/<file>`.

    Returns `(None, None)` when no match.
    """
    if not path:
        return None, None
    m = PATH_GUID_DATE_RE.search(path)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def table_path(workspace_id: str, lakehouse_id: str, table: str,
               schema: str | None = None) -> str:
    """Build an ABFSS path to a Lakehouse Delta table."""
    if schema:
        return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
                f"{lakehouse_id}/Tables/{schema}/{table}")
    return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
            f"{lakehouse_id}/Tables/{table}")


def files_path(workspace_id: str, lakehouse_id: str, subpath: str) -> str:
    """Build an ABFSS path to a Lakehouse Files subpath (or LH root)."""
    sub = (subpath or "").lstrip("/")
    if sub:
        return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
                f"{lakehouse_id}/{sub}")
    return f"abfss://{workspace_id}@{ONELAKE_HOST}/{lakehouse_id}"


def _import_nbu():
    """Lazy import of notebookutils (with mssparkutils fallback). Returns
    None when neither is importable — caller handles."""
    try:
        import notebookutils as _nbu  # type: ignore
        return _nbu
    except ImportError:
        try:
            import mssparkutils as _nbu  # type: ignore
            return _nbu
        except ImportError:
            return None


def detect_notebook_runtime() -> dict[str, str]:
    """Inspect `notebookutils.runtime.context` (or mssparkutils) to figure
    out which workspace + lakehouse this notebook is currently attached to.

    Returns a dict; missing keys are empty strings. Empty dict on failure
    (running outside Fabric, no default lakehouse mounted, etc.)."""
    _nbu = _import_nbu()
    if _nbu is None:
        return {}
    try:
        ctx = _nbu.runtime.context
    except Exception:
        return {}

    def _g(*keys: str) -> str:
        for k in keys:
            try:
                v = ctx.get(k) if hasattr(ctx, "get") else getattr(ctx, k, None)
            except Exception:
                v = None
            if v:
                return v
        return ""

    return {
        "current_workspace_id":   _g("currentWorkspaceId", "workspaceId"),
        "current_workspace_name": _g("currentWorkspaceName", "workspaceName"),
        "default_lakehouse_id":   _g("defaultLakehouseId", "defaultLakehouse"),
        "default_lakehouse_name": _g("defaultLakehouseName"),
        "default_lakehouse_workspace_id":
            _g("defaultLakehouseWorkspaceId"),
        "default_lakehouse_workspace_name":
            _g("defaultLakehouseWorkspaceName"),
    }


def fs_ls(path: str) -> list[Any]:
    """Thin wrapper around `notebookutils.fs.ls` / `mssparkutils.fs.ls`.
    Raises ImportError when neither is available."""
    _nbu = _import_nbu()
    if _nbu is None:
        raise ImportError(
            "notebookutils / mssparkutils are not importable in this runtime")
    return _nbu.fs.ls(path)


def enumerate_dated_workspace_dirs(
    base_uri: str,
    ls: Callable[[str], Iterable[Any]] | None = None,
) -> list[dict]:
    """For a Files-section layout of

        <base_uri>/<workspace_guid>/<datestamp>/<files...>

    return one dict per workspace folder pointing at its MOST RECENT
    dated subdir. Workspaces with no dated subdirs are silently skipped.
    Lex-max selection works for any fixed-width, date-ordered timestamp
    (yyyymmdd, yyyymmddhhmmss, yyyy-mm-dd, ISO 8601 + Z, …).

    Each dict has keys: `workspace_id`, `datestamp`, `dir_path`.

    `ls` is an injectable directory-listing callable (mainly for tests);
    when None, it defaults to the runtime `fs_ls`.
    """
    _ls = ls or fs_ls
    try:
        top = _ls(base_uri)
    except Exception as e:
        raise RuntimeError(
            f"ws_dated layout: could not list base path '{base_uri}': "
            f"{type(e).__name__}: {e}"
        )

    out: list[dict] = []
    for entry in top:
        if not getattr(entry, "isDir", False):
            continue
        ws_id = getattr(entry, "name", "") or ""
        ws_path = (getattr(entry, "path", None)
                   or f"{base_uri.rstrip('/')}/{ws_id}")
        try:
            subs = _ls(ws_path)
        except Exception:
            continue
        dated = [s for s in subs
                 if getattr(s, "isDir", False) and getattr(s, "name", "")]
        if not dated:
            continue
        latest = max(dated, key=lambda s: getattr(s, "name", ""))
        out.append({
            "workspace_id": ws_id,
            "datestamp":    getattr(latest, "name", ""),
            "dir_path":     (getattr(latest, "path", None)
                             or f"{ws_path.rstrip('/')}/"
                                f"{getattr(latest, 'name', '')}"),
        })
    return out


@dataclass(frozen=True)
class ResolvedPaths:
    """Result of `resolve_paths(config)` — everything downstream cells need
    to know about read targets, write targets, and the detected runtime."""
    source_uri: str | None
    source_paths: tuple[str, ...]
    dated_index: dict[str, str]
    source_kind_label: str
    write_kind: str
    inventory_target: str
    output_target: str
    runtime: dict[str, str]
    source_workspace_id: str
    source_workspace_name: str
    source_lakehouse_id: str
    source_lakehouse_name: str


def resolve_paths(
    config: ScannerConfig,
    *,
    runtime_provider: Callable[[], dict] | None = None,
    ls: Callable[[str], Iterable[Any]] | None = None,
) -> ResolvedPaths:
    """Compute the read targets, write targets, and metadata implied by a
    `ScannerConfig`. Does NOT touch notebookutils in API mode; in lakehouse
    mode it pulls the runtime context (default lakehouse, current workspace)
    to auto-fill any source_lakehouse_* fields the caller left blank.

    `runtime_provider` / `ls` exist purely so tests can inject fakes.
    """
    if config.source_mode == "lakehouse":
        rp = runtime_provider or detect_notebook_runtime
        runtime = rp() or {}
    else:
        runtime = {}

    src_ws_id   = config.source_lakehouse_workspace_id
    src_ws_name = config.source_lakehouse_workspace_name
    src_lh_id   = config.source_lakehouse_id
    src_lh_name = config.source_lakehouse_name

    if config.source_mode == "lakehouse" and runtime:
        src_lh_id   = src_lh_id   or runtime.get("default_lakehouse_id", "")
        src_lh_name = src_lh_name or runtime.get("default_lakehouse_name", "")
        src_ws_id   = (src_ws_id
                       or runtime.get("default_lakehouse_workspace_id", "")
                       or runtime.get("current_workspace_id", ""))
        src_ws_name = (src_ws_name
                       or runtime.get("default_lakehouse_workspace_name", "")
                       or runtime.get("current_workspace_name", ""))

    if config.write_to_default_lakehouse:
        inventory_target = config.inventory_table
        output_target    = config.output_table
        write_kind = "saveAsTable (default attached Lakehouse)"
    else:
        inventory_target = table_path(config.write_workspace_id,
                                      config.write_lakehouse_id,
                                      config.inventory_table,
                                      config.write_schema)
        output_target    = table_path(config.write_workspace_id,
                                      config.write_lakehouse_id,
                                      config.output_table,
                                      config.write_schema)
        write_kind = (f"ABFSS Delta path "
                      f"(workspace {config.write_workspace_id})")

    source_uri: str | None = None
    source_kind_label: str
    if config.source_mode == "lakehouse":
        if src_ws_id and src_lh_id:
            source_uri = files_path(src_ws_id, src_lh_id, config.source_subpath)
            if runtime and src_lh_id == runtime.get("default_lakehouse_id"):
                source_kind_label = ("mounted lakehouse (auto-detected from "
                                     "notebookutils.runtime.context)")
            else:
                source_kind_label = (f"ABFSS Lakehouse path "
                                     f"(workspace {src_ws_id})")
        else:
            source_uri = config.source_subpath or "Files"
            source_kind_label = (
                "attached default Lakehouse (relative — could not detect "
                "mounted LH; workspace/source_lakehouse columns will be "
                "empty)")
    else:
        source_kind_label = ("admin scanner (all workspaces)"
                             if config.admin_mode
                             else "user-accessible workspaces")

    source_paths: list[str] = []
    dated_index: dict[str, str] = {}
    if config.source_mode == "lakehouse":
        if config.source_layout == "ws_dated":
            if not (src_ws_id and src_lh_id):
                raise RuntimeError(
                    "source_layout='ws_dated' requires a known source "
                    "workspace + lakehouse (either set "
                    "source_lakehouse_* on ScannerConfig or mount a "
                    "default lakehouse on this notebook so the runtime "
                    "context can auto-fill them).")
            assert source_uri is not None
            dated = enumerate_dated_workspace_dirs(source_uri, ls=ls)
            if not dated:
                raise RuntimeError(
                    f"source_layout='ws_dated' found 0 workspace folders "
                    f"with dated subdirs under '{source_uri}'. Expected "
                    f"layout: <base>/<workspace_guid>/<yyyymmddhhmmss>/"
                    f"<files>")
            source_paths = [d["dir_path"] for d in dated]
            dated_index  = {d["workspace_id"]: d["datestamp"] for d in dated}
        elif source_uri:
            source_paths = [source_uri]

    return ResolvedPaths(
        source_uri=source_uri,
        source_paths=tuple(source_paths),
        dated_index=dated_index,
        source_kind_label=source_kind_label,
        write_kind=write_kind,
        inventory_target=inventory_target,
        output_target=output_target,
        runtime=runtime,
        source_workspace_id=src_ws_id,
        source_workspace_name=src_ws_name,
        source_lakehouse_id=src_lh_id,
        source_lakehouse_name=src_lh_name,
    )
