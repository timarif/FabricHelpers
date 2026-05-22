"""Lakehouse mount + ABFSS path math for the downloader.

Pure-Python at the top level — `notebookutils` is only touched when the
caller actually needs runtime detection or directory listings (and even
then it's a lazy import so the module loads cleanly on any laptop).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .config import DownloaderConfig


ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"
DEFAULT_LAKEHOUSE_MOUNT = "/lakehouse/default/Files"


_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_segment(s: str | None, maxlen: int = 80) -> str:
    """Strip filesystem-hostile characters from a workspace / item / part
    name. Mirrors the helper from the seed notebook (`_safe_segment`)."""
    if not s:
        return "unnamed"
    s = _SAFE_RE.sub("_", str(s))
    s = s.strip("._-") or "unnamed"
    return s[:maxlen]


def auto_run_label() -> str:
    """Default `RUN_LABEL` when the caller leaves it blank."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def table_path(workspace_id: str, lakehouse_id: str, table: str,
               schema: str | None = None) -> str:
    """Build an ABFSS path to a Lakehouse Delta table."""
    if schema:
        return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
                f"{lakehouse_id}/Tables/{schema}/{table}")
    return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
            f"{lakehouse_id}/Tables/{table}")


def files_uri(workspace_id: str, lakehouse_id: str,
              subpath: str = "Files") -> str:
    """Build an ABFSS path to the Files section (or any subpath) of a
    Lakehouse."""
    sub = (subpath or "").lstrip("/")
    if sub:
        return (f"abfss://{workspace_id}@{ONELAKE_HOST}/"
                f"{lakehouse_id}/{sub}")
    return f"abfss://{workspace_id}@{ONELAKE_HOST}/{lakehouse_id}"


def _import_nbu():
    """Lazy import of notebookutils (with mssparkutils fallback). Returns
    None when neither is importable."""
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
    """Inspect `notebookutils.runtime.context` to figure out which workspace
    + lakehouse this notebook is currently attached to. Empty dict when
    notebookutils isn't importable or no default lakehouse is mounted."""
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
    """Thin wrapper around `notebookutils.fs.ls`. Raises ImportError when
    neither notebookutils nor mssparkutils are available."""
    _nbu = _import_nbu()
    if _nbu is None:
        raise ImportError(
            "notebookutils / mssparkutils are not importable in this runtime")
    return _nbu.fs.ls(path)


@dataclass(frozen=True)
class ResolvedPaths:
    """Result of `resolve_paths(config)` — everything downstream cells need
    to know about the resolved write target and the detected runtime."""
    lakehouse_mount: str | None
    """Path on the local mount (e.g. `/lakehouse/default/Files`) when
    `write_to_default_lakehouse=True`. None otherwise."""

    abfss_files_prefix: str | None
    """ABFSS URI for the Files section of the target lakehouse, when
    `write_to_default_lakehouse=False`. None otherwise."""

    manifest_target: str
    """saveAsTable name (default LH) or ABFSS Delta path."""

    write_workspace_id: str
    write_lakehouse_id: str
    write_schema: str | None
    run_label: str
    output_root: str
    runtime: dict[str, str]

    # Convenience flag the runner uses to pick the persist code path.
    @property
    def write_to_default_lakehouse(self) -> bool:
        return self.lakehouse_mount is not None

    def join_target(self, rel_path: str) -> str:
        """Convert a Files-relative path into the actual write URI."""
        rel = (rel_path or "").lstrip("/")
        if self.lakehouse_mount is not None:
            return f"{self.lakehouse_mount}/{rel}"
        assert self.abfss_files_prefix is not None
        return f"{self.abfss_files_prefix}/{rel}"


def resolve_paths(
    config: DownloaderConfig,
    *,
    runtime_provider: Callable[[], dict] | None = None,
) -> ResolvedPaths:
    """Compute the write target + manifest target implied by a
    `DownloaderConfig`. `runtime_provider` exists purely so tests can
    inject a fake runtime context."""
    runtime: dict[str, str] = {}

    run_label = config.run_label or auto_run_label()

    if config.write_to_default_lakehouse:
        rp = runtime_provider or detect_notebook_runtime
        runtime = rp() or {}
        lakehouse_mount = DEFAULT_LAKEHOUSE_MOUNT
        abfss_files_prefix = None
        manifest_target = (f"{config.write_schema}.{config.manifest_table}"
                           if config.write_schema
                           else config.manifest_table)
        write_workspace_id = runtime.get("default_lakehouse_workspace_id", "")
        write_lakehouse_id = runtime.get("default_lakehouse_id", "")
    else:
        if not (config.write_workspace_id and config.write_lakehouse_id):
            raise RuntimeError(
                "write_to_default_lakehouse=False requires "
                "write_workspace_id + write_lakehouse_id on the config.")
        lakehouse_mount = None
        abfss_files_prefix = files_uri(
            config.write_workspace_id, config.write_lakehouse_id, "Files")
        manifest_target = table_path(
            config.write_workspace_id, config.write_lakehouse_id,
            config.manifest_table, config.write_schema)
        write_workspace_id = config.write_workspace_id
        write_lakehouse_id = config.write_lakehouse_id

    return ResolvedPaths(
        lakehouse_mount=lakehouse_mount,
        abfss_files_prefix=abfss_files_prefix,
        manifest_target=manifest_target,
        write_workspace_id=write_workspace_id,
        write_lakehouse_id=write_lakehouse_id,
        write_schema=config.write_schema,
        run_label=run_label,
        output_root=config.output_root,
        runtime=runtime,
    )


# ---------------------------------------------------------------------------
# Output path construction (pure functions, no I/O)
# ---------------------------------------------------------------------------


def workspace_folder(output_root: str, run_label: str,
                     workspace_id: str, workspace_name: str) -> str:
    """`<output_root>/<run_label>/<safe_ws>__<wsid>` — the per-workspace
    folder under Files/. Returns a relative path."""
    safe_ws = safe_segment(workspace_name or workspace_id or "unknown_ws")
    return f"{output_root}/{run_label}/{safe_ws}__{workspace_id}"


def item_folder(
    output_root: str,
    run_label: str,
    workspace_id: str,
    workspace_name: str,
    item_type: str,
    *,
    group_by_type: bool = True,
) -> str:
    """`<ws_folder>[/<ItemType>]` — directory each downloaded item's files
    live in. When `group_by_type=False`, returns the bare workspace folder
    (legacy seed-notebook layout)."""
    ws = workspace_folder(output_root, run_label, workspace_id, workspace_name)
    if group_by_type:
        return f"{ws}/{safe_segment(item_type, maxlen=40)}"
    return ws


def build_paths(
    *,
    output_root: str,
    run_label: str,
    workspace_id: str,
    workspace_name: str,
    item_type: str,
    item_id: str,
    item_name: str,
    export_mode: str,
    group_by_type: bool = True,
) -> tuple[str, str]:
    """Return `(primary_rel_path, item_json_rel_path)` for one item.

    `primary_rel_path` is the file the manifest's `rel_path` column points
    at (the single `.ipynb` in ipynb-mode for notebooks; a placeholder
    in parts-mode that gets overwritten when the real part filename is
    known — see `partition.py`).

    `item_json_rel_path` is where the raw getDefinition JSON envelope is
    written when `include_raw_definition=True`.
    """
    folder = item_folder(output_root, run_label, workspace_id,
                         workspace_name, item_type,
                         group_by_type=group_by_type)
    safe_name = safe_segment(item_name or item_id or "unnamed")
    fname = f"{safe_name}__{item_id}"
    if export_mode == "ipynb":
        primary = f"{folder}/{fname}.ipynb"
    else:
        # Placeholder; the real path is filled in by the partition fn after
        # it sees which "notebook-content" / "pipeline-content" / "mashup"
        # part comes back from the API.
        primary = f"{folder}/{fname}__definition.txt"
    return primary, f"{folder}/{fname}.item.json"


# ---------------------------------------------------------------------------
# I/O helpers used by executors (run on the Spark worker)
# ---------------------------------------------------------------------------


def write_text(target_uri: str, text: str) -> None:
    """Write a text payload to either a local mount path or an ABFSS URI."""
    if target_uri.startswith("abfss://"):
        _nbu = _import_nbu()
        if _nbu is None:
            raise RuntimeError(
                f"Cannot write to {target_uri}: notebookutils not available")
        _nbu.fs.put(target_uri, text, True)
        return
    import os as _os
    _os.makedirs(_os.path.dirname(target_uri), exist_ok=True)
    with open(target_uri, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def target_exists(target_uri: str) -> bool:
    """True if the file at `target_uri` already exists."""
    if target_uri.startswith("abfss://"):
        _nbu = _import_nbu()
        if _nbu is None:
            return False
        try:
            return bool(_nbu.fs.exists(target_uri))
        except AttributeError:
            try:
                _nbu.fs.head(target_uri, 1)
                return True
            except Exception:
                return False
        except Exception:
            return False
    import os as _os
    return _os.path.exists(target_uri)


def list_dir(path: str,
             ls: Callable[[str], Iterable[Any]] | None = None) -> list[Any]:
    """Wrapper around `fs_ls` used by diagnostics. Injectable for tests."""
    _ls = ls or fs_ls
    return list(_ls(path))
