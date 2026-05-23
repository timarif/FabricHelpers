"""Compatibility wrapper over :mod:`fabric_core.auth`."""
from __future__ import annotations

from typing import Any

from fabric_core.auth import (
    TokenError,
    _from_azure_cli,
    _from_default_credential,
    _from_env,
    _from_mssparkutils,
    _from_notebookutils,
)
from fabric_core.auth import (
    get_token as _core_get_token,
)


def get_token(
    audience: str = "https://api.fabric.microsoft.com",
    *,
    force_refresh: bool = False,
    **kw: Any,
) -> str:
    """Return a bearer token for the scanner's default Fabric audience."""
    _ = force_refresh
    return _core_get_token(audience=audience, **kw)


__all__ = [
    "TokenError",
    "get_token",
    "_from_notebookutils",
    "_from_mssparkutils",
    "_from_env",
    "_from_azure_cli",
    "_from_default_credential",
]
