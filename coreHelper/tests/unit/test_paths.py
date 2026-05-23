"""Unit tests for shared fabric_core.paths helpers."""
from __future__ import annotations

import builtins
import sys
from types import ModuleType, SimpleNamespace

import pytest

from fabric_core import paths
from fabric_core.paths import ONELAKE_HOST, files_path, files_uri, fs_ls, table_path


WS = "11111111-1111-1111-1111-111111111111"
LH = "22222222-2222-2222-2222-222222222222"


def module(name: str, **attrs) -> ModuleType:
    mod = ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def block_runtime_imports(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {"notebookutils", "mssparkutils"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_onelake_host_constant():
    assert ONELAKE_HOST == "onelake.dfs.fabric.microsoft.com"


@pytest.mark.parametrize(
    "table,schema,expected_suffix",
    [
        ("inventory", None, f"/{LH}/Tables/inventory"),
        ("scan_results", "bronze", f"/{LH}/Tables/bronze/scan_results"),
    ],
)
def test_table_path_builds_abfss_table_paths(table, schema, expected_suffix):
    assert table_path(WS, LH, table, schema) == f"abfss://{WS}@{ONELAKE_HOST}{expected_suffix}"


def test_table_path_accepts_schema_keyword():
    assert table_path("ws", "lh", "facts", schema="dbo") == (
        f"abfss://ws@{ONELAKE_HOST}/lh/Tables/dbo/facts"
    )


@pytest.mark.parametrize(
    "subpath,expected",
    [
        ("", f"abfss://{WS}@{ONELAKE_HOST}/{LH}"),
        ("Files/notebooks", f"abfss://{WS}@{ONELAKE_HOST}/{LH}/Files/notebooks"),
        ("/Files/data", f"abfss://{WS}@{ONELAKE_HOST}/{LH}/Files/data"),
        ("Files/data/", f"abfss://{WS}@{ONELAKE_HOST}/{LH}/Files/data/"),
    ],
)
def test_files_path_handles_subpaths(subpath, expected):
    assert files_path(WS, LH, subpath) == expected


def test_files_uri_defaults_to_files_section():
    assert files_uri("ws", "lh") == f"abfss://ws@{ONELAKE_HOST}/lh/Files"


@pytest.mark.parametrize(
    "subpath,expected",
    [
        ("Files/sub", f"abfss://ws@{ONELAKE_HOST}/lh/Files/sub"),
        ("", f"abfss://ws@{ONELAKE_HOST}/lh"),
    ],
)
def test_files_uri_uses_files_path_rules(subpath, expected):
    assert files_uri("ws", "lh", subpath) == expected


def test_import_nbu_prefers_notebookutils(monkeypatch):
    notebookutils = module("notebookutils")
    mssparkutils = module("mssparkutils")
    monkeypatch.setitem(sys.modules, "notebookutils", notebookutils)
    monkeypatch.setitem(sys.modules, "mssparkutils", mssparkutils)

    assert paths._import_nbu() is notebookutils


def test_import_nbu_falls_back_to_mssparkutils(monkeypatch):
    mssparkutils = module("mssparkutils")
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)
    monkeypatch.setitem(sys.modules, "mssparkutils", mssparkutils)

    assert paths._import_nbu() is mssparkutils


def test_import_nbu_returns_none_when_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)
    monkeypatch.delitem(sys.modules, "mssparkutils", raising=False)
    block_runtime_imports(monkeypatch)

    assert paths._import_nbu() is None


def test_detect_notebook_runtime_reads_dict_context(monkeypatch):
    fake_nbu = SimpleNamespace(runtime=SimpleNamespace(context={
        "currentWorkspaceId": "current-ws-id",
        "currentWorkspaceName": "Current WS",
        "defaultLakehouseId": "default-lh-id",
        "defaultLakehouseName": "Default LH",
        "defaultLakehouseWorkspaceId": "default-ws-id",
        "defaultLakehouseWorkspaceName": "Default WS",
    }))
    monkeypatch.setattr(paths, "_import_nbu", lambda: fake_nbu)

    assert paths.detect_notebook_runtime() == {
        "current_workspace_id": "current-ws-id",
        "current_workspace_name": "Current WS",
        "default_lakehouse_id": "default-lh-id",
        "default_lakehouse_name": "Default LH",
        "default_lakehouse_workspace_id": "default-ws-id",
        "default_lakehouse_workspace_name": "Default WS",
    }


def test_detect_notebook_runtime_reads_attribute_context_and_synapse_keys(monkeypatch):
    ctx = SimpleNamespace(
        workspaceId="synapse-ws-id",
        workspaceName="Synapse WS",
        defaultLakehouse="synapse-lh-id",
    )
    fake_nbu = SimpleNamespace(runtime=SimpleNamespace(context=ctx))
    monkeypatch.setattr(paths, "_import_nbu", lambda: fake_nbu)

    assert paths.detect_notebook_runtime() == {
        "current_workspace_id": "synapse-ws-id",
        "current_workspace_name": "Synapse WS",
        "default_lakehouse_id": "synapse-lh-id",
        "default_lakehouse_name": "",
        "default_lakehouse_workspace_id": "",
        "default_lakehouse_workspace_name": "",
    }


def test_detect_notebook_runtime_returns_empty_when_import_missing(monkeypatch):
    monkeypatch.setattr(paths, "_import_nbu", lambda: None)

    assert paths.detect_notebook_runtime() == {}


def test_detect_notebook_runtime_returns_empty_when_context_unavailable(monkeypatch):
    fake_nbu = SimpleNamespace(runtime=SimpleNamespace())
    monkeypatch.setattr(paths, "_import_nbu", lambda: fake_nbu)

    assert paths.detect_notebook_runtime() == {}


def test_fs_ls_calls_runtime_listing(monkeypatch):
    calls: list[str] = []
    entries = [SimpleNamespace(name="folder", isDir=True)]

    def ls(path):
        calls.append(path)
        return entries

    fake_nbu = SimpleNamespace(fs=SimpleNamespace(ls=ls))
    monkeypatch.setattr(paths, "_import_nbu", lambda: fake_nbu)

    assert fs_ls("abfss://ws/lh/Files") is entries
    assert calls == ["abfss://ws/lh/Files"]


def test_fs_ls_raises_import_error_when_runtime_missing(monkeypatch):
    monkeypatch.setattr(paths, "_import_nbu", lambda: None)

    with pytest.raises(ImportError, match="notebookutils / mssparkutils"):
        fs_ls("abfss://ws/lh/Files")
