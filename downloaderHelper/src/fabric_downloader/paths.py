"""Lakehouse mount + ABFSS path math for the downloader."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fabric_core.paths import (
    ONELAKE_HOST,
    _import_nbu,
    detect_notebook_runtime,
    files_path,
    files_uri,
    fs_ls,
    table_path,
)

from .config import DownloaderConfig

DEFAULT_LAKEHOUSE_MOUNT = "/lakehouse/default/Files"

__all__ = [
    "ONELAKE_HOST",
    "DEFAULT_LAKEHOUSE_MOUNT",
    "ResolvedPaths",
    "_import_nbu",
    "auto_run_label",
    "build_paths",
    "detect_notebook_runtime",
    "files_path",
    "files_uri",
    "fs_ls",
    "item_folder",
    "list_dir",
    "resolve_paths",
    "safe_segment",
    "table_path",
    "target_exists",
    "workspace_folder",
    "write_text",
]

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_segment(s: str | None, maxlen: int = 80) -> str:
    """Strip filesystem-hostile characters from a workspace / item / part name."""
    if not s:
        return "unnamed"
    s = _SAFE_RE.sub("_", str(s))
    s = s.strip("._-") or "unnamed"
    return s[:maxlen]


def auto_run_label() -> str:
    """Default ``RUN_LABEL`` when the caller leaves it blank."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


@dataclass(frozen=True)
class ResolvedPaths:
    """Result of ``resolve_paths(config)`` for downstream cells."""

    lakehouse_mount: str | None
    abfss_files_prefix: str | None
    manifest_target: str
    write_workspace_id: str
    write_lakehouse_id: str
    write_schema: str | None
    run_label: str
    output_root: str
    runtime: dict[str, str]

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
    """Compute the write target + manifest target implied by a config."""
    runtime: dict[str, str] = {}
    run_label = config.run_label or auto_run_label()

    if config.write_to_default_lakehouse:
        rp = runtime_provider or detect_notebook_runtime
        runtime = rp() or {}
        lakehouse_mount = DEFAULT_LAKEHOUSE_MOUNT
        abfss_files_prefix = None
        manifest_target = (f"{config.write_schema}.{config.manifest_table}"
                           if config.write_schema else config.manifest_table)
        write_workspace_id = runtime.get("default_lakehouse_workspace_id", "")
        write_lakehouse_id = runtime.get("default_lakehouse_id", "")
    else:
        if not (config.write_workspace_id and config.write_lakehouse_id):
            raise RuntimeError(
                "write_to_default_lakehouse=False requires "
                "write_workspace_id + write_lakehouse_id on the config."
            )
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


def workspace_folder(output_root: str, run_label: str,
                     workspace_id: str, workspace_name: str) -> str:
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
    """Return ``(primary_rel_path, item_json_rel_path)`` for one item."""
    folder = item_folder(output_root, run_label, workspace_id, workspace_name,
                         item_type, group_by_type=group_by_type)
    safe_name = safe_segment(item_name or item_id or "unnamed")
    fname = f"{safe_name}__{item_id}"
    if export_mode == "ipynb":
        primary = f"{folder}/{fname}.ipynb"
    elif export_mode == "py":
        # Placeholder extension at planning time. `process_definition_body`
        # refines this to the actual language extension (`.py` / `.scala` /
        # `.sql` / `.r`) once it sees the part the API returns.
        primary = f"{folder}/{fname}.py"
    elif export_mode == "txt":
        primary = f"{folder}/{fname}.txt"
    else:
        primary = f"{folder}/{fname}__definition.txt"
    return primary, f"{folder}/{fname}.item.json"


def write_text(target_uri: str, text: str) -> None:
    """Write a text payload to either a local mount path or an ABFSS URI."""
    if target_uri.startswith("abfss://"):
        nbu = _import_nbu()
        if nbu is None:
            raise RuntimeError(
                f"Cannot write to {target_uri}: notebookutils not available")
        nbu.fs.put(target_uri, text, True)
        return
    import os as _os
    _os.makedirs(_os.path.dirname(target_uri), exist_ok=True)
    with open(target_uri, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def target_exists(target_uri: str) -> bool:
    """True if the file at ``target_uri`` already exists."""
    if target_uri.startswith("abfss://"):
        nbu = _import_nbu()
        if nbu is None:
            return False
        try:
            return bool(nbu.fs.exists(target_uri))
        except AttributeError:
            try:
                nbu.fs.head(target_uri, 1)
                return True
            except Exception:
                return False
        except Exception:
            return False
    import os as _os
    return _os.path.exists(target_uri)


def list_dir(path: str,
             ls: Callable[[str], Iterable[Any]] | None = None) -> list[Any]:
    """Wrapper around ``fs_ls`` used by diagnostics. Injectable for tests."""
    ls_fn = ls or fs_ls
    return list(ls_fn(path))
