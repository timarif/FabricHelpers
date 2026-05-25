"""Unit tests for ``fabric_reporting.models``.

Covers:
- Happy-path validation for every canonical table model.
- Rejection of rows with invalid field values.
- ``validate_rows`` helper for batch validation.
- ``TABLE_REGISTRY`` completeness.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from fabric_reporting.models import (
    CANONICAL_TABLES,
    TABLE_REGISTRY,
    DimItemType,
    DimSeverity,
    DimWorkspace,
    FactDownload,
    FactMpeLifecycle,
    FactScanFinding,
    validate_rows,
)

_NOW = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TABLE_REGISTRY completeness
# ---------------------------------------------------------------------------

def test_registry_has_six_tables():
    assert len(TABLE_REGISTRY) == 6


def test_canonical_tables_match_registry():
    assert set(CANONICAL_TABLES) == set(TABLE_REGISTRY)


def test_registry_contains_expected_names():
    expected = {
        "fact_scan_findings",
        "fact_downloads",
        "fact_mpe_lifecycle",
        "dim_workspace",
        "dim_item_type",
        "dim_severity",
    }
    assert set(TABLE_REGISTRY) == expected


# ---------------------------------------------------------------------------
# FactScanFinding
# ---------------------------------------------------------------------------

class TestFactScanFinding:
    def _valid(self, **overrides) -> dict:
        base = {
            "finding_id": "abc-123",
            "scan_run_id": "run-2024",
            "workspace_id": "ws-guid",
            "source_dated_partition": "2024-01-15",
            "notebook_id": "nb-guid",
            "severity": "high",
            "kind": "entropy",
            "redacted_snippet": "tok = '***'",
            "url": None,
            "detected_at": _NOW,
        }
        base.update(overrides)
        return base

    def test_happy_path(self):
        row = FactScanFinding.model_validate(self._valid())
        assert row.finding_id == "abc-123"
        assert row.severity == "high"

    def test_all_optional_fields_none(self):
        row = FactScanFinding.model_validate({"finding_id": "x"})
        assert row.scan_run_id is None

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError, match="severity"):
            FactScanFinding.model_validate(self._valid(severity="critical-plus"))

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            FactScanFinding.model_validate(self._valid(bogus_field="oops"))

    def test_missing_pk_rejected(self):
        """finding_id is required (no default)."""
        with pytest.raises(ValidationError):
            FactScanFinding.model_validate({})


# ---------------------------------------------------------------------------
# FactDownload
# ---------------------------------------------------------------------------

class TestFactDownload:
    def _valid(self, **overrides) -> dict:
        base = {
            "download_id": "dl-001",
            "run_id": "run-2024",
            "workspace_id": "ws-guid",
            "item_id": "item-guid",
            "item_type": "Notebook",
            "format": "ipynb",
            "downloaded_at": _NOW,
            "bytes": 4096,
            "sha256": "deadbeef" * 8,
        }
        base.update(overrides)
        return base

    def test_happy_path(self):
        row = FactDownload.model_validate(self._valid())
        assert row.download_id == "dl-001"
        assert row.bytes == 4096

    def test_negative_bytes_rejected(self):
        with pytest.raises(ValidationError, match="bytes"):
            FactDownload.model_validate(self._valid(bytes=-1))

    def test_zero_bytes_allowed(self):
        row = FactDownload.model_validate(self._valid(bytes=0))
        assert row.bytes == 0

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            FactDownload.model_validate(self._valid(extra_col="x"))


# ---------------------------------------------------------------------------
# FactMpeLifecycle
# ---------------------------------------------------------------------------

class TestFactMpeLifecycle:
    def _valid(self, **overrides) -> dict:
        base = {
            "event_id": "evt-001",
            "workspace_id": "ws-guid",
            "mpe_id": "mpe-guid",
            "target_resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/privateEndpoints/pe",
            "action": "created",
            "actor": "admin@contoso.com",
            "timestamp": _NOW,
        }
        base.update(overrides)
        return base

    def test_happy_path(self):
        row = FactMpeLifecycle.model_validate(self._valid())
        assert row.action == "created"

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError, match="action"):
            FactMpeLifecycle.model_validate(self._valid(action="updated"))

    @pytest.mark.parametrize("action", ["created", "deleted", "approved"])
    def test_all_valid_actions(self, action):
        row = FactMpeLifecycle.model_validate(self._valid(action=action))
        assert row.action == action


# ---------------------------------------------------------------------------
# DimWorkspace
# ---------------------------------------------------------------------------

class TestDimWorkspace:
    def test_happy_path(self):
        row = DimWorkspace.model_validate({
            "workspace_id": "ws-001",
            "workspace_name": "My WS",
            "capacity_id": "cap-guid",
            "last_seen": _NOW,
        })
        assert row.workspace_id == "ws-001"

    def test_optional_fields_default_none(self):
        row = DimWorkspace.model_validate({"workspace_id": "ws-001"})
        assert row.workspace_name is None
        assert row.capacity_id is None

    def test_missing_pk_rejected(self):
        with pytest.raises(ValidationError):
            DimWorkspace.model_validate({})


# ---------------------------------------------------------------------------
# DimItemType
# ---------------------------------------------------------------------------

class TestDimItemType:
    def test_happy_path(self):
        row = DimItemType.model_validate({"item_type": "Notebook", "family": "data_engineering"})
        assert row.item_type == "Notebook"
        assert row.family == "data_engineering"

    def test_family_optional(self):
        row = DimItemType.model_validate({"item_type": "Pipeline"})
        assert row.family is None


# ---------------------------------------------------------------------------
# DimSeverity
# ---------------------------------------------------------------------------

class TestDimSeverity:
    def test_happy_path(self):
        row = DimSeverity.model_validate({"severity": "critical", "ordinal": 0, "color": "#C00000"})
        assert row.ordinal == 0

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            DimSeverity.model_validate({"severity": "blocker", "ordinal": 0})

    def test_negative_ordinal_rejected(self):
        with pytest.raises(ValidationError, match="ordinal"):
            DimSeverity.model_validate({"severity": "low", "ordinal": -1})

    @pytest.mark.parametrize("severity", ["low", "medium", "high", "critical"])
    def test_all_severities_valid(self, severity):
        row = DimSeverity.model_validate({"severity": severity, "ordinal": 0})
        assert row.severity == severity


# ---------------------------------------------------------------------------
# validate_rows helper
# ---------------------------------------------------------------------------

class TestValidateRows:
    def test_empty_list_returns_empty(self):
        result = validate_rows("fact_scan_findings", [])
        assert result == []

    def test_single_valid_row(self):
        rows = validate_rows("fact_scan_findings", [{"finding_id": "x"}])
        assert len(rows) == 1
        assert rows[0].finding_id == "x"

    def test_multiple_rows(self):
        rows = validate_rows("dim_severity", [
            {"severity": "critical", "ordinal": 0},
            {"severity": "high", "ordinal": 1},
        ])
        assert len(rows) == 2

    def test_unknown_table_raises_key_error(self):
        with pytest.raises(KeyError, match="no_such_table"):
            validate_rows("no_such_table", [])

    def test_invalid_row_raises_validation_error(self):
        with pytest.raises(ValidationError):
            validate_rows("fact_scan_findings", [{"finding_id": "x", "severity": "oops"}])
