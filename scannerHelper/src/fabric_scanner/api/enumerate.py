"""Notebook enumeration wrapper over :mod:`fabric_core.enumerate`."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import fabric_core.enumerate as _core_enum
from fabric_core.enumerate import (
    _http_json,
    _list_fabric_admin_workspaces,
    _list_pbi_admin_workspaces,
    _list_user_workspaces,
)

from ..config import ScannerConfig

log = logging.getLogger(__name__)

WorkspaceLister = Callable[..., Awaitable[list[dict]]]


def _is_notebook(item: dict, _workspace: dict) -> bool:
    item_type = item.get("type") or item.get("itemType") or ""
    return item_type.lower() == "notebook"


def _allowlist(config: ScannerConfig) -> set[str]:
    return {workspace_id for workspace_id in config.read_workspace_ids if workspace_id}


def _item_filter(config: ScannerConfig) -> Callable[[dict, dict], bool]:
    allowed = _allowlist(config)

    def include(item: dict, workspace: dict) -> bool:
        workspace_id = (
            workspace.get("id")
            or item.get("workspaceId")
            or (item.get("workspace") or {}).get("id")
            or ""
        )
        if allowed and workspace_id not in allowed:
            return False
        return _is_notebook(item, workspace)

    return include


def _filter_lister(fn: WorkspaceLister, allowed: set[str]) -> WorkspaceLister:
    async def wrapped(*args: Any, **kw: Any) -> list[dict]:
        rows = await fn(*args, **kw)
        if not allowed:
            return rows
        return [row for row in rows if row.get("id") in allowed]

    return wrapped


async def _admin_disabled(*_args: Any, **_kw: Any) -> list[dict]:
    raise RuntimeError("admin workspace endpoints disabled by scanner config")


class _CoreListerPatch:
    def __init__(self, config: ScannerConfig) -> None:
        self.config = config
        self.allowed = _allowlist(config)
        self.originals: dict[str, WorkspaceLister] = {}

    def __enter__(self) -> None:
        for name in (
            "_list_pbi_admin_workspaces",
            "_list_fabric_admin_workspaces",
            "_list_user_workspaces",
        ):
            self.originals[name] = getattr(_core_enum, name)

        if not self.config.admin_mode:
            _core_enum._list_pbi_admin_workspaces = _admin_disabled
            _core_enum._list_fabric_admin_workspaces = _admin_disabled

        if self.allowed:
            if self.config.admin_mode:
                _core_enum._list_pbi_admin_workspaces = _filter_lister(
                    _core_enum._list_pbi_admin_workspaces, self.allowed
                )
                _core_enum._list_fabric_admin_workspaces = _filter_lister(
                    _core_enum._list_fabric_admin_workspaces, self.allowed
                )
            _core_enum._list_user_workspaces = _filter_lister(
                _core_enum._list_user_workspaces, self.allowed
            )

    def __exit__(self, *_exc: object) -> None:
        for name, fn in self.originals.items():
            setattr(_core_enum, name, fn)


def _scanner_record(item: dict) -> dict:
    workspace_id = item.get("workspaceId") or (item.get("workspace") or {}).get("id") or ""
    return {
        "workspaceId": workspace_id,
        "workspaceName": item.get("workspaceName") or workspace_id,
        "id": item.get("id") or "",
        "displayName": item.get("displayName") or item.get("name"),
    }


async def enumerate_notebooks(
    config: ScannerConfig,
    token: str,
    *,
    concurrency: int = 50,
) -> list[dict]:
    """Return notebook descriptors: ``{workspaceId, workspaceName, id, displayName}``."""
    with _CoreListerPatch(config):
        items = await _core_enum.enumerate_workspaces_items(
            token=token,
            pbi_base=config.pbi_base,
            fabric_base=config.fabric_base,
            timeout=900.0,
            workspace_concurrency=concurrency,
            item_filter=_item_filter(config),
            log=log,
        )
    return [_scanner_record(item) for item in items]


def run_enumeration_sync(config: ScannerConfig, token: str) -> list[dict]:
    """Sync wrapper around :func:`enumerate_notebooks`, safe inside running loops."""
    return _run_sync_via_core_patch(config, token)


def _run_sync_via_core_patch(config: ScannerConfig, token: str) -> list[dict]:
    with _CoreListerPatch(config):
        items = _core_enum.run_enumeration_sync(
            token=token,
            pbi_base=config.pbi_base,
            fabric_base=config.fabric_base,
            timeout=900.0,
            workspace_concurrency=50,
            item_filter=_item_filter(config),
            log=log,
        )
    return [_scanner_record(item) for item in items]


__all__ = [
    "enumerate_notebooks",
    "run_enumeration_sync",
    "_http_json",
    "_list_pbi_admin_workspaces",
    "_list_fabric_admin_workspaces",
    "_list_user_workspaces",
]
