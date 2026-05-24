"""Tests for ``fabric_mpe.auth`` shim over ``fabric_core.auth``."""
from __future__ import annotations

from unittest.mock import patch

from fabric_mpe import MpeConfig
from fabric_mpe.auth import (
    ARM_SPN_CLIENT_ENV,
    ARM_SPN_SECRET_ENV,
    ARM_SPN_TENANT_ENV,
    ARM_TOKEN_ENV,
    get_arm_token,
    get_fabric_token,
)


def test_get_fabric_token_delegates_to_core_with_audience():
    cfg = MpeConfig(token_audience="https://aud.example/")
    with patch("fabric_mpe.auth.get_token", return_value="tok") as gt:
        assert get_fabric_token(cfg) == "tok"
    gt.assert_called_once_with("https://aud.example/")


def test_get_arm_token_uses_arm_token_env_when_set():
    cfg = MpeConfig()
    with patch.dict("os.environ", {ARM_TOKEN_ENV: "  paste-tok  "}, clear=True), patch(
        "fabric_mpe.auth.get_token"
    ) as gt, patch("fabric_mpe.auth.fetch_token_via_client_credentials") as fc:
        assert get_arm_token(cfg) == "paste-tok"
    gt.assert_not_called()
    fc.assert_not_called()


def test_get_arm_token_uses_arm_spn_env_when_all_three_set():
    cfg = MpeConfig(arm_audience="https://management.azure.com")
    env = {
        ARM_SPN_TENANT_ENV: "tenant",
        ARM_SPN_CLIENT_ENV: "client",
        ARM_SPN_SECRET_ENV: "secret",
    }
    with patch.dict("os.environ", env, clear=True), patch(
        "fabric_mpe.auth.fetch_token_via_client_credentials",
        return_value="spn-tok",
    ) as fc, patch("fabric_mpe.auth.get_token") as gt:
        assert get_arm_token(cfg) == "spn-tok"

    fc.assert_called_once()
    _args, kwargs = fc.call_args
    assert kwargs["scope"] == "https://management.azure.com/.default"
    gt.assert_not_called()


def test_get_arm_token_falls_back_to_core_chain_when_no_env_vars():
    cfg = MpeConfig(arm_audience="https://management.azure.com")
    with patch.dict("os.environ", {}, clear=True), patch(
        "fabric_mpe.auth.get_token", return_value="core-tok"
    ) as gt:
        assert get_arm_token(cfg) == "core-tok"
    gt.assert_called_once_with("https://management.azure.com")
