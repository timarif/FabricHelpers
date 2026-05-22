"""Tests for cross-workspace URL parsing and resolution."""
from __future__ import annotations

from fabric_scanner.engine.resolve import (
    parse_dest_workspace,
    resolve_dest_workspace,
    GUID_RE,
    WORKSPACE_URL_RE,
)


WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
LH_X = "33333333-3333-3333-3333-333333333333"


def test_parse_abfss():
    url = f"abfss://{WS_B}@onelake.dfs.fabric.microsoft.com/{LH_X}/Files/x"
    assert parse_dest_workspace(url) == WS_B


def test_parse_fabric_api():
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{WS_B}/items"
    assert parse_dest_workspace(url) == WS_B


def test_parse_powerbi_groups():
    url = f"https://app.powerbi.com/groups/{WS_B}/datasets/abc"
    assert parse_dest_workspace(url) == WS_B


def test_parse_returns_none_for_non_workspace_url():
    assert parse_dest_workspace("https://example.com/foo") is None
    assert parse_dest_workspace("") is None
    assert parse_dest_workspace(None) is None


def test_resolve_cross_workspace_true():
    url = f"abfss://{WS_B}@onelake.dfs.fabric.microsoft.com/{LH_X}/Files/x"
    dest_id, dest_name, cross = resolve_dest_workspace(
        url, WS_A, "src-ws", ws_name_by_id={WS_B: "Analytics"})
    assert dest_id == WS_B
    assert dest_name == "Analytics"
    assert cross is True


def test_resolve_cross_workspace_false():
    url = f"abfss://{WS_A}@onelake.dfs.fabric.microsoft.com/{LH_X}/Files/x"
    dest_id, _, cross = resolve_dest_workspace(
        url, WS_A, "src-ws", ws_name_by_id={WS_A: "Src"})
    assert dest_id == WS_A
    assert cross is False


def test_resolve_unknown_dest_keeps_id_drops_name():
    url = f"abfss://{WS_B}@onelake.dfs.fabric.microsoft.com/{LH_X}/Files/x"
    dest_id, dest_name, cross = resolve_dest_workspace(
        url, WS_A, "src-ws", ws_name_by_id={})
    assert dest_id == WS_B
    assert dest_name is None
    assert cross is True


def test_resolve_no_workspace_returns_none_tuple():
    dest_id, dest_name, cross = resolve_dest_workspace(
        "https://example.com/", WS_A, "src", ws_name_by_id={})
    assert (dest_id, dest_name, cross) == (None, None, None)


def test_guid_re_matches_with_and_without_dashes():
    assert GUID_RE.match("11111111-1111-1111-1111-111111111111")
    assert GUID_RE.match("11111111111111111111111111111111")
    assert not GUID_RE.match("not-a-guid")
