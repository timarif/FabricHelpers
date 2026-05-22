"""Spark + Fabric REST integration layer for `fabric_downloader`.

Optional subpackage. Importing it from a pure-Python install will fail at
the `pyspark` import in `runner.py`; install with `pip install
fabric-downloader[spark]` (or `[spark,api]`) to enable.
"""
from .runner import run, DownloaderResult

__all__ = ["run", "DownloaderResult"]
