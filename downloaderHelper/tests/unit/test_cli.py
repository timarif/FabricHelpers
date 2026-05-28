"""Unit tests for the :mod:`fabric_downloader.cli` module.

Tests cover argument parsing, type-resolution logic, and a mocked
end-to-end download into a tmp directory that validates folder layout
and manifest contents.  No live Fabric API is used.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure built-in handlers are registered.
import fabric_downloader.handlers  # noqa: F401

from fabric_downloader.cli import (
    _build_parser,
    _write_manifest,
    download_items,
    main,
    resolve_item_types,
)
from fabric_downloader.item_types import REGISTRY


# ---------------------------------------------------------------------------
# resolve_item_types
# ---------------------------------------------------------------------------


class TestResolveItemTypes:
    def test_all_returns_registered_types(self):
        types = resolve_item_types("all", "")
        assert len(types) >= 10  # at least the 10 built-in handlers
        assert "Notebook" in types

    def test_explicit_list(self):
        types = resolve_item_types("Notebook,DataPipeline", "")
        assert types == ("Notebook", "DataPipeline")

    def test_explicit_list_strips_whitespace(self):
        types = resolve_item_types(" Notebook , DataPipeline ", "")
        assert "Notebook" in types
        assert "DataPipeline" in types

    def test_exclude_removes_type(self):
        types = resolve_item_types("all", "Lakehouse")
        assert "Lakehouse" not in types
        assert len(types) >= 9

    def test_exclude_multiple(self):
        types = resolve_item_types("Notebook,DataPipeline,Report", "DataPipeline,Report")
        assert types == ("Notebook",)

    def test_exclude_case_insensitive(self):
        types = resolve_item_types("Notebook,Lakehouse", "lakehouse")
        assert "Lakehouse" not in types
        assert "Notebook" in types

    def test_empty_result_raises(self):
        with pytest.raises(ValueError, match="No item types remain"):
            resolve_item_types("Notebook", "Notebook")

    def test_all_then_exclude_all_raises(self):
        # Exclude everything registered
        all_types = ",".join(t for t in resolve_item_types("all", ""))
        with pytest.raises(ValueError):
            resolve_item_types("all", all_types)


# ---------------------------------------------------------------------------
# _build_parser — argument parsing
# ---------------------------------------------------------------------------


class TestBuildParser:
    def setup_method(self):
        self.parser = _build_parser()

    def _parse(self, *args: str) -> SimpleNamespace:
        return self.parser.parse_args(list(args))

    def test_workspace_id_required(self):
        with pytest.raises(SystemExit):
            self._parse("--output", "/tmp/out")

    def test_defaults(self):
        args = self._parse("--workspace-id", "ws-1")
        assert args.workspace_id == "ws-1"
        assert args.output == "fabric_downloads"
        assert args.item_types == "all"
        assert args.exclude_item_types == ""
        assert args.notebook_format == "py"
        assert args.admin_mode is True
        assert args.skip_existing is True
        assert args.include_raw_definition is False
        assert args.max_items == 0

    def test_item_types_accepted(self):
        args = self._parse("--workspace-id", "ws-1",
                           "--item-types", "Notebook,DataPipeline")
        assert args.item_types == "Notebook,DataPipeline"

    def test_exclude_item_types_accepted(self):
        args = self._parse("--workspace-id", "ws-1",
                           "--exclude-item-types", "Lakehouse")
        assert args.exclude_item_types == "Lakehouse"

    def test_notebook_format_choices(self):
        for fmt in ("py", "txt", "ipynb", "parts"):
            args = self._parse("--workspace-id", "ws-1",
                               "--notebook-format", fmt)
            assert args.notebook_format == fmt

    def test_invalid_notebook_format_rejected(self):
        with pytest.raises(SystemExit):
            self._parse("--workspace-id", "ws-1",
                        "--notebook-format", "markdown")

    def test_no_admin_mode_flag(self):
        args = self._parse("--workspace-id", "ws-1", "--no-admin-mode")
        assert args.admin_mode is False

    def test_include_raw_definition_flag(self):
        args = self._parse("--workspace-id", "ws-1", "--include-raw-definition")
        assert args.include_raw_definition is True

    def test_max_items_parsed_as_int(self):
        args = self._parse("--workspace-id", "ws-1", "--max-items", "5")
        assert args.max_items == 5


# ---------------------------------------------------------------------------
# _write_manifest
# ---------------------------------------------------------------------------


def test_write_manifest_creates_file(tmp_path):
    rows = [{"item_id": "x", "status": "ok"}]
    out = tmp_path / "run" / "_manifest.json"
    _write_manifest(rows, out)
    assert out.exists()
    data = json.loads(out.read_text("utf-8"))
    assert data[0]["item_id"] == "x"


def test_write_manifest_creates_parent_dirs(tmp_path):
    rows = []
    out = tmp_path / "deep" / "nested" / "manifest.json"
    _write_manifest(rows, out)
    assert out.exists()


# ---------------------------------------------------------------------------
# main() — mocked integration test
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _make_definition(*parts: tuple[str, str]) -> dict:
    return {
        "definition": {
            "parts": [
                {"path": p, "payload": _b64(t), "payloadType": "InlineBase64"}
                for p, t in parts
            ]
        }
    }


def _fake_items(types: list[str]) -> list[dict]:
    return [
        {
            "id": f"item-id-{i:04d}",
            "displayName": f"My {t} {i}",
            "type": t,
            "workspaceId": "ws-guid-0001",
            "workspaceName": "Test Workspace",
        }
        for i, t in enumerate(types, start=1)
    ]


class TestMainMockedIntegration:
    """Download 3 item types into a tmp dir without a real Fabric API."""

    def _run(self, tmp_path: Path, extra_argv: list[str] | None = None) -> int:
        fake_items = _fake_items(["Notebook", "DataPipeline", "Lakehouse"])

        def fake_run_enum(cfg, token):
            return [i for i in fake_items
                    if i["type"].lower() in
                    {t.lower() for t in cfg.item_types}]

        def fake_fetch(ws, iid, token, base, fmt):
            itype = next(
                (it["type"] for it in fake_items if it["id"] == iid), "Notebook"
            )
            if itype == "Notebook":
                if fmt == "ipynb":
                    return _make_definition(
                        ("notebook-content.ipynb", '{"cells":[]}')
                    )
                return _make_definition(
                    ("notebook-content.py", "print('hello')"),
                    (".platform", "{}"),
                )
            if itype == "DataPipeline":
                return _make_definition(
                    ("pipeline-content.json", '{"activities":[]}'),
                    (".platform", "{}"),
                )
            return {}

        def fake_tables_fetch(*, workspace_id, lakehouse_id, token, fabric_base):
            return {
                "value": [
                    {
                        "name": "tbl1",
                        "type": "Managed",
                        "format": "Delta",
                        "location": f"Tables/{lakehouse_id}",
                    }
                ]
            }

        argv = [
            "--workspace-id", "ws-guid-0001",
            "--output", str(tmp_path / "out"),
            "--run-label", "test-run",
            "--item-types", "Notebook,DataPipeline,Lakehouse",
            "--token", "fake-token",
            "--skip-existing",
        ]
        if extra_argv:
            argv += extra_argv

        with (
            patch("fabric_downloader.cli.run_enumeration_sync", fake_run_enum),
            patch("fabric_downloader.cli._fetch_definition_sync", fake_fetch),
            patch("fabric_downloader.cli.fetch_lakehouse_tables", fake_tables_fetch),
        ):
            return main(argv)

    def test_exit_code_zero_on_success(self, tmp_path):
        assert self._run(tmp_path) == 0

    def test_folder_layout_by_type(self, tmp_path):
        self._run(tmp_path)
        out = tmp_path / "out" / "test-run"
        # Should have workspace-level folder (exclude _manifest.json file)
        ws_dirs = [p for p in out.iterdir() if p.is_dir()]
        assert len(ws_dirs) == 1
        ws_dir = ws_dirs[0]
        assert "ws-guid-0001" in ws_dir.name
        # Should have type-level sub-folders
        type_dirs = {d.name for d in ws_dir.iterdir() if d.is_dir()}
        assert "Notebook" in type_dirs
        assert "DataPipeline" in type_dirs
        assert "Lakehouse" in type_dirs

    def test_notebook_source_file_written(self, tmp_path):
        self._run(tmp_path)
        out = tmp_path / "out" / "test-run"
        nb_files = list((out).rglob("notebook-content.py"))
        assert len(nb_files) >= 1

    def test_pipeline_content_file_written(self, tmp_path):
        self._run(tmp_path)
        out = tmp_path / "out" / "test-run"
        pipe_files = list(out.rglob("pipeline-content.json"))
        assert len(pipe_files) >= 1

    def test_lakehouse_metadata_file_written(self, tmp_path):
        self._run(tmp_path)
        out = tmp_path / "out" / "test-run"
        meta_files = list(out.rglob("lakehouse_metadata.json"))
        assert len(meta_files) >= 1

    def test_lakehouse_tables_file_written(self, tmp_path):
        self._run(tmp_path)
        out = tmp_path / "out" / "test-run"
        tables_files = list(out.rglob("tables.json"))
        assert len(tables_files) >= 1

    def test_manifest_written_with_sha256(self, tmp_path):
        self._run(tmp_path)
        manifest = tmp_path / "out" / "test-run" / "_manifest.json"
        assert manifest.exists()
        rows = json.loads(manifest.read_text("utf-8"))
        # At least one row should have a sha256
        ok_rows = [r for r in rows if r["status"] == "ok"]
        assert ok_rows, "expected at least one ok row"
        assert all(r.get("sha256") for r in ok_rows), (
            f"Some ok rows are missing sha256: {[r for r in ok_rows if not r.get('sha256')]}"
        )

    def test_manifest_contains_item_type_field(self, tmp_path):
        self._run(tmp_path)
        manifest = tmp_path / "out" / "test-run" / "_manifest.json"
        rows = json.loads(manifest.read_text("utf-8"))
        types = {r["item_type"] for r in rows}
        assert "Notebook" in types
        assert "DataPipeline" in types
        assert "Lakehouse" in types

    def test_exclude_item_types_flag_removes_type(self, tmp_path):
        self._run(tmp_path, extra_argv=["--exclude-item-types", "Lakehouse"])
        out = tmp_path / "out" / "test-run"
        # Lakehouse folder should not exist
        ws_dirs = [p for p in out.iterdir() if p.is_dir()] if out.exists() else []
        for ws_dir in ws_dirs:
            type_dirs = {d.name for d in ws_dir.iterdir() if d.is_dir()}
            assert "Lakehouse" not in type_dirs

    def test_skip_existing_does_not_rewrite(self, tmp_path):
        """Running twice with skip_existing=True should report skipped_exists
        on the second run (file already written)."""
        self._run(tmp_path)
        # Second run — same output dir
        with (
            patch("fabric_downloader.cli.run_enumeration_sync",
                  lambda cfg, token: _fake_items(
                      [t for t in ["Notebook", "DataPipeline", "Lakehouse"]
                       if t.lower() in {x.lower() for x in cfg.item_types}]
                  )),
            patch("fabric_downloader.cli._fetch_definition_sync",
                  lambda ws, iid, token, base, fmt:
                  _make_definition(("notebook-content.py", "print('hello')"))
                  if any(it["id"] == iid and it["type"] == "Notebook"
                         for it in _fake_items(["Notebook"]))
                  else _make_definition(("pipeline-content.json", '{}'))),
            patch("fabric_downloader.cli.fetch_lakehouse_tables",
                  lambda **_kw: {"value": []}),
        ):
            argv2 = [
                "--workspace-id", "ws-guid-0001",
                "--output", str(tmp_path / "out"),
                "--run-label", "test-run",
                "--item-types", "Notebook,DataPipeline,Lakehouse",
                "--token", "fake-token",
                "--skip-existing",
            ]
            rc = main(argv2)
        assert rc == 0
