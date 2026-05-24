"""fabric_downloader — back up Fabric notebooks, pipelines, dataflows, and
more from a tenant to a Lakehouse.

Public API (stable from v0.1):

    >>> from fabric_downloader import DownloaderConfig, resolve_paths, probe
    >>> cfg = DownloaderConfig(item_types=("Notebook", "DataPipeline"))
    >>> resolved = resolve_paths(cfg)
    >>> probe(cfg, resolved, token=None)            # add token for API probe

    >>> from fabric_downloader.spark import run     # requires pyspark
    >>> result = run(cfg, spark)
    >>> result.summary.by_status.show()

The Spark + Fabric REST helpers are opt-in via the `[spark]` / `[api]`
extras so the engine half of the package imports cleanly in any Python
environment (laptops, CI, lightweight Fabric kernels).

Item-type registry (v0.4+):

    >>> from fabric_downloader.item_types import REGISTRY
    >>> list(REGISTRY.keys())

    Import ``fabric_downloader.handlers`` to auto-register all built-in
    handlers; the CLI does this automatically.
"""
from .config import DownloaderConfig
from .paths import ResolvedPaths, resolve_paths, safe_segment
from .diagnostics import probe
from ._version import __version__

__all__ = [
    "DownloaderConfig",
    "ResolvedPaths",
    "resolve_paths",
    "safe_segment",
    "probe",
    "__version__",
]
