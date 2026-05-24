"""Tests for ai.partition — the pure-Python chunk_notebook helper.

Spark-based `build_chunk_rows` is not tested here (requires SparkSession);
the equivalent driver-side logic is covered by `chunk_notebook` which is
called directly by `build_chunk_rows` per row.
"""
from __future__ import annotations

import json

import pytest

from fabric_scanner.ai.partition import _content_hash, chunk_notebook

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


def _ctx(**overrides):
    base = dict(
        workspace_id=WS_A,
        workspace_name="Alpha",
        source_lakehouse_id="33333333-3333-3333-3333-333333333333",
        source_lakehouse_name="Bronze",
        source_dated_partition="20260522",
        ws_name_by_id={WS_A.lower(): "Alpha", WS_B.lower(): "Beta"},
    )
    base.update(overrides)
    return base


def _nb(cells):
    return json.dumps({
        "cells": cells, "metadata": {},
        "nbformat": 4, "nbformat_minor": 5,
    }).encode("utf-8")


def _code(src):
    return {"cell_type": "code", "source": src, "metadata": {},
            "execution_count": None, "outputs": []}


# --- happy path ------------------------------------------------------------

def test_chunk_notebook_emits_one_chunk_per_small_notebook():
    nb = _nb([_code("print(1)"), _code("print(2)")])
    rows = chunk_notebook("/folder/n.ipynb", nb, _ctx(),
                          max_chars=10_000)
    assert len(rows) == 1
    r = rows[0]
    assert r["notebook_id"] == "/folder/n.ipynb"
    assert r["display_name"] == "n.ipynb"
    assert r["workspace_id"] == WS_A
    assert r["workspace_name"] == "Alpha"
    assert r["source_lakehouse_id"].startswith("33333333")
    assert r["source_dated_partition"] == "20260522"
    assert r["chunk_index"] == 0
    assert r["chunk_count"] == 1
    assert "print(1)" in r["chunk_text"]
    assert "print(2)" in r["chunk_text"]


def test_chunk_notebook_emits_provenance_per_chunk_row():
    nb = _nb([_code("a" * 3000), _code("b" * 3000), _code("c" * 3000)])
    rows = chunk_notebook("/x/big.ipynb", nb, _ctx(),
                          max_chars=4000)
    assert len(rows) >= 2
    # Same notebook_id / workspace_id / hash across all chunks
    ids = {r["notebook_id"] for r in rows}
    hashes = {r["content_hash"] for r in rows}
    counts = {r["chunk_count"] for r in rows}
    assert ids == {"/x/big.ipynb"}
    assert len(hashes) == 1
    assert len(counts) == 1
    # chunk_count == len(rows)
    assert counts.pop() == len(rows)
    # chunk_index runs 0..n-1
    indices = sorted(r["chunk_index"] for r in rows)
    assert indices == list(range(len(rows)))


def test_chunk_notebook_includes_attached_lakehouse_metadata():
    nb = _nb([_code("# tiny")])
    nb_obj = json.loads(nb.decode())
    nb_obj["metadata"] = {
        "dependencies": {
            "lakehouse": {
                "default_lakehouse": "lh-abc",
                "default_lakehouse_name": "MyLH",
                "default_lakehouse_workspace_id": WS_B,
            }
        }
    }
    nb2 = json.dumps(nb_obj).encode("utf-8")
    rows = chunk_notebook("/p/n.ipynb", nb2, _ctx(),
                          max_chars=10_000)
    assert len(rows) == 1
    r = rows[0]
    assert r["attached_lakehouse_id"] == "lh-abc"
    assert r["attached_lakehouse_name"] == "MyLH"
    assert r["attached_lakehouse_workspace_id"] == WS_B
    assert r["attached_lakehouse_workspace_name"] == "Beta"


def test_chunk_notebook_empty_notebook_returns_empty_list():
    rows = chunk_notebook("/p/empty.ipynb",
                          _nb([_code("")]), _ctx(),
                          max_chars=10_000)
    assert rows == []


def test_chunk_notebook_completely_blank_content_returns_empty_list():
    rows = chunk_notebook("/p/x.ipynb", b"", _ctx(), max_chars=10_000)
    assert rows == []


def test_chunk_notebook_handles_unparseable_bytes_gracefully():
    # Unparseable bytes are treated by extract_blocks as plain source
    # (so a Fabric `.py`-exported notebook works). Either no-rows or a
    # single chunk is acceptable; both indicate we didn't crash.
    rows = chunk_notebook("/p/junk.ipynb", b"not a notebook",
                          _ctx(), max_chars=10_000)
    assert isinstance(rows, list)
    assert len(rows) <= 1


def test_chunk_notebook_basename_from_path():
    nb = _nb([_code("x = 1")])
    rows = chunk_notebook(
        "abfss://lh@onelake.dfs.fabric.microsoft.com/Files/exports/ws-1/2026/notebook_x.ipynb",
        nb, _ctx(), max_chars=10_000)
    assert rows[0]["display_name"] == "notebook_x.ipynb"


def test_chunk_notebook_content_length_matches_joined_text():
    nb = _nb([_code("aaaa"), _code("bbbb")])
    rows = chunk_notebook("/p.ipynb", nb, _ctx(), max_chars=10_000)
    # Single chunk: content_length is len(joined) using CELL_BOUNDARY.
    boundary = "\n\n# --- cell boundary ---\n\n"
    expected = len("aaaa" + boundary + "bbbb")
    assert rows[0]["content_length"] == expected


# --- _content_hash --------------------------------------------------------

def test_content_hash_stable_and_short():
    h1 = _content_hash("hello world")
    h2 = _content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 16


def test_content_hash_empty_returns_empty_string():
    assert _content_hash("") == ""
    assert _content_hash(None) == ""


def test_content_hash_changes_with_content():
    assert _content_hash("a") != _content_hash("b")


# --- _row_field defensive lookup -----------------------------------------

class _FakeRow:
    """Mimics `pyspark.sql.Row.__getitem__` semantics: looking up a missing
    str key raises `ValueError` (the Row impl does `__fields__.index(k)`,
    which is `list.index`'s native exception)."""
    def __init__(self, **fields):
        self._fields = fields

    def __getitem__(self, key):
        try:
            return self._fields[key]
        except KeyError:
            raise ValueError(f"{key!r} is not in list")

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError as e:
            raise AttributeError(name) from e


def test_row_field_returns_default_on_missing_field_via_valueerror():
    """Regression for the AI auditor `'workspace_id' is not in list` crash.

    `pyspark.sql.Row[str]` raises ValueError (not KeyError) when the
    field is missing; `_row_field` must catch that and fall through to
    the `getattr` fallback / default rather than propagating the error.
    """
    from fabric_scanner.ai.partition import _row_field
    row = _FakeRow(path="/x/y.ipynb", content=b"...")
    assert _row_field(row, "workspace_id", "DEFAULT") == "DEFAULT"
    assert _row_field(row, "source_dated_partition", None) is None


def test_row_field_returns_value_when_present():
    from fabric_scanner.ai.partition import _row_field
    row = _FakeRow(workspace_id="ws-1", path="/x")
    assert _row_field(row, "workspace_id", "DEFAULT") == "ws-1"
    assert _row_field(row, "path", "") == "/x"


def test_row_field_with_real_pyspark_row_missing_field():
    """Smoke test against the actual pyspark.sql.Row class, which is the
    source of the ValueError we're defending against."""
    pyspark = pytest.importorskip("pyspark")  # noqa: F841
    from pyspark.sql import Row
    from fabric_scanner.ai.partition import _row_field
    row = Row(path="/x", content=b"...")
    assert _row_field(row, "workspace_id", "DEFAULT") == "DEFAULT"
