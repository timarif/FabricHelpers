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

# -----------------------------------------------------------------
# Fabric notebook source-export format (`.py` with `# META {...}`)
# -----------------------------------------------------------------

FABRIC_PY_SAMPLE = """\
# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "cb9fac32-f954-42b3-858a-7fd14458f26a",
# META       "default_lakehouse_name": "rawlakehouse",
# META       "default_lakehouse_workspace_id": "b72cdac7-93af-4903-9d2a-14d3e635674d",
# META       "known_lakehouses": [
# META         {
# META           "id": "cb9fac32-f954-42b3-858a-7fd14458f26a"
# META         }
# META       ]
# META     },
# META     "environment": {
# META       "environmentId": "7711d72e-a934-4f45-b330-0a2e04c4ee9d",
# META       "workspaceId": "a9fbdebe-644c-4a6b-a4a9-47c1373f4572"
# META     }
# META   }
# META }

# CELL ********************

# Read a Delta table
import polars as pl
df = pl.read_delta("abfss://rawdata@onelake.dfs.fabric.microsoft.com/rawlakehouse.Lakehouse/Tables/dimension_employee", columns=["EmployeeKey"])

df.write_delta("abfss://rawdata@onelake.dfs.fabric.microsoft.com/rawlakehouse.Lakehouse/Tables/test1234")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
"""


def test_attached_lakehouse_from_fabric_py_source():
    info = extract_attached_lakehouse(FABRIC_PY_SAMPLE.encode("utf-8"), "notebook-content.py")
    assert info["attached_lakehouse_id"] == "cb9fac32-f954-42b3-858a-7fd14458f26a"
    assert info["attached_lakehouse_name"] == "rawlakehouse"
    assert info["attached_lakehouse_workspace_id"] == "b72cdac7-93af-4903-9d2a-14d3e635674d"
    assert info["attached_lakehouse_workspace_name"] is None


def test_extract_blocks_fabric_py_source_splits_cells():
    blocks = extract_blocks(FABRIC_PY_SAMPLE.encode("utf-8"), "notebook-content.py")
    assert len(blocks) == 1
    text, idx, kind, part_path = blocks[0]
    assert kind == "code"
    assert idx == 0
    assert part_path == ""
    assert "# META" not in text
    assert "import polars" in text
    assert "write_delta" in text


def test_extract_blocks_fabric_py_multiple_cells():
    multi = """\
# Fabric notebook source

# METADATA ********************

# META {
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "lh-1",
# META       "default_lakehouse_name": "Bronze"
# META     }
# META   }
# META }

# CELL ********************

x = 1

# METADATA ********************

# META { "language": "python" }

# CELL ********************

y = 2

# METADATA ********************

# META { "language": "python" }
"""
    blocks = extract_blocks(multi.encode("utf-8"), "nb.py")
    assert [b[1] for b in blocks] == [0, 1]
    assert [b[2] for b in blocks] == ["code", "code"]
    assert blocks[0][0].strip() == "x = 1"
    assert blocks[1][0].strip() == "y = 2"


def test_extract_blocks_fabric_py_with_markdown_cell():
    src = """\
# Fabric notebook source

# METADATA ********************

# META { "dependencies": {} }

# MARKDOWN ********************

# # Heading
#
# Some text with a link to https://example.com

# CELL ********************

x = 1
"""
    blocks = extract_blocks(src.encode("utf-8"), "nb.py", include_md_and_outputs=True)
    kinds = [b[2] for b in blocks]
    assert "markdown" in kinds and "code" in kinds
    md = [b[0] for b in blocks if b[2] == "markdown"][0]
    assert md.startswith("# Heading")
    assert "https://example.com" in md


def test_extract_blocks_fabric_py_markdown_suppressed():
    src = """\
# Fabric notebook source

# METADATA ********************

# META { "dependencies": {} }

# MARKDOWN ********************

# # Heading

# CELL ********************

x = 1
"""
    blocks = extract_blocks(src.encode("utf-8"), "nb.py", include_md_and_outputs=False)
    assert [b[2] for b in blocks] == ["code"]


def test_plain_py_without_fabric_header_unchanged():
    blocks = extract_blocks(b"x = 1\nprint(x)\n", "regular.py")
    assert blocks == [("x = 1\nprint(x)\n", 0, "code", "")]


def test_attached_lakehouse_plain_py_returns_empty():
    info = extract_attached_lakehouse(b"x = 1", "regular.py")
    assert info == {
        "attached_lakehouse_id": None,
        "attached_lakehouse_name": None,
        "attached_lakehouse_workspace_id": None,
        "attached_lakehouse_workspace_name": None,
    }


def test_attached_lakehouse_fabric_py_inside_item_json_parts():
    inner_py = FABRIC_PY_SAMPLE
    outer = json.dumps({
        "definition": {
            "parts": [
                {"path": "notebook-content.py",
                 "payload": base64.b64encode(inner_py.encode("utf-8")).decode("ascii")},
            ],
        },
    }).encode("utf-8")
    info = extract_attached_lakehouse(outer, "item.json")
    assert info["attached_lakehouse_id"] == "cb9fac32-f954-42b3-858a-7fd14458f26a"
    assert info["attached_lakehouse_name"] == "rawlakehouse"


def test_extract_blocks_fabric_py_inside_item_json_parts():
    inner_py = FABRIC_PY_SAMPLE
    outer = json.dumps({
        "definition": {
            "parts": [
                {"path": "notebook-content.py",
                 "payload": base64.b64encode(inner_py.encode("utf-8")).decode("ascii")},
            ],
        },
    }).encode("utf-8")
    blocks = extract_blocks(outer, "item.json")
    code_texts = [b[0] for b in blocks if b[2] == "code"]
    assert any("import polars" in t for t in code_texts)
    assert all(b[3] == "notebook-content.py" for b in blocks)
    assert all("# META" not in b[0] for b in blocks if b[2] == "code")
