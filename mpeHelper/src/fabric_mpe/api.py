"""Fabric + ARM REST helpers for Managed Private Endpoints.

All HTTP plumbing — retry, backoff, pagination, JSON parsing — is
delegated to :mod:`fabric_core.http`. Filter helpers stay here because
they're MPE-specific (operate on already-flattened inventory rows).
"""
from __future__ import annotations

import re
from typing import Any

from fabric_core.http import collect_paged, request_json

from .arm import pec_api_version
from .config import MpeConfig

# ---- Fabric workspaces / MPEs --------------------------------------------


def list_workspaces(cfg: MpeConfig, token: str) -> list[dict]:
    """GET /v1/workspaces (paged). Raises RuntimeError on any non-200 page."""
    items, status, body = collect_paged(
        f"{cfg.fabric_base}/v1/workspaces",
        token=token,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )
    if status != 200:
        raise RuntimeError(f"List workspaces failed: HTTP {status} {body}")
    return items


def list_mpes(
    cfg: MpeConfig, workspace_id: str, token: str
) -> tuple[list[dict], dict | None]:
    """GET /v1/workspaces/{wid}/managedPrivateEndpoints (paged).

    Returns ``(rows, None)`` on success, ``([], {"status": s, "body": b})``
    on the first non-200 page so callers can keep going.
    """
    items, status, body = collect_paged(
        f"{cfg.fabric_base}/v1/workspaces/{workspace_id}/managedPrivateEndpoints",
        token=token,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )
    if status != 200:
        return [], {"status": status, "body": body}
    return items, None


def delete_mpe(
    cfg: MpeConfig, workspace_id: str, mpe_id: str, token: str
) -> tuple[int, Any]:
    """DELETE /v1/workspaces/{wid}/managedPrivateEndpoints/{mpeId}."""
    url = (
        f"{cfg.fabric_base}/v1/workspaces/{workspace_id}"
        f"/managedPrivateEndpoints/{mpe_id}"
    )
    return request_json(
        "DELETE",
        url,
        token=token,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )


def create_mpe(
    cfg: MpeConfig, workspace_id: str, body: dict, token: str
) -> tuple[int, Any]:
    """POST /v1/workspaces/{wid}/managedPrivateEndpoints.

    ``body`` must include ``name`` and ``targetPrivateLinkResourceId``;
    optional keys: ``targetSubresourceType``, ``requestMessage``,
    ``targetFQDNs``.
    """
    url = f"{cfg.fabric_base}/v1/workspaces/{workspace_id}/managedPrivateEndpoints"
    return request_json(
        "POST",
        url,
        token=token,
        body=body,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )


# ---- ARM private endpoint connections ------------------------------------


def list_pecs(
    cfg: MpeConfig, target_resource_id: str, token: str
) -> tuple[int, Any, str | None, str]:
    """LIST privateEndpointConnections on a target Azure resource.

    Returns ``(status, payload_or_list, rp, api_version)``. On 200 the
    second element is a flat list of PEC objects; otherwise it's the
    error body returned by the first failing page.
    """
    api, rp = pec_api_version(target_resource_id)
    url = (
        f"{cfg.arm_base}{target_resource_id}/privateEndpointConnections"
        f"?api-version={api}"
    )
    items, status, body = collect_paged(
        url,
        token=token,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )
    if status != 200:
        return status, body, rp, api
    return 200, items, rp, api


def approve_pec(
    cfg: MpeConfig,
    target_resource_id: str,
    pec_name: str,
    token: str,
    *,
    description: str | None = None,
    api_version: str | None = None,
) -> tuple[int, Any]:
    """PUT Approved on a single privateEndpointConnection.

    ``api_version`` is auto-derived from ``target_resource_id`` if omitted.
    """
    if api_version is None:
        api_version, _ = pec_api_version(target_resource_id)
    url = (
        f"{cfg.arm_base}{target_resource_id}/privateEndpointConnections/"
        f"{pec_name}?api-version={api_version}"
    )
    body = {
        "properties": {
            "privateLinkServiceConnectionState": {
                "status": "Approved",
                "description": description or "Approved",
            }
        }
    }
    return request_json(
        "PUT",
        url,
        token=token,
        body=body,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )


# ---- Filtering -----------------------------------------------------------


def apply_filters(
    inventory: list[dict],
    *,
    name_filter: str | None = None,
    id_filter: list[str] | tuple[str, ...] | None = None,
    target_filter: str | None = None,
) -> list[dict]:
    """Return the subset of inventory rows matching all supplied filters.

    Filters accept the same shape as the rows produced by
    :mod:`fabric_mpe.inventory`: ``mpe_id``, ``mpe_name``,
    ``target_resource_id``. Missing fields are treated as empty strings.
    """
    out = inventory
    if id_filter:
        wanted = set(id_filter)
        out = [m for m in out if m.get("mpe_id") in wanted]
    if name_filter:
        rx = re.compile(name_filter)
        out = [m for m in out if rx.search(m.get("mpe_name") or "")]
    if target_filter:
        rx = re.compile(target_filter)
        out = [m for m in out if rx.search(m.get("target_resource_id") or "")]
    return out


__all__ = [
    "list_workspaces",
    "list_mpes",
    "delete_mpe",
    "create_mpe",
    "list_pecs",
    "approve_pec",
    "apply_filters",
]
