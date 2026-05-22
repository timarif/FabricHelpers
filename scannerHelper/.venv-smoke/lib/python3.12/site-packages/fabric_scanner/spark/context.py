"""Per-partition execution context.

The legacy `08_mappartitions.py` cell scattered ~15 module-globals
(`_LH_WS_BC`, `_WS_NAME_BY_ID_BC`, `_FABRIC_BASE_BC`, …) that Spark
closure-captured into every executor task. `PartitionContext` collapses
all of that into one frozen dataclass that the runner builds on the
driver and pickles into the closure of `mapPartitions`. The two
partition functions accept it as a parameter — no module-globals, no
build-time string substitution.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartitionContext:
    """Everything the partition functions need to know that they can't
    discover from a row.

    All collections are frozen / hashable so the dataclass is itself
    serializable by Spark's pickler without surprises.
    """
    # Mode: "lakehouse" or "api"
    mode: str

    # Source-lakehouse defaults (constants for every row in lakehouse mode;
    # always blank in API mode).
    source_workspace_id:   str = ""
    source_workspace_name: str = ""
    source_lakehouse_id:   str = ""
    source_lakehouse_name: str = ""

    # ws_dated layout knobs (extracted via regex from each row's path).
    source_layout:   str = "flat"
    ws_dated_base:   str = ""

    # Workspace ID <-> name lookup tables (lowercased keys). Used by:
    #  - URL classification (resolve_dest_workspace)
    #  - ws_dated path extraction (workspace_id -> friendly name)
    #  - attached-lakehouse workspace name backfill
    ws_name_by_id: dict[str, str] = field(default_factory=dict)
    ws_id_by_name: dict[str, str] = field(default_factory=dict)

    # API-mode endpoint config (ignored in lakehouse mode).
    fabric_base:          str = "https://api.fabric.microsoft.com"
    executor_concurrency: int = 16
    max_retries:          int = 4
    token_audience:       str = "https://api.fabric.microsoft.com"
    fallback_token:       str | None = None

    # Engine knobs (passed straight through to scan_notebook_bytes).
    min_severity:              str = "low"
    max_snippet_bytes:         int = 256
    scan_markdown_and_outputs: bool = True


def build_partition_context(
    config,
    resolved,
    workspaces: list[dict] | None = None,
    fallback_token: str | None = None,
) -> PartitionContext:
    """Driver-side factory. Squashes a ScannerConfig + ResolvedPaths +
    workspace list into the immutable PartitionContext the executors
    will see."""
    ws_name_by_id: dict[str, str] = {}
    ws_id_by_name: dict[str, str] = {}
    for w in (workspaces or []):
        wid = (w.get("id") or "").lower()
        name = (w.get("name") or w.get("displayName") or "")
        if wid:
            ws_name_by_id[wid] = name
        if name:
            ws_id_by_name[name.lower()] = wid

    return PartitionContext(
        mode=config.source_mode,
        source_workspace_id=resolved.source_workspace_id or "",
        source_workspace_name=(resolved.source_workspace_name
                               or resolved.source_workspace_id or ""),
        source_lakehouse_id=resolved.source_lakehouse_id or "",
        source_lakehouse_name=(resolved.source_lakehouse_name
                               or resolved.source_lakehouse_id or ""),
        source_layout=config.source_layout,
        ws_dated_base=((resolved.source_uri or "").rstrip("/")
                       if (config.source_mode == "lakehouse"
                           and config.source_layout == "ws_dated"
                           and resolved.source_uri)
                       else ""),
        ws_name_by_id=ws_name_by_id,
        ws_id_by_name=ws_id_by_name,
        fabric_base=config.fabric_base,
        executor_concurrency=config.executor_concurrency,
        max_retries=config.max_retries,
        token_audience=config.token_audience,
        fallback_token=fallback_token,
        min_severity=config.min_severity,
        max_snippet_bytes=config.max_snippet_bytes,
        scan_markdown_and_outputs=config.scan_markdown_and_outputs,
    )
