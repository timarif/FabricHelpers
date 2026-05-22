"""Pure-Python row builders + Spark partition glue.

Two layers, by design:

  - `scan_row(path, content, ctx)` and `fetch_row(meta, body, error, ctx)`
    are pure Python: they take raw inputs and return a list of dicts each
    keyed by `RESULT_COLUMNS`. Testable with a vanilla pytest run — no
    Spark, no Fabric, no JVM.

  - `scan_partition_lakehouse(rows_iter, ctx)` and
    `fetch_partition(rows_iter, ctx)` are the thin generators Spark
    actually calls via `mapPartitions`. They lazy-import
    `pyspark.sql.Row`, parse `(path, content)` / `(workspace_id, ...)`
    out of each Row, forward to the pure layer, and yield Row instances
    matching `spark.schema.result_schema`.

This split is the main reason Phase 3 doesn't need pyspark in `[dev]` —
all the interesting logic is reachable without it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from ..engine.extract import extract_attached_lakehouse
from ..engine.resolve import resolve_dest_workspace
from ..engine.scanner import scan_notebook_bytes
from ..config import ScannerConfig
from .context import PartitionContext
from .schema import RESULT_COLUMNS


def _engine_config_from_ctx(ctx: PartitionContext) -> ScannerConfig:
    """Reconstruct a minimal ScannerConfig for the engine layer. We can't
    pickle the original ScannerConfig (well, we can, but threading it
    everywhere bloats the closure); rebuild from the ctx fields the
    engine actually reads."""
    return ScannerConfig(
        source_mode=("api" if ctx.mode == "api" else "lakehouse"),
        min_severity=ctx.min_severity,
        max_snippet_bytes=ctx.max_snippet_bytes,
        scan_markdown_and_outputs=ctx.scan_markdown_and_outputs,
    )


def _empty_row_dict(
    *,
    workspace_id: str,
    workspace_name: str,
    notebook_id: str,
    display_name: str,
    scanned_at: datetime,
    source_lakehouse_id: str | None = None,
    source_lakehouse_name: str | None = None,
    source_dated_partition: str | None = None,
    attached_lakehouse_id: str | None = None,
    attached_lakehouse_name: str | None = None,
    attached_lakehouse_workspace_id: str | None = None,
    attached_lakehouse_workspace_name: str | None = None,
    error: str | None = None,
) -> dict:
    """Build one 'no findings' row dict. Every key in RESULT_COLUMNS is
    populated so the dict trivially round-trips through pyspark.sql.Row
    and the StructType cast."""
    return {
        "workspace_id": workspace_id or None,
        "workspace_name": workspace_name or None,
        "source_lakehouse_id": source_lakehouse_id or None,
        "source_lakehouse_name": source_lakehouse_name or None,
        "source_dated_partition": source_dated_partition,
        "notebook_id": notebook_id or None,
        "display_name": display_name or None,
        "attached_lakehouse_id": attached_lakehouse_id,
        "attached_lakehouse_name": attached_lakehouse_name,
        "attached_lakehouse_workspace_id": attached_lakehouse_workspace_id,
        "attached_lakehouse_workspace_name": attached_lakehouse_workspace_name,
        "part_path": None, "source_kind": None,
        "cell_index": 0, "line_number": 0,
        "finding_type": None, "category": None, "severity": None,
        "message": None, "code_snippet": None,
        "url": None, "direction": None,
        "dest_workspace_id": None, "dest_workspace_name": None,
        "cross_workspace": None,
        "error": error,
        "scanned_at": scanned_at,
    }


def _row_dict_from_finding(
    f: dict, ctx: PartitionContext,
    *,
    workspace_id: str, workspace_name: str,
    notebook_id: str, display_name: str,
    scanned_at: datetime,
    source_lakehouse_id: str | None,
    source_lakehouse_name: str | None,
    source_dated_partition: str | None,
) -> dict:
    """Convert one engine finding dict to a full RESULT_COLUMNS row dict.
    Resolves dest_workspace via the context's WS map and backfills
    attached_lakehouse_workspace_name when only the id is known."""
    url = f.get("url")
    if url:
        d_id, d_name, cross = resolve_dest_workspace(
            url, workspace_id or "", workspace_name or "",
            ctx.ws_name_by_id, ctx.ws_id_by_name,
        )
    else:
        d_id, d_name, cross = (None, None, None)

    lh_wsid = f.get("attached_lakehouse_workspace_id")
    lh_wsname = f.get("attached_lakehouse_workspace_name")
    if lh_wsid and not lh_wsname:
        lh_wsname = ctx.ws_name_by_id.get((lh_wsid or "").lower())

    return {
        "workspace_id": workspace_id or None,
        "workspace_name": workspace_name or None,
        "source_lakehouse_id": source_lakehouse_id or None,
        "source_lakehouse_name": source_lakehouse_name or None,
        "source_dated_partition": source_dated_partition,
        "notebook_id": notebook_id or None,
        "display_name": display_name or None,
        "attached_lakehouse_id": f.get("attached_lakehouse_id"),
        "attached_lakehouse_name": f.get("attached_lakehouse_name"),
        "attached_lakehouse_workspace_id": lh_wsid,
        "attached_lakehouse_workspace_name": lh_wsname,
        "part_path": f.get("part_path") or None,
        "source_kind": f.get("source_kind") or None,
        "cell_index": int(f.get("cell_index", 0) or 0),
        "line_number": int(f.get("line", 0) or 0),
        "finding_type": f.get("finding_type"),
        "category": f.get("category"),
        "severity": f.get("severity"),
        "message": f.get("message"),
        "code_snippet": f.get("code_snippet"),
        "url": url, "direction": f.get("direction"),
        "dest_workspace_id": d_id, "dest_workspace_name": d_name,
        "cross_workspace": cross,
        "error": None,
        "scanned_at": scanned_at,
    }


# --- Lakehouse-mode pure helper ---------------------------------------------

def scan_row(
    path: str,
    content: bytes,
    ctx: PartitionContext,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Scan one notebook file's bytes. Returns one row dict per finding,
    or exactly one 'empty' row dict when the file produced no findings.

    `path` is the abfss://... (or local) path of the file; `content` is
    the raw .ipynb bytes (or already-decoded JSON bytes — either works).

    Pure Python. No Spark, no aiohttp. Used by `scan_partition_lakehouse`
    and exercised directly in tests.
    """
    scanned_at = now or datetime.now(timezone.utc)
    cfg = _engine_config_from_ctx(ctx)

    # Per-row workspace + datestamp when ws_dated; otherwise ctx defaults.
    wid     = ctx.source_workspace_id
    wname   = ctx.source_workspace_name or ctx.source_workspace_id
    dated   = None
    if ctx.source_layout == "ws_dated" and ctx.ws_dated_base:
        m = re.search(
            re.escape(ctx.ws_dated_base) + r"/([^/]+)/([^/]+)/",
            path or "",
        )
        if m:
            wid = m.group(1) or wid
            dated = m.group(2) or None
            wname = ctx.ws_name_by_id.get((wid or "").lower(), wid)

    nb_id = path or ""
    nb_name = (path or "").rsplit("/", 1)[-1]
    lh_src_id   = ctx.source_lakehouse_id or None
    lh_src_name = ctx.source_lakehouse_name or None

    try:
        lh = extract_attached_lakehouse(content or b"", path or "")
        findings = scan_notebook_bytes(content or b"", path or "", cfg)
    except Exception as e:
        return [_empty_row_dict(
            workspace_id=wid, workspace_name=wname,
            notebook_id=nb_id, display_name=nb_name,
            scanned_at=scanned_at,
            source_lakehouse_id=lh_src_id, source_lakehouse_name=lh_src_name,
            source_dated_partition=dated,
            error=f"scan error: {type(e).__name__}: {e}",
        )]

    # Backfill attached LH name from the workspace map when only id is known.
    if (lh.get("attached_lakehouse_workspace_id")
            and not lh.get("attached_lakehouse_workspace_name")):
        lh["attached_lakehouse_workspace_name"] = ctx.ws_name_by_id.get(
            (lh["attached_lakehouse_workspace_id"] or "").lower())

    if not findings:
        return [_empty_row_dict(
            workspace_id=wid, workspace_name=wname,
            notebook_id=nb_id, display_name=nb_name,
            scanned_at=scanned_at,
            source_lakehouse_id=lh_src_id, source_lakehouse_name=lh_src_name,
            source_dated_partition=dated,
            attached_lakehouse_id=lh.get("attached_lakehouse_id"),
            attached_lakehouse_name=lh.get("attached_lakehouse_name"),
            attached_lakehouse_workspace_id=lh.get(
                "attached_lakehouse_workspace_id"),
            attached_lakehouse_workspace_name=lh.get(
                "attached_lakehouse_workspace_name"),
        )]

    out: list[dict] = []
    for f in findings:
        out.append(_row_dict_from_finding(
            f, ctx,
            workspace_id=wid, workspace_name=wname,
            notebook_id=nb_id, display_name=nb_name,
            scanned_at=scanned_at,
            source_lakehouse_id=lh_src_id,
            source_lakehouse_name=lh_src_name,
            source_dated_partition=dated,
        ))
    return out


# --- API-mode pure helper ---------------------------------------------------

def process_fetched_row(
    workspace_id: str,
    workspace_name: str,
    notebook_id: str,
    display_name: str,
    body: dict | None,
    error: str | None,
    ctx: PartitionContext,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Build row dicts for one fetched notebook in API mode.

    Either `body` is the parsed getDefinition JSON OR `error` describes
    the failure. (Exactly one of the two is non-None when called from
    the production code path; both can be set in tests to assert
    precedence.)
    """
    import json as _json
    scanned_at = now or datetime.now(timezone.utc)

    if error is not None or body is None:
        return [_empty_row_dict(
            workspace_id=workspace_id, workspace_name=workspace_name,
            notebook_id=notebook_id, display_name=display_name,
            scanned_at=scanned_at, error=error,
        )]

    cfg = _engine_config_from_ctx(ctx)
    label = f"{display_name or notebook_id or 'notebook'}.ipynb"
    try:
        body_bytes = _json.dumps(body).encode("utf-8")
        lh = extract_attached_lakehouse(body_bytes, label)
        findings = scan_notebook_bytes(body_bytes, label, cfg)
    except Exception as e:
        return [_empty_row_dict(
            workspace_id=workspace_id, workspace_name=workspace_name,
            notebook_id=notebook_id, display_name=display_name,
            scanned_at=scanned_at,
            error=f"scan error: {type(e).__name__}: {e}",
        )]

    if (lh.get("attached_lakehouse_workspace_id")
            and not lh.get("attached_lakehouse_workspace_name")):
        lh["attached_lakehouse_workspace_name"] = ctx.ws_name_by_id.get(
            (lh["attached_lakehouse_workspace_id"] or "").lower())

    if not findings:
        return [_empty_row_dict(
            workspace_id=workspace_id, workspace_name=workspace_name,
            notebook_id=notebook_id, display_name=display_name,
            scanned_at=scanned_at,
            attached_lakehouse_id=lh.get("attached_lakehouse_id"),
            attached_lakehouse_name=lh.get("attached_lakehouse_name"),
            attached_lakehouse_workspace_id=lh.get(
                "attached_lakehouse_workspace_id"),
            attached_lakehouse_workspace_name=lh.get(
                "attached_lakehouse_workspace_name"),
        )]

    out: list[dict] = []
    for f in findings:
        out.append(_row_dict_from_finding(
            f, ctx,
            workspace_id=workspace_id, workspace_name=workspace_name,
            notebook_id=notebook_id, display_name=display_name,
            scanned_at=scanned_at,
            source_lakehouse_id=None, source_lakehouse_name=None,
            source_dated_partition=None,
        ))
    return out


# --- Row helpers (work for both Spark Row and dict) -------------------------

def _row_field(row: Any, name: str, default: Any = None) -> Any:
    """Tolerant getter — works for pyspark.sql.Row, dict, and SimpleNamespace
    test doubles."""
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        pass
    return getattr(row, name, default)


def _emit(d: dict):
    """Convert a row dict to a pyspark.sql.Row in the exact column order
    declared by `RESULT_COLUMNS`. Lazy import keeps the module importable
    in pyspark-free environments."""
    from pyspark.sql import Row
    return Row(**{k: d.get(k) for k in RESULT_COLUMNS})


# --- Spark generators (mapPartitions targets) -------------------------------

def scan_partition_lakehouse(
    rows: Iterable[Any], ctx: PartitionContext,
) -> Iterator[Any]:
    """Spark `mapPartitions` target for lakehouse mode."""
    for r in rows:
        path = _row_field(r, "path", "") or ""
        content = _row_field(r, "content", b"") or b""
        for d in scan_row(path, content, ctx):
            yield _emit(d)


def fetch_partition(
    rows: Iterable[Any], ctx: PartitionContext,
) -> Iterator[Any]:
    """Spark `mapPartitions` target for API mode.

    Refreshes the bearer token on the executor (long-running jobs may
    outlast the driver-side token), then fetches all notebook bodies in
    the partition with bounded concurrency via the same
    `fetch_notebook_definition` helper used elsewhere.
    """
    import asyncio
    import aiohttp

    from ..api.auth import get_token, TokenError
    from ..api.fetch import fetch_notebook_definition

    materialized = list(rows)
    if not materialized:
        return

    # Try to refresh from the runtime first; fall back to the driver's
    # snapshot if the executor isn't in a Fabric kernel.
    try:
        token = get_token(ctx.token_audience)
    except TokenError:
        token = ctx.fallback_token
    if not token:
        scanned_at = datetime.now(timezone.utc)
        for r in materialized:
            yield _emit(_empty_row_dict(
                workspace_id=_row_field(r, "workspace_id", "") or "",
                workspace_name=_row_field(r, "workspace_name", "") or "",
                notebook_id=_row_field(r, "notebook_id", "") or "",
                display_name=_row_field(r, "display_name", "") or "",
                scanned_at=scanned_at,
                error="no token available on executor",
            ))
        return

    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    sem = asyncio.Semaphore(ctx.executor_concurrency)

    async def one(session, wid, wname, iid, name):
        async with sem:
            body, err = await fetch_notebook_definition(
                session, ctx.fabric_base, wid, iid,
                max_retries=ctx.max_retries,
            )
            return wid, wname, iid, name, body, err

    async def run_all():
        connector = aiohttp.TCPConnector(limit=ctx.executor_concurrency * 2)
        timeout = aiohttp.ClientTimeout(total=1200, connect=30)
        async with aiohttp.ClientSession(
                connector=connector, headers=headers, timeout=timeout
        ) as session:
            tasks = [
                one(session,
                    _row_field(r, "workspace_id", "") or "",
                    _row_field(r, "workspace_name", "") or "",
                    _row_field(r, "notebook_id", "") or "",
                    _row_field(r, "display_name", "") or "")
                for r in materialized
            ]
            return await asyncio.gather(*tasks)

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(run_all())
    finally:
        loop.close()

    now = datetime.now(timezone.utc)
    for wid, wname, iid, name, body, err in results:
        for d in process_fetched_row(wid, wname, iid, name, body, err, ctx,
                                     now=now):
            yield _emit(d)
