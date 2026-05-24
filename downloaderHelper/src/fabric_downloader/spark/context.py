"""Per-partition execution context for the downloader.

Carries everything the executors need that they can't recover from a row:
the resolved write paths, per-type format overrides, Fabric endpoint, and
all retry / concurrency knobs. Frozen dataclass so Spark's pickler doesn't
trip over mutable state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..config import DownloaderConfig
from ..paths import ResolvedPaths


@dataclass(frozen=True)
class DownloadContext:
    """Everything the partition function needs to know that it can't
    discover from a row."""

    # --- Output ----------------------------------------------------------
    lakehouse_mount: str | None
    abfss_files_prefix: str | None
    output_root: str
    run_label: str
    group_by_type: bool
    include_raw_definition: bool
    skip_existing: bool

    # --- Per-type format hints -------------------------------------------
    format_by_type: Mapping[str, str] = field(default_factory=dict)
    notebook_format: str = "py"

    # --- Fabric REST -----------------------------------------------------
    fabric_base:          str = "https://api.fabric.microsoft.com"
    token_audience:       str = "pbi"
    fallback_token:       str | None = None
    executor_concurrency: int = 30
    max_retries:          int = 4

    def format_for(self, item_type: str) -> str | None:
        """Mirror of `DownloaderConfig.format_for` — kept in sync so the
        executor doesn't need a back-reference to the driver-side config."""
        if item_type == "Notebook":
            return "ipynb" if self.notebook_format == "ipynb" else None
        return self.format_by_type.get(item_type)

    def export_mode_for(self, item_type: str) -> str:
        """Mirror of `DownloaderConfig.export_mode_for`."""
        if item_type == "Notebook":
            return self.notebook_format
        return ("ipynb" if self.format_by_type.get(item_type) == "ipynb"
                else "parts")

    def join_target(self, rel_path: str) -> str:
        rel = (rel_path or "").lstrip("/")
        if self.lakehouse_mount is not None:
            return f"{self.lakehouse_mount}/{rel}"
        assert self.abfss_files_prefix is not None
        return f"{self.abfss_files_prefix}/{rel}"


def build_download_context(
    config: DownloaderConfig,
    resolved: ResolvedPaths,
    *,
    fallback_token: str | None = None,
) -> DownloadContext:
    """Driver-side factory. Squashes a DownloaderConfig + ResolvedPaths
    into the immutable DownloadContext the executors will see."""
    return DownloadContext(
        lakehouse_mount=resolved.lakehouse_mount,
        abfss_files_prefix=resolved.abfss_files_prefix,
        output_root=resolved.output_root,
        run_label=resolved.run_label,
        group_by_type=config.group_by_type,
        include_raw_definition=config.include_raw_definition,
        skip_existing=config.skip_existing,
        format_by_type=dict(config.format_by_type),
        notebook_format=config.notebook_format,
        fabric_base=config.fabric_base,
        token_audience=config.token_audience,
        fallback_token=fallback_token,
        executor_concurrency=config.executor_concurrency,
        max_retries=config.max_retries,
    )
