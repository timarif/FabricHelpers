"""Pytest configuration shared by all unit tests.

Provides a session-scoped `fake_notebookutils` fixture so tests that need to
exercise lakehouse-path enumeration can monkeypatch `notebookutils.fs.ls`
without dragging in pyspark or the Fabric runtime.

Also auto-builds the test fixtures on first run — the secrets fixture is
intentionally not committed (the synthetic tokens would trigger GitHub's
push-protection secret scanner), so `build_fixtures.py` regenerates it
locally before the tests start.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures"
REQUIRED_FIXTURES = (
    "sample_clean.ipynb",
    "sample_secrets.ipynb",
    "sample_cross_workspace.ipynb",
    "sample_attached_lh.ipynb",
)


def _ensure_fixtures() -> None:
    missing = [n for n in REQUIRED_FIXTURES if not (FIXTURE_DIR / n).exists()]
    if not missing:
        return
    builder = FIXTURE_DIR / "build_fixtures.py"
    subprocess.run([sys.executable, str(builder)], check=True)


_ensure_fixtures()


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def load_fixture() -> Callable[[str], bytes]:
    """Return a helper that reads a fixture file as bytes."""
    def _load(name: str) -> bytes:
        return (FIXTURE_DIR / name).read_bytes()
    return _load


@pytest.fixture
def fake_notebookutils(monkeypatch):
    """Install a minimal `notebookutils.fs.ls`-style stub into sys.modules.

    The default returns an empty list. Tests can override `.fs.ls` with
    their own callable to simulate a Lakehouse directory listing.
    """
    fs = SimpleNamespace(ls=lambda path: [])
    mod = SimpleNamespace(fs=fs)
    monkeypatch.setitem(sys.modules, "notebookutils", mod)
    return mod


def make_ipynb(cells: list[dict], metadata: dict | None = None) -> bytes:
    """Build a minimal valid .ipynb document as bytes."""
    nb = {
        "cells": cells,
        "metadata": metadata or {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(nb).encode("utf-8")


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "source": src, "metadata": {},
            "execution_count": None, "outputs": []}


def md_cell(src: str) -> dict:
    return {"cell_type": "markdown", "source": src, "metadata": {}}
