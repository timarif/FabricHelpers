"""Tests for `fabric_scanner.api.auth.get_token`."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from fabric_scanner.api.auth import TokenError, get_token


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Strip Fabric/Azure env tokens for every test so we control the
    resolution order explicitly."""
    monkeypatch.delenv("FABRIC_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("AZURE_ACCESS_TOKEN", raising=False)


@pytest.fixture
def no_runtime_modules(monkeypatch):
    """Ensure neither notebookutils nor mssparkutils is importable.

    We replace builtins.__import__ with a wrapper that still honors
    sys.modules (so tests can pre-install fakes) but raises ImportError
    when the runtime modules are not pre-installed.
    """
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)
    monkeypatch.delitem(sys.modules, "mssparkutils", raising=False)
    real_import = __import__

    def fake_import(name, *a, **kw):
        if name in ("notebookutils", "mssparkutils") and name not in sys.modules:
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", fake_import)


def _install_fake(monkeypatch, mod_name: str, audience_token: dict):
    """Install a fake notebookutils/mssparkutils into sys.modules."""
    creds = SimpleNamespace(
        getToken=lambda aud: audience_token.get(aud))
    mod = SimpleNamespace(credentials=creds)
    monkeypatch.setitem(sys.modules, mod_name, mod)


def test_runtime_provider_wins(no_runtime_modules):
    t = get_token("https://api.fabric.microsoft.com",
                  runtime_token_provider=lambda _a: "INJECTED-TOKEN")
    assert t == "INJECTED-TOKEN"


def test_falls_back_to_notebookutils(monkeypatch, no_runtime_modules):
    _install_fake(monkeypatch, "notebookutils",
                  {"https://api.fabric.microsoft.com": "NBU-TOKEN"})
    t = get_token("https://api.fabric.microsoft.com")
    assert t == "NBU-TOKEN"


def test_falls_back_to_mssparkutils(monkeypatch, no_runtime_modules):
    _install_fake(monkeypatch, "mssparkutils",
                  {"https://api.fabric.microsoft.com": "MSS-TOKEN"})
    t = get_token("https://api.fabric.microsoft.com")
    assert t == "MSS-TOKEN"


def test_falls_back_to_env(no_runtime_modules, monkeypatch):
    monkeypatch.setenv("FABRIC_BEARER_TOKEN", "ENV-TOKEN")
    t = get_token("https://api.fabric.microsoft.com")
    assert t == "ENV-TOKEN"


def test_azure_env_var_also_works(no_runtime_modules, monkeypatch):
    monkeypatch.setenv("AZURE_ACCESS_TOKEN", "AZ-TOKEN")
    t = get_token("https://api.fabric.microsoft.com")
    assert t == "AZ-TOKEN"


def test_raises_when_no_source(no_runtime_modules):
    with pytest.raises(TokenError, match="No Fabric credential source"):
        get_token("https://api.fabric.microsoft.com")


def test_default_audience():
    """Default audience matches the Fabric REST API host."""
    with pytest.raises(TokenError):
        get_token()  # no token sources, but exercises default arg
