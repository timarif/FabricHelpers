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


# ---- SPN client-credentials source ----------------------------------------


SPN_VARS = {
    auth.SPN_TENANT_ENV: "tenant",
    auth.SPN_CLIENT_ENV: "client",
    auth.SPN_SECRET_ENV: "secret",
}


def _spn_token_response(payload):
    body = __import__("json").dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

        def read(self_inner):
            return body

    return _Resp()


def test_fetch_token_via_client_credentials_success_posts_form_and_returns_token():
    captured = {}

    def fake_open(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["timeout"] = timeout
        return _spn_token_response({"access_token": "spn-tok", "token_type": "Bearer"})

    token = auth.fetch_token_via_client_credentials(
        "tenant-id", "client-id", "shh", scope="https://aud/.default", opener=fake_open
    )
    assert token == "spn-tok"
    assert captured["url"] == "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token"
    assert captured["method"] == "POST"
    assert b"grant_type=client_credentials" in captured["data"]
    assert b"client_id=client-id" in captured["data"]
    assert b"client_secret=shh" in captured["data"]
    assert b"scope=https%3A%2F%2Faud%2F.default" in captured["data"]


def test_fetch_token_via_client_credentials_missing_args_raise_token_error():
    with pytest.raises(TokenError):
        auth.fetch_token_via_client_credentials("", "c", "s", scope="x")
    with pytest.raises(TokenError):
        auth.fetch_token_via_client_credentials("t", "", "s", scope="x")
    with pytest.raises(TokenError):
        auth.fetch_token_via_client_credentials("t", "c", "", scope="x")


def test_fetch_token_via_client_credentials_endpoint_error_wraps_as_token_error():
    def fake_open(*_a, **_k):
        raise OSError("network down")

    with pytest.raises(TokenError, match="OSError"):
        auth.fetch_token_via_client_credentials("t", "c", "s", scope="x", opener=fake_open)


def test_fetch_token_via_client_credentials_missing_access_token_raises():
    def fake_open(*_a, **_k):
        return _spn_token_response({"error": "invalid_client"})

    with pytest.raises(TokenError, match="did not return access_token"):
        auth.fetch_token_via_client_credentials("t", "c", "s", scope="x", opener=fake_open)


def test_from_spn_env_returns_none_when_any_var_missing():
    with patch.dict("os.environ", {}, clear=True):
        assert auth._from_spn_env(AUDIENCE) is None

    partial = dict(SPN_VARS)
    partial.pop(auth.SPN_SECRET_ENV)
    with patch.dict("os.environ", partial, clear=True):
        assert auth._from_spn_env(AUDIENCE) is None


def test_from_spn_env_calls_token_endpoint_and_returns_token():
    captured = {}

    def fake_fetch(tenant, client, secret, *, scope, timeout=30.0, opener=None):
        captured["args"] = (tenant, client, secret, scope)
        return "env-spn-tok"

    with patch.dict("os.environ", SPN_VARS, clear=True), patch(
        "fabric_core.auth.fetch_token_via_client_credentials", side_effect=fake_fetch
    ):
        assert auth._from_spn_env("https://api.fabric.microsoft.com") == "env-spn-tok"

    tenant, client, secret, scope = captured["args"]
    assert (tenant, client, secret) == ("tenant", "client", "secret")
    assert scope == "https://api.fabric.microsoft.com/.default"


def test_from_spn_env_returns_none_when_fetch_raises_token_error():
    def boom(*_a, **_k):
        raise TokenError("nope")

    with patch.dict("os.environ", SPN_VARS, clear=True), patch(
        "fabric_core.auth.fetch_token_via_client_credentials", side_effect=boom
    ):
        assert auth._from_spn_env(AUDIENCE) is None


def test_from_spn_env_passes_scope_unchanged_when_already_dot_default():
    captured = {}

    def fake_fetch(*_a, **kwargs):
        captured["scope"] = kwargs["scope"]
        return "tok"

    with patch.dict("os.environ", SPN_VARS, clear=True), patch(
        "fabric_core.auth.fetch_token_via_client_credentials", side_effect=fake_fetch
    ):
        auth._from_spn_env("https://management.azure.com/.default")

    assert captured["scope"] == "https://management.azure.com/.default"


def test_get_token_uses_spn_env_after_env_vars_and_before_cli():
    calls: list[str] = []

    def source(name, result=None):
        def _inner(audience):
            calls.append(name)
            return result

        return _inner

    with (
        patch("fabric_core.auth._from_notebookutils", side_effect=source("notebook")),
        patch("fabric_core.auth._from_mssparkutils", side_effect=source("msspark")),
        patch("fabric_core.auth._from_env", side_effect=source("env")),
        patch("fabric_core.auth._from_spn_env", side_effect=source("spn", result="spn-tok")),
        patch("fabric_core.auth._from_azure_cli", side_effect=source("cli", result="cli-tok")),
        patch("fabric_core.auth._from_default_credential", side_effect=source("default")),
    ):
        assert get_token(AUDIENCE) == "spn-tok"

    assert calls == ["notebook", "msspark", "env", "spn"]
