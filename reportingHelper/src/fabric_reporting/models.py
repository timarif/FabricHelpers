"""Pydantic v2 row models for every canonical reporting table.

Each model represents one row in the corresponding Delta table and is
used by ``ReportingAdapter.write_facts`` for client-side validation
before any data touches Delta.

Schema reference: ``SCHEMA.md`` (in the root of ``reportingHelper/``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Fact tables
# ---------------------------------------------------------------------------

class FactScanFinding(BaseModel):
    """One finding emitted by ``scannerHelper`` (``fact_scan_findings``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    """Stable unique identifier for this finding (UUID4 recommended)."""
    scan_run_id: Optional[str] = None
    """Identifier of the scanner run that produced this finding."""
    workspace_id: Optional[str] = None
    """Fabric workspace GUID where the notebook lives."""
    source_dated_partition: Optional[str] = None
    """``ws_dated`` partition label (e.g. ``2024-01-15``)."""
    notebook_id: Optional[str] = None
    """Fabric notebook item GUID."""
    severity: Optional[Literal["low", "medium", "high", "critical"]] = None
    """Finding severity level."""
    kind: Optional[str] = None
    """Finding type / category (e.g. ``url``, ``entropy``, ``potential_write``)."""
    redacted_snippet: Optional[str] = None
    """Short code snippet with sensitive values redacted."""
    url: Optional[str] = None
    """URL found in the notebook, if applicable."""
    detected_at: Optional[datetime] = None
    """UTC timestamp when the finding was detected."""


class FactDownload(BaseModel):
    """One downloaded artifact emitted by ``downloaderHelper`` (``fact_downloads``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    download_id: str
    """Stable unique identifier for this download record (UUID4 recommended)."""
    run_id: Optional[str] = None
    """Downloader run identifier."""
    workspace_id: Optional[str] = None
    """Fabric workspace GUID."""
    item_id: Optional[str] = None
    """Fabric item GUID."""
    item_type: Optional[str] = None
    """Fabric item type (e.g. ``Notebook``, ``Pipeline``, ``Dataflow``)."""
    format: Optional[str] = None
    """Download format (e.g. ``ipynb``, ``json``)."""
    downloaded_at: Optional[datetime] = None
    """UTC timestamp of the download."""
    bytes: Optional[int] = None
    """Artifact size in bytes."""
    sha256: Optional[str] = None
    """SHA-256 hex digest of the downloaded content."""

    @field_validator("bytes")
    @classmethod
    def _bytes_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("bytes must be >= 0")
        return v


class FactMpeLifecycle(BaseModel):
    """One MPE lifecycle event emitted by ``mpeHelper`` (``fact_mpe_lifecycle``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    """Stable unique identifier for this lifecycle event (UUID4 recommended)."""
    workspace_id: Optional[str] = None
    """Fabric workspace GUID where the MPE was managed."""
    mpe_id: Optional[str] = None
    """Managed Private Endpoint GUID."""
    target_resource_id: Optional[str] = None
    """Azure resource ID of the MPE target."""
    action: Optional[Literal["created", "deleted", "approved"]] = None
    """Lifecycle action performed on the MPE."""
    actor: Optional[str] = None
    """Identity (UPN or object ID) that performed the action."""
    timestamp: Optional[datetime] = None
    """UTC timestamp of the lifecycle event."""


# ---------------------------------------------------------------------------
# Dimension tables
# ---------------------------------------------------------------------------

class DimWorkspace(BaseModel):
    """Workspace dimension record (``dim_workspace``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    """Fabric workspace GUID (primary key)."""
    workspace_name: Optional[str] = None
    """Human-readable workspace display name."""
    capacity_id: Optional[str] = None
    """Fabric capacity GUID the workspace is assigned to."""
    last_seen: Optional[datetime] = None
    """UTC timestamp when this workspace was last observed."""


class DimItemType(BaseModel):
    """Item-type dimension record (``dim_item_type``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_type: str
    """Fabric item type string (primary key), e.g. ``Notebook``."""
    family: Optional[str] = None
    """Logical family grouping (e.g. ``data_engineering``, ``data_factory``)."""


class DimSeverity(BaseModel):
    """Severity dimension record (``dim_severity``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Literal["low", "medium", "high", "critical"]
    """Severity level (primary key)."""
    ordinal: int
    """Sort order: 0 = critical, 1 = high, 2 = medium, 3 = low."""
    color: Optional[str] = None
    """Hex color code for the severity level (e.g. ``#FF0000``)."""

    @field_validator("ordinal")
    @classmethod
    def _ordinal_in_range(cls, v: int) -> int:
        if v < 0:
            raise ValueError("ordinal must be >= 0")
        return v


# ---------------------------------------------------------------------------
# Registry: table name → (model class, primary-key column)
# ---------------------------------------------------------------------------

#: Maps each canonical table name to its Pydantic model class and PK column.
TABLE_REGISTRY: dict[str, tuple[type[BaseModel], str]] = {
    "fact_scan_findings": (FactScanFinding, "finding_id"),
    "fact_downloads":     (FactDownload,    "download_id"),
    "fact_mpe_lifecycle": (FactMpeLifecycle, "event_id"),
    "dim_workspace":      (DimWorkspace,    "workspace_id"),
    "dim_item_type":      (DimItemType,     "item_type"),
    "dim_severity":       (DimSeverity,     "severity"),
}

CANONICAL_TABLES: tuple[str, ...] = tuple(TABLE_REGISTRY)


def validate_rows(table_name: str, rows: list[dict]) -> list[BaseModel]:
    """Validate *rows* against the Pydantic model for *table_name*.

    Parameters
    ----------
    table_name:
        One of the six canonical table names (e.g. ``"fact_scan_findings"``).
    rows:
        List of plain dicts — each dict must match the Pydantic model's
        required and optional fields.

    Returns
    -------
    list[BaseModel]
        Validated model instances.

    Raises
    ------
    KeyError
        If *table_name* is not in ``TABLE_REGISTRY``.
    pydantic.ValidationError
        If any row fails schema validation.
    """
    if table_name not in TABLE_REGISTRY:
        raise KeyError(
            f"Unknown table '{table_name}'. "
            f"Expected one of: {sorted(TABLE_REGISTRY)}"
        )
    model_cls, _ = TABLE_REGISTRY[table_name]
    return [model_cls.model_validate(row) for row in rows]
