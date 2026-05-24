"""Auto-approve Azure-side privateEndpointConnections for recreated MPEs.

Reads the recreate audit table, groups by target resource, LISTs PECs on
each via ARM REST, filters to ``Pending`` PECs whose description contains
the ``[run=<label>]`` marker stamped by :mod:`fabric_mpe.recreate`, and
(when ``cfg.approve`` is True) PUTs Approved on each one.

Uses an ARM-audience token from :func:`fabric_mpe.auth.get_arm_token`,
which is different from the Fabric token used by inventory / delete /
recreate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import api, persist
from .auth import get_arm_token
from .config import MpeConfig


@dataclass
class ApproveResult:
    queue: list[dict] = field(default_factory=list)
    audit_rows: list[dict] = field(default_factory=list)
    list_errors: list[dict] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    committed: bool = False
    audit_table: str = ""
    source_run_label: str = ""
    run_label: str = ""
    source_missing: bool = False


def _load_candidates(
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
            "Provide rows= or spark=; can't read the recreate table without Spark."
        )
    table = cfg.delta_target(cfg.recreate_table)
    if not spark.catalog.tableExists(table):
        return [], True
    df = (
        spark.read.table(table)
        .where(f"run_label = '{source_run_label}'")
        .where("create_status BETWEEN 200 AND 299")
    )
    return [r.asDict() for r in df.collect()], False


def _build_queue(
    cfg: MpeConfig, candidates: list[dict], token: str, marker: str
) -> tuple[list[dict], list[dict]]:
    by_target: dict[str, list[dict]] = {}
    for row in candidates:
        by_target.setdefault(row["target_resource_id"], []).append(row)

    queue: list[dict] = []
    list_errors: list[dict] = []
    for tgt, rows in by_target.items():
        status, payload, rp, api_v = api.list_pecs(cfg, tgt, token)
        if status != 200:
            list_errors.append(
                {
                    "target_resource_id": tgt,
                    "rp": rp,
                    "api_version": api_v,
                    "status": status,
                    "payload": payload,
                }
            )
            continue
        for pec in payload:
            state = (
                pec.get("properties", {})
                .get("privateLinkServiceConnectionState", {})
            )
            if state.get("status") != "Pending":
                continue
            if marker not in (state.get("description") or ""):
                continue
            queue.append(
                {
                    "target_resource_id": tgt,
                    "rp": rp,
                    "api_version": api_v,
                    "pec_name": pec["name"],
                    "pec_description": state.get("description"),
                    "mpe_rows": rows,
                }
            )
    return queue, list_errors


def _list_error_audit_row(
    err: dict, *, source_run_label: str, run_label: str
) -> dict:
    return {
        "target_resource_id": err["target_resource_id"],
        "target_rp": err["rp"],
        "api_version": err["api_version"],
        "pec_name": None,
        "pec_description": None,
        "mpe_name": None,
        "original_mpe_id": None,
        "new_mpe_id": None,
        "request_message": None,
        "approve_status": int(err["status"]),
        "approve_response": persist.encode_body(err["payload"]),
        "new_connection_state": None,
        "source_run_label": source_run_label,
        "run_label": run_label,
        "approved_at": datetime.now(timezone.utc),
    }


def run(
    cfg: MpeConfig,
    spark: Any | None = None,
    *,
    token: str | None = None,
    rows: list[dict] | None = None,
) -> ApproveResult:
    """Approve the Pending PECs created by :mod:`fabric_mpe.recreate`.

    When ``cfg.approve`` is False, returns the preview result (``queue``
    populated, no PUTs issued). When True, raises ``RuntimeError`` on a
    missing recreate table or on more queued PECs than ``cfg.max_approves``.
    """
    source_run_label = cfg.approve_run_label or cfg.run_label
    candidates, missing = _load_candidates(
        cfg, spark=spark, rows=rows, source_run_label=source_run_label
    )

    result = ApproveResult(
        audit_table=cfg.delta_target(cfg.approve_table),
        source_run_label=source_run_label,
        run_label=cfg.run_label,
        source_missing=missing,
    )

    if missing:
        if cfg.approve:
            raise RuntimeError(
                f"Recreate table '{cfg.delta_target(cfg.recreate_table)}' "
                "does not exist yet."
            )
        return result

    if not candidates:
        return result

    arm_token = token or get_arm_token(cfg)
    marker = f"[run={source_run_label}]"
    queue, list_errors = _build_queue(cfg, candidates, arm_token, marker)
    result.queue = queue
    result.list_errors = list_errors

    if not cfg.approve:
        return result
    if not queue and not list_errors:
        return result
    if len(queue) > cfg.max_approves:
        raise RuntimeError(
            f"ABORT: {len(queue)} queued exceed max_approves "
            f"({cfg.max_approves}). Narrow the run_label or raise the cap."
        )

    audit: list[dict] = []
    ok = err = 0
    for q in queue:
        linked = q["mpe_rows"][0] if q["mpe_rows"] else {}
        status, resp = api.approve_pec(
            cfg,
            q["target_resource_id"],
            q["pec_name"],
            arm_token,
            description=cfg.approve_description,
            api_version=q["api_version"],
        )
        new_state = None
        if isinstance(resp, dict):
            new_state = (
                resp.get("properties", {})
                .get("privateLinkServiceConnectionState", {})
                .get("status")
            )
        audit.append(
            {
                "target_resource_id": q["target_resource_id"],
                "target_rp": q["rp"],
                "api_version": q["api_version"],
                "pec_name": q["pec_name"],
                "pec_description": q["pec_description"],
                "mpe_name": linked.get("mpe_name"),
                "original_mpe_id": linked.get("original_mpe_id"),
                "new_mpe_id": linked.get("new_mpe_id"),
                "request_message": linked.get("request_message"),
                "approve_status": int(status),
                "approve_response": persist.encode_body(resp),
                "new_connection_state": new_state,
                "source_run_label": source_run_label,
                "run_label": cfg.run_label,
                "approved_at": datetime.now(timezone.utc),
            }
        )
        if 200 <= status < 300:
            ok += 1
        else:
            err += 1

    for le in list_errors:
        audit.append(
            _list_error_audit_row(
                le, source_run_label=source_run_label, run_label=cfg.run_label
            )
        )

    if spark is not None and audit:
        persist.append_delta(spark, audit, result.audit_table)

    result.audit_rows = audit
    result.succeeded = ok
    result.failed = err
    result.committed = True
    return result


__all__ = ["ApproveResult", "run"]
