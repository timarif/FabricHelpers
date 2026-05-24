"""Tests for `fabric_scanner.spark.inventory`.

Most of these need a real SparkSession (provided by the `spark` fixture in
conftest.py, which skips when pyspark is missing or the local cluster
can't spin up — typical on Windows without JDK).

The key regression covered here: `attach_inventory_columns` must put
`workspace_id` and `source_dated_partition` onto the scan DataFrame so
the AI auditor's per-row context function can read them. Before the fix
this was only done on the snapshot projection, which is why
`run_ai_audit` crashed with `'workspace_id' is not in list`.
"""
from __future__ import annotations

from types import SimpleNamespace

from fabric_scanner.config import ScannerConfig
from fabric_scanner.spark.inventory import attach_inventory_columns


def _resolved_stub(**overrides):
    base = dict(
        source_lakehouse_id="lh-id",
        source_lakehouse_name="LH",
        source_workspace_id="ws-resolved",
        source_workspace_name="WS-Resolved",
        source_uri=None,
        source_paths=("abfss://lh/Files/notebook_exports",),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_attach_inventory_columns_universal_regex_extracts_guid(spark):
    """The dominant real-world layout:
    notebook_exports/<workspace-guid>/<datestamp>/<file>. The universal
    regex should extract both pieces and attach them to scan_df."""
    cfg = ScannerConfig(source_mode="lakehouse", source_layout="flat",
                        source_subpath="Files/notebook_exports")
    resolved = _resolved_stub()
    wsg = "abcdef01-2345-6789-abcd-ef0123456789"
    df = spark.createDataFrame(
        [(f"abfss://lh/Files/notebook_exports/{wsg}/20260524/x.ipynb", b"...")],
        ["path", "content"],
    )
    out = attach_inventory_columns(df, cfg, resolved)

    cols = set(out.columns)
    assert "workspace_id" in cols
    assert "workspace_name" in cols
    assert "source_dated_partition" in cols
    assert "path" in cols
    assert "content" in cols

    row = out.collect()[0]
    assert row["workspace_id"] == wsg
    assert row["source_dated_partition"] == "20260524"


def test_attach_inventory_columns_falls_back_to_resolved(spark):
    """Path doesn't contain a `/guid/datestamp/` segment, so
    `workspace_id` should fall back to `resolved.source_workspace_id`
    and `source_dated_partition` should be NULL."""
    cfg = ScannerConfig(source_mode="lakehouse", source_layout="flat")
    resolved = _resolved_stub()
    df = spark.createDataFrame(
        [("abfss://lh/Files/regular/x.ipynb", b"...")],
        ["path", "content"],
    )
    out = attach_inventory_columns(df, cfg, resolved)
    row = out.collect()[0]
    assert row["workspace_id"] == "ws-resolved"
    assert row["workspace_name"] == "WS-Resolved"
    assert row["source_dated_partition"] is None


def test_attach_inventory_columns_ws_dated_base_takes_priority(spark):
    """When `source_layout='ws_dated'` AND `source_uri` is set, the
    base-relative regex should win over the universal regex (it's more
    specific)."""
    cfg = ScannerConfig(source_mode="lakehouse", source_layout="ws_dated",
                        source_subpath="Files/exports")
    base = "abfss://lh/Files/exports"
    wsg = "11111111-1111-1111-1111-111111111111"
    resolved = _resolved_stub(source_uri=base, source_paths=(base,))
    df = spark.createDataFrame(
        [(f"{base}/{wsg}/20260101/n.ipynb", b"...")],
        ["path", "content"],
    )
    out = attach_inventory_columns(df, cfg, resolved)
    row = out.collect()[0]
    assert row["workspace_id"] == wsg
    assert row["source_dated_partition"] == "20260101"


def test_attach_inventory_columns_preserves_original_columns(spark):
    """The helper must not drop the original `path`/`content` columns —
    downstream `mapPartitions` consumers (rule scanner, AI auditor) rely
    on them."""
    cfg = ScannerConfig(source_mode="lakehouse")
    resolved = _resolved_stub()
    df = spark.createDataFrame(
        [("abfss://lh/Files/x.ipynb", b"abc")],
        ["path", "content"],
    )
    out = attach_inventory_columns(df, cfg, resolved)
    row = out.collect()[0]
    assert row["path"] == "abfss://lh/Files/x.ipynb"
    assert row["content"] == b"abc"
