from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import release_package as rp  # noqa: E402


def stub_git(monkeypatch: pytest.MonkeyPatch, tags: list[str]) -> None:
    monkeypatch.setattr(rp, "git_tag_names", lambda package: tags)
    monkeypatch.setattr(rp, "tag_exists", lambda tag: tag in tags)
    monkeypatch.setattr(rp, "tag_points_at_head", lambda tag: False)
    monkeypatch.setattr(rp, "tags_pointing_at_head", lambda: set())


def test_compute_respects_version_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "read_file_version", lambda package: "0.1.0")
    stub_git(monkeypatch, ["core-v0.1.0"])

    version, tag = rp.compute_release("core", bump="patch", version_override="0.2.0")

    assert version == "0.2.0"
    assert tag == "core-v0.2.0"


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("patch", "1.2.5"), ("minor", "1.3.0"), ("major", "2.0.0")],
)
def test_compute_bumps_from_latest_tag(
    monkeypatch: pytest.MonkeyPatch,
    bump: str,
    expected: str,
) -> None:
    monkeypatch.setattr(rp, "read_file_version", lambda package: "1.2.3")
    stub_git(monkeypatch, ["core-v1.2.4"])

    version, tag = rp.compute_release("core", bump=bump)

    assert version == expected
    assert tag == f"core-v{expected}"


def test_verify_tag_rejects_mismatched_package() -> None:
    with pytest.raises(SystemExit, match="does not start"):
        rp.verify_tag("scanner", "core-v0.1.0")


def test_scanner_legacy_parsing_uses_removeprefix_not_lstrip() -> None:
    assert rp.parse_tag("scanner", "vscanner-0.3.4") is None


def test_scanner_legacy_tag_is_considered_for_next_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rp, "read_file_version", lambda package: "0.3.4")
    stub_git(monkeypatch, ["v0.3.4"])

    version, tag = rp.compute_release("scanner", bump="patch")

    assert version == "0.3.5"
    assert tag == "scanner-v0.3.5"


@pytest.mark.parametrize("package", ["core", "downloader"])
def test_non_scanner_packages_ignore_legacy_v_tags(
    monkeypatch: pytest.MonkeyPatch,
    package: str,
) -> None:
    monkeypatch.setattr(rp, "read_file_version", lambda package: "0.1.0")
    stub_git(monkeypatch, ["v9.9.9"])

    version, tag = rp.compute_release(package, bump="patch")

    assert version == "0.1.1"
    assert tag == f"{package}-v0.1.1"
