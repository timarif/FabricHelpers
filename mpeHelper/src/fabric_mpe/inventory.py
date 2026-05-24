"""Discover MPEs across workspaces and persist them to Delta + Files.

Mirrors cell 3 of the legacy ``mpe_manager.ipynb`` minus the inline
``display()`` calls — the orchestrator notebook is responsible for
displaying the returned DataFrames.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import api, persist
from .auth import get_fabric_token
from .config import MpeConfig


@dataclass
class InventoryResult:
    rows: list[dict] = field(default_factory=list)
    workspace_ids: list[str] = field(default_factory=list)
    workspace_names: dict[str, str | None] = field(default_factory=dict)
    skipped: list[tuple[str, dict]] = field(default_factory=list)
    inventory_table: str = ""
    files_dir: str = ""
    json_path: str = ""
    csv_path: str = ""
    run_label: str = ""


def _resolve_workspaces(
    cfg: MpeConfig,
    token: str,
    spark: Any | None,
) -> tuple[list[str], dict[str, str | None]]:
    if cfg.workspace_scope == "visible":
        rows = api.list_workspaces(cfg, token)
        ids = [r["id"] for r in rows if r.get("id")]
        names = {r["id"]: r.get("displayName") for r in rows if r.get("id")}
        return ids, names
    if cfg.workspace_scope == "list":
        return list(cfg.workspaces), {}
    if cfg.workspace_scope == "from_inventory":
        if spark is None:
            raise RuntimeError(
                "workspace_scope='from_inventory' requires a Spark session"
            )
        prior = spark.read.table(cfg.delta_target(cfg.inventory_table))
        ids = sorted(
            {r.workspace_id for r in prior.select("workspace_id").distinct().collect()}
        )
        return ids, {}
    raise RuntimeError(f"Unknown workspace_scope: {cfg.workspace_scope!r}")


def _flatten(ep: dict, workspace_id: str, workspace_name: str | None, run_label: str) -> dict:
    cs = ep.get("connectionState") or {}
    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "mpe_id": ep.get("id"),
        "mpe_name": ep.get("name"),
        "target_resource_id": ep.get("targetPrivateLinkResourceId"),
        "target_subresource_type": ep.get("targetSubresourceType"),
        "provisioning_state": ep.get("provisioningState"),
        "connection_status": cs.get("status"),
        "connection_description": cs.get("description"),
        "run_label": run_label,
        "collected_at": datetime.now(timezone.utc),
    }


def collect(
    cfg: MpeConfig,
    *,
    token: str | None = None,
    spark: Any | None = None,
) -> InventoryResult:
    """Walk the configured workspaces and return inventory rows in memory.

    No persistence side effects — call :func:`run` for the full Delta+Files
    flow. Tests use this entry point to verify enumeration end-to-end with
    mocked HTTP, no Spark required (unless ``workspace_scope='from_inventory'``).
    """
    bearer = token or get_fabric_token(cfg)
    ids, names = _resolve_workspaces(cfg, bearer, spark)

    rows: list[dict] = []
    skipped: list[tuple[str, dict]] = []
    for wid in ids:
        eps, err = api.list_mpes(cfg, wid, bearer)
        if err is not None:
            skipped.append((wid, err))
            continue
        for ep in eps:
            rows.append(_flatten(ep, wid, names.get(wid), cfg.run_label))

    return InventoryResult(
        rows=rows,
        workspace_ids=list(ids),
        workspace_names=names,
        skipped=skipped,
        inventory_table=cfg.delta_target(cfg.inventory_table),
        run_label=cfg.run_label,
    )


def run(
    cfg: MpeConfig,
    spark: Any | None = None,
    *,
    token: str | None = None,
) -> InventoryResult:
    """Inventory + persist to Delta + Files (JSON+CSV). Returns the result.

    ``spark`` is required for the Delta append; pass ``None`` for a
    file-only / preview run (e.g., from the CLI). The function never calls
    ``display()`` — the orchestrator notebook is expected to do that on
    the returned table.
    """
    result = collect(cfg, token=token, spark=spark)
    directory, json_path, csv_path = persist.write_inventory_files(
        cfg, result.rows, run_label=result.run_label
    )
    result.files_dir = directory
    result.json_path = json_path
    result.csv_path = csv_path

    if spark is not None and result.rows:
        persist.append_delta(spark, result.rows, result.inventory_table)
    return result


__all__ = ["InventoryResult", "collect", "run"]
