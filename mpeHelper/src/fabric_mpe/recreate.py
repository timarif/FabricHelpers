"""Recreate MPEs from a prior delete-audit or inventory snapshot.

Gated by ``cfg.recreate``; aborts on more matches than
``cfg.max_recreates``. Each create request's ``requestMessage`` is
prefixed with ``[run=<run_label>]`` so :mod:`fabric_mpe.approve` can match
the resulting Pending PECs back to this run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import api, persist
from .auth import get_fabric_token
from .config import MpeConfig


@dataclass
class RecreateResult:
    targets: list[dict] = field(default_factory=list)
    audit_rows: list[dict] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    committed: bool = False
    audit_table: str = ""
    source: str = ""
    source_run_label: str = ""
    run_label: str = ""
    source_missing: bool = False


def _source_table(cfg: MpeConfig) -> str:
    table = (
        cfg.audit_table
        if cfg.recreate_source == "audit"
        else cfg.inventory_table
    )
    return cfg.delta_target(table)


def _load_source_rows(
    cfg: MpeConfig,
    *,
    spark: Any | None,
    rows: list[dict] | None,
    source_run_label: str,
) -> tuple[list[dict], bool]:
    if rows is not None:
        return rows, False
    if spark is None:
        raise RuntimeError(
            "Provide rows= or spark=; can't read the source table without Spark."
        )
    src_table = _source_table(cfg)
    if not spark.catalog.tableExists(src_table):
        return [], True
    df = spark.read.table(src_table).where(f"run_label = '{source_run_label}'")
    if cfg.recreate_source == "audit":
        df = df.where("delete_status BETWEEN 200 AND 299")
    return [r.asDict() for r in df.collect()], False


def _build_body(
    row: dict, *, request_message: str, run_marker: str
) -> dict:
    body: dict[str, Any] = {
        "name": row.get("mpe_name"),
        "targetPrivateLinkResourceId": row.get("target_resource_id"),
    }
    if row.get("target_subresource_type"):
        body["targetSubresourceType"] = row["target_subresource_type"]
    base_msg = request_message or "Recreated via fabric-mpe"
    body["requestMessage"] = f"{run_marker} {base_msg}"[:140]
    return body


def run(
    cfg: MpeConfig,
    spark: Any | None = None,
    *,
    token: str | None = None,
    rows: list[dict] | None = None,
) -> RecreateResult:
    """Recreate MPEs from the configured source (audit or inventory).

    Raises ``RuntimeError`` if ``cfg.recreate`` is True and the source
    table doesn't exist, or if the candidate count exceeds
    ``cfg.max_recreates``. When ``cfg.recreate`` is False, returns the
    preview-only result with ``committed=False``.
    """
    source_run_label = cfg.recreate_run_label or cfg.run_label
    source_rows, missing = _load_source_rows(
        cfg, spark=spark, rows=rows, source_run_label=source_run_label
    )

    result = RecreateResult(
        audit_table=cfg.delta_target(cfg.recreate_table),
        source=cfg.recreate_source,
        source_run_label=source_run_label,
        run_label=cfg.run_label,
        source_missing=missing,
    )

    if missing:
        if cfg.recreate:
            raise RuntimeError(
                f"Source table '{_source_table(cfg)}' does not exist yet."
            )
        return result

    # IDs change on recreate, so id_filter is intentionally ignored here.
    targets = api.apply_filters(
        source_rows,
        name_filter=cfg.name_filter,
        target_filter=cfg.target_filter,
    )
    result.targets = list(targets)

    if not cfg.recreate or not targets:
        return result
    if len(targets) > cfg.max_recreates:
        raise RuntimeError(
            f"ABORT: {len(targets)} matches exceed max_recreates "
            f"({cfg.max_recreates}). Narrow the filter or raise the cap."
        )

    bearer = token or get_fabric_token(cfg)
    run_marker = f"[run={cfg.run_label}]"
    audit: list[dict] = []
    ok = err = 0
    for r in targets:
        body = _build_body(
            r,
            request_message=cfg.recreate_request_message,
            run_marker=run_marker,
        )
        status, resp = api.create_mpe(cfg, r["workspace_id"], body, bearer)
        new_id = resp.get("id") if isinstance(resp, dict) else None
        new_state = (
            resp.get("provisioningState") if isinstance(resp, dict) else None
        )
        audit.append(
            {
                "workspace_id": r["workspace_id"],
                "workspace_name": r.get("workspace_name"),
                "original_mpe_id": r.get("mpe_id"),
                "new_mpe_id": new_id,
                "mpe_name": r.get("mpe_name"),
                "target_resource_id": r.get("target_resource_id"),
                "target_subresource_type": r.get("target_subresource_type"),
                "request_message": cfg.recreate_request_message,
                "create_status": int(status),
                "create_response": persist.encode_body(resp),
                "new_provisioning_state": new_state,
                "source": cfg.recreate_source,
                "source_run_label": source_run_label,
                "run_label": cfg.run_label,
                "created_at": datetime.now(timezone.utc),
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


__all__ = ["RecreateResult", "run"]
