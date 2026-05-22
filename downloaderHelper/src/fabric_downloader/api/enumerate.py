"""Async workspace + multi-type item enumeration via Fabric / Power BI REST.

Strategy (mirrors `fabric_scanner.api.enumerate`):

1. List workspaces, trying the admin chain first when `admin_mode=True`:
   a) PBI admin   `/v1.0/myorg/admin/groups`
   b) Fabric admin `/v1/admin/workspaces`
   c) Fabric user `/v1/workspaces`
2. List items per workspace in parallel, filtering by the caller's
   `item_types` set (admin items endpoint for admin chains, user items
   endpoint otherwise).
3. Falls back gracefully through each layer so a capacity admin without
   PBI admin role still gets results.

`enumerate_items(config, token)` is the async public API. Sync callers
(notebooks, scripts) use `run_enumeration_sync(config, token)` which
correctly handles a kernel that's already running its own event loop.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import aiohttp

from ..config import DownloaderConfig


log = logging.getLogger(__name__)


# Items returned by /admin/items use PascalCase ("Notebook", "DataPipeline").
# Users sometimes pass them lowercased (or as Fabric "kind" values like
# "dataflow"); normalize on the way in so the set membership test is robust.
def _normalize(t: str) -> str:
    return (t or "").strip().lower()


async def _http_json(session: aiohttp.ClientSession, method: str, url: str,
                     **kw) -> tuple[int, Any, dict[str, str]]:
    async with session.request(method, url, **kw) as r:
        try:
            body = await r.json(content_type=None)
        except Exception:
            body = await r.text()
        return r.status, body, dict(r.headers)


async def _list_pbi_admin_workspaces(session: aiohttp.ClientSession,
                                     pbi_base: str) -> list[dict]:
    out, skip, page_size = [], 0, 5000
    while True:
        params = {"$top": page_size, "$skip": skip}
        status, body, _ = await _http_json(
            session, "GET",
            f"{pbi_base}/v1.0/myorg/admin/groups",
            params=params,
        )
        if status != 200:
            raise RuntimeError(
                f"PBI admin/groups HTTP {status}: {str(body)[:300]}")
        page = body.get("value", []) if isinstance(body, dict) else []
        out.extend(page)
        if len(page) < page_size:
            break
        skip += page_size
    return out


async def _list_fabric_admin_workspaces(session: aiohttp.ClientSession,
                                        fabric_base: str) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/admin/workspaces"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(
                f"Fabric admin/workspaces HTTP {status}: {str(body)[:300]}")
        out.extend((body or {}).get("value", []))
        url = (body or {}).get("continuationUri")
    return out


async def _list_user_workspaces(session: aiohttp.ClientSession,
                                fabric_base: str) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/workspaces"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(
                f"User /workspaces HTTP {status}: {str(body)[:300]}")
        out.extend((body or {}).get("value", []))
        url = (body or {}).get("continuationUri")
    return out


def _item_to_descriptor(it: dict, wid: str,
                        allowed: set[str]) -> dict | None:
    """Filter+normalize one /admin/items or /workspaces/{}/items row."""
    raw_type = (it.get("type") or it.get("itemType") or "")
    if _normalize(raw_type) not in allowed:
        return None
    return {
        "workspaceId": wid or (it.get("workspaceId")
                               or (it.get("workspace") or {}).get("id")),
        "id":          it["id"],
        "type":        raw_type,
        "displayName": it.get("displayName") or it.get("name"),
    }


async def _list_admin_items_tenant(session: aiohttp.ClientSession,
                                   fabric_base: str,
                                   allowed: set[str]) -> list[dict]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/admin/items"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            raise RuntimeError(
                f"Fabric admin/items HTTP {status}: {str(body)[:300]}")
        items = ((body or {}).get("itemEntities")
                 or (body or {}).get("value") or [])
        for it in items:
            d = _item_to_descriptor(it, "", allowed)
            if d and d["workspaceId"]:
                out.append(d)
        url = (body or {}).get("continuationUri")
    return out


async def _list_admin_items_workspace(
    session: aiohttp.ClientSession, fabric_base: str, wid: str,
    allowed: set[str],
) -> tuple[list[dict] | None, int]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/admin/items?workspaceId={wid}"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            return None, status
        items = ((body or {}).get("itemEntities")
                 or (body or {}).get("value") or [])
        for it in items:
            d = _item_to_descriptor(it, wid, allowed)
            if d:
                out.append(d)
        url = (body or {}).get("continuationUri")
    return out, 200


async def _list_user_items_workspace(
    session: aiohttp.ClientSession, fabric_base: str, wid: str,
    allowed: set[str],
) -> tuple[list[dict] | None, int]:
    out: list[dict] = []
    url: str | None = f"{fabric_base}/v1/workspaces/{wid}/items"
    while url:
        status, body, _ = await _http_json(session, "GET", url)
        if status != 200:
            return None, status
        for it in (body or {}).get("value", []):
            d = _item_to_descriptor(it, wid, allowed)
            if d:
                out.append(d)
        url = (body or {}).get("continuationUri")
    return out, 200


async def enumerate_items(config: DownloaderConfig, token: str,
                          *, concurrency: int = 50) -> list[dict]:
    """Return list of item descriptors matching `config.item_types`:

        [{workspaceId, workspaceName, id, type, displayName}, ...]

    Honors `config.admin_mode` and `config.read_workspace_ids`. Raises on
    fatal failures (no workspace listing endpoint accessible); returns an
    empty list when authentication succeeds but the caller has no
    workspaces or no items of the requested types.
    """
    allowed = {_normalize(t) for t in config.item_types}
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=900, connect=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as s:

        used_admin = False
        workspaces: list[dict] = []
        if config.admin_mode:
            chain = [
                ("PBI admin groups",
                 lambda: _list_pbi_admin_workspaces(s, config.pbi_base), True),
                ("Fabric admin workspaces",
                 lambda: _list_fabric_admin_workspaces(s, config.fabric_base),
                 True),
                ("User /v1/workspaces",
                 lambda: _list_user_workspaces(s, config.fabric_base), False),
            ]
        else:
            chain = [("User /v1/workspaces",
                      lambda: _list_user_workspaces(s, config.fabric_base),
                      False)]

        for label, fn, is_admin in chain:
            try:
                ws = await fn()
                log.info("[%s] returned %d workspaces", label, len(ws))
                if ws:
                    workspaces = ws
                    used_admin = is_admin
                    break
            except Exception as e:
                log.warning("[%s] FAILED: %s", label, e)

        ws_ids = [w["id"] for w in workspaces]
        ws_name_by_id = {
            w["id"]: (w.get("name") or w.get("displayName") or w["id"])
            for w in workspaces
        }
        if config.read_workspace_ids:
            allow = set(config.read_workspace_ids)
            ws_ids = [w for w in ws_ids if w in allow]

        if not ws_ids:
            return []

        items: list[dict] = []
        if used_admin:
            try:
                tenant = await _list_admin_items_tenant(
                    s, config.fabric_base, allowed)
                if config.read_workspace_ids:
                    allow = set(config.read_workspace_ids)
                    tenant = [n for n in tenant if n["workspaceId"] in allow]
                if tenant:
                    for n in tenant:
                        n["workspaceName"] = ws_name_by_id.get(
                            n.get("workspaceId"),
                            n.get("workspaceId", ""))
                    return tenant
            except Exception as e:
                log.info("tenant-wide admin items failed: %s; "
                         "falling back to per-workspace", e)

            sem = asyncio.Semaphore(concurrency)

            async def one_admin(wid: str):
                async with sem:
                    return wid, await _list_admin_items_workspace(
                        s, config.fabric_base, wid, allowed)

            results = await asyncio.gather(
                *(one_admin(w) for w in ws_ids))
        else:
            sem = asyncio.Semaphore(concurrency)

            async def one_user(wid: str):
                async with sem:
                    return wid, await _list_user_items_workspace(
                        s, config.fabric_base, wid, allowed)

            results = await asyncio.gather(*(one_user(w) for w in ws_ids))

        for _wid, (rows, _status) in results:
            if rows:
                items.extend(rows)

        for n in items:
            n["workspaceName"] = ws_name_by_id.get(
                n.get("workspaceId"), n.get("workspaceId", ""))
        return items


def run_enumeration_sync(config: DownloaderConfig, token: str) -> list[dict]:
    """Sync wrapper around `enumerate_items` that handles a kernel which
    already has a running event loop (i.e. Jupyter / Fabric)."""
    coro = enumerate_items(config, token)
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

    t = threading.Thread(target=worker, name="fabric-downloader-asyncio")
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
