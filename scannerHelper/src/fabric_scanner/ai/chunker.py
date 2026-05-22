"""Notebook content chunker for the AI auditor.

Splits a list of extracted code blocks (one per notebook cell) into
~`max_chars`-sized chunks for the AI model. Strategy:

1. Walk the blocks in order. Maintain a running buffer of joined cells.
2. When the buffer + next cell would exceed `max_chars`, flush the buffer
   as one chunk and start a new one with the current cell.
3. If a single cell is larger than `max_chars`, split it at the nearest
   line boundary inside the limit (or hard-cut as a last resort).

This is dramatically better than naive char-count splitting because it
keeps each cell's read/write logic together in a single AI request,
which is exactly the context the model needs to detect dataflow risk.

The function is pure Python and has no Spark dependency — it runs inside
the executor as part of the mapPartitions step.
"""
from __future__ import annotations

from collections.abc import Iterable

# String used to mark cell boundaries inside a chunk so the AI can see
# where one cell ends and the next begins. Same marker NotebookAudit used.
CELL_BOUNDARY = "\n\n# --- cell boundary ---\n\n"


def _split_oversized_cell(text: str, max_chars: int) -> list[str]:
    """Split a single cell that is itself larger than max_chars.

    Prefer line boundaries; hard-cut a single oversized line if there
    is no line break inside the window. Returns a list of pieces, each
    <= max_chars in length.
    """
    if max_chars <= 0:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # Find the last newline at or before max_chars
        cut = remaining.rfind("\n", 0, max_chars)
        if cut <= 0:
            # No newline in the window — hard cut.
            cut = max_chars
        pieces.append(remaining[:cut])
        # Skip the newline we cut on (if any) to avoid leading blank line.
        if cut < len(remaining) and remaining[cut] == "\n":
            remaining = remaining[cut + 1:]
        else:
            remaining = remaining[cut:]
    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_blocks(
    blocks: Iterable[str],
    max_chars: int = 14000,
    *,
    min_chunk_chars: int = 0,
    boundary: str = CELL_BOUNDARY,
) -> list[str]:
    """Pack cell text blocks into chunks of up to `max_chars` characters.

    Parameters
    ----------
    blocks :
        Iterable of cell text (strings). Empty strings are skipped.
    max_chars :
        Hard upper bound on the length of each returned chunk.
    min_chunk_chars :
        Optional lower bound. Chunks smaller than this are still emitted
        if they are the only chunk from a notebook (we never drop the
        last chunk). Default 0 = no minimum.
    boundary :
        Separator inserted between cells inside the same chunk.

    Returns
    -------
    list[str]
        Chunks in source order. Always at least one chunk when the input
        has any non-empty block; returns `[]` when input is all empty.
    """
    if max_chars <= 0:
        raise ValueError(f"max_chars must be > 0 (got {max_chars})")

    cells = [b for b in blocks if b]
    if not cells:
        return []

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    def _flush():
        nonlocal cur, cur_len
        if not cur:
            return
        chunks.append(boundary.join(cur))
        cur = []
        cur_len = 0

    for cell in cells:
        # Oversized single cell — split it and treat each piece as its
        # own block of work.
        if len(cell) > max_chars:
            _flush()
            for piece in _split_oversized_cell(cell, max_chars):
                if not piece:
                    continue
                chunks.append(piece)
            continue

        sep_len = len(boundary) if cur else 0
        added_len = sep_len + len(cell)
        if cur and cur_len + added_len > max_chars:
            _flush()
            cur = [cell]
            cur_len = len(cell)
        else:
            cur.append(cell)
            cur_len += added_len

    _flush()

    # min_chunk_chars: merge tiny trailing chunks into the previous one
    # when possible (still respecting max_chars). The first chunk is
    # never dropped even if it's below the minimum.
    if min_chunk_chars > 0 and len(chunks) > 1:
        merged: list[str] = [chunks[0]]
        for c in chunks[1:]:
            if (len(c) < min_chunk_chars
                    and len(merged[-1]) + len(boundary) + len(c) <= max_chars):
                merged[-1] = merged[-1] + boundary + c
            else:
                merged.append(c)
        chunks = merged

    return chunks


def chunk_text(text: str, max_chars: int = 14000) -> list[str]:
    """Convenience wrapper: treat `text` as a single block and chunk it.

    Useful when the caller already concatenated cells (e.g., reading a
    plain .py file) and only needs the chunking behavior.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    return _split_oversized_cell(text, max_chars)
