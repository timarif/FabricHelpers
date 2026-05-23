"""Unit tests for `process_definition_body` — the pure layer of
`partition.py`. Spark is never imported."""
from __future__ import annotations

import base64
import json

import pytest

from fabric_downloader import DownloaderConfig, resolve_paths
from fabric_downloader.spark.context import build_download_context
from fabric_downloader.spark.partition import (
    _is_content_part, process_definition_body,
)
from fabric_downloader.spark.schema import MANIFEST_COLUMNS


# -------------------- helpers --------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _make_ctx(item_types=("Notebook",), format_by_type=None,
              skip_existing=False, group_by_type=True,
              include_raw_definition=False):
    cfg = DownloaderConfig(
        item_types=item_types,
        format_by_type=(format_by_type if format_by_type is not None
                        else {"Notebook": "ipynb"}),
        skip_existing=skip_existing,
        group_by_type=group_by_type,
        include_raw_definition=include_raw_definition,
        write_to_default_lakehouse=False,
        write_workspace_id="ws-W",
        write_lakehouse_id="lh-W",
        run_label="run-T",
        output_root="backups",
    )
    resolved = resolve_paths(cfg)
    return build_download_context(cfg, resolved)


def _writer():
    writes: list[tuple[str, str]] = []

    def _w(uri, text):
        writes.append((uri, text))

    return _w, writes


def _exists_factory(existing: set[str] | None = None):
    existing = existing or set()

    def _e(uri):
        return uri in existing

    return _e


# -------------------- content-part detection --------------------


@pytest.mark.parametrize("path,expected", [
    ("notebook-content.py",     True),
    ("notebook-content.ipynb",  True),
    ("pipeline-content.json",   True),
    ("mashup.pq",               True),
    ("queryGroups.json",        False),
    (".platform",               False),
    ("",                        False),
])
def test_is_content_part(path, expected):
    assert _is_content_part(path) is expected


# -------------------- error / edge cases --------------------


def test_error_when_body_is_none():
    ctx = _make_ctx()
    writer, writes = _writer()
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="WS",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body=None, http_status=500, attempts=3, token_refreshes=0,
        error="boom", writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "error"
    assert row["error"] == "boom"
    assert row["attempts"] == 3
    assert writes == []


def test_error_when_parts_empty():
    ctx = _make_ctx()
    writer, writes = _writer()
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="WS",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body={"definition": {"parts": []}},
        http_status=200, attempts=1, token_refreshes=0, error=None,
        writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "error"
    assert "empty definition.parts" in row["error"]
    assert row["part_count"] == 0
    assert writes == []


def test_ipynb_mode_missing_ipynb_part_is_error():
    ctx = _make_ctx()
    writer, writes = _writer()
    body = {"definition": {"parts": [
        {"path": "notebook-content.py", "payload": _b64("print('x')"),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="WS",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "error"
    assert "no .ipynb part" in row["error"]
    assert writes == []


# -------------------- ipynb mode --------------------


def test_ipynb_mode_writes_one_file_and_emits_ok_row():
    ctx = _make_ctx()
    writer, writes = _writer()
    nb_text = '{"cells": []}'
    body = {"definition": {"parts": [
        {"path": "notebook-content.py", "payload": _b64("ignored"),
         "payloadType": "InlineBase64"},
        {"path": "notebook-content.ipynb", "payload": _b64(nb_text),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="My WS",
        item_type="Notebook", item_id="nb-1", display_name="Cool NB",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["part_count"] == 2
    assert row["parts_saved"] == 1
    assert row["has_content_part"] is True
    assert row["payload_bytes"] == len(nb_text)
    assert row["export_format"] == "ipynb"
    assert row["item_type"] == "Notebook"

    assert len(writes) == 1
    uri, text = writes[0]
    assert uri.endswith("Cool_NB__nb-1.ipynb")
    assert text == nb_text
    # output goes under Files/<output_root>/<run_label>/<ws>/<type>/
    assert "/backups/run-T/My_WS__ws-1/Notebook/" in uri


def test_ipynb_mode_skip_existing():
    ctx = _make_ctx(skip_existing=True)
    writer, writes = _writer()
    nb_text = '{"cells": []}'
    body = {"definition": {"parts": [
        {"path": "notebook-content.ipynb", "payload": _b64(nb_text),
         "payloadType": "InlineBase64"},
    ]}}

    # Pre-populate the expected target so the writer is a no-op.
    target = ctx.join_target(
        "backups/run-T/ws__ws-1/Notebook/N__nb-1.ipynb")
    exists = _exists_factory({target})
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=exists,
    )
    assert row["status"] == "skipped_exists"
    assert row["parts_saved"] == 0
    assert writes == []


# -------------------- parts mode --------------------


def test_parts_mode_writes_every_part_and_picks_content_target():
    ctx = _make_ctx(item_types=("DataPipeline",), format_by_type={})
    writer, writes = _writer()
    body = {"definition": {"parts": [
        {"path": "pipeline-content.json",
         "payload": _b64('{"activities":[]}'),
         "payloadType": "InlineBase64"},
        {"path": ".platform",
         "payload": _b64('{"$schema":"x"}'),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="DataPipeline", item_id="pid-1", display_name="MyPipe",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["export_format"] == "parts"
    assert row["part_count"] == 2
    assert row["parts_saved"] == 2
    assert row["has_content_part"] is True
    # primary_target should be the pipeline-content one
    assert row["primary_target"].endswith(
        "MyPipe__pid-1__pipeline-content.json.txt")
    # Two files written, into the DataPipeline subfolder. Note that
    # `.platform` has its leading dot stripped by `safe_segment` — the
    # downloader's filenames are deliberately filesystem-safe.
    assert len(writes) == 2
    assert any(u.endswith("MyPipe__pid-1__pipeline-content.json.txt")
               for u, _ in writes)
    assert any(u.endswith("MyPipe__pid-1__platform.txt")
               for u, _ in writes)
    assert all("/DataPipeline/" in u for u, _ in writes)


def test_parts_mode_flat_layout_skips_type_subfolder():
    ctx = _make_ctx(
        item_types=("Notebook",),
        format_by_type={},          # parts mode for notebooks too
        group_by_type=False,
    )
    writer, writes = _writer()
    body = {"definition": {"parts": [
        {"path": "notebook-content.py", "payload": _b64("print(1)"),
         "payloadType": "InlineBase64"},
        {"path": ".platform", "payload": _b64("{}"),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "ok"
    for uri, _ in writes:
        assert "/Notebook/" not in uri
        assert "/ws__ws-1/" in uri


def test_parts_mode_missing_content_part_records_warning():
    ctx = _make_ctx(item_types=("DataPipeline",), format_by_type={})
    writer, writes = _writer()
    body = {"definition": {"parts": [
        {"path": ".platform", "payload": _b64("{}"),
         "payloadType": "InlineBase64"},
        {"path": "queryGroups.json", "payload": _b64("[]"),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="DataPipeline", item_id="pid-1", display_name="Mostly",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "ok"
    assert row["has_content_part"] is False
    assert "no notebook-content" in row["error"]
    assert row["parts_saved"] == 2


def test_parts_mode_skip_existing_skips_only_present_parts():
    ctx = _make_ctx(item_types=("Dataflow",), format_by_type={},
                    skip_existing=True)
    writer, writes = _writer()
    body = {"definition": {"parts": [
        {"path": "mashup.pq", "payload": _b64("let Source = 1 in Source"),
         "payloadType": "InlineBase64"},
        {"path": ".platform", "payload": _b64("{}"),
         "payloadType": "InlineBase64"},
    ]}}

    # `safe_segment` strips the leading dot off `.platform` so the actual
    # filename for the .platform part is `DF__df-1__platform.txt`.
    existing_uri = ctx.join_target(
        "backups/run-T/ws__ws-1/Dataflow/DF__df-1__platform.txt")
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="Dataflow", item_id="df-1", display_name="DF",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory({existing_uri}),
    )
    assert row["status"] == "ok"
    assert row["parts_saved"] == 1   # the .platform was skipped
    assert len(writes) == 1
    assert writes[0][0].endswith("mashup.pq.txt")


def test_include_raw_definition_writes_envelope_too():
    ctx = _make_ctx(include_raw_definition=True)
    writer, writes = _writer()
    nb_text = '{"cells": []}'
    body = {"definition": {"parts": [
        {"path": "notebook-content.ipynb", "payload": _b64(nb_text),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="ws-1", workspace_name="ws",
        item_type="Notebook", item_id="nb-1", display_name="N",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert row["status"] == "ok"
    assert row["item_json_target"] is not None
    assert any(u.endswith(".item.json") for u, _ in writes)
    # The envelope should be valid JSON containing the parts
    envelope_text = next(t for u, t in writes if u.endswith(".item.json"))
    parsed = json.loads(envelope_text)
    assert parsed["definition"]["parts"][0]["path"] == "notebook-content.ipynb"


# -------------------- row schema --------------------


def test_row_dict_keys_match_manifest_columns():
    """Every row produced by `process_definition_body` must carry exactly
    the keys declared in MANIFEST_COLUMNS — otherwise `_emit` will drop
    columns or raise. Critical contract between the pure layer and Spark."""
    ctx = _make_ctx()
    body = {"definition": {"parts": [
        {"path": "notebook-content.ipynb", "payload": _b64('{"cells":[]}'),
         "payloadType": "InlineBase64"},
    ]}}
    writer, _ = _writer()
    row = process_definition_body(
        ctx=ctx, workspace_id="w", workspace_name="w",
        item_type="Notebook", item_id="i", display_name="d",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=writer, exists=_exists_factory(),
    )
    assert set(row.keys()) == set(MANIFEST_COLUMNS)


def test_writer_exception_surfaces_as_error_row():
    ctx = _make_ctx()

    def boom(*_a):
        raise IOError("disk full")

    body = {"definition": {"parts": [
        {"path": "notebook-content.ipynb", "payload": _b64("{}"),
         "payloadType": "InlineBase64"},
    ]}}
    row = process_definition_body(
        ctx=ctx, workspace_id="w", workspace_name="w",
        item_type="Notebook", item_id="i", display_name="d",
        body=body, http_status=200, attempts=1, token_refreshes=0,
        error=None, writer=boom, exists=_exists_factory(),
    )
    assert row["status"] == "error"
    assert "OSError" in row["error"] or "IOError" in row["error"]
    assert "disk full" in row["error"]
