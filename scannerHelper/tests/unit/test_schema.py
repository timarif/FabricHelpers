"""Tests for `fabric_scanner.spark.schema` — schema shape + column drift."""
from __future__ import annotations

import pytest


def test_result_columns_count_is_27():
    from fabric_scanner.spark.schema import RESULT_COLUMNS
    assert len(RESULT_COLUMNS) == 27


def test_result_columns_have_no_duplicates():
    from fabric_scanner.spark.schema import RESULT_COLUMNS
    assert len(set(RESULT_COLUMNS)) == len(RESULT_COLUMNS)


def test_required_columns_present():
    """Anchor specific columns the persist/runner code reads by name."""
    from fabric_scanner.spark.schema import RESULT_COLUMNS
    required = {
        "workspace_id", "workspace_name",
        "source_lakehouse_id", "source_lakehouse_name",
        "source_dated_partition",
        "notebook_id", "display_name",
        "attached_lakehouse_id", "attached_lakehouse_name",
        "finding_type", "category", "severity",
        "url", "direction",
        "dest_workspace_id", "dest_workspace_name", "cross_workspace",
        "error", "scanned_at",
    }
    assert required.issubset(set(RESULT_COLUMNS))


def test_row_dict_keys_match_schema():
    """Every row dict emitted by `_empty_row_dict` and
    `_row_dict_from_finding` must have exactly the same keys as
    RESULT_COLUMNS — otherwise the Row(**d) call inside `_emit` will
    drop columns or pyspark will complain about field mismatches."""
    from datetime import datetime, timezone

    from fabric_scanner.spark.context import PartitionContext
    from fabric_scanner.spark.partition import (
        _empty_row_dict, _row_dict_from_finding,
    )
    from fabric_scanner.spark.schema import RESULT_COLUMNS

    now = datetime.now(timezone.utc)

    empty = _empty_row_dict(
        workspace_id="w", workspace_name="W",
        notebook_id="nb-1", display_name="x.ipynb",
        scanned_at=now,
    )
    assert set(empty.keys()) == set(RESULT_COLUMNS)

    ctx = PartitionContext(mode="api")
    finding_row = _row_dict_from_finding(
        {"finding_type": "url", "category": "data", "severity": "low",
         "message": "m", "url": "https://example.com",
         "direction": "read", "line": 3, "cell_index": 0},
        ctx,
        workspace_id="w", workspace_name="W",
        notebook_id="nb-1", display_name="x.ipynb",
        scanned_at=now,
        source_lakehouse_id=None, source_lakehouse_name=None,
        source_dated_partition=None,
    )
    assert set(finding_row.keys()) == set(RESULT_COLUMNS)
