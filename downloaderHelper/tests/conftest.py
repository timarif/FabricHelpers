"""Shared pytest fixtures for fabric_downloader unit tests.

We deliberately avoid spinning up a Spark session — every test in
`tests/unit/` exercises a pure-Python helper. A `fake_notebookutils`
fixture is provided so the `paths.fs_ls` codepath can be exercised
without the Fabric runtime.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def fake_notebookutils(monkeypatch):
    """Install a minimal `notebookutils.fs.{ls,put,exists}` stub.

    Tests can swap `mod.fs.X` for their own callables to simulate
    Lakehouse listings, writes, and existence checks without dragging
    in the real runtime.
    """
    writes: list[tuple[str, str, bool]] = []
    existing: set[str] = set()

    def _put(uri, text, overwrite=True):
        writes.append((uri, text, overwrite))

    def _exists(uri):
        return uri in existing

    fs = SimpleNamespace(
        ls=lambda path: [],
        put=_put,
        exists=_exists,
    )
    mod = SimpleNamespace(
        fs=fs,
        runtime=SimpleNamespace(context={}),
        credentials=SimpleNamespace(getToken=lambda audience: None),
    )
    monkeypatch.setitem(sys.modules, "notebookutils", mod)
    # expose collected state for assertions
    mod._writes = writes  # type: ignore[attr-defined]
    mod._existing = existing  # type: ignore[attr-defined]
    return mod
