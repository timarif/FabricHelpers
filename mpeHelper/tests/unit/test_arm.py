"""Tests for ``fabric_mpe.arm`` resource-provider / api-version helpers."""
from __future__ import annotations

import pytest

from fabric_mpe.arm import (
    PEC_API_VERSIONS,
    PEC_DEFAULT_API_VERSION,
    pec_api_version,
    rp_from_resource_id,
)


def _id(rp: str, name: str = "x") -> str:
    return f"/subscriptions/00000000/resourceGroups/rg/providers/{rp}/{name}"


@pytest.mark.parametrize(
    "rp,name",
    [
        ("Microsoft.Storage/storageAccounts", "acct"),
        ("Microsoft.Sql/servers", "srv"),
        ("Microsoft.KeyVault/vaults", "kv"),
    ],
)
def test_rp_from_resource_id_extracts_two_segment_rp(rp, name):
    assert rp_from_resource_id(_id(rp, name)) == rp


def test_rp_from_resource_id_handles_nested_paths():
    rid = (
        "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/"
        "storageAccounts/acct/blobServices/default/containers/c1"
    )
    assert rp_from_resource_id(rid) == "Microsoft.Storage/storageAccounts"


@pytest.mark.parametrize("bad", [None, "", "not-a-resource-id", "/subscriptions/x"])
def test_rp_from_resource_id_returns_none_for_invalid_inputs(bad):
    assert rp_from_resource_id(bad) is None


def test_pec_api_version_returns_known_rp_and_version():
    rid = _id("Microsoft.Storage/storageAccounts")
    api, rp = pec_api_version(rid)
    assert rp == "Microsoft.Storage/storageAccounts"
    assert api == PEC_API_VERSIONS["Microsoft.Storage/storageAccounts"]


def test_pec_api_version_returns_default_for_unknown_rp():
    rid = _id("Contoso.Custom/widgets")
    api, rp = pec_api_version(rid)
    assert rp == "Contoso.Custom/widgets"
    assert api == PEC_DEFAULT_API_VERSION


def test_pec_api_version_returns_default_for_unparseable_id():
    api, rp = pec_api_version(None)
    assert rp is None
    assert api == PEC_DEFAULT_API_VERSION
