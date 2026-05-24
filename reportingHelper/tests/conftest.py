"""Pytest configuration for reportingHelper tests.

Provides a session-scoped ``spark`` fixture for tests that exercise the
Spark + Delta integration.  Mirrors the fixture in
``scannerHelper/tests/conftest.py``.
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture(scope="session")
def spark():
    """Local SparkSession for integration tests.

    Skipped when:
      - pyspark is not installed (typical CI without the ``spark`` extra), OR
      - SparkSession startup fails (no JDK, broken winutils, etc.), OR
      - A trivial collect() fails (Python worker mis-spawn).
    """
    pyspark = pytest.importorskip("pyspark")
    import os
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    try:
        from pyspark.sql import SparkSession
        s = (SparkSession.builder
             .appName("fabric_reporting-tests")
             .master("local[2]")
             .config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "2")
             .getOrCreate())
        s.createDataFrame([(1,)], ["x"]).collect()
    except Exception as e:
        pytest.skip(f"SparkSession not runnable in this environment: {e}")
    yield s
    s.stop()
