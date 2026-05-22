"""fabric_scanner — audit Fabric notebooks for URLs, secrets, and writes.

Public API (stable from v0.1):

    >>> from fabric_scanner import ScannerConfig, scan_notebook_bytes
    >>> cfg = ScannerConfig(source_mode="lakehouse", source_layout="ws_dated")
    >>> findings = scan_notebook_bytes(open("notebook.ipynb", "rb").read(),
    ...                                "notebook.ipynb")

Phase 2 adds Lakehouse path resolution + source diagnostics:

    >>> from fabric_scanner import resolve_paths, probe
    >>> rp = resolve_paths(cfg)
    >>> probe(cfg, rp, token=None)            # lakehouse mode

Spark + Fabric REST support is opt-in:

    >>> from fabric_scanner.spark import run            # requires pyspark
    >>> from fabric_scanner.api  import fetch_notebook_definition  # aiohttp
"""
from .config import ScannerConfig
from .engine.scanner import scan_notebook_bytes
from .paths import resolve_paths, ResolvedPaths
from .diagnostics import probe
from ._version import __version__

__all__ = [
    "ScannerConfig",
    "scan_notebook_bytes",
    "resolve_paths",
    "ResolvedPaths",
    "probe",
    "__version__",
]

