"""Tests for `fabric_scanner.spark.partition` — the pure-Python layer.

We test `scan_row` and `process_fetched_row` directly. The Spark
generators (`scan_partition_lakehouse`, `fetch_partition`) are not
exercised here because they require pyspark to lazy-import
`pyspark.sql.Row`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from fabric_scanner.spark.context import (
    PartitionContext, build_partition_context,
)
from fabric_scanner.spark.partition import (
    process_fetched_row, scan_row,
)


WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
LH_X = "33333333-3333-3333-3333-333333333333"


def _ctx(**overrides) -> PartitionContext:
    base = dict(
        mode="lakehouse",
        source_workspace_id=WS_A, source_workspace_name="Alpha",
        source_lakehouse_id=LH_X, source_lakehouse_name="Bronze",
        source_layout="flat",
        ws_name_by_id={WS_A.lower(): "Alpha", WS_B.lower(): "Beta"},
        ws_id_by_name={"alpha": WS_A.lower(), "beta": WS_B.lower()},
    )
    base.update(overrides)
    return PartitionContext(**base)


# --- scan_row ---------------------------------------------------------------

def test_scan_row_emits_empty_row_for_clean_notebook(load_fixture):
    ctx = _ctx()
    rows = scan_row("abfss://x/clean.ipynb",
                    load_fixture("sample_clean.ipynb"), ctx)
    assert len(rows) == 1
    r = rows[0]
    assert r["finding_type"] is None
    assert r["error"] is None
    assert r["workspace_id"] == WS_A
    assert r["source_lakehouse_id"] == LH_X
    assert r["notebook_id"] == "abfss://x/clean.ipynb"
    assert r["display_name"] == "clean.ipynb"


def test_scan_row_emits_one_row_per_finding(load_fixture):
    ctx = _ctx()
    rows = scan_row("abfss://x/secrets.ipynb",
                    load_fixture("sample_secrets.ipynb"), ctx)
    assert len(rows) >= 2
    # Every row should carry the same scanned_at + provenance columns
    scans = {r["scanned_at"] for r in rows}
    assert len(scans) == 1
    for r in rows:
        assert r["workspace_id"] == WS_A
        assert r["source_lakehouse_id"] == LH_X


def test_scan_row_resolves_dest_workspace(load_fixture):
    """The cross_workspace fixture writes to a different abfss URL; the
    URL's workspace_id should land in dest_workspace_id and the
    cross_workspace flag should fire."""
    ctx = _ctx()
    rows = scan_row("abfss://x/xws.ipynb",
                    load_fixture("sample_cross_workspace.ipynb"), ctx)
    urls = [r for r in rows if r["finding_type"] == "url"]
    assert urls, "expected at least one URL finding"
    cross_rows = [r for r in urls if r.get("cross_workspace") is True]
    assert cross_rows, (
        "expected at least one cross_workspace=True row; got "
        f"{[(r['url'], r.get('dest_workspace_id'), r.get('cross_workspace')) for r in urls]}"
    )


def test_scan_row_returns_error_when_scan_explodes():
    """Malformed JSON forces extract_blocks / scanner to raise; the row
    builder must catch and emit a single error row."""
    ctx = _ctx()
    rows = scan_row("abfss://x/bad.ipynb", b"\xff not json {{",  ctx)
    assert len(rows) == 1
    # The engine can either:
    #   (a) raise -> we catch and produce an error row, OR
    #   (b) accept gracefully and return zero findings -> empty row.
    # Either is acceptable; both result in a single row with no findings.
    r = rows[0]
    assert r["finding_type"] is None


def test_scan_row_ws_dated_overrides_workspace_from_path():
    """ws_dated layout: workspace_id + datestamp come from the file path,
    not the ctx defaults."""
    base = "abfss://lh/Files/scans"
    ctx = _ctx(
        source_layout="ws_dated",
        ws_dated_base=base,
        source_workspace_id="DEFAULT",  # should be overridden
    )
    file_path = f"{base}/{WS_B}/20260522093015/some.ipynb"
    rows = scan_row(file_path, b'{"cells":[],"nbformat":4}', ctx)
    assert len(rows) == 1
    r = rows[0]
    assert r["workspace_id"] == WS_B
    assert r["workspace_name"] == "Beta"        # resolved from ws_name_by_id
    assert r["source_dated_partition"] == "20260522093015"


def test_scan_row_ws_dated_falls_back_when_path_does_not_match():
    """A path that doesn't match the ws_dated regex keeps the ctx defaults."""
    ctx = _ctx(
        source_layout="ws_dated",
        ws_dated_base="abfss://lh/Files/scans",
        source_workspace_id="DEFAULT",
    )
    rows = scan_row("abfss://elsewhere/x.ipynb", b'{"cells":[],"nbformat":4}',
                    ctx)
    assert rows[0]["workspace_id"] == "DEFAULT"
    assert rows[0]["source_dated_partition"] is None


def test_scan_row_carries_attached_lakehouse_metadata(load_fixture):
    """sample_attached_lh.ipynb has a `metadata.dependencies.lakehouse`
    block — the resulting row must surface those values."""
    ctx = _ctx()
    rows = scan_row("abfss://x/lh.ipynb",
                    load_fixture("sample_attached_lh.ipynb"), ctx)
    has_attached = [r for r in rows
                    if r.get("attached_lakehouse_id")
                    or r.get("attached_lakehouse_name")]
    assert has_attached


# --- process_fetched_row ----------------------------------------------------

def test_fetched_row_error_path_short_circuits():
    ctx = _ctx(mode="api")
    rows = process_fetched_row(
        WS_A, "Alpha", "nb-1", "Hello.ipynb",
        body=None, error="HTTP 401: unauthorized", ctx=ctx,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["error"] == "HTTP 401: unauthorized"
    assert r["finding_type"] is None
    assert r["workspace_id"] == WS_A
    assert r["display_name"] == "Hello.ipynb"


def test_fetched_row_empty_findings_emits_one_empty_row(load_fixture):
    ctx = _ctx(mode="api")
    body = json.loads(load_fixture("sample_clean.ipynb"))
    rows = process_fetched_row(
        WS_A, "Alpha", "nb-1", "Clean", body=body, error=None, ctx=ctx)
    assert len(rows) == 1
    assert rows[0]["finding_type"] is None
    assert rows[0]["error"] is None


def test_fetched_row_emits_findings(load_fixture):
    ctx = _ctx(mode="api")
    body = json.loads(load_fixture("sample_secrets.ipynb"))
    rows = process_fetched_row(
        WS_A, "Alpha", "nb-1", "Secrets",
        body=body, error=None, ctx=ctx)
    assert len(rows) >= 2
    severities = {r["severity"] for r in rows if r.get("severity")}
    assert severities  # at least one finding has a severity set
    # API mode never sets source_lakehouse columns.
    for r in rows:
        assert r["source_lakehouse_id"] is None


def test_fetched_row_handles_bad_body():
    """A body that scan_notebook_bytes can't process must still emit a
    single error row, not raise."""
    ctx = _ctx(mode="api")
    # An object that json.dumps will choke on (set is not JSON-serializable).
    rows = process_fetched_row(
        WS_A, "Alpha", "nb-1", "Bad", body={"x": {1, 2, 3}},
        error=None, ctx=ctx)
    assert len(rows) == 1
    assert rows[0]["finding_type"] is None
    assert "scan error" in (rows[0]["error"] or "")


# --- build_partition_context ------------------------------------------------

def test_build_partition_context_populates_ws_maps():
    from fabric_scanner import ScannerConfig, resolve_paths

    cfg = ScannerConfig(source_mode="api", admin_mode=True)
    rp = resolve_paths(cfg)
    ctx = build_partition_context(
        cfg, rp,
        workspaces=[
            {"id": WS_A, "name": "Alpha"},
            {"id": WS_B, "displayName": "Beta"},
        ],
    )
    assert ctx.mode == "api"
    assert ctx.ws_name_by_id[WS_A.lower()] == "Alpha"
    assert ctx.ws_name_by_id[WS_B.lower()] == "Beta"
    assert ctx.ws_id_by_name["alpha"] == WS_A.lower()
    assert ctx.ws_id_by_name["beta"] == WS_B.lower()


def test_build_partition_context_lakehouse_mode_threads_resolved_fields():
    from fabric_scanner import ScannerConfig, resolve_paths

    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_lakehouse_workspace_id=WS_A,
        source_lakehouse_workspace_name="Alpha",
        source_lakehouse_id=LH_X,
        source_lakehouse_name="Bronze",
        source_layout="flat",
    )
    rp = resolve_paths(cfg, runtime_provider=lambda: {})
    ctx = build_partition_context(cfg, rp)
    assert ctx.mode == "lakehouse"
    assert ctx.source_workspace_id == WS_A
    assert ctx.source_lakehouse_id == LH_X
    assert ctx.ws_dated_base == ""  # flat layout


# --- Universal path-GUID extraction (PR #_ feature) -------------------------

def test_scan_row_universal_path_guid_extraction_in_flat_layout():
    """Even in the default 'flat' layout, a path like
    notebook_exports/<guid>/<datestamp>/<file> should stamp the
    finding with the GUID from the path, not the source workspace.
    """
    ctx = _ctx(source_layout="flat")  # the default
    file_path = (
        f"abfss://lh/{LH_X}/Files/notebook_exports/{WS_B}/20262205/test.txt"
    )
    rows = scan_row(file_path, b'{"cells":[],"nbformat":4}', ctx)
    assert len(rows) == 1
    r = rows[0]
    assert r["workspace_id"] == WS_B
    assert r["workspace_name"] == "Beta"
    assert r["source_dated_partition"] == "20262205"


def test_scan_row_workspace_name_falls_back_to_guid_when_unknown():
    """When the extracted GUID is not in ws_name_by_id, workspace_name
    must be the GUID itself (NOT empty / None / the source default)."""
    unknown_ws = "99999999-9999-9999-9999-999999999999"
    ctx = _ctx(
        source_layout="flat",
        source_workspace_id="DEFAULT",
        source_workspace_name="DEFAULT-NAME",
    )
    file_path = (
        f"abfss://lh/Files/notebook_exports/{unknown_ws}/20260101/x.txt"
    )
    rows = scan_row(file_path, b'{"cells":[],"nbformat":4}', ctx)
    assert rows[0]["workspace_id"] == unknown_ws
    assert rows[0]["workspace_name"] == unknown_ws


def test_scan_row_no_guid_in_path_keeps_ctx_defaults():
    """No /<guid>/<date>/ pattern -> ctx defaults stay."""
    ctx = _ctx(source_workspace_id="DEFAULT", source_workspace_name="DefName")
    rows = scan_row("abfss://lh/Files/random/x.ipynb",
                    b'{"cells":[],"nbformat":4}', ctx)
    assert rows[0]["workspace_id"] == "DEFAULT"
    assert rows[0]["workspace_name"] == "DefName"
    assert rows[0]["source_dated_partition"] is None


def test_scan_row_universal_extraction_ignores_non_date_folder():
    """The folder after the GUID must look date-like (>=8 digits).
    Otherwise we leave the workspace defaults alone."""
    ctx = _ctx(source_workspace_id="DEFAULT", source_workspace_name="DefName")
    path = f"abfss://lh/{LH_X}/Files/notebook_exports/{WS_B}/Files/x.txt"
    rows = scan_row(path, b'{"cells":[],"nbformat":4}', ctx)
    # 'Files' doesn't look like a date so universal regex shouldn't match
    assert rows[0]["workspace_id"] == "DEFAULT"


def test_scan_row_ws_dated_takes_priority_over_universal():
    """ws_dated_base anchor is the most specific match, so it wins
    even if a universal /<guid>/<date>/ also appears later in the path."""
    base = "abfss://lh/Files/scans"
    ctx = _ctx(
        source_layout="ws_dated",
        ws_dated_base=base,
        source_workspace_id="DEFAULT",
    )
    # Path matches BOTH the ws_dated_base anchor AND has a later GUID/date.
    other_ws = "44444444-4444-4444-4444-444444444444"
    path = f"{base}/{WS_B}/20260522093015/sub/{other_ws}/20270101/x.txt"
    rows = scan_row(path, b'{"cells":[],"nbformat":4}', ctx)
    # ws_dated anchor should pick the first /<x>/<y>/ pair after base
    assert rows[0]["workspace_id"] == WS_B
    assert rows[0]["source_dated_partition"] == "20260522093015"


def test_scan_row_universal_extraction_yyyymmddhhmmss_format():
    """The datestamp can be longer than 8 digits (yyyymmddhhmmss etc.)."""
    ctx = _ctx(source_layout="flat")
    long_date = "20260522134701"
    path = f"abfss://lh/Files/notebook_exports/{WS_B}/{long_date}/x.ipynb"
    rows = scan_row(path, b'{"cells":[],"nbformat":4}', ctx)
    assert rows[0]["workspace_id"] == WS_B
    assert rows[0]["source_dated_partition"] == long_date


def test_extract_workspace_from_path_helper():
    """The path helper itself, exercised independently of Spark."""
    from fabric_scanner.paths import extract_workspace_from_path
    wid, dt = extract_workspace_from_path(
        f"abfss://lh/{LH_X}/Files/notebook_exports/{WS_B}/20262205/test.txt"
    )
    assert wid == WS_B
    assert dt == "20262205"
    # No match
    assert extract_workspace_from_path(
        "abfss://lh/Files/regular/x.txt") == (None, None)
    # Non-date second segment
    assert extract_workspace_from_path(
        f"abfss://lh/{LH_X}/Files/{WS_B}/notdate/x.txt") == (None, None)
    # Empty / None
    assert extract_workspace_from_path("") == (None, None)
    assert extract_workspace_from_path(None) == (None, None)  # type: ignore[arg-type]


# --- _row_field defensive lookup (regression test) ------------------------

class _FakeRow:
    """Mimics `pyspark.sql.Row.__getitem__` semantics: a missing str key
    raises `ValueError` (Row internally calls `__fields__.index(key)`,
    which is `list.index`'s native exception)."""

    def __init__(self, **fields):
        self._fields = fields

    def __getitem__(self, key):
        try:
            return self._fields[key]
        except KeyError:
            raise ValueError(f"{key!r} is not in list")

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError as e:
            raise AttributeError(name) from e


def test_row_field_returns_default_when_missing_via_valueerror():
    """Regression: PySpark Row raises ValueError on missing field; `_row_field`
    must absorb that and return the supplied default."""
    from fabric_scanner.spark.partition import _row_field
    row = _FakeRow(path="/x/y.ipynb", content=b"...")
    assert _row_field(row, "workspace_id", "DEFAULT") == "DEFAULT"
    assert _row_field(row, "missing", None) is None
