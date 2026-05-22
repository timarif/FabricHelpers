"""Spark + Fabric REST integration layer for `fabric_scanner`.

Optional subpackage. Importing it from a pure-Python install will fail at
the `pyspark` import in `runner.py`; install with `pip install
fabric-scanner[spark]` (or `[spark,api]`) to enable.
"""
from .runner import run, ScannerResult

__all__ = ["run", "ScannerResult"]
