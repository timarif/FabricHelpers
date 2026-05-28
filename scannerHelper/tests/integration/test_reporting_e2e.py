from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fabric_scanner import ScannerConfig
from fabric_scanner.spark import run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="Spark integration tests are skipped on Windows.",
    ),
]

_WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
_DATE_PARTITION = "20260101010101"
_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source" / _WORKSPACE_ID / _DATE_PARTITION
    root.mkdir(parents=True, exist_ok=True)
    return root


def _copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    src_root = _source_root(tmp_path)
    fixture = _FIXTURES_DIR / fixture_name
    dst = src_root / fixture_name
    shutil.copyfile(fixture, dst)
    return tmp_path / "source"


def _delta_rows(spark, reporting_path: Path) -> list[dict]:
    return [
        row.asDict(recursive=True)
        for row in spark.read.format("delta").load(str(reporting_path / "fact_scan_findings")).collect()
    ]


def _table_name(prefix: str, tmp_path: Path) -> str:
    suffix = "".join(ch if ch.isalnum() else "_" for ch in tmp_path.name).lower()
    return f"{prefix}_{suffix}"


@pytest.fixture
def _require_delta(spark, tmp_path):
    pytest.importorskip("delta")
    probe = tmp_path / "_delta_probe"
    try:
        spark.range(1).write.format("delta").mode("overwrite").save(str(probe))
        spark.read.format("delta").load(str(probe)).count()
    except Exception as exc:
        pytest.skip(f"Delta not available in this Spark session: {exc}")


def test_reporting_e2e_writes_findings_to_lakehouse(tmp_path, spark, _require_delta):
    source_path = _copy_fixture(tmp_path, "sample_secrets.ipynb")
    reporting_path = tmp_path / "reporting"
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_subpath=str(source_path),
        reporting_lakehouse=str(reporting_path),
        inventory_table=_table_name("v2_inventory", tmp_path),
        output_table=_table_name("v2_findings", tmp_path),
    )

    result = run(cfg, spark, compute_summary=False)
    rows = _delta_rows(spark, reporting_path)

    assert result.findings_count > 0
    assert len(rows) == result.findings_count

    finding_rows = [r for r in rows if r["kind"] is not None]
    assert finding_rows
    first = finding_rows[0]
    assert first["scan_run_id"]
    assert first["workspace_id"] == _WORKSPACE_ID
    assert first["notebook_id"]
    assert first["kind"]
    assert first["severity"]
    assert first["detected_at"] is not None


def test_reporting_e2e_flag_off_skips_adapter(tmp_path, spark, _require_delta):
    source_path = _copy_fixture(tmp_path, "sample_secrets.ipynb")
    reporting_path = tmp_path / "reporting"
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_subpath=str(source_path),
        inventory_table=_table_name("v2_inventory", tmp_path),
        output_table=_table_name("v2_findings", tmp_path),
    )

    result = run(cfg, spark, compute_summary=False)

    assert result.findings_count > 0
    assert not reporting_path.exists()


def test_reporting_e2e_no_findings_writes_placeholder_row(tmp_path, spark, _require_delta):
    source_path = _copy_fixture(tmp_path, "sample_clean.ipynb")
    reporting_path = tmp_path / "reporting"
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_subpath=str(source_path),
        reporting_lakehouse=str(reporting_path),
        min_severity="critical",
        inventory_table=_table_name("v2_inventory", tmp_path),
        output_table=_table_name("v2_findings", tmp_path),
    )

    result = run(cfg, spark, compute_summary=False)
    rows = _delta_rows(spark, reporting_path)

    assert result.findings_count == 1
    assert len(rows) == 1
    assert rows[0]["kind"] is None
    assert rows[0]["severity"] is None


def _fixed_uuid4_factory():
    counter = 0

    def _fixed_uuid4():
        nonlocal counter
        counter += 1
        return uuid.UUID(int=counter)

    return _fixed_uuid4


def test_reporting_e2e_idempotent_rescan_same_scan_id(tmp_path, spark, monkeypatch, _require_delta):
    source_path = _copy_fixture(tmp_path, "sample_secrets.ipynb")
    reporting_path = tmp_path / "reporting"
    cfg = ScannerConfig(
        source_mode="lakehouse",
        source_subpath=str(source_path),
        reporting_lakehouse=str(reporting_path),
        inventory_table=_table_name("v2_inventory", tmp_path),
        output_table=_table_name("v2_findings", tmp_path),
    )

    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr("fabric_scanner.spark.runner.datetime", _FixedDatetime)
    monkeypatch.setattr("fabric_scanner.reporting.uuid.uuid4", _fixed_uuid4_factory())
    first = run(cfg, spark, compute_summary=False)
    first_count = len(_delta_rows(spark, reporting_path))

    monkeypatch.setattr("fabric_scanner.reporting.uuid.uuid4", _fixed_uuid4_factory())
    second = run(cfg, spark, compute_summary=False)
    second_count = len(_delta_rows(spark, reporting_path))

    assert first.findings_count > 0
    assert first.findings_count == second.findings_count
    assert first_count == first.findings_count
    assert second_count == first_count
