"""Unit tests for :mod:`fabric_splitter.classify`."""
from __future__ import annotations

import pytest

from fabric_splitter.classify import classify


# ---------------------------------------------------------------------------
# Basic classification
# ---------------------------------------------------------------------------


def test_classify_puts_matching_types_in_a():
    items = [
        {"id": "nb1", "type": "Notebook", "displayName": "NB 1"},
        {"id": "rpt1", "type": "Report", "displayName": "Rpt 1"},
    ]
    result = classify(items, types_to_a={"notebook"})
    assert result == {"nb1": "A", "rpt1": "B"}


def test_classify_puts_all_in_b_when_types_empty():
    items = [
        {"id": "nb1", "type": "Notebook"},
        {"id": "lh1", "type": "Lakehouse"},
    ]
    result = classify(items, types_to_a=set())
    assert result == {"nb1": "B", "lh1": "B"}


def test_classify_puts_all_in_a_when_all_types_listed():
    items = [
        {"id": "nb1", "type": "Notebook"},
        {"id": "lh1", "type": "Lakehouse"},
    ]
    result = classify(items, {"notebook", "lakehouse"})
    assert result == {"nb1": "A", "lh1": "A"}


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_classify_is_case_insensitive_allow_list():
    items = [{"id": "nb1", "type": "Notebook"}]
    assert classify(items, {"NOTEBOOK"})["nb1"] == "A"
    assert classify(items, {"notebook"})["nb1"] == "A"
    assert classify(items, {"NoTeBooK"})["nb1"] == "A"


def test_classify_is_case_insensitive_item_type():
    items = [{"id": "nb1", "type": "NOTEBOOK"}]
    assert classify(items, {"notebook"})["nb1"] == "A"


# ---------------------------------------------------------------------------
# itemType field alias
# ---------------------------------------------------------------------------


def test_classify_accepts_itemtype_field():
    items = [{"id": "sm1", "itemType": "SemanticModel"}]
    result = classify(items, {"semanticmodel"})
    assert result["sm1"] == "A"


# ---------------------------------------------------------------------------
# Items without id
# ---------------------------------------------------------------------------


def test_classify_skips_items_with_no_id():
    items = [
        {"type": "Notebook"},          # no id — skipped
        {"id": "nb1", "type": "Notebook"},
    ]
    result = classify(items, {"notebook"})
    assert result == {"nb1": "A"}


# ---------------------------------------------------------------------------
# Multiple types to A
# ---------------------------------------------------------------------------


def test_classify_multiple_types_to_a():
    items = [
        {"id": "nb1", "type": "Notebook"},
        {"id": "lh1", "type": "Lakehouse"},
        {"id": "dp1", "type": "DataPipeline"},
        {"id": "sm1", "type": "SemanticModel"},
        {"id": "rpt1", "type": "Report"},
    ]
    result = classify(items, {"notebook", "lakehouse", "datapipeline"})
    assert result["nb1"] == "A"
    assert result["lh1"] == "A"
    assert result["dp1"] == "A"
    assert result["sm1"] == "B"
    assert result["rpt1"] == "B"


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_classify_empty_items_returns_empty_dict():
    assert classify([], {"notebook"}) == {}


def test_classify_whitespace_only_types_ignored():
    items = [{"id": "nb1", "type": "Notebook"}]
    # "  " should be stripped and treated as empty → not matched
    result = classify(items, {"  "})
    assert result["nb1"] == "B"
