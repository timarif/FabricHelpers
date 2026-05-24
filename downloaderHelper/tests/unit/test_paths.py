"""Unit tests for `paths.py` — pure helpers + resolve_paths + I/O wrappers."""
from __future__ import annotations

import pytest

from fabric_downloader import DownloaderConfig, resolve_paths, safe_segment
from fabric_downloader.paths import (
    DEFAULT_LAKEHOUSE_MOUNT, ONELAKE_HOST, ResolvedPaths, auto_run_label,
    build_paths, files_uri, item_folder, list_dir, table_path, target_exists,
    workspace_folder, write_text,
)


# -------------------- safe_segment --------------------


@pytest.mark.parametrize("raw,expected", [
    # Trailing "_" comes from ")" -> "_", then `s.strip("._-")` removes it.
    ("My Workspace (Prod)", "My_Workspace__Prod"),
    ("",                     "unnamed"),
    (None,                   "unnamed"),
    ("a/b/c\\d",             "a_b_c_d"),
    ("...trim_me...",        "trim_me"),
    ("ok-name_1.2",          "ok-name_1.2"),
])
def test_safe_segment(raw, expected):
    assert safe_segment(raw) == expected


def test_safe_segment_strips_leading_dot():
    """Filesystem-style hidden-file prefixes are stripped — `safe_segment`
    is meant for path segments, not real dotfiles."""
    assert safe_segment(".platform") == "platform"


def test_safe_segment_truncates_to_maxlen():
    out = safe_segment("x" * 200, maxlen=20)
    assert len(out) == 20


# -------------------- URI builders --------------------


def test_files_uri_root_section():
    assert (files_uri("ws-id", "lh-id")
            == f"abfss://ws-id@{ONELAKE_HOST}/lh-id/Files")


def test_files_uri_with_custom_subpath():
    assert (files_uri("ws", "lh", "Files/sub")
            == f"abfss://ws@{ONELAKE_HOST}/lh/Files/sub")


def test_files_uri_empty_subpath_drops_trailing_slash():
    assert files_uri("ws", "lh", "") == f"abfss://ws@{ONELAKE_HOST}/lh"


def test_table_path_without_schema():
    assert (table_path("ws", "lh", "my_table")
            == f"abfss://ws@{ONELAKE_HOST}/lh/Tables/my_table")


def test_table_path_with_schema():
    assert (table_path("ws", "lh", "my_table", "dbo")
            == f"abfss://ws@{ONELAKE_HOST}/lh/Tables/dbo/my_table")


# -------------------- output path builders --------------------


def test_workspace_folder():
    out = workspace_folder("backups", "run-1", "ws-guid", "My Workspace")
    assert out == "backups/run-1/My_Workspace__ws-guid"


def test_workspace_folder_uses_id_when_name_missing():
    out = workspace_folder("backups", "run-1", "ws-guid", "")
    assert out == "backups/run-1/ws-guid__ws-guid"


def test_item_folder_groups_by_type_by_default():
    out = item_folder("backups", "run-1", "ws-guid", "My WS", "DataPipeline")
    assert out == "backups/run-1/My_WS__ws-guid/DataPipeline"


def test_item_folder_flat_when_group_by_type_false():
    out = item_folder("backups", "run-1", "ws-guid", "My WS", "Notebook",
                      group_by_type=False)
    assert out == "backups/run-1/My_WS__ws-guid"


def test_build_paths_ipynb_mode():
    primary, item_json = build_paths(
        output_root="backups", run_label="run-1",
        workspace_id="ws", workspace_name="ws",
        item_type="Notebook", item_id="nb", item_name="My NB",
        export_mode="ipynb",
    )
    assert primary == "backups/run-1/ws__ws/Notebook/My_NB__nb.ipynb"
    assert item_json == "backups/run-1/ws__ws/Notebook/My_NB__nb.item.json"


def test_build_paths_py_mode_uses_py_placeholder():
    """`py` is the planning-time placeholder. The writer refines this to
    the actual language extension (`.py` / `.scala` / `.sql` / `.r`)
    once it inspects the API response."""
    primary, _ = build_paths(
        output_root="backups", run_label="run-1",
        workspace_id="ws", workspace_name="ws",
        item_type="Notebook", item_id="nb", item_name="My NB",
        export_mode="py",
    )
    assert primary == "backups/run-1/ws__ws/Notebook/My_NB__nb.py"


def test_build_paths_parts_mode_placeholder():
    primary, _ = build_paths(
        output_root="backups", run_label="run-1",
        workspace_id="ws", workspace_name="ws",
        item_type="DataPipeline", item_id="pid", item_name="Pipe",
        export_mode="parts",
    )
    assert primary.endswith("__definition.txt")


# -------------------- auto_run_label --------------------


def test_auto_run_label_is_sortable_utc_timestamp():
    label = auto_run_label()
    # YYYY-MM-DD_HH-MM-SS shape
    assert len(label) == 19
    assert label[4] == "-" and label[10] == "_"


# -------------------- resolve_paths --------------------


def test_resolve_paths_default_lakehouse_mode():
    cfg = DownloaderConfig(run_label="run-A")
    resolved = resolve_paths(cfg, runtime_provider=lambda: {
        "default_lakehouse_workspace_id": "ws-1",
        "default_lakehouse_id": "lh-1",
    })
    assert isinstance(resolved, ResolvedPaths)
    assert resolved.lakehouse_mount == DEFAULT_LAKEHOUSE_MOUNT
    assert resolved.abfss_files_prefix is None
    assert resolved.manifest_target == "fabric_download_manifest"
    assert resolved.run_label == "run-A"
    assert resolved.write_workspace_id == "ws-1"
    assert resolved.write_to_default_lakehouse is True


def test_resolve_paths_default_with_schema():
    cfg = DownloaderConfig(write_schema="myschema", run_label="run-B")
    resolved = resolve_paths(cfg, runtime_provider=lambda: {})
    assert resolved.manifest_target == "myschema.fabric_download_manifest"
    assert resolved.write_schema == "myschema"


def test_resolve_paths_external_lakehouse():
    cfg = DownloaderConfig(
        write_to_default_lakehouse=False,
        write_workspace_id="ws-X",
        write_lakehouse_id="lh-X",
        run_label="run-C",
    )
    resolved = resolve_paths(cfg)
    assert resolved.lakehouse_mount is None
    assert resolved.abfss_files_prefix == (
        f"abfss://ws-X@{ONELAKE_HOST}/lh-X/Files")
    assert resolved.manifest_target.startswith(
        f"abfss://ws-X@{ONELAKE_HOST}/lh-X/Tables/")
    assert resolved.write_to_default_lakehouse is False


def test_resolve_paths_auto_run_label():
    cfg = DownloaderConfig()
    resolved = resolve_paths(cfg, runtime_provider=lambda: {})
    assert resolved.run_label  # non-empty
    assert "T" not in resolved.run_label  # uses _, not ISO 'T'


def test_resolved_paths_join_target_local_mount():
    resolved = ResolvedPaths(
        lakehouse_mount="/lakehouse/default/Files",
        abfss_files_prefix=None,
        manifest_target="t", write_workspace_id="ws",
        write_lakehouse_id="lh", write_schema=None,
        run_label="r", output_root="o", runtime={},
    )
    assert (resolved.join_target("backups/x.txt")
            == "/lakehouse/default/Files/backups/x.txt")


def test_resolved_paths_join_target_abfss():
    resolved = ResolvedPaths(
        lakehouse_mount=None,
        abfss_files_prefix=f"abfss://ws@{ONELAKE_HOST}/lh/Files",
        manifest_target="t", write_workspace_id="ws",
        write_lakehouse_id="lh", write_schema=None,
        run_label="r", output_root="o", runtime={},
    )
    assert (resolved.join_target("/backups/x.txt")
            == f"abfss://ws@{ONELAKE_HOST}/lh/Files/backups/x.txt")


# -------------------- write_text / target_exists --------------------


def test_write_text_local_creates_parents(tmp_path):
    target = str(tmp_path / "a" / "b" / "out.txt")
    write_text(target, "hello world")
    with open(target, encoding="utf-8") as f:
        assert f.read() == "hello world"


def test_target_exists_local(tmp_path):
    target = str(tmp_path / "out.txt")
    assert target_exists(target) is False
    write_text(target, "x")
    assert target_exists(target) is True


def test_write_text_abfss_routes_through_notebookutils(fake_notebookutils):
    abfss = f"abfss://ws@{ONELAKE_HOST}/lh/Files/x.txt"
    write_text(abfss, "payload")
    assert fake_notebookutils._writes == [(abfss, "payload", True)]


def test_target_exists_abfss_routes_through_notebookutils(fake_notebookutils):
    abfss = f"abfss://ws@{ONELAKE_HOST}/lh/Files/x.txt"
    assert target_exists(abfss) is False
    fake_notebookutils._existing.add(abfss)
    assert target_exists(abfss) is True


def test_list_dir_uses_injected_ls():
    seen: list[str] = []

    def fake_ls(path):
        seen.append(path)
        return [("a",), ("b",)]

    out = list_dir("abfss://foo/Files", ls=fake_ls)
    assert seen == ["abfss://foo/Files"]
    assert out == [("a",), ("b",)]
