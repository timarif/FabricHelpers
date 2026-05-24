"""Dry-run + commit deletion of MPEs.

Both functions read the current run's inventory from Delta (so the user
gets the same filter logic / safety caps regardless of where in the
workflow they are). Loading rows from a list (instead of Spark) is also
supported for testing and for non-Spark CLI use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import api, persist
from .auth import get_fabric_token
from .config import MpeConfig


@dataclass
class DeleteResult:
    targets: list[dict] = field(default_factory=list)
    audit_rows: list[dict] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    committed: bool = False
    audit_table: str = ""
    run_label: str = ""


def _load_run_rows(
    cfg: MpeConfig,
    *,
    rows: list[dict] | None,
    spark: Any | None,
    run_label: str | None,
) -> list[dict]:
    if rows is not None:
        return rows
    if spark is None:
        raise RuntimeError(
            "Provide rows= or spark=; can't read the inventory table without Spark."
        )
    label = run_label or cfg.run_label
    inv = spark.read.table(cfg.delta_target(cfg.inventory_table)).where(
        f"run_label = '{label}'"
    )
    return [r.asDict() for r in inv.collect()]


def _select_targets(cfg: MpeConfig, source_rows: list[dict]) -> list[dict]:
    return api.apply_filters(
        source_rows,
        name_filter=cfg.name_filter,
        id_filter=cfg.id_filter or None,
        target_filter=cfg.target_filter,
    )


def dry_run(
    cfg: MpeConfig,
    spark: Any | None = None,
    *,
    rows: list[dict] | None = None,
    run_label: str | None = None,
) -> list[dict]:
    """Return the MPEs that :func:`commit` would delete. No HTTP calls."""
    source = _load_run_rows(cfg, rows=rows, spark=spark, run_label=run_label)
    return _select_targets(cfg, source)


def commit(
    cfg: MpeConfig,
    spark: Any | None = None,
    *,
    token: str | None = None,
    rows: list[dict] | None = None,
    run_label: str | None = None,
) -> DeleteResult:
    """Delete MPEs matching the filters, gated by ``cfg.commit``.

    Returns a :class:`DeleteResult` with the planned targets and (when
    committed) per-MPE audit rows. Raises ``RuntimeError`` if the target
    count exceeds ``cfg.max_deletes`` — the safety guarantee from the
    legacy notebook.
    """
    targets = dry_run(cfg, spark, rows=rows, run_label=run_label)
    result = DeleteResult(
        targets=list(targets),
        audit_table=cfg.delta_target(cfg.audit_table),
        run_label=cfg.run_label,
    )

    if not cfg.commit or not targets:
        return result
    if len(targets) > cfg.max_deletes:
        raise RuntimeError(
            f"ABORT: {len(targets)} matches exceed max_deletes "
            f"({cfg.max_deletes}). Narrow the filter or raise the cap."
        )

    bearer = token or get_fabric_token(cfg)
    audit: list[dict] = []
    ok = err = 0
    for m in targets:
        status, body = api.delete_mpe(cfg, m["workspace_id"], m["mpe_id"], bearer)
        audit.append(
            {
                "workspace_id": m["workspace_id"],
                "workspace_name": m.get("workspace_name"),
                "mpe_id": m["mpe_id"],
                "mpe_name": m.get("mpe_name"),
                "target_resource_id": m.get("target_resource_id"),
                "target_subresource_type": m.get("target_subresource_type"),
                "provisioning_state": m.get("provisioning_state"),
                "connection_status": m.get("connection_status"),
                "delete_status": int(status),
                "delete_response": persist.encode_body(body),
                "run_label": cfg.run_label,
                "deleted_at": datetime.now(timezone.utc),
            }
        )
        if 200 <= status < 300:
            ok += 1
        else:
            err += 1

    if spark is not None and audit:
        persist.append_delta(spark, audit, result.audit_table)

    result.audit_rows = audit
    result.succeeded = ok
    result.failed = err
    result.committed = True
    return result


__all__ = ["DeleteResult", "dry_run", "commit"]
