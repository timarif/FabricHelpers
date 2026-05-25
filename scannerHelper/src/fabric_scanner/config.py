"""User-facing configuration for the Fabric notebook scanner.

`ScannerConfig` is a frozen dataclass — every knob lives here and the rest of
the package threads it through unchanged. Defaults match the post-v0.1
behavior of the legacy `_v2_cells/01_config.py` so a no-arg construction
produces a sensible API-mode scan.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal


SeverityLevel = Literal["low", "medium", "high", "critical"]
SourceMode    = Literal["api", "lakehouse"]
SourceLayout  = Literal["flat", "ws_dated"]


@dataclass(frozen=True)
class ScannerConfig:
    # --- Where to read notebooks from -------------------------------------
    source_mode: SourceMode = "api"

    # API-mode knobs
    admin_mode: bool = False
    read_workspace_ids: tuple[str, ...] = field(default_factory=tuple)
    fabric_base: str = "https://api.fabric.microsoft.com"
    pbi_base:    str = "https://api.powerbi.com"
    token_audience: str = "https://api.fabric.microsoft.com"
    executor_concurrency: int = 16
    max_retries: int = 4

    # Lakehouse-mode knobs (leave blank to auto-detect mounted LH)
    source_lakehouse_workspace_id:   str = ""
    source_lakehouse_workspace_name: str = ""
    source_lakehouse_id:             str = ""
    source_lakehouse_name:           str = ""
    source_subpath:                  str = "Files/notebooks"
    source_file_glob:                str = "*.ipynb"
    source_layout:                   SourceLayout = "flat"

    # --- Where to write outputs -------------------------------------------
    write_to_default_lakehouse: bool = True
    write_workspace_id: str = ""
    write_lakehouse_id: str = ""
    write_schema: str | None = None
    inventory_table: str = "v2_inventory"
    output_table:    str = "v2_findings"

    # --- Shared reporting lakehouse (opt-in, default off) -----------------
    # When set, the runner writes fact_scan_findings rows to the shared
    # reporting lakehouse via fabric_reporting.ReportingAdapter after the
    # scan completes.  Requires the fabric-reporting package to be installed.
    reporting_lakehouse: str = ""

    # --- Scanning behavior -------------------------------------------------
    min_severity: SeverityLevel = "low"
    scan_markdown_and_outputs: bool = True
    max_snippet_bytes: int = 256
    max_notebooks: int = 0       # 0 = no cap (test-mode helper)
    target_partition_size: int = 200

    # ----------------------------------------------------------------------
    def __post_init__(self) -> None:
        if self.source_mode not in ("api", "lakehouse"):
            raise ValueError(f"source_mode must be 'api' or 'lakehouse', got "
                             f"{self.source_mode!r}")
        if self.source_layout not in ("flat", "ws_dated"):
            raise ValueError(f"source_layout must be 'flat' or 'ws_dated', "
                             f"got {self.source_layout!r}")
        if self.min_severity not in ("low", "medium", "high", "critical"):
            raise ValueError(f"min_severity must be one of "
                             f"low|medium|high|critical, got "
                             f"{self.min_severity!r}")
        if self.executor_concurrency < 1:
            raise ValueError("executor_concurrency must be >= 1")
        if self.target_partition_size < 1:
            raise ValueError("target_partition_size must be >= 1")
        if self.max_snippet_bytes < 16:
            raise ValueError("max_snippet_bytes must be >= 16")

    @classmethod
    def from_dict(cls, d: dict) -> "ScannerConfig":
        """Build a config from a plain dict (e.g. JSON-loaded notebook params).
        Unknown keys raise TypeError so typos show up loudly."""
        valid = {f.name for f in fields(cls)}
        unknown = set(d) - valid
        if unknown:
            raise TypeError(f"Unknown ScannerConfig fields: {sorted(unknown)}")
        return cls(**d)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}
