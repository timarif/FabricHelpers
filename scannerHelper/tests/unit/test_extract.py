"""Tests for the multi-format content extractor + attached-lakehouse parser."""
from __future__ import annotations

import base64
import json

from fabric_scanner.engine.extract import (
    extract_blocks,
    extract_attached_lakehouse,
)


def _ipynb(cells, metadata=None) -> bytes:
    return json.dumps({
        "cells": cells, "metadata": metadata or {},
        "nbformat": 4, "nbformat_minor": 5,
    }).encode("utf-8")


def test_extract_py_passthrough():
    blocks = extract_blocks(b"print('hi')", "foo.py")
    assert blocks == [("print('hi')", 0, "code", "")]


def test_extract_md_passthrough():
    blocks = extract_blocks(b"# Title", "README.md")
    assert blocks == [("# Title", 0, "markdown", "")]


def test_extract_ipynb_code_and_markdown():
    content = _ipynb([
        {"cell_type": "code", "source": "x = 1", "outputs": []},
        {"cell_type": "markdown", "source": "## hi"},
        {"cell_type": "code", "source": "y = 2", "outputs": []},
    ])
    blocks = extract_blocks(content, "a.ipynb")
    kinds = [b[2] for b in blocks]
    assert kinds.count("code") == 2
    assert kinds.count("markdown") == 1


def test_extract_ipynb_outputs_emitted_when_enabled():
    content = _ipynb([{
        "cell_type": "code", "source": "print('see https://example.com')",
        "outputs": [{"output_type": "stream", "name": "stdout",
                     "text": "see https://example.com\n"}],
    }])
    blocks = extract_blocks(content, "a.ipynb", include_md_and_outputs=True)
    kinds = [b[2] for b in blocks]
    assert "output" in kinds


def test_extract_outputs_suppressed_when_disabled():
    content = _ipynb([{
        "cell_type": "code", "source": "x",
        "outputs": [{"output_type": "stream", "text": "out"}],
    }, {"cell_type": "markdown", "source": "## hi"}])
    blocks = extract_blocks(content, "a.ipynb", include_md_and_outputs=False)
    kinds = [b[2] for b in blocks]
    assert "output" not in kinds
    assert "markdown" not in kinds
    assert "code" in kinds


def test_extract_fabric_item_json_with_base64_parts():
    inner_nb = _ipynb([{"cell_type": "code", "source": "import boto3"}])
    outer = json.dumps({
        "definition": {
            "parts": [
                {"path": "notebook-content.ipynb",
                 "payload": base64.b64encode(inner_nb).decode("ascii")},
            ],
        },
    }).encode("utf-8")
    blocks = extract_blocks(outer, "item.json")
    texts = [b[0] for b in blocks if b[2] == "code"]
    assert any("import boto3" in t for t in texts)
    assert all(b[3] == "notebook-content.ipynb"
               for b in blocks if b[2] == "code")


def test_extract_invalid_json_falls_back_to_raw():
    blocks = extract_blocks(b"{not json", "a.ipynb")
    assert blocks == [("{not json", 0, "raw", "")]


def test_attached_lakehouse_from_plain_ipynb():
    meta = {
        "dependencies": {
            "lakehouse": {
                "default_lakehouse": "lh-id-aaa",
                "default_lakehouse_name": "Bronze",
                "default_lakehouse_workspace_id": "ws-id-bbb",
            },
        },
    }
    content = _ipynb([{"cell_type": "code", "source": "x"}], meta)
    info = extract_attached_lakehouse(content, "a.ipynb")
    assert info["attached_lakehouse_id"] == "lh-id-aaa"
    assert info["attached_lakehouse_name"] == "Bronze"
    assert info["attached_lakehouse_workspace_id"] == "ws-id-bbb"
    assert info["attached_lakehouse_workspace_name"] is None


def test_attached_lakehouse_from_fabric_item_json():
    inner = _ipynb([{"cell_type": "code", "source": "x"}], {
        "dependencies": {"lakehouse": {
            "default_lakehouse": "from-parts",
            "default_lakehouse_name": "Gold",
            "default_lakehouse_workspace_id": "ws-yyy",
        }}
    })
    outer = json.dumps({"definition": {"parts": [
        {"path": "notebook-content.ipynb",
         "payload": base64.b64encode(inner).decode("ascii")},
    ]}}).encode("utf-8")
    info = extract_attached_lakehouse(outer, "item.json")
    assert info["attached_lakehouse_id"] == "from-parts"
    assert info["attached_lakehouse_name"] == "Gold"


def test_attached_lakehouse_missing_returns_all_none():
    info = extract_attached_lakehouse(b"{}", "a.ipynb")
    assert info == {
        "attached_lakehouse_id": None,
        "attached_lakehouse_name": None,
        "attached_lakehouse_workspace_id": None,
        "attached_lakehouse_workspace_name": None,
    }


def test_attached_lakehouse_known_lakehouses_fallback():
    meta = {"dependencies": {"lakehouse": {
        "known_lakehouses": [{"id": "fallback-lh"}],
    }}}
    content = _ipynb([{"cell_type": "code", "source": "x"}], meta)
    info = extract_attached_lakehouse(content, "a.ipynb")
    assert info["attached_lakehouse_id"] == "fallback-lh"
