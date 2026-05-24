"""Tests for ``fabric_mpe.config``."""
from __future__ import annotations

import pytest

from fabric_mpe import MpeConfig


def test_defaults_are_safe_preview_only():
    cfg = MpeConfig()
    assert cfg.workspace_scope == "visible"
    assert cfg.commit is False
    assert cfg.recreate is False
    assert cfg.approve is False
    assert cfg.recreate_source == "audit"
    assert cfg.fabric_base.startswith("https://api.fabric.")
    assert cfg.arm_base.startswith("https://management.")


def test_delta_target_uses_schema_when_set():
    assert MpeConfig().delta_target("t") == "t"
    cfg = MpeConfig(write_schema="bronze")
    assert cfg.delta_target("t") == "bronze.t"


def test_files_dir_uses_mounted_files_path_and_run_label():
    cfg = MpeConfig(files_subdir="mpe", run_label="r1")
    assert cfg.files_dir() == "/lakehouse/default/Files/mpe/r1"
    assert cfg.files_dir("r2") == "/lakehouse/default/Files/mpe/r2"


def test_invalid_workspace_scope_rejected():
    with pytest.raises(ValueError, match="workspace_scope"):
        MpeConfig(workspace_scope="bogus")  # type: ignore[arg-type]


def test_list_scope_requires_workspaces():
    with pytest.raises(ValueError, match="workspaces"):
        MpeConfig(workspace_scope="list")


def test_invalid_recreate_source_rejected():
    with pytest.raises(ValueError, match="recreate_source"):
        MpeConfig(recreate_source="other")  # type: ignore[arg-type]


@pytest.mark.parametrize("kw", ["max_deletes", "max_recreates", "max_approves", "max_retries"])
def test_caps_must_be_positive(kw):
    with pytest.raises(ValueError, match=kw):
        MpeConfig(**{kw: 0})


def test_request_timeout_must_be_positive():
    with pytest.raises(ValueError, match="request_timeout"):
        MpeConfig(request_timeout=0)


def test_from_dict_rejects_unknown_keys():
    with pytest.raises(TypeError, match="Unknown"):
        MpeConfig.from_dict({"bogus": 1})


def test_to_dict_round_trips():
    cfg = MpeConfig(
        workspace_scope="list",
        workspaces=("ws-a", "ws-b"),
        commit=True,
        run_label="r1",
    )
    rebuilt = MpeConfig.from_dict(cfg.to_dict())
    assert rebuilt == cfg
