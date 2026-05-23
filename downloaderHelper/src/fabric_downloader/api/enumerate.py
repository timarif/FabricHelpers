"""Item enumeration wrapper over :mod:`fabric_core.enumerate`."""
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

from ..config import DownloaderConfig

log = logging.getLogger(__name__)

WorkspaceLister = Callable[..., Awaitable[list[dict]]]
aiohttp = _core_enum.aiohttp


def _normalize(t: str | None) -> str:
    return (t or "").strip().lower()


def _allowlist(config: DownloaderConfig) -> set[str]:
    return {workspace_id for workspace_id in config.read_workspace_ids if workspace_id}


def _allowed_types(config: DownloaderConfig) -> set[str]:
    return {_normalize(item_type) for item_type in config.item_types}


def _item_workspace_id(item: dict, workspace: dict | None = None) -> str:
    workspace_obj = item.get("workspace") or {}
    return (
        (workspace or {}).get("id")
        or item.get("workspaceId")
        or workspace_obj.get("id")
        or ""
    )


def _item_to_descriptor(it: dict, wid: str, allowed: set[str]) -> dict | None:
    """Filter one item and preserve all fields from the Fabric response."""
    raw_type = it.get("type") or it.get("itemType") or ""
    if _normalize(raw_type) not in allowed:
        return None
    out = dict(it)
    workspace_id = wid or _item_workspace_id(it)
    if workspace_id:
        out["workspaceId"] = workspace_id
    out["id"] = it["id"]
    out["type"] = raw_type
    out["displayName"] = it.get("displayName") or it.get("name")
    return out


def _item_filter(config: DownloaderConfig) -> Callable[[dict, dict], bool]:
    allowed = _allowed_types(config)
    workspace_ids = _allowlist(config)

    def include(item: dict, workspace: dict) -> bool:
        workspace_id = _item_workspace_id(item, workspace)
        if workspace_ids and workspace_id not in workspace_ids:
            return False
        raw_type = item.get("type") or item.get("itemType") or ""
        return _normalize(raw_type) in allowed

    return include


def _filter_lister(fn: WorkspaceLister, allowed: set[str]) -> WorkspaceLister:
    async def wrapped(*args: Any, **kw: Any) -> list[dict]:
        rows = await fn(*args, **kw)
        if not allowed:
            return rows
        return [row for row in rows if row.get("id") in allowed]

    return wrapped


async def _admin_disabled(*_args: Any, **_kw: Any) -> list[dict]:
    raise RuntimeError("admin workspace endpoints disabled by downloader config")


class _CoreListerPatch:
    def __init__(self, config: DownloaderConfig) -> None:
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


def _downloader_record(item: dict) -> dict:
    out = dict(item)
    workspace = out.get("workspace") or {}
    workspace_id = out.get("workspaceId") or workspace.get("id") or ""
    item_id = out.get("id", "")
    item_name = out.get("name") or out.get("displayName") or item_id
    out.update({
        "id": item_id,
        "name": item_name,
        "displayName": out.get("displayName") or item_name,
        "type": out.get("type") or out.get("itemType") or "",
        "workspaceId": workspace_id,
        "workspaceName": out.get("workspaceName")
        or workspace.get("name")
        or workspace.get("displayName")
        or workspace_id,
    })
    return out


async def enumerate_items(
    config: DownloaderConfig,
    token: str,
    *,
    concurrency: int = 50,
) -> list[dict]:
    """Return full item records matching ``config.item_types``."""
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
    return [_downloader_record(item) for item in items]


def run_enumeration_sync(config: DownloaderConfig, token: str) -> list[dict]:
    """Sync wrapper around :func:`enumerate_items`, safe inside running loops."""
    if enumerate_items is not _DEFAULT_ENUMERATE_ITEMS:
        return _run_monkeypatched_enumeration_sync(config, token)
    return _run_sync_via_core_patch(config, token)


def _run_sync_via_core_patch(config: DownloaderConfig, token: str) -> list[dict]:
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
    return [_downloader_record(item) for item in items]


def _run_monkeypatched_enumeration_sync(config: DownloaderConfig, token: str) -> list[dict]:
    original = _core_enum.enumerate_workspaces_items

    async def wrapped(**_kw: Any) -> list[dict]:
        return await enumerate_items(config, token)

    _core_enum.enumerate_workspaces_items = wrapped
    try:
        return _core_enum.run_enumeration_sync()
    finally:
        _core_enum.enumerate_workspaces_items = original


_DEFAULT_ENUMERATE_ITEMS = enumerate_items


__all__ = [
    "enumerate_items",
    "run_enumeration_sync",
    "_http_json",
    "_list_pbi_admin_workspaces",
    "_list_fabric_admin_workspaces",
    "_list_user_workspaces",
]
