"""Tests for ``fabric_core.auth`` token acquisition helpers."""
from __future__ import annotations

import importlib
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from fabric_core import auth
from fabric_core.auth import TokenError, get_token

AUDIENCE = "https://api.fabric.microsoft.com"


def _runtime_module(token_or_mock):
    get_token_mock = token_or_mock if isinstance(token_or_mock, Mock) else Mock(return_value=token_or_mock)
    return SimpleNamespace(credentials=SimpleNamespace(getToken=get_token_mock)), get_token_mock


def test_token_error_identity_and_catching():
    assert issubclass(TokenError, RuntimeError)
    with pytest.raises(TokenError, match="boom"):
        raise TokenError("boom")

    try:
        raise auth.TokenError("caught")
    except TokenError as exc:
        assert str(exc) == "caught"


def test_runtime_module_sources_success():
    for module_name, source in (
        ("notebookutils", auth._from_notebookutils),
        ("mssparkutils", auth._from_mssparkutils),
    ):
        module, get_token_mock = _runtime_module(f"{module_name}-token")
        with patch.dict(sys.modules, {module_name: module}):
            assert source(AUDIENCE) == f"{module_name}-token"
        get_token_mock.assert_called_once_with(AUDIENCE)


def test_runtime_module_sources_missing_module():
    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name in {"notebookutils", "mssparkutils"}:
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    with patch("importlib.import_module", side_effect=fake_import_module):
        assert auth._from_notebookutils(AUDIENCE) is None
        assert auth._from_mssparkutils(AUDIENCE) is None


def test_runtime_module_sources_missing_attribute():
    for module_name, source in (
        ("notebookutils", auth._from_notebookutils),
        ("mssparkutils", auth._from_mssparkutils),
    ):
        with patch.dict(sys.modules, {module_name: SimpleNamespace()}):
            assert source(AUDIENCE) is None

        with patch.dict(sys.modules, {module_name: SimpleNamespace(credentials=SimpleNamespace())}):
            assert source(AUDIENCE) is None


def test_runtime_module_sources_exception_path():
    for module_name, source in (
        ("notebookutils", auth._from_notebookutils),
        ("mssparkutils", auth._from_mssparkutils),
    ):
        module, get_token_mock = _runtime_module(Mock(side_effect=RuntimeError("no token")))
        with patch.dict(sys.modules, {module_name: module}):
            assert source(AUDIENCE) is None
        get_token_mock.assert_called_once_with(AUDIENCE)


def test_env_source_success_precedence_and_missing():
    with patch.dict(
        "os.environ",
        {"FABRIC_BEARER_TOKEN": "fabric-token", "AZURE_ACCESS_TOKEN": "azure-token"},
        clear=True,
    ):
        assert auth._from_env(AUDIENCE) == "fabric-token"

    with patch.dict("os.environ", {"AZURE_ACCESS_TOKEN": "azure-token"}, clear=True):
        assert auth._from_env(AUDIENCE) == "azure-token"

    with patch.dict("os.environ", {}, clear=True):
        assert auth._from_env(AUDIENCE) is None


def test_azure_cli_source_success():
    completed = SimpleNamespace(stdout="cli-token\n")
    with patch("subprocess.run", return_value=completed) as run_mock:
        assert auth._from_azure_cli(AUDIENCE) == "cli-token"

    run_mock.assert_called_once_with(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            AUDIENCE,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_azure_cli_source_failure_paths():
    with patch("subprocess.run", side_effect=FileNotFoundError("az")):
        assert auth._from_azure_cli(AUDIENCE) is None

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "az")):
        assert auth._from_azure_cli(AUDIENCE) is None

    with patch("subprocess.run", return_value=SimpleNamespace()):
        assert auth._from_azure_cli(AUDIENCE) is None


def test_default_credential_source_success():
    credential = SimpleNamespace(get_token=Mock(return_value=SimpleNamespace(token="adc-token")))
    identity = SimpleNamespace(DefaultAzureCredential=Mock(return_value=credential))

    with patch.dict(sys.modules, {"azure.identity": identity}):
        assert auth._from_default_credential(AUDIENCE) == "adc-token"

    identity.DefaultAzureCredential.assert_called_once_with()
    credential.get_token.assert_called_once_with(f"{AUDIENCE}/.default")


def test_default_credential_source_missing_module():
    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "azure.identity":
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    with patch("importlib.import_module", side_effect=fake_import_module):
        assert auth._from_default_credential(AUDIENCE) is None


def test_default_credential_source_missing_attribute_and_exception():
    with patch.dict(sys.modules, {"azure.identity": SimpleNamespace()}):
        assert auth._from_default_credential(AUDIENCE) is None

    credential = SimpleNamespace(get_token=Mock(side_effect=RuntimeError("denied")))
    identity = SimpleNamespace(DefaultAzureCredential=Mock(return_value=credential))
    with patch.dict(sys.modules, {"azure.identity": identity}):
        assert auth._from_default_credential(AUDIENCE) is None


def test_get_token_runtime_provider_wins_and_receives_audience():
    provider = Mock(return_value="provider-token")
    with patch("fabric_core.auth._from_notebookutils", Mock()) as notebook_source:
        assert get_token(AUDIENCE, runtime_token_provider=provider) == "provider-token"

    provider.assert_called_once_with(AUDIENCE)
    notebook_source.assert_not_called()


def test_get_token_order_and_token_error_fallthrough():
    calls: list[str] = []

    def source(name: str, result: str | None = None, raises: bool = False):
        def _inner(audience: str):
            calls.append(f"{name}:{audience}")
            if raises:
                raise TokenError(name)
            return result

        return _inner

    with (
        patch("fabric_core.auth._from_notebookutils", side_effect=source("notebook", raises=True)),
        patch("fabric_core.auth._from_mssparkutils", side_effect=source("msspark", result=None)),
        patch("fabric_core.auth._from_env", side_effect=source("env", raises=True)),
        patch("fabric_core.auth._from_azure_cli", side_effect=source("cli", result="cli-token")),
        patch("fabric_core.auth._from_default_credential", side_effect=source("default", result="unused")),
    ):
        assert get_token(AUDIENCE) == "cli-token"

    assert calls == [
        f"notebook:{AUDIENCE}",
        f"msspark:{AUDIENCE}",
        f"env:{AUDIENCE}",
        f"cli:{AUDIENCE}",
    ]


def test_get_token_all_sources_fail_forwards_audience_and_raises():
    calls: list[tuple[str, str]] = []

    def none_source(name: str):
        def _inner(audience: str):
            calls.append((name, audience))
            return None

        return _inner

    with (
        patch("fabric_core.auth._from_notebookutils", side_effect=none_source("notebookutils")),
        patch("fabric_core.auth._from_mssparkutils", side_effect=none_source("mssparkutils")),
        patch("fabric_core.auth._from_env", side_effect=none_source("env")),
        patch("fabric_core.auth._from_azure_cli", side_effect=none_source("azure_cli")),
        patch("fabric_core.auth._from_default_credential", side_effect=none_source("default_credential")),
        pytest.raises(TokenError, match="No Fabric credential source"),
    ):
        get_token(AUDIENCE)

    assert calls == [
        ("notebookutils", AUDIENCE),
        ("mssparkutils", AUDIENCE),
        ("env", AUDIENCE),
        ("azure_cli", AUDIENCE),
        ("default_credential", AUDIENCE),
    ]


def test_get_token_without_audience_raises_type_error():
    with pytest.raises(TypeError):
        get_token()
