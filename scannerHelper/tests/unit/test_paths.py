"""Tests for `fabric_scanner.paths` — pure path math + ws_dated enumeration."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from fabric_scanner import ScannerConfig
from fabric_scanner.paths import (
    ONELAKE_HOST,
    files_path,
    table_path,
    enumerate_dated_workspace_dirs,
    resolve_paths,
)


WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
LH_X = "33333333-3333-3333-3333-333333333333"
LH_Y = "44444444-4444-4444-4444-444444444444"


def _entry(name: str, path: str, is_dir: bool) -> SimpleNamespace:
    """Build a fake fs.ls entry that matches notebookutils' contract."""
    return SimpleNamespace(name=name, path=path, isDir=is_dir)


# --- Path math --------------------------------------------------------------

def test_table_path_without_schema():
    assert table_path(WS_A, LH_X, "t1") == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Tables/t1")


def test_table_path_with_schema():
    assert table_path(WS_A, LH_X, "t1", schema="bronze") == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Tables/bronze/t1")


def test_files_path_with_subpath():
    assert files_path(WS_A, LH_X, "Files/notebooks") == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/notebooks")


def test_files_path_strips_leading_slash():
    assert files_path(WS_A, LH_X, "/Files/data") == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/data")


def test_files_path_root_when_empty():
    assert files_path(WS_A, LH_X, "") == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}")


# --- enumerate_dated_workspace_dirs ----------------------------------------

def test_enumerate_dated_picks_lex_max():
    """Two workspaces, three dated subdirs each; selects the lex-max one."""
    base = f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/scans"

    def fake_ls(path: str):
        if path == base:
            return [
                _entry(WS_A, f"{base}/{WS_A}", True),
                _entry(WS_B, f"{base}/{WS_B}", True),
                _entry("not-a-folder.txt", f"{base}/not-a-folder.txt", False),
            ]
        if path == f"{base}/{WS_A}":
            return [
                _entry("20240101", f"{base}/{WS_A}/20240101", True),
                _entry("20260522", f"{base}/{WS_A}/20260522", True),
                _entry("20250619", f"{base}/{WS_A}/20250619", True),
            ]
        if path == f"{base}/{WS_B}":
            return [
                _entry("20240101120000", f"{base}/{WS_B}/20240101120000",
                       True),
                _entry("20260522093015", f"{base}/{WS_B}/20260522093015",
                       True),
            ]
        return []

    out = enumerate_dated_workspace_dirs(base, ls=fake_ls)
    assert len(out) == 2
    by_ws = {d["workspace_id"]: d for d in out}
    assert by_ws[WS_A]["datestamp"] == "20260522"
    assert by_ws[WS_A]["dir_path"] == f"{base}/{WS_A}/20260522"
    assert by_ws[WS_B]["datestamp"] == "20260522093015"


def test_enumerate_dated_skips_workspaces_without_subdirs():
    base = f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/scans"

    def fake_ls(path: str):
        if path == base:
            return [
                _entry(WS_A, f"{base}/{WS_A}", True),
                _entry(WS_B, f"{base}/{WS_B}", True),
            ]
        if path == f"{base}/{WS_A}":
            return [_entry("20260101", f"{base}/{WS_A}/20260101", True)]
        if path == f"{base}/{WS_B}":
            return []  # empty workspace folder — must be skipped
        return []

    out = enumerate_dated_workspace_dirs(base, ls=fake_ls)
    assert len(out) == 1
    assert out[0]["workspace_id"] == WS_A


def test_enumerate_dated_raises_when_base_listing_fails():
    def boom(_path: str):
        raise PermissionError("denied")

    with pytest.raises(RuntimeError, match="could not list base path"):
        enumerate_dated_workspace_dirs("abfss://nope/", ls=boom)


def test_enumerate_dated_skips_workspace_when_inner_ls_fails():
    base = f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/scans"

    def fake_ls(path: str):
        if path == base:
            return [
                _entry(WS_A, f"{base}/{WS_A}", True),
                _entry(WS_B, f"{base}/{WS_B}", True),
            ]
        if path == f"{base}/{WS_A}":
            return [_entry("20260101", f"{base}/{WS_A}/20260101", True)]
        raise PermissionError("inner failed")

    out = enumerate_dated_workspace_dirs(base, ls=fake_ls)
    assert len(out) == 1
    assert out[0]["workspace_id"] == WS_A


# --- resolve_paths -----------------------------------------------------------

def test_resolve_paths_api_mode_skips_runtime_and_listing():
    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    rp = resolve_paths(cfg)
    assert rp.source_uri is None
    assert rp.source_paths == ()
    assert rp.dated_index == {}
    assert "admin scanner" in rp.source_kind_label.lower()
    assert rp.runtime == {}
    assert rp.inventory_target == "v2_inventory"
    assert "saveAsTable" in rp.write_kind


def test_resolve_paths_lakehouse_flat_with_explicit_lh():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_id=LH_X,
        source_subpath="Files/notebooks",
        source_layout="flat",
    )
    rp = resolve_paths(cfg, runtime_provider=lambda: {})
    assert rp.source_uri == (f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/"
                             f"Files/notebooks")
    assert rp.source_paths == (rp.source_uri,)
    assert rp.dated_index == {}


def test_resolve_paths_lakehouse_auto_fills_from_runtime():
    cfg = ScannerConfig(source_mode="lakehouse")
    fake_runtime = {
        "default_lakehouse_id": LH_X,
        "default_lakehouse_name": "Bronze",
        "default_lakehouse_workspace_id": WS_A,
        "default_lakehouse_workspace_name": "MyWorkspace",
        "current_workspace_id": WS_A,
    }
    rp = resolve_paths(cfg, runtime_provider=lambda: fake_runtime)
    assert rp.source_workspace_id == WS_A
    assert rp.source_lakehouse_id == LH_X
    assert rp.source_lakehouse_name == "Bronze"
    assert "mounted lakehouse" in rp.source_kind_label.lower()
    assert rp.source_uri is not None
    assert WS_A in rp.source_uri and LH_X in rp.source_uri


def test_resolve_paths_explicit_config_wins_over_runtime():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_lakehouse_workspace_id=WS_B,
        source_lakehouse_id=LH_Y,
    )
    fake_runtime = {
        "default_lakehouse_id": LH_X,
        "default_lakehouse_workspace_id": WS_A,
    }
    rp = resolve_paths(cfg, runtime_provider=lambda: fake_runtime)
    assert rp.source_workspace_id == WS_B
    assert rp.source_lakehouse_id == LH_Y


def test_resolve_paths_lakehouse_no_lh_info_falls_back_to_relative():
    cfg = ScannerConfig(source_mode="lakehouse",
                        source_subpath="Files/notebooks")
    rp = resolve_paths(cfg, runtime_provider=lambda: {})
    assert rp.source_uri == "Files/notebooks"
    assert "could not detect" in rp.source_kind_label.lower()


def test_resolve_paths_ws_dated_requires_source_lh():
    cfg = ScannerConfig(source_mode="lakehouse", source_layout="ws_dated")
    with pytest.raises(RuntimeError, match="requires a known source"):
        resolve_paths(cfg, runtime_provider=lambda: {})


def test_resolve_paths_ws_dated_raises_on_empty_enum():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_layout="ws_dated",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_id=LH_X,
    )
    with pytest.raises(RuntimeError, match="found 0 workspace folders"):
        resolve_paths(cfg, runtime_provider=lambda: {}, ls=lambda _p: [])


def test_resolve_paths_ws_dated_populates_index_and_paths():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_layout="ws_dated",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_id=LH_X,
        source_subpath="Files/scans",
    )

    expected_base = (f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Files/scans")

    def fake_ls(path: str):
        if path == expected_base:
            return [_entry(WS_B, f"{expected_base}/{WS_B}", True)]
        if path == f"{expected_base}/{WS_B}":
            return [_entry("20260522", f"{expected_base}/{WS_B}/20260522",
                           True)]
        return []

    rp = resolve_paths(cfg, runtime_provider=lambda: {}, ls=fake_ls)
    assert rp.dated_index == {WS_B: "20260522"}
    assert rp.source_paths == (f"{expected_base}/{WS_B}/20260522",)


def test_resolve_paths_explicit_write_path():
    cfg = ScannerConfig(
        source_mode="api",
        write_to_default_lakehouse=False,
        write_workspace_id=WS_A,
        write_lakehouse_id=LH_X,
        write_schema="bronze",
        inventory_table="my_inv",
        output_table="my_out",
    )
    rp = resolve_paths(cfg)
    assert rp.inventory_target == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Tables/bronze/my_inv")
    assert rp.output_target == (
        f"abfss://{WS_A}@{ONELAKE_HOST}/{LH_X}/Tables/bronze/my_out")
    assert "ABFSS" in rp.write_kind
