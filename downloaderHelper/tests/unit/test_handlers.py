"""Unit tests for the built-in item-type handler implementations.

Each test exercises ``to_files(item, definition)`` without live API calls.
"""
from __future__ import annotations

import base64
import json

import pytest

# Ensure handlers are registered.
import fabric_downloader.handlers  # noqa: F401

from fabric_downloader.handlers.dataflow import DataflowHandler
from fabric_downloader.handlers.environment import EnvironmentHandler
from fabric_downloader.handlers.eventstream import EventstreamHandler
from fabric_downloader.handlers.kql_database import KQLDatabaseHandler
from fabric_downloader.handlers.lakehouse import LakehouseHandler
from fabric_downloader.handlers.notebook import NotebookHandler
from fabric_downloader.handlers.pipeline import DataPipelineHandler
from fabric_downloader.handlers.report import ReportHandler
from fabric_downloader.handlers.semantic_model import SemanticModelHandler
from fabric_downloader.handlers.spark_job_definition import SparkJobDefinitionHandler


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _parts_body(*parts: tuple[str, str]) -> dict:
    """Build a minimal getDefinition body from (path, text) pairs."""
    return {
        "definition": {
            "parts": [
                {"path": path, "payload": _b64(text), "payloadType": "InlineBase64"}
                for path, text in parts
            ]
        }
    }


_ITEM: dict = {
    "id": "item-id-1234",
    "displayName": "My Item",
    "workspaceId": "ws-id-5678",
    "type": "Notebook",
    "description": "",
    "properties": {},
}


# ---------------------------------------------------------------------------
# NotebookHandler
# ---------------------------------------------------------------------------


class TestNotebookHandler:
    def setup_method(self):
        self.h = NotebookHandler()

    def test_item_type(self):
        assert NotebookHandler.item_type == "Notebook"

    def test_ipynb_mode_returns_ipynb_bytes(self):
        body = _parts_body(
            ("notebook-content.ipynb", '{"cells": []}'),
            (".platform", "plat"),
        )
        files = self.h.to_files(_ITEM, body, notebook_format="ipynb")
        assert any(k.endswith(".ipynb") for k in files)
        assert b'{"cells": []}' in list(files.values())

    def test_py_mode_returns_source(self):
        body = _parts_body(
            ("notebook-content.py", "print('hello')"),
            (".platform", "plat"),
        )
        files = self.h.to_files(_ITEM, body, notebook_format="py")
        assert "notebook-content.py" in files
        assert files["notebook-content.py"] == b"print('hello')"

    def test_txt_mode_uses_txt_extension(self):
        body = _parts_body(
            ("notebook-content.py", "print('hello')"),
        )
        files = self.h.to_files(_ITEM, body, notebook_format="txt")
        assert "notebook-content.txt" in files

    def test_parts_mode_returns_all_parts(self):
        body = _parts_body(
            ("notebook-content.py", "x = 1"),
            (".platform", "{}"),
        )
        files = self.h.to_files(_ITEM, body, notebook_format="parts")
        assert "notebook-content.py" in files
        assert ".platform" in files

    def test_ipynb_mode_returns_empty_when_no_ipynb_part(self):
        body = _parts_body(("notebook-content.py", "x = 1"))
        files = self.h.to_files(_ITEM, body, notebook_format="ipynb")
        assert files == {}

    def test_py_mode_ignores_unknown_extensions(self):
        body = _parts_body(("notebook-content.unknown", "x = 1"))
        files = self.h.to_files(_ITEM, body, notebook_format="py")
        assert files == {}

    def test_scala_notebook_source(self):
        body = _parts_body(("notebook-content.scala", "val x = 1"))
        files = self.h.to_files(_ITEM, body, notebook_format="py")
        assert "notebook-content.scala" in files

    def test_empty_definition_returns_empty(self):
        files = self.h.to_files(_ITEM, {})
        assert files == {}


# ---------------------------------------------------------------------------
# SemanticModelHandler
# ---------------------------------------------------------------------------


class TestSemanticModelHandler:
    def test_item_type(self):
        assert SemanticModelHandler.item_type == "SemanticModel"

    def test_returns_parts(self):
        body = _parts_body(("model.bim", '{"model":{}}'), (".platform", "{}"))
        files = SemanticModelHandler().to_files(_ITEM, body)
        assert "model.bim" in files
        assert ".platform" in files


# ---------------------------------------------------------------------------
# ReportHandler
# ---------------------------------------------------------------------------


class TestReportHandler:
    def test_item_type(self):
        assert ReportHandler.item_type == "Report"

    def test_returns_all_parts(self):
        body = _parts_body(
            ("report.json", '{"version":"1.0"}'),
            ("definition.pbir", "{}"),
        )
        files = ReportHandler().to_files(_ITEM, body)
        assert "report.json" in files
        assert "definition.pbir" in files


# ---------------------------------------------------------------------------
# DataflowHandler
# ---------------------------------------------------------------------------


class TestDataflowHandler:
    def test_item_type(self):
        assert DataflowHandler.item_type == "Dataflow"

    def test_returns_mashup_part(self):
        body = _parts_body(("mashup.pq", "let x = 1 in x"), (".platform", "{}"))
        files = DataflowHandler().to_files(_ITEM, body)
        assert "mashup.pq" in files


# ---------------------------------------------------------------------------
# DataPipelineHandler
# ---------------------------------------------------------------------------


class TestDataPipelineHandler:
    def test_item_type(self):
        assert DataPipelineHandler.item_type == "DataPipeline"

    def test_returns_pipeline_content(self):
        body = _parts_body(
            ("pipeline-content.json", '{"activities":[]}'),
            (".platform", "{}"),
        )
        files = DataPipelineHandler().to_files(_ITEM, body)
        assert "pipeline-content.json" in files


# ---------------------------------------------------------------------------
# SparkJobDefinitionHandler
# ---------------------------------------------------------------------------


class TestSparkJobDefinitionHandler:
    def test_item_type(self):
        assert SparkJobDefinitionHandler.item_type == "SparkJobDefinition"

    def test_returns_definition_parts(self):
        body = _parts_body(
            ("SparkJobDefinitionV1.json", '{"executableFile": "main.py"}'),
        )
        files = SparkJobDefinitionHandler().to_files(_ITEM, body)
        assert "SparkJobDefinitionV1.json" in files


# ---------------------------------------------------------------------------
# KQLDatabaseHandler
# ---------------------------------------------------------------------------


class TestKQLDatabaseHandler:
    def test_item_type(self):
        assert KQLDatabaseHandler.item_type == "KQLDatabase"

    def test_returns_parts(self):
        body = _parts_body(("DatabaseSchema.kql", ".create table T ()"))
        files = KQLDatabaseHandler().to_files(_ITEM, body)
        assert "DatabaseSchema.kql" in files


# ---------------------------------------------------------------------------
# EventstreamHandler
# ---------------------------------------------------------------------------


class TestEventstreamHandler:
    def test_item_type(self):
        assert EventstreamHandler.item_type == "Eventstream"

    def test_returns_topology(self):
        body = _parts_body(("eventstream-content.json", '{"nodes":[]}'))
        files = EventstreamHandler().to_files(_ITEM, body)
        assert "eventstream-content.json" in files


# ---------------------------------------------------------------------------
# EnvironmentHandler
# ---------------------------------------------------------------------------


class TestEnvironmentHandler:
    def test_item_type(self):
        assert EnvironmentHandler.item_type == "Environment"

    def test_returns_env_yml(self):
        body = _parts_body(("environment.yml", "name: my-env\n"))
        files = EnvironmentHandler().to_files(_ITEM, body)
        assert "environment.yml" in files


# ---------------------------------------------------------------------------
# LakehouseHandler (metadata-only)
# ---------------------------------------------------------------------------


class TestLakehouseHandler:
    def test_item_type(self):
        assert LakehouseHandler.item_type == "Lakehouse"

    def test_returns_metadata_json(self):
        item = {
            "id": "lh-id",
            "displayName": "My Lakehouse",
            "workspaceId": "ws-id",
            "type": "Lakehouse",
            "description": "desc",
            "properties": {"enableSchemas": True},
        }
        files = LakehouseHandler().to_files(item, {})
        assert "lakehouse_metadata.json" in files
        meta = json.loads(files["lakehouse_metadata.json"].decode("utf-8"))
        assert meta["id"] == "lh-id"
        assert meta["displayName"] == "My Lakehouse"
        assert meta["properties"] == {"enableSchemas": True}

    def test_ignores_definition_body(self):
        """LakehouseHandler never reads the definition body."""
        item = {"id": "x", "displayName": "X", "workspaceId": "ws", "type": "Lakehouse"}
        # non-empty definition body should be silently ignored
        files = LakehouseHandler().to_files(item, {"junk": "data"})
        assert "lakehouse_metadata.json" in files

    def test_empty_item_produces_valid_json(self):
        files = LakehouseHandler().to_files({}, {})
        meta = json.loads(files["lakehouse_metadata.json"].decode("utf-8"))
        assert meta["id"] == ""
