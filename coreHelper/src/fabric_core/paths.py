"""Shared Lakehouse path helpers and notebook runtime shims.

This module is intentionally pure-Python at import time. Fabric runtime
packages are imported lazily only when runtime detection or filesystem access
is requested.
"""
from __future__ import annotations

from typing import Any


ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"


def table_path(
    workspace_id: str,
    lakehouse_id: str,
    table: str,
    schema: str | None = None,
) -> str:
    """Build an ABFSS path to a Lakehouse Delta table."""
    if schema:
        return (
            f"abfss://{workspace_id}@{ONELAKE_HOST}/"
            f"{lakehouse_id}/Tables/{schema}/{table}"
        )
    return f"abfss://{workspace_id}@{ONELAKE_HOST}/{lakehouse_id}/Tables/{table}"


def files_path(workspace_id: str, lakehouse_id: str, subpath: str = "") -> str:
    """Build an ABFSS path to a Lakehouse Files subpath or root."""
    sub = (subpath or "").lstrip("/")
    if sub:
        return f"abfss://{workspace_id}@{ONELAKE_HOST}/{lakehouse_id}/{sub}"
    return f"abfss://{workspace_id}@{ONELAKE_HOST}/{lakehouse_id}"


def files_uri(workspace_id: str, lakehouse_id: str, subpath: str = "Files") -> str:
    """Build an ABFSS URI to the Files section or another Lakehouse subpath."""
    return files_path(workspace_id, lakehouse_id, subpath)


def mounted_files_path(subpath: str = "") -> str:
    """Build a POSIX path to the attached lakehouse's ``Files`` mount.

    Fabric notebooks expose the default lakehouse at
    ``/lakehouse/default/Files``. This helper keeps every caller using the
    same path math so subpath quirks (leading slashes, empty input) are
    handled identically.
    """
    base = "/lakehouse/default/Files"
    sub = (subpath or "").lstrip("/")
    return f"{base}/{sub}" if sub else base


def _import_nbu():
    """Lazy import of notebookutils with mssparkutils fallback.

    Returns None when neither runtime package is importable.
    """
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
    """Return Fabric/Synapse workspace and lakehouse context when available."""
    _nbu = _import_nbu()
    if _nbu is None:
        return {}
    try:
        ctx = _nbu.runtime.context
    except Exception:
        return {}

    def _g(*keys: str) -> str:
        for key in keys:
            try:
                value = ctx.get(key) if hasattr(ctx, "get") else getattr(ctx, key, None)
            except Exception:
                value = None
            if value:
                return value
        return ""

    return {
        "current_workspace_id": _g("currentWorkspaceId", "workspaceId"),
        "current_workspace_name": _g("currentWorkspaceName", "workspaceName"),
        "default_lakehouse_id": _g("defaultLakehouseId", "defaultLakehouse"),
        "default_lakehouse_name": _g("defaultLakehouseName"),
        "default_lakehouse_workspace_id": _g("defaultLakehouseWorkspaceId"),
        "default_lakehouse_workspace_name": _g("defaultLakehouseWorkspaceName"),
    }


def fs_ls(path: str) -> list[Any]:
    """Call notebookutils.fs.ls or mssparkutils.fs.ls for a directory path."""
    _nbu = _import_nbu()
    if _nbu is None:
        raise ImportError("notebookutils / mssparkutils are not importable in this runtime")
    return _nbu.fs.ls(path)
