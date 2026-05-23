"""Unit tests for DownloaderConfig validation, serialization, and
per-type format helpers."""
from __future__ import annotations

import pytest

from fabric_downloader import DownloaderConfig
from fabric_downloader.config import KNOWN_ITEM_TYPES, DEFAULT_FORMAT_BY_TYPE


# -------------------- defaults --------------------


def test_default_config_is_notebook_ipynb_mode():
    cfg = DownloaderConfig()
    assert cfg.item_types == ("Notebook",)
    assert cfg.format_for("Notebook") == "ipynb"
    assert cfg.export_mode_for("Notebook") == "ipynb"
    assert cfg.export_mode_for("DataPipeline") == "parts"
    assert cfg.write_to_default_lakehouse is True


def test_known_item_types_covers_documented_set():
    for t in ("Notebook", "DataPipeline", "Dataflow",
              "Report", "SemanticModel"):
        assert t in KNOWN_ITEM_TYPES


def test_default_format_by_type_only_overrides_notebook():
    assert DEFAULT_FORMAT_BY_TYPE == {"Notebook": "ipynb"}


# -------------------- validation --------------------


def test_empty_item_types_rejected():
    with pytest.raises(ValueError, match="item_types"):
        DownloaderConfig(item_types=())


def test_blank_item_type_rejected():
    with pytest.raises(ValueError, match="non-empty strings"):
        DownloaderConfig(item_types=("",))


def test_blank_output_root_rejected():
    with pytest.raises(ValueError, match="output_root"):
        DownloaderConfig(output_root="")


def test_executor_concurrency_must_be_positive():
    with pytest.raises(ValueError, match="executor_concurrency"):
        DownloaderConfig(executor_concurrency=0)


def test_negative_retries_rejected():
    with pytest.raises(ValueError, match="max_retries"):
        DownloaderConfig(max_retries=-1)


def test_external_lakehouse_requires_both_ids():
    with pytest.raises(ValueError, match="write_workspace_id"):
        DownloaderConfig(
            write_to_default_lakehouse=False,
            write_workspace_id="ws",
            # missing write_lakehouse_id
        )


def test_external_lakehouse_accepted_with_both_ids():
    cfg = DownloaderConfig(
        write_to_default_lakehouse=False,
        write_workspace_id="ws-1",
        write_lakehouse_id="lh-1",
    )
    assert cfg.write_to_default_lakehouse is False
    assert cfg.write_workspace_id == "ws-1"


# -------------------- format / export_mode --------------------


def test_format_for_returns_none_when_no_override():
    cfg = DownloaderConfig(item_types=("DataPipeline",),
                           format_by_type={})
    assert cfg.format_for("DataPipeline") is None
    assert cfg.export_mode_for("DataPipeline") == "parts"


def test_export_mode_for_notebook_when_overridden_to_ipynb():
    cfg = DownloaderConfig(format_by_type={"Notebook": "ipynb"})
    assert cfg.export_mode_for("Notebook") == "ipynb"


def test_export_mode_for_falls_back_to_parts_for_non_ipynb_overrides():
    cfg = DownloaderConfig(
        item_types=("Report",),
        format_by_type={"Report": "pbix"},
    )
    assert cfg.format_for("Report") == "pbix"
    assert cfg.export_mode_for("Report") == "parts"


# -------------------- from_dict / to_dict --------------------


def test_from_dict_round_trip():
    cfg = DownloaderConfig(
        item_types=("Notebook", "DataPipeline"),
        format_by_type={"Notebook": "ipynb"},
        admin_mode=False,
        max_items=10,
        skip_existing=False,
    )
    d = cfg.to_dict()
    cfg2 = DownloaderConfig.from_dict(d)
    assert cfg2 == cfg


def test_from_dict_accepts_list_for_tuple_fields():
    cfg = DownloaderConfig.from_dict({
        "item_types": ["Notebook", "DataPipeline"],
        "read_workspace_ids": ["ws-1", "ws-2"],
    })
    assert cfg.item_types == ("Notebook", "DataPipeline")
    assert cfg.read_workspace_ids == ("ws-1", "ws-2")


def test_from_dict_rejects_unknown_fields():
    with pytest.raises(TypeError, match="Unknown DownloaderConfig fields"):
        DownloaderConfig.from_dict({"bogus_field": True})


def test_to_dict_serializes_tuples_and_mappings_to_plain():
    cfg = DownloaderConfig(item_types=("Notebook", "DataPipeline"))
    d = cfg.to_dict()
    assert d["item_types"] == ["Notebook", "DataPipeline"]
    assert isinstance(d["format_by_type"], dict)


# -------------------- immutability --------------------


def test_config_is_frozen():
    cfg = DownloaderConfig()
    with pytest.raises(Exception):
        cfg.output_root = "other"  # type: ignore[misc]
