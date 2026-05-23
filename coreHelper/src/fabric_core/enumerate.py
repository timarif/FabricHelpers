"""Async workspace + item enumeration via Fabric / Power BI REST."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any


class _LazyAioHttp:
    def __getattr__(self, name: str) -> Any:
        import aiohttp as real_aiohttp

        return getattr(real_aiohttp, name)


aiohttp: Any = _LazyAioHttp()

ItemFilter = Callable[[dict, dict], bool]

_module_log = logging.getLogger(__name__)


async def _http_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    **kw: Any,
) -> tuple[int, Any, dict[str, str]]:
    """Return (status, json-or-text body, headers) without raising for HTTP errors."""
    async with session.request(method, url, **kw) as r:
        try:
            body = await r.json(content_type=None)
        except Exception:
            body = await r.text()
        return r.status, body, dict(r.headers)


async def _list_pbi_admin_workspaces(
    session: aiohttp.ClientSession,
    pbi_base: str,
) -> list[dict]:
    out: list[dict] = []
    skip, page_size = 0, 5000
    while True:
        status, body, _ = await _http_json(
            session,
            "GET",
            f"{pbi_base}/v1.0/myorg/admin/groups",
            params={"$top": page_size, "$skip": skip},
        )
        if status != 200:
            raise RuntimeError(f"PBI admin/groups HTTP {status}: {str(body)[:300]}")
        page = body.get("value", []) if isinstance(body, dict) else []
        out.extend(page)
        if len(page) < page_size:
            break
        skip += page_size
    return out


async def _list_fabric_admin_workspaces(
    session: aiohttp.ClientSession,
    fabric_base: str,
) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/admin/workspaces"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(f"Fabric admin/workspaces HTTP {status}: {str(body)[:300]}")
        out.extend(body.get("value", []) if isinstance(body, dict) else [])
        url = body.get("continuationUri") if isinstance(body, dict) else None
    return out


async def _list_user_workspaces(
    session: aiohttp.ClientSession,
    fabric_base: str,
) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/workspaces"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(f"User /workspaces HTTP {status}: {str(body)[:300]}")
        out.extend(body.get("value", []) if isinstance(body, dict) else [])
        url = body.get("continuationUri") if isinstance(body, dict) else None
    return out


def _workspace_name(workspace: dict) -> str:
    return workspace.get("name") or workspace.get("displayName") or workspace.get("id", "")


def _item_workspace_id(item: dict, workspace: dict | None = None) -> str:
    workspace_obj = item.get("workspace") or {}
    return (
        (workspace or {}).get("id")
        or item.get("workspaceId")
        or workspace_obj.get("id")
        or ""
    )


def _item_record(item: dict, workspace: dict) -> dict:
    item_id = item.get("id", "")
    item_name = item.get("name") or item.get("displayName") or item_id
    item_type = item.get("type") or item.get("itemType") or ""
    record = dict(item)
    record.update(
        {
            "id": item_id,
            "name": item_name,
            "displayName": item.get("displayName") or item_name,
            "type": item_type,
            "workspaceId": _item_workspace_id(item, workspace),
            "workspaceName": _workspace_name(workspace),
        }
    )
    return record


def _include_item(item: dict, workspace: dict, item_filter: ItemFilter | None) -> bool:
    if item_filter is None:
        return True
    return bool(item_filter(item, workspace))


async def _list_admin_items_tenant(
    session: aiohttp.ClientSession,
    fabric_base: str,
    workspaces_by_id: dict[str, dict],
    item_filter: ItemFilter | None,
) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/admin/items"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(f"Fabric admin/items HTTP {status}: {str(body)[:300]}")
        items = []
        if isinstance(body, dict):
            items = body.get("itemEntities") or body.get("value") or []
        for item in items:
            workspace_id = _item_workspace_id(item)
            if not workspace_id:
                continue
            workspace = workspaces_by_id.get(workspace_id) or item.get("workspace") or {"id": workspace_id}
            if _include_item(item, workspace, item_filter):
                out.append(_item_record(item, workspace))
        url = body.get("continuationUri") if isinstance(body, dict) else None
    return out


async def _list_admin_items_workspace(
    session: aiohttp.ClientSession,
    fabric_base: str,
    workspace: dict,
    item_filter: ItemFilter | None,
) -> tuple[list[dict] | None, int]:
    out: list[dict] = []
    workspace_id = workspace["id"]
    url: str | None = f"{fabric_base}/v1/admin/items?workspaceId={workspace_id}"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            return None, status
        items = []
        if isinstance(body, dict):
            items = body.get("itemEntities") or body.get("value") or []
        for item in items:
            if _include_item(item, workspace, item_filter):
                out.append(_item_record(item, workspace))
        url = body.get("continuationUri") if isinstance(body, dict) else None
    return out, 200


async def _list_user_items_workspace(
    session: aiohttp.ClientSession,
    fabric_base: str,
    workspace: dict,
    item_filter: ItemFilter | None,
) -> tuple[list[dict] | None, int]:
    out: list[dict] = []
    workspace_id = workspace["id"]
    url: str | None = f"{fabric_base}/v1/workspaces/{workspace_id}/items"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            return None, status
        items = body.get("value", []) if isinstance(body, dict) else []
        for item in items:
            if _include_item(item, workspace, item_filter):
                out.append(_item_record(item, workspace))
        url = body.get("continuationUri") if isinstance(body, dict) else None
    return out, 200


async def enumerate_workspaces_items(
    *,
    token: str,
    pbi_base: str,
    fabric_base: str,
    timeout: float,
    workspace_concurrency: int,
    item_filter: ItemFilter | None = None,
    log: Any = None,
) -> list[dict]:
    """Enumerate Fabric workspaces and return item records from accessible endpoints.

    If ``item_filter`` is ``None``, all items are returned. Otherwise the callback
    receives ``(item, workspace)`` and only truthy callback results are included.
    """
    logger = log or _module_log
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    async with aiohttp.ClientSession(headers=headers, timeout=client_timeout) as session:
        workspaces: list[dict] = []
        used_admin = False
        chain = [
            ("PBI admin groups", lambda: _list_pbi_admin_workspaces(session, pbi_base), True),
            (
                "Fabric admin workspaces",
                lambda: _list_fabric_admin_workspaces(session, fabric_base),
                True,
            ),
            ("User /v1/workspaces", lambda: _list_user_workspaces(session, fabric_base), False),
        ]

        for label, fn, is_admin in chain:
            try:
                rows = await fn()
                logger.info("[%s] returned %d workspaces", label, len(rows))
                if rows:
                    workspaces = rows
                    used_admin = is_admin
                    break
            except Exception as e:
                logger.warning("[%s] FAILED: %s", label, e)

        workspaces = [workspace for workspace in workspaces if workspace.get("id")]
        if not workspaces:
            return []

        workspaces_by_id = {workspace["id"]: workspace for workspace in workspaces}

        if used_admin:
            try:
                tenant_items = await _list_admin_items_tenant(
                    session,
                    fabric_base,
                    workspaces_by_id,
                    item_filter,
                )
                if tenant_items:
                    return tenant_items
            except Exception as e:
                logger.info(
                    "tenant-wide admin items failed: %s; falling back to per-workspace",
                    e,
                )

            sem = asyncio.Semaphore(max(1, workspace_concurrency))

            async def one_admin(workspace: dict) -> tuple[str, tuple[list[dict] | None, int]]:
                async with sem:
                    return workspace["id"], await _list_admin_items_workspace(
                        session,
                        fabric_base,
                        workspace,
                        item_filter,
                    )

            results = await asyncio.gather(*(one_admin(workspace) for workspace in workspaces))
        else:
            sem = asyncio.Semaphore(max(1, workspace_concurrency))

            async def one_user(workspace: dict) -> tuple[str, tuple[list[dict] | None, int]]:
                async with sem:
                    return workspace["id"], await _list_user_items_workspace(
                        session,
                        fabric_base,
                        workspace,
                        item_filter,
                    )

            results = await asyncio.gather(*(one_user(workspace) for workspace in workspaces))

        items: list[dict] = []
        for _workspace_id, (rows, _status) in results:
            if rows:
                items.extend(rows)
        return items


def run_enumeration_sync(**kwargs: Any) -> list[dict]:
    """Run ``enumerate_workspaces_items`` from sync code, even inside running loops."""
    coro = enumerate_workspaces_items(**kwargs)
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False

    if not running:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def worker() -> None:
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            box["value"] = new_loop.run_until_complete(coro)
        except BaseException as e:
            box["error"] = e
        finally:
            new_loop.close()

    thread = threading.Thread(target=worker, name="fabric-core-enumerate-asyncio")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
