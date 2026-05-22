"""Token acquisition for Fabric / Power BI REST calls.

Resolution order:

    1. ``runtime_token_provider(audience)`` callable (test injection)
    2. ``notebookutils.credentials.getToken(audience)``
    3. ``mssparkutils.credentials.getToken(audience)``
    4. ``FABRIC_BEARER_TOKEN`` env var (laptop dev fallback)
    5. ``AZURE_ACCESS_TOKEN`` env var (``az account get-access-token`` flow)
    6. ``az account get-access-token --resource <audience>``
    7. ``azure.identity.DefaultAzureCredential``

``get_token`` intentionally has no default audience. Consumer packages keep their
own product-specific defaults and pass the resolved audience into this shared helper.
If none of these succeed, ``TokenError`` is raised.
"""
from __future__ import annotations

import importlib
import os
import subprocess
from collections.abc import Callable


class TokenError(RuntimeError):
    """Raised when no credential source can produce a token."""


def _from_runtime_module(module_name: str, audience: str) -> str | None:
    try:
        module = importlib.import_module(module_name)
        credentials = module.credentials
        get_token = credentials.getToken
        return get_token(audience) or None
    except Exception:
        return None


def _from_notebookutils(audience: str) -> str | None:
    """Return a Fabric runtime token from ``notebookutils``, if available."""
    return _from_runtime_module("notebookutils", audience)


def _from_mssparkutils(audience: str) -> str | None:
    """Return a Fabric/Synapse runtime token from ``mssparkutils``, if available."""
    return _from_runtime_module("mssparkutils", audience)


def _from_env(audience: str | None = None) -> str | None:
    """Return a bearer token from supported environment variables, if set.

    ``audience`` is accepted for source-chain signature compatibility and ignored.
    """
    for var in ("FABRIC_BEARER_TOKEN", "AZURE_ACCESS_TOKEN"):
        token = os.environ.get(var)
        if token:
            return token
    return None


def _from_azure_cli(audience: str) -> str | None:
    """Return a token from Azure CLI, if ``az`` is installed and signed in."""
    try:
        completed = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                audience,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        token = getattr(completed, "stdout", "").strip()
        return token or None
    except Exception:
        return None


def _scope_from_audience(audience: str) -> str:
    if audience.endswith("/.default"):
        return audience
    if "://" in audience:
        return f"{audience.rstrip('/')}/.default"
    return audience


def _from_default_credential(audience: str) -> str | None:
    """Return a token from ``azure.identity.DefaultAzureCredential``, if available."""
    try:
        identity = importlib.import_module("azure.identity")
        credential = identity.DefaultAzureCredential()
        access_token = credential.get_token(_scope_from_audience(audience))
        return getattr(access_token, "token", None) or None
    except Exception:
        return None


def get_token(
    audience: str,
    *,
    runtime_token_provider: Callable[[str], str | None] | None = None,
) -> str:
    """Return a bearer token usable for the explicitly supplied audience.

    ``runtime_token_provider`` is a test hook: a callable that takes the audience
    string and returns either a token or ``None``. Production callers can ignore it.
    """
    if runtime_token_provider is not None:
        try:
            token = runtime_token_provider(audience)
        except TokenError:
            token = None
        if token:
            return token

    for source in (
        _from_notebookutils,
        _from_mssparkutils,
        _from_env,
        _from_azure_cli,
        _from_default_credential,
    ):
        try:
            token = source(audience)
        except TokenError:
            continue
        if token:
            return token

    raise TokenError(
        "No Fabric credential source produced a token. Tried notebookutils, "
        "mssparkutils, FABRIC_BEARER_TOKEN, AZURE_ACCESS_TOKEN, Azure CLI, "
        "and DefaultAzureCredential. Either run inside a Fabric notebook, "
        "set FABRIC_BEARER_TOKEN, sign in with `az login`, or configure Azure Identity."
    )
