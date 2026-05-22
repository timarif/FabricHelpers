"""Token acquisition for Fabric / Power BI REST calls.

Resolution order (matches `fabric_scanner.api.auth`):

    1. `runtime_token_provider(audience)` callable (test injection)
    2. `notebookutils.credentials.getToken(audience)`
    3. `mssparkutils.credentials.getToken(audience)`
    4. `FABRIC_BEARER_TOKEN` env var (laptop dev fallback)
    5. `AZURE_ACCESS_TOKEN` env var (`az account get-access-token` flow)

If none of these succeed, `TokenError` is raised.
"""
from __future__ import annotations

import os
from typing import Callable


class TokenError(RuntimeError):
    """Raised when no credential source can produce a token."""


def _from_notebookutils(audience: str) -> str | None:
    try:
        import notebookutils  # type: ignore
        return notebookutils.credentials.getToken(audience)
    except Exception:
        return None


def _from_mssparkutils(audience: str) -> str | None:
    try:
        import mssparkutils  # type: ignore
        return mssparkutils.credentials.getToken(audience)
    except Exception:
        return None


def _from_env() -> str | None:
    for var in ("FABRIC_BEARER_TOKEN", "AZURE_ACCESS_TOKEN"):
        v = os.environ.get(var)
        if v:
            return v
    return None


def get_token(
    audience: str = "pbi",
    *,
    runtime_token_provider: Callable[[str], str | None] | None = None,
) -> str:
    """Return a bearer token usable for the given Fabric audience.

    `runtime_token_provider` is a hook for tests; production callers can
    ignore it.
    """
    if runtime_token_provider is not None:
        t = runtime_token_provider(audience)
        if t:
            return t

    for src in (_from_notebookutils, _from_mssparkutils):
        t = src(audience)
        if t:
            return t

    t = _from_env()
    if t:
        return t

    raise TokenError(
        "No Fabric credential source produced a token. Tried "
        "notebookutils, mssparkutils, FABRIC_BEARER_TOKEN, and "
        "AZURE_ACCESS_TOKEN. Either run inside a Fabric notebook, or "
        "set FABRIC_BEARER_TOKEN to a bearer string from "
        "`az account get-access-token --resource "
        "https://api.fabric.microsoft.com`.")
