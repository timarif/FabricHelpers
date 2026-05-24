"""Pure-Python download row builders + Spark partition glue.

Two layers, by design:

  - `process_definition_body(...)` is pure Python: takes a getDefinition
    response body, the item metadata, and a writer callback, and produces a
    manifest row dict + a list of (target_uri, text) tuples to write.
    Testable without Spark, without Fabric, without I/O.

  - `download_partition(rows_iter, ctx)` is the thin generator Spark
    actually calls via `mapPartitions`. It lazy-imports `pyspark.sql.Row`,
    sets up the aiohttp session + token refresh machinery, fans out
    `fetch_item_definition` calls with bounded concurrency, then forwards
    each (item, body, error) tuple to the pure layer for writing +
    manifest-row emission.
"""
from __future__ import annotations

import base64
import json as _json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator

from ..paths import (
    build_paths, item_folder, safe_segment, target_exists, write_text,
)
from .context import DownloadContext
from .schema import MANIFEST_COLUMNS


# ---------------------------------------------------------------------------
# Manifest row dict
# ---------------------------------------------------------------------------


def _row_dict(
    *,
    ctx: DownloadContext,
    workspace_id: str,
    workspace_name: str,
    item_type: str,
    item_id: str,
    display_name: str,
    export_format: str,
    now: datetime,
    rel_path: str | None = None,
    primary_target: str | None = None,
    item_json_target: str | None = None,
    part_count: int | None = None,
    parts_saved: int = 0,
    has_content_part: bool | None = None,
    payload_bytes: int | None = None,
    attempts: int = 0,
    token_refreshes: int = 0,
    http_status: int = 0,
    status: str = "error",
    error: str | None = None,
) -> dict:
    return {
        "workspace_id":     workspace_id or None,
        "workspace_name":   workspace_name or None,
        "item_type":        item_type or None,
        "item_id":          item_id or None,
        "display_name":     display_name or None,
        "rel_path":         rel_path,
        "primary_target":   primary_target,
        "item_json_target": item_json_target,
        "export_format":    export_format,
        "part_count":       (int(part_count) if part_count is not None
                             else None),
        "parts_saved":      int(parts_saved),
        "has_content_part": has_content_part,
        "payload_bytes":    (int(payload_bytes) if payload_bytes is not None
                             else None),
        "attempts":         int(attempts),
        "token_refreshes":  int(token_refreshes),
        "http_status":      int(http_status or 0),
        "status":           status,
        "error":            error,
        "run_label":        ctx.run_label,
        "downloaded_at":    now,
    }


# ---------------------------------------------------------------------------
# Pure body processor (no Spark, no aiohttp, no I/O — writer is injected)
# ---------------------------------------------------------------------------


# A writer callback decides what actually happens to a (target_uri, text)
# pair. Production: `paths.write_text`. Tests: capture into a list.
Writer = Callable[[str, str], None]
ExistsCheck = Callable[[str], bool]


def _is_content_part(part_path: str) -> bool:
    """True for the 'main payload' part of a definition.

    Covers the canonical part names Fabric returns today:
      - `notebook-content.py` / `notebook-content.ipynb` (Notebook)
      - `pipeline-content.json`                          (DataPipeline)
      - `mashup.pq`                                      (Dataflow Gen2)
    Plus a generic substring match so future item types are picked up
    automatically.
    """
    p = (part_path or "").lower()
    return ("notebook-content" in p
            or "pipeline-content" in p
            or "mashup" in p
            or p.endswith(".ipynb"))


# Notebook source-mode extensions. The Fabric `fabricGitSource` response
# returns `notebook-content.<lang>` where `<lang>` is the notebook language:
# `py` (PySpark / Python), `scala`, `sql`, `r`. The whitelist keeps the
# downloader from being tricked into writing arbitrary filenames if the
# API ever returns an unexpected part path.
_NOTEBOOK_SOURCE_EXTS: tuple[str, ...] = ("py", "scala", "sql", "r")


def _find_notebook_source_part(
    parts: list[dict],
) -> tuple[dict | None, str | None, list[str]]:
    """Locate the single `notebook-content.<lang>` part in a definition.

    Returns ``(part, ext_without_dot, all_matches)``. ``part`` is None when
    no source part exists; ``all_matches`` carries every matched basename
    so callers can render an unambiguous error if more than one is found.
    """
    matches: list[tuple[dict, str]] = []
    for p in parts:
        raw = (p.get("path") or "").strip("/")
        basename = raw.rsplit("/", 1)[-1].lower()
        if not basename.startswith("notebook-content."):
            continue
        ext = basename[len("notebook-content."):]
        if not ext or "." in ext:
            continue
        if ext not in _NOTEBOOK_SOURCE_EXTS:
            continue
        matches.append((p, ext))
    if not matches:
        return None, None, []
    seen = [f"notebook-content.{e}" for _, e in matches]
    return matches[0][0], matches[0][1], seen


def process_definition_body(
    *,
    ctx: DownloadContext,
    workspace_id: str,
    workspace_name: str,
    item_type: str,
    item_id: str,
    display_name: str,
    body: dict | None,
    http_status: int,
    attempts: int,
    token_refreshes: int,
    error: str | None,
    writer: Writer | None = None,
    exists: ExistsCheck | None = None,
    now: datetime | None = None,
) -> dict:
    """Process one fetched item: write its files via `writer` and return
    one manifest row dict.

    Either `body` is the parsed getDefinition JSON OR `error` describes
    the failure. (Exactly one of the two is non-None when called from
    the production code path.)
    """
    now = now or datetime.now(timezone.utc)
    _write = writer if writer is not None else write_text
    _exists = exists if exists is not None else target_exists

    export_mode = ctx.export_mode_for(item_type)

    primary_rel, item_json_rel = build_paths(
        output_root=ctx.output_root,
        run_label=ctx.run_label,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        item_type=item_type,
        item_id=item_id,
        item_name=display_name,
        export_mode=export_mode,
        group_by_type=ctx.group_by_type,
    )
    primary_target = ctx.join_target(primary_rel)
    item_target_uri = ctx.join_target(item_json_rel)

    base_kwargs = dict(
        ctx=ctx,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        item_type=item_type,
        item_id=item_id,
        display_name=display_name,
        export_format=export_mode,
        now=now,
        rel_path=primary_rel,
        primary_target=primary_target,
        attempts=attempts,
        token_refreshes=token_refreshes,
        http_status=http_status,
    )

    if error is not None or body is None:
        return _row_dict(**base_kwargs,
                         status="error",
                         error=(error or "no body returned"))

    parts = (body.get("definition") or {}).get("parts") or []
    if not parts:
        return _row_dict(**base_kwargs,
                         part_count=0, has_content_part=False,
                         status="error",
                         error="empty definition.parts in response")

    has_content_part = any(_is_content_part(p.get("path") or "")
                           for p in parts)
    folder = item_folder(
        ctx.output_root, ctx.run_label,
        workspace_id, workspace_name, item_type,
        group_by_type=ctx.group_by_type,
    )
    safe_name = safe_segment(display_name or item_id or "unnamed")
    fname_prefix = f"{safe_name}__{item_id}"

    parts_saved = 0
    payload_bytes = 0
    final_primary_rel = primary_rel
    final_primary_target = primary_target

    try:
        if export_mode == "ipynb":
            ipynb_text = None
            for p in parts:
                ppath = (p.get("path") or "").lower()
                payload = p.get("payload") or ""
                if payload and ppath.endswith(".ipynb"):
                    decoded = base64.b64decode(payload)
                    ipynb_text = decoded.decode("utf-8", errors="replace")
                    payload_bytes = len(decoded)
                    break
            if ipynb_text is None:
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), has_content_part=has_content_part,
                    status="error",
                    error=(f"no .ipynb part in definition "
                           f"(got {len(parts)} parts)"))
            if ctx.skip_existing and _exists(primary_target):
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), parts_saved=0,
                    has_content_part=has_content_part,
                    payload_bytes=payload_bytes,
                    item_json_target=(item_target_uri
                                      if ctx.include_raw_definition else None),
                    status="skipped_exists", error=None)
            _write(primary_target, ipynb_text)
            parts_saved = 1

        elif export_mode in ("py", "txt"):
            # Single-file native-source mode. The API returns the source
            # under `notebook-content.<lang>` plus `.platform`; we save
            # only the source. In "py" mode the extension matches the
            # notebook's actual language (`.py`, `.scala`, `.sql`, `.r`);
            # in "txt" mode the source is always saved as `.txt`.
            src_part, ext, all_matches = _find_notebook_source_part(parts)
            if src_part is None:
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), has_content_part=has_content_part,
                    status="error",
                    error=(f"no notebook-content.<py|scala|sql|r> part in "
                           f"definition (got {len(parts)} parts)"))
            if len(all_matches) > 1:
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), has_content_part=has_content_part,
                    status="error",
                    error=(f"multiple notebook source parts found: "
                           f"{all_matches}"))
            payload = src_part.get("payload") or ""
            if not payload:
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), has_content_part=has_content_part,
                    status="error",
                    error=(f"notebook-content.{ext} part has empty "
                           f"payload"))
            decoded = base64.b64decode(payload)
            src_text = decoded.decode("utf-8", errors="replace")
            payload_bytes = len(decoded)
            # In "py" mode honor the source language; in "txt" mode flatten
            # everything to `.txt`.
            file_ext = ext if export_mode == "py" else "txt"
            final_primary_rel = f"{folder}/{fname_prefix}.{file_ext}"
            final_primary_target = ctx.join_target(final_primary_rel)
            base_kwargs["rel_path"] = final_primary_rel
            base_kwargs["primary_target"] = final_primary_target
            if ctx.skip_existing and _exists(final_primary_target):
                return _row_dict(
                    **base_kwargs,
                    part_count=len(parts), parts_saved=0,
                    has_content_part=has_content_part,
                    payload_bytes=payload_bytes,
                    item_json_target=(item_target_uri
                                      if ctx.include_raw_definition else None),
                    status="skipped_exists", error=None)
            _write(final_primary_target, src_text)
            parts_saved = 1

        else:  # parts mode (universal for non-notebook types)
            for p in parts:
                raw_ppath = (p.get("path") or "").strip("/")
                payload = p.get("payload") or ""
                if not payload or not raw_ppath:
                    continue
                decoded = base64.b64decode(payload)
                try:
                    text = decoded.decode("utf-8", errors="replace")
                except Exception:
                    text = decoded.decode("latin-1", errors="replace")
                safe_part = safe_segment(
                    raw_ppath.replace("/", "__"), maxlen=160)
                part_rel = f"{folder}/{fname_prefix}__{safe_part}.txt"
                part_uri = ctx.join_target(part_rel)
                if ctx.skip_existing and _exists(part_uri):
                    continue
                _write(part_uri, text)
                parts_saved += 1
                if _is_content_part(raw_ppath):
                    final_primary_rel = part_rel
                    final_primary_target = part_uri
                    payload_bytes = len(decoded)

        item_target_written = None
        if ctx.include_raw_definition:
            try:
                _write(item_target_uri, _json.dumps(body, indent=1))
                item_target_written = item_target_uri
            except Exception:
                pass

        return _row_dict(
            ctx=ctx,
            workspace_id=workspace_id, workspace_name=workspace_name,
            item_type=item_type, item_id=item_id, display_name=display_name,
            export_format=export_mode, now=now,
            rel_path=final_primary_rel,
            primary_target=final_primary_target,
            item_json_target=item_target_written,
            part_count=len(parts), parts_saved=parts_saved,
            has_content_part=has_content_part,
            payload_bytes=payload_bytes,
            attempts=attempts, token_refreshes=token_refreshes,
            http_status=http_status,
            status=("ok" if parts_saved > 0 else "skipped_exists"),
            error=(None if has_content_part
                   else "no notebook-content / pipeline-content / "
                        "mashup part in definition"),
        )

    except Exception as e:
        return _row_dict(
            **base_kwargs,
            part_count=len(parts),
            has_content_part=has_content_part,
            status="error",
            error=f"write/decode error: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Row helpers (work for both Spark Row and dict)
# ---------------------------------------------------------------------------


def _row_field(row: Any, name: str, default: Any = None) -> Any:
    """Tolerant getter — works for pyspark.sql.Row, dict, and
    SimpleNamespace test doubles."""
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        pass
    return getattr(row, name, default)


def _emit(d: dict):
    """Convert a row dict to a pyspark.sql.Row in the exact column order
    declared by `MANIFEST_COLUMNS`. Lazy import keeps the module
    importable in pyspark-free environments."""
    from pyspark.sql import Row
    return Row(**{k: d.get(k) for k in MANIFEST_COLUMNS})


# ---------------------------------------------------------------------------
# Spark generator (mapPartitions target)
# ---------------------------------------------------------------------------


def download_partition(
    rows: Iterable[Any], ctx: DownloadContext,
) -> Iterator[Any]:
    """Spark `mapPartitions` target.

    Refreshes the bearer token on the executor (long-running jobs may
    outlast the driver-side token), then fetches all item bodies in the
    partition with bounded concurrency via `fetch_item_definition`. A
    shared mutable token + asyncio.Lock pair gives us single-flight 401
    refresh without tearing down the aiohttp session.
    """
    import asyncio
    import aiohttp

    from ..api.auth import get_token, TokenError
    from ..api.fetch import fetch_item_definition

    materialized = list(rows)
    if not materialized:
        return

    # --- Token bootstrap on the executor ---------------------------------
    try:
        starting_token = get_token(ctx.token_audience)
    except TokenError:
        starting_token = ctx.fallback_token
    if not starting_token:
        now = datetime.now(timezone.utc)
        for r in materialized:
            yield _emit(_row_dict(
                ctx=ctx,
                workspace_id=_row_field(r, "workspace_id", "") or "",
                workspace_name=_row_field(r, "workspace_name", "") or "",
                item_type=_row_field(r, "item_type", "") or "",
                item_id=_row_field(r, "item_id", "") or "",
                display_name=_row_field(r, "display_name", "") or "",
                export_format=ctx.export_mode_for(
                    _row_field(r, "item_type", "") or ""),
                now=now,
                status="error",
                error="no token available on executor",
            ))
        return

    current_token = {"value": starting_token}
    refresh_counter = {"n": 0}

    async def _refresh_token() -> bool:
        async with token_lock:
            try:
                current_token["value"] = get_token(ctx.token_audience)
                refresh_counter["n"] += 1
                return True
            except TokenError:
                return False

    token_lock = asyncio.Lock()

    def _headers() -> dict[str, str]:
        return {"Authorization": f"Bearer {current_token['value']}",
                "Content-Type": "application/json"}

    sem = asyncio.Semaphore(ctx.executor_concurrency)

    async def one(session, wid, wname, itype, iid, name):
        async with sem:
            body, http_status, attempts, err = await fetch_item_definition(
                session, ctx.fabric_base, wid, iid,
                format_hint=ctx.format_for(itype),
                headers_provider=_headers,
                on_unauthorized=_refresh_token,
                max_retries=ctx.max_retries,
            )
            return (wid, wname, itype, iid, name,
                    body, http_status, attempts, err)

    async def run_all():
        connector = aiohttp.TCPConnector(limit=ctx.executor_concurrency * 2)
        timeout = aiohttp.ClientTimeout(total=1200, connect=30)
        async with aiohttp.ClientSession(
                connector=connector, timeout=timeout,
        ) as session:
            tasks = [
                one(session,
                    _row_field(r, "workspace_id", "") or "",
                    _row_field(r, "workspace_name", "") or "",
                    _row_field(r, "item_type", "") or "Notebook",
                    _row_field(r, "item_id", "") or "",
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
    for (wid, wname, itype, iid, name,
         body, http_status, attempts, err) in results:
        d = process_definition_body(
            ctx=ctx,
            workspace_id=wid, workspace_name=wname,
            item_type=itype, item_id=iid, display_name=name,
            body=body, http_status=http_status,
            attempts=attempts,
            token_refreshes=refresh_counter["n"],
            error=err,
            now=now,
        )
        yield _emit(d)
