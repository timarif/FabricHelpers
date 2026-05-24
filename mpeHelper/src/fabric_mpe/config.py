"""User-facing configuration for the Fabric Managed Private Endpoint manager.

``MpeConfig`` is a frozen dataclass — every knob lives here and the rest of
the package threads it through unchanged. Defaults match the post-v0.1
behavior of the legacy monolithic ``mpe_manager.ipynb`` cell-1 config so a
no-arg construction produces a safe, preview-only inventory scan.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Literal

WorkspaceScope = Literal["visible", "list", "from_inventory"]
RecreateSource = Literal["audit", "inventory"]


def _default_run_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


@dataclass(frozen=True)
class MpeConfig:
    # ---- Workspace scope --------------------------------------------------
    workspace_scope: WorkspaceScope = "visible"
    workspaces: tuple[str, ...] = field(default_factory=tuple)

    # ---- Persistence ------------------------------------------------------
    inventory_table: str = "mpe_inventory"
    audit_table: str = "mpe_delete_audit"
    recreate_table: str = "mpe_recreate_audit"
    approve_table: str = "mpe_approve_audit"
    write_schema: str = ""
    files_subdir: str = "mpe_manager"

    # ---- Filters (applied in dry-run / commit / recreate) -----------------
    name_filter: str | None = None
    id_filter: tuple[str, ...] = field(default_factory=tuple)
    target_filter: str | None = None

    # ---- Deletion safety --------------------------------------------------
    commit: bool = False
    max_deletes: int = 25

    # ---- Recreate ---------------------------------------------------------
    recreate: bool = False
    recreate_source: RecreateSource = "audit"
    recreate_run_label: str | None = None
    recreate_request_message: str = "Recreated via fabric-mpe"
    max_recreates: int = 25

    # ---- Approve ----------------------------------------------------------
    approve: bool = False
    approve_description: str = "Approved by fabric-mpe"
    approve_run_label: str | None = None
    max_approves: int = 25

    # ---- API / Auth -------------------------------------------------------
    fabric_base: str = "https://api.fabric.microsoft.com"
    arm_base: str = "https://management.azure.com"
    token_audience: str = "https://api.fabric.microsoft.com"
    arm_audience: str = "https://management.azure.com"
    pbi_base: str = "https://api.powerbi.com"
    max_retries: int = 5
    request_timeout: float = 60.0

    # ---- Auto-generated ---------------------------------------------------
    run_label: str = field(default_factory=_default_run_label)

    # ----------------------------------------------------------------------
    def __post_init__(self) -> None:
        if self.workspace_scope not in ("visible", "list", "from_inventory"):
            raise ValueError(
                f"workspace_scope must be 'visible', 'list', or 'from_inventory'; "
                f"got {self.workspace_scope!r}"
            )
        if self.recreate_source not in ("audit", "inventory"):
            raise ValueError(
                f"recreate_source must be 'audit' or 'inventory'; "
                f"got {self.recreate_source!r}"
            )
        if self.workspace_scope == "list" and not self.workspaces:
            raise ValueError("workspace_scope='list' requires non-empty workspaces")
        for n, label in (
            (self.max_deletes, "max_deletes"),
            (self.max_recreates, "max_recreates"),
            (self.max_approves, "max_approves"),
            (self.max_retries, "max_retries"),
        ):
            if n < 1:
                raise ValueError(f"{label} must be >= 1")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be > 0")

    # --- helpers used across the package -----------------------------------
    def delta_target(self, table: str) -> str:
        """Schema-qualified Delta table name (``schema.table`` or ``table``)."""
        return f"{self.write_schema}.{table}" if self.write_schema else table

    def files_dir(self, run_label: str | None = None) -> str:
        """POSIX path under the attached lakehouse for JSON/CSV export."""
        from fabric_core.paths import mounted_files_path

        return mounted_files_path(f"{self.files_subdir}/{run_label or self.run_label}")

    @classmethod
    def from_dict(cls, d: dict) -> MpeConfig:
        """Build a config from a plain dict. Unknown keys raise TypeError."""
        valid = {f.name for f in fields(cls)}
        unknown = set(d) - valid
        if unknown:
            raise TypeError(f"Unknown MpeConfig fields: {sorted(unknown)}")
        return cls(**d)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}
