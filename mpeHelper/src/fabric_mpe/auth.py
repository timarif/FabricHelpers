"""Thin auth shim over :mod:`fabric_core.auth`.

Both helpers resolve tokens via the shared six-source chain
(``notebookutils`` → ``mssparkutils`` → ``FABRIC_BEARER_TOKEN`` /
``AZURE_ACCESS_TOKEN`` env vars → SPN client-credentials env vars →
``az`` CLI → ``DefaultAzureCredential``). They only differ in audience.

If you want explicit ARM env vars (``ARM_TOKEN``,
``ARM_SPN_TENANT_ID`` / ``ARM_SPN_CLIENT_ID`` / ``ARM_SPN_CLIENT_SECRET``)
that override the chain — like the legacy notebook did — set them
yourself before calling :func:`get_arm_token`; they're consulted first.
"""
from __future__ import annotations

import os

from fabric_core.auth import TokenError, fetch_token_via_client_credentials, get_token

from .config import MpeConfig

ARM_TOKEN_ENV = "ARM_TOKEN"
ARM_SPN_TENANT_ENV = "ARM_SPN_TENANT_ID"
ARM_SPN_CLIENT_ENV = "ARM_SPN_CLIENT_ID"
ARM_SPN_SECRET_ENV = "ARM_SPN_CLIENT_SECRET"


def get_fabric_token(cfg: MpeConfig) -> str:
    """Return a bearer token for ``cfg.token_audience`` (default Fabric)."""
    return get_token(cfg.token_audience)


def get_arm_token(cfg: MpeConfig) -> str:
    """Return a bearer token for the ARM audience.

    Resolution order, picking the first success:

    1. ``ARM_TOKEN`` env var (paste-a-token escape hatch).
    2. ``ARM_SPN_TENANT_ID`` / ``ARM_SPN_CLIENT_ID`` /
       ``ARM_SPN_CLIENT_SECRET`` env vars (the reliable path in Fabric
       because the workspace identity usually can't mint ARM tokens via
       ``notebookutils``).
    3. The shared :func:`fabric_core.auth.get_token` chain, applied to
       ``cfg.arm_audience``.
    """
    explicit = os.environ.get(ARM_TOKEN_ENV)
    if explicit:
        return explicit.strip()

    tenant = os.environ.get(ARM_SPN_TENANT_ENV)
    client = os.environ.get(ARM_SPN_CLIENT_ENV)
    secret = os.environ.get(ARM_SPN_SECRET_ENV)
    if tenant and client and secret:
        scope = f"{cfg.arm_audience.rstrip('/')}/.default"
        return fetch_token_via_client_credentials(
            tenant, client, secret, scope=scope, timeout=cfg.request_timeout,
        )

    return get_token(cfg.arm_audience)


__all__ = [
    "ARM_TOKEN_ENV",
    "ARM_SPN_TENANT_ENV",
    "ARM_SPN_CLIENT_ENV",
    "ARM_SPN_SECRET_ENV",
    "TokenError",
    "get_fabric_token",
    "get_arm_token",
]
