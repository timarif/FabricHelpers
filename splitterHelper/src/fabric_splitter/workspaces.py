"""Workspace provisioning and role-assignment helpers.

Creates target workspaces if they are missing and optionally copies all role
assignments from the source workspace to both targets.
"""
from __future__ import annotations

import logging

from ._http import FABRIC_BASE, _request, paged_get

log = logging.getLogger(__name__)


def get_workspace_id(name: str, token: str, *, fabric_base: str = FABRIC_BASE) -> str | None:
    """Return the ID of the workspace named *name*, or ``None`` if not found."""
    workspaces = paged_get(f"{fabric_base}/v1/workspaces", token)
    for ws in workspaces:
        if (ws.get("displayName") or ws.get("name")) == name:
            return ws["id"]
    return None


def get_or_create_workspace(
    name: str,
    token: str,
    *,
    capacity_id: str | None = None,
    fabric_base: str = FABRIC_BASE,
) -> str:
    """Return the ID of the workspace named *name*, creating it if necessary.

    Parameters
    ----------
    name:
        Display name of the workspace to find or create.
    token:
        Bearer token with workspace-creation permissions.
    capacity_id:
        Optional Fabric capacity ID to assign to a newly created workspace.
    fabric_base:
        Fabric REST API base URL (override for testing).

    Returns
    -------
    Workspace ID string.
    """
    existing = get_workspace_id(name, token, fabric_base=fabric_base)
    if existing:
        log.info("Workspace '%s' already exists: %s", name, existing)
        return existing

    payload: dict = {"displayName": name}
    if capacity_id:
        payload["capacityId"] = capacity_id

    resp = _request("POST", f"{fabric_base}/v1/workspaces", token, body=payload)
    ws_id: str = resp["id"]
    log.info("Created workspace '%s': %s", name, ws_id)
    return ws_id


def copy_role_assignments(
    source_id: str,
    target_id: str,
    token: str,
    *,
    fabric_base: str = FABRIC_BASE,
) -> int:
    """Copy all role assignments from *source_id* to *target_id*.

    Assignments that already exist in the target (identified by principal ID +
    role) are silently skipped.

    Parameters
    ----------
    source_id:
        Workspace ID to copy role assignments *from*.
    target_id:
        Workspace ID to copy role assignments *to*.
    token:
        Bearer token.
    fabric_base:
        Fabric REST API base URL (override for testing).

    Returns
    -------
    Number of role assignments successfully copied.
    """
    assignments = paged_get(
        f"{fabric_base}/v1/workspaces/{source_id}/roleAssignments", token
    )
    copied = 0
    for assignment in assignments:
        principal = assignment.get("principal", {})
        role = assignment.get("role")
        if not principal or not role:
            continue
        try:
            _request(
                "POST",
                f"{fabric_base}/v1/workspaces/{target_id}/roleAssignments",
                token,
                body={"role": role, "principal": principal},
            )
            log.info(
                "Copied role %s to workspace %s for principal %s",
                role,
                target_id,
                principal.get("id"),
            )
            copied += 1
        except Exception as exc:
            log.warning("Failed to copy role assignment to %s: %s", target_id, exc)
    return copied
