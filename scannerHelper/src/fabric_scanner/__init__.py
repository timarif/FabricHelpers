"""fabric_scanner — audit Fabric notebooks for URLs, secrets, and writes.

Public API (stable from v0.1):

    >>> from fabric_scanner import ScannerConfig, scan_notebook_bytes
    >>> cfg = ScannerConfig(source_mode="lakehouse", source_layout="ws_dated")
    >>> findings = scan_notebook_bytes(open("notebook.ipynb", "rb").read(),
    ...                                "notebook.ipynb")

Spark + Fabric REST support is opt-in:

    >>> from fabric_scanner.spark import run            # requires pyspark
    >>> from fabric_scanner.api  import fetch_partition # requires aiohttp
"""
from .config import ScannerConfig
from .engine.scanner import scan_notebook_bytes
from ._version import __version__

__all__ = ["ScannerConfig", "scan_notebook_bytes", "__version__"]
