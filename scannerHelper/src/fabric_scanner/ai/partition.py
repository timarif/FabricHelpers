"""Spark `mapPartitions` glue for the AI auditor.

`build_chunk_rows(rows_iter, ctx)` is a generator that takes the
inventory `scan_df` rows (`path, content, workspace_id,
source_dated_partition, source_lakehouse_*` already populated) and yields
one chunk-row per (notebook, chunk_index) — with the four
`attached_lakehouse_*` columns enriched and the cell-boundary-aware
chunker applied.

Mirror of `spark.partition.scan_partition_lakehouse`: same input shape,
same Spark contract, different downstream output. The pure-Python
`chunk_notebook(path, content, ctx)` helper is used directly in tests
without Spark.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from typing import Any

from ..engine.enrich import enrich_attached_lakehouse
from ..engine.extract import extract_blocks
from .chunker import chunk_blocks
from .schema import AI_CHUNK_PRE_AI_COLUMNS


def _row_field(row: Any, name: str, default: Any = None) -> Any:
    """Tolerant getter — works for pyspark.sql.Row, dict, and
    SimpleNamespace test doubles."""
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        pass
    return getattr(row, name, default)


def _content_hash(text: str) -> str:
    """Short stable hash of the extracted notebook text.

    Used as both a cache key for resume semantics (future v2) and as
    additional precision on the join key when display_names collide.
    """
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def chunk_notebook(
    path: str,
    content: bytes,
    ctx: dict,
    *,
    max_chars: int,
    min_chunk_chars: int = 0,
) -> list[dict]:
    """Pure-Python: turn one notebook's bytes into a list of chunk-row dicts.

    `ctx` is a small dict (not the rule-based PartitionContext — keeping
    the AI partition lightweight) containing:
      - workspace_id, workspace_name, source_lakehouse_id,
        source_lakehouse_name, source_dated_partition
      - ws_name_by_id : Mapping[str, str] for attached-LH name backfill

    Returns one row dict per chunk. Returns an empty list when the
    notebook has no extractable code blocks (caller should treat as a
    "no chunks" outcome).
    """
    nb_id = path or ""
    nb_name = (path or "").rsplit("/", 1)[-1]

    try:
        blocks_raw = extract_blocks(content or b"", path or "",
                                    include_md_and_outputs=False)
    except Exception:
        return []

    code_texts = [b[0] for b in blocks_raw if b and b[0]]

    try:
        chunks = chunk_blocks(code_texts, max_chars=max_chars,
                              min_chunk_chars=min_chunk_chars)
    except Exception:
        return []

    if not chunks:
        return []

    full_text = "\n\n# --- cell boundary ---\n\n".join(code_texts)
    content_length = len(full_text)
    content_hash = _content_hash(full_text)

    # Enrich attached lakehouse columns once per notebook.
    try:
        lh = enrich_attached_lakehouse(content or b"", path or "",
                                       ctx.get("ws_name_by_id") or {})
    except Exception:
        lh = {
            "attached_lakehouse_id": None,
            "attached_lakehouse_name": None,
            "attached_lakehouse_workspace_id": None,
            "attached_lakehouse_workspace_name": None,
        }

    n = len(chunks)
    out: list[dict] = []
    for i, chunk in enumerate(chunks):
        out.append({
            "workspace_id":                     ctx.get("workspace_id") or None,
            "workspace_name":                   ctx.get("workspace_name") or None,
            "source_lakehouse_id":              ctx.get("source_lakehouse_id") or None,
            "source_lakehouse_name":            ctx.get("source_lakehouse_name") or None,
            "source_dated_partition":           ctx.get("source_dated_partition") or None,
            "notebook_id":                      nb_id or None,
            "display_name":                     nb_name or None,
            "attached_lakehouse_id":            lh.get("attached_lakehouse_id"),
            "attached_lakehouse_name":          lh.get("attached_lakehouse_name"),
            "attached_lakehouse_workspace_id":  lh.get("attached_lakehouse_workspace_id"),
            "attached_lakehouse_workspace_name": lh.get("attached_lakehouse_workspace_name"),
            "content_length":                   content_length,
            "content_hash":                     content_hash,
            "chunk_index":                      i,
            "chunk_count":                      n,
            "chunk_text":                       chunk,
        })
    return out


def build_chunk_rows(
    rows: Iterable[Any],
    ctx_fn,
    *,
    max_chars: int,
    min_chunk_chars: int = 0,
) -> Iterator[Any]:
    """Spark `mapPartitions` target for the AI auditor.

    `ctx_fn(row) -> dict` extracts per-row context (workspace_id,
    source_lakehouse_*, source_dated_partition) from the inventory Row,
    plus the `ws_name_by_id` lookup. The function shape avoids closing
    over a heavy PartitionContext when we don't need one.
    """
    from pyspark.sql import Row

    cols = AI_CHUNK_PRE_AI_COLUMNS
    for r in rows:
        path = _row_field(r, "path", "") or ""
        content = _row_field(r, "content", b"") or b""
        ctx = ctx_fn(r) or {}
        for d in chunk_notebook(path, content, ctx,
                                max_chars=max_chars,
                                min_chunk_chars=min_chunk_chars):
            yield Row(**{k: d.get(k) for k in cols})
