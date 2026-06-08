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
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture(scope="session")
def spark():
    """Local SparkSession for tests that exercise Spark SQL expressions.

    Skipped when:
      - pyspark is not installed (typical CI without the `spark` extra), OR
      - SparkSession startup fails (no JDK, broken winutils, etc.), OR
      - A trivial collect() fails (Python worker mis-spawn — common on
        Windows + Python 3.12).
    """
    pytest.importorskip("pyspark")
    import os
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    try:
        from pyspark.sql import SparkSession
        builder = (SparkSession.builder
                   .appName("fabric_scanner-tests")
                   .master("local[2]")
                   .config("spark.ui.enabled", "false")
                   .config("spark.sql.shuffle.partitions", "2"))
        try:
            from delta import configure_spark_with_delta_pip
        except Exception:
            pass
        else:
            builder = (builder
                       .config(
                           "spark.sql.extensions",
                           "io.delta.sql.DeltaSparkSessionExtension",
                       )
                       .config(
                           "spark.sql.catalog.spark_catalog",
                           "org.apache.spark.sql.delta.catalog.DeltaCatalog",
                       ))
            builder = configure_spark_with_delta_pip(builder)
        s = builder.getOrCreate()
        # Smoke-test the Python worker pathway — `createDataFrame` from
        # a Python list spawns a Python worker, which is exactly what
        # fails on a broken JDK/winutils install. If it doesn't work,
        # skip rather than fail every Spark-dependent test.
        s.createDataFrame([(1,)], ["x"]).collect()
    except Exception as e:
        pytest.skip(f"SparkSession not runnable in this environment: {e}")
    yield s
    s.stop()


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
