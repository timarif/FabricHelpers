"""Tests for `fabric_scanner.diagnostics.probe` — lakehouse + API modes."""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from fabric_scanner import ScannerConfig
from fabric_scanner.diagnostics import probe
from fabric_scanner.paths import resolve_paths


WS_A = "11111111-1111-1111-1111-111111111111"
LH_X = "33333333-3333-3333-3333-333333333333"


def _entry(name, path, is_dir):
    return SimpleNamespace(name=name, path=path, isDir=is_dir)


def test_probe_lakehouse_prints_summary_and_listing():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_id=LH_X,
        source_subpath="Files/notebooks",
    )
    rp = resolve_paths(cfg, runtime_provider=lambda: {})

    def fake_ls(_path):
        return [
            _entry("a.ipynb", f"{rp.source_uri}/a.ipynb", False),
            _entry("b.ipynb", f"{rp.source_uri}/b.ipynb", False),
            _entry("sub",     f"{rp.source_uri}/sub",     True),
        ]

    buf = io.StringIO()
    probe(cfg, rp, ls=fake_ls, stream=buf)
    out = buf.getvalue()
    assert "Lakehouse mode" in out
    assert rp.source_uri in out
    assert "Top-level entries: 3" in out
    assert "2 files, 1 folders" in out


def test_probe_lakehouse_warns_when_no_lh_known():
    cfg = ScannerConfig(source_mode="lakehouse")
    rp = resolve_paths(cfg, runtime_provider=lambda: {})

    buf = io.StringIO()
    probe(cfg, rp, ls=lambda _p: [], stream=buf)
    out = buf.getvalue()
    assert "[WARN]" in out


def test_probe_lakehouse_handles_ls_failure():
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_id=LH_X,
    )
    rp = resolve_paths(cfg, runtime_provider=lambda: {})

    def boom(_p):
        raise PermissionError("denied")

    buf = io.StringIO()
    probe(cfg, rp, ls=boom, stream=buf)
    assert "[ERR]" in buf.getvalue()


def test_probe_api_requires_token():
    cfg = ScannerConfig(source_mode="api")
    rp = resolve_paths(cfg)
    with pytest.raises(ValueError, match="requires a token"):
        probe(cfg, rp)


def test_probe_api_prints_status_for_each_endpoint():
    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    rp = resolve_paths(cfg)

    calls: list[str] = []

    def fake_http_get(url, headers, params):
        calls.append(url)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"value": [{}, {}]},
            text='{"value": []}',
        )

    buf = io.StringIO()
    probe(cfg, rp, token="TOKEN", http_get=fake_http_get, stream=buf)
    out = buf.getvalue()
    # Exactly four endpoints should be probed (each prints "[200]").
    assert out.count("[200]") == 4
    assert any("admin/groups" in u for u in calls)
    assert any("admin/workspaces" in u for u in calls)
    assert any("admin/items" in u for u in calls)
    assert any("/v1/workspaces" in u for u in calls)


def test_probe_api_logs_exception_as_err():
    cfg = ScannerConfig(source_mode="api", admin_mode=False)
    rp = resolve_paths(cfg)

    def boom(_u, _h, _p):
        raise ConnectionError("network down")

    buf = io.StringIO()
    probe(cfg, rp, token="T", http_get=boom, stream=buf)
    out = buf.getvalue()
    assert "[ERR]" in out
    assert "ConnectionError" in out
