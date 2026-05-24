"""Unit tests for :mod:`fabric_downloader.item_types` — the registry,
:class:`ItemHandler` ABC, and helper utilities."""
from __future__ import annotations

import base64
import json

import pytest

from fabric_downloader.item_types import (
    REGISTRY,
    ItemHandler,
    _decode_part,
    _parts_from_body,
    _safe_path,
    generic_parts_to_files,
    register,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _make_handler(name: str, itype: str) -> type[ItemHandler]:
    """Dynamically create a concrete ItemHandler subclass for testing."""

    class _Handler(ItemHandler):
        item_type = itype

        def to_files(self, item, definition):
            return generic_parts_to_files(definition)

    _Handler.__name__ = name
    _Handler.__qualname__ = name
    return _Handler


# ---------------------------------------------------------------------------
# Registry: register / lookup
# ---------------------------------------------------------------------------


def test_register_and_lookup():
    H = _make_handler("TestHandler_lookup", "TestType_lookup")
    register(H)
    assert REGISTRY["testtype_lookup"] is H


def test_register_is_idempotent_for_same_class():
    H = _make_handler("TestHandler_idem", "TestType_idem")
    register(H)
    register(H)  # second call must not raise
    assert REGISTRY["testtype_idem"] is H


def test_register_raises_on_duplicate_different_class():
    H1 = _make_handler("H_dup1", "TestType_dup")
    H2 = _make_handler("H_dup2", "TestType_dup")
    register(H1)
    with pytest.raises(ValueError, match="already registered"):
        register(H2)


def test_register_decorator_returns_class():
    H = _make_handler("TestHandler_ret", "TestType_ret")
    result = register(H)
    assert result is H


# ---------------------------------------------------------------------------
# Registry: built-in handlers are pre-registered
# ---------------------------------------------------------------------------


def test_builtin_handlers_registered_after_import():
    """Importing fabric_downloader.handlers populates REGISTRY with all
    ten built-in handlers."""
    import fabric_downloader.handlers  # noqa: F401 (side-effect import)

    expected = {
        "notebook",
        "semanticmodel",
        "report",
        "dataflow",
        "datapipeline",
        "sparkjobdefinition",
        "kqldatabase",
        "eventstream",
        "environment",
        "lakehouse",
    }
    assert expected.issubset(REGISTRY.keys()), (
        f"Missing handlers: {expected - set(REGISTRY.keys())}"
    )


# ---------------------------------------------------------------------------
# _decode_part
# ---------------------------------------------------------------------------


def test_decode_part_decodes_base64():
    part = {"payload": _b64("hello world")}
    assert _decode_part(part) == b"hello world"


def test_decode_part_empty_payload():
    assert _decode_part({"payload": ""}) == b""
    assert _decode_part({}) == b""


# ---------------------------------------------------------------------------
# _parts_from_body
# ---------------------------------------------------------------------------


def test_parts_from_body_standard():
    body = {"definition": {"parts": [{"path": "a.json", "payload": _b64("x")}]}}
    parts = _parts_from_body(body)
    assert len(parts) == 1
    assert parts[0]["path"] == "a.json"


def test_parts_from_body_missing_definition():
    assert _parts_from_body({}) == []
    assert _parts_from_body({"definition": {}}) == []


# ---------------------------------------------------------------------------
# _safe_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("pipeline-content.json",    "pipeline-content.json"),
    ("sub/path/file.json",       "sub__path__file.json"),
    (".platform",                "platform"),
    ("",                         "part"),
])
def test_safe_path(raw, expected):
    assert _safe_path(raw) == expected


# ---------------------------------------------------------------------------
# generic_parts_to_files
# ---------------------------------------------------------------------------


def test_generic_parts_to_files_decodes_all_parts():
    body = {
        "definition": {
            "parts": [
                {"path": "pipeline-content.json", "payload": _b64('{"a":1}')},
                {"path": ".platform",             "payload": _b64("plat")},
            ]
        }
    }
    files = generic_parts_to_files(body)
    assert "pipeline-content.json" in files
    assert files["pipeline-content.json"] == b'{"a":1}'
    assert ".platform" in files
    assert files[".platform"] == b"plat"


def test_generic_parts_to_files_skips_empty_payload():
    body = {
        "definition": {
            "parts": [
                {"path": "empty.json", "payload": ""},
                {"path": "ok.json",    "payload": _b64("data")},
            ]
        }
    }
    files = generic_parts_to_files(body)
    assert "empty.json" not in files
    assert "ok.json" in files


def test_generic_parts_to_files_empty_body():
    assert generic_parts_to_files({}) == {}
