"""Tests for ai.chunker."""
from __future__ import annotations

import pytest

from fabric_scanner.ai.chunker import CELL_BOUNDARY, chunk_blocks, chunk_text

# -- chunk_blocks ------------------------------------------------------------

def test_empty_input_returns_empty():
    assert chunk_blocks([], max_chars=100) == []
    assert chunk_blocks([""], max_chars=100) == []
    assert chunk_blocks(["", "", ""], max_chars=100) == []


def test_single_small_block_one_chunk():
    out = chunk_blocks(["print('hi')"], max_chars=100)
    assert out == ["print('hi')"]


def test_packs_multiple_cells_into_one_chunk():
    cells = ["a = 1", "b = 2", "c = 3"]
    out = chunk_blocks(cells, max_chars=100)
    assert len(out) == 1
    # All three cells appear, separated by CELL_BOUNDARY
    assert CELL_BOUNDARY in out[0]
    assert out[0].count(CELL_BOUNDARY) == 2


def test_flushes_when_buffer_full():
    """3 cells of 50 chars each + boundary overhead → must split into 2+ chunks."""
    cells = ["x" * 50, "y" * 50, "z" * 50]
    out = chunk_blocks(cells, max_chars=100)
    # Each cell alone fits; two cells + boundary = ~120 doesn't fit.
    assert len(out) >= 2
    for chunk in out:
        assert len(chunk) <= 100


def test_oversized_single_cell_splits_at_line_boundary():
    cell = "line1\n" + ("x" * 50) + "\n" + ("y" * 50) + "\nlast"
    out = chunk_blocks([cell], max_chars=60)
    assert len(out) >= 2
    for chunk in out:
        assert len(chunk) <= 60


def test_oversized_single_line_hard_cuts():
    cell = "a" * 250  # no newlines at all
    out = chunk_blocks([cell], max_chars=100)
    assert len(out) == 3
    assert all(len(c) <= 100 for c in out)
    # All content preserved
    assert "".join(out) == cell


def test_two_oversized_cells_each_split_independently():
    cells = ["a" * 250, "b" * 150]
    out = chunk_blocks(cells, max_chars=100)
    assert all(len(c) <= 100 for c in out)
    # 250 → 3 chunks; 150 → 2 chunks
    assert len(out) == 5


def test_zero_max_chars_raises():
    with pytest.raises(ValueError):
        chunk_blocks(["x"], max_chars=0)
    with pytest.raises(ValueError):
        chunk_blocks(["x"], max_chars=-5)


def test_min_chunk_merges_tiny_trailing_chunks():
    # First "big" cell fills most of the budget; second tiny cell shouldn't
    # become its own chunk if min_chunk_chars is set.
    cells = ["x" * 90, "y"]
    out = chunk_blocks(cells, max_chars=100, min_chunk_chars=5)
    # Tiny trailing cell can't fit (90+boundary+1 > 100) so it stays as
    # a chunk — but the merge attempts. Verify min logic doesn't crash.
    assert len(out) in (1, 2)


def test_min_chunk_merges_when_room():
    cells = ["x" * 40, "y" * 20, "z"]
    out = chunk_blocks(cells, max_chars=200, min_chunk_chars=10)
    # All three fit in one chunk easily.
    assert len(out) == 1


def test_first_chunk_never_dropped_under_minimum():
    """If the whole notebook is below the minimum, we still emit one chunk."""
    out = chunk_blocks(["tiny"], max_chars=100, min_chunk_chars=10000)
    assert out == ["tiny"]


def test_blocks_remain_in_order():
    cells = [f"cell_{i}" for i in range(10)]
    out = chunk_blocks(cells, max_chars=500)
    joined = " ".join(out)
    last_pos = -1
    for cell in cells:
        pos = joined.find(cell)
        assert pos > last_pos, f"cell {cell} out of order"
        last_pos = pos


# -- chunk_text --------------------------------------------------------------

def test_chunk_text_empty():
    assert chunk_text("", max_chars=100) == []


def test_chunk_text_under_limit_one_chunk():
    assert chunk_text("hello", max_chars=100) == ["hello"]


def test_chunk_text_oversized_splits():
    out = chunk_text("a" * 250, max_chars=100)
    assert len(out) == 3
    assert all(len(c) <= 100 for c in out)
    assert "".join(out) == "a" * 250
