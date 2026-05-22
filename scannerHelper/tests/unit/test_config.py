"""Tests for `fabric_scanner.config.ScannerConfig`."""
from __future__ import annotations

import pytest

from fabric_scanner import ScannerConfig
from fabric_scanner.config import ScannerConfig as DataclassRef


def test_defaults_match_api_mode():
    cfg = ScannerConfig()
    assert cfg.source_mode == "api"
    assert cfg.source_layout == "flat"
    assert cfg.min_severity == "low"
    assert cfg.scan_markdown_and_outputs is True
    assert cfg.executor_concurrency == 16
    assert cfg.max_snippet_bytes == 256
    assert cfg.read_workspace_ids == ()


def test_is_frozen():
    cfg = ScannerConfig()
    with pytest.raises(Exception):
        cfg.source_mode = "lakehouse"


@pytest.mark.parametrize("field,value,err", [
    ("source_mode", "files", "source_mode"),
    ("source_layout", "wsdated", "source_layout"),
    ("min_severity", "info", "min_severity"),
    ("executor_concurrency", 0, "executor_concurrency"),
    ("target_partition_size", 0, "target_partition_size"),
    ("max_snippet_bytes", 5, "max_snippet_bytes"),
])
def test_invalid_field_rejected(field, value, err):
    with pytest.raises(ValueError, match=err):
        ScannerConfig(**{field: value})


def test_from_dict_round_trip():
    cfg = ScannerConfig(source_mode="lakehouse",
                        source_layout="ws_dated",
                        min_severity="high",
                        max_snippet_bytes=128)
    d = cfg.to_dict()
    cfg2 = ScannerConfig.from_dict(d)
    assert cfg == cfg2


def test_from_dict_rejects_unknown_field():
    with pytest.raises(TypeError, match="bogus"):
        ScannerConfig.from_dict({"source_mode": "api", "bogus": 1})


def test_dataclass_identity():
    assert DataclassRef is ScannerConfig
