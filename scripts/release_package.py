"""Cross-package release helper.

Each command takes --package {core|scanner|downloader} and operates on
that package's _version.py and tag scheme. Tag scheme:

  core-vX.Y.Z       (new)
  downloader-vX.Y.Z (new)
  scanner-vX.Y.Z    (new) — but legacy vX.Y.Z also recognized for scanner

Output to stdout is GitHub Actions $GITHUB_OUTPUT format for `compute`,
`bump` is a side-effecting mutator that prints a brief confirmation.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_ASSIGN_RE = re.compile(r"(__version__\s*=\s*['\"])([^'\"]+)(['\"])")


@dataclass(frozen=True)
class PackageConfig:
    name: str
    directory: Path
    module_name: str
    tag_prefix: str
    legacy_tag_prefixes: tuple[str, ...] = ()

    @property
    def version_file(self) -> Path:
        return self.directory / "src" / self.module_name / "_version.py"

    @property
    def notebook_builder(self) -> Path:
        return self.directory / "scripts" / "build_notebook.py"


@dataclass(frozen=True)
class ParsedTag:
    version: tuple[int, int, int]
    tag: str
    is_prefixed: bool


PACKAGE_CONFIGS: dict[str, PackageConfig] = {
    "core": PackageConfig(
        name="core",
        directory=REPO_ROOT / "coreHelper",
        module_name="fabric_core",
        tag_prefix="core-v",
    ),
    "scanner": PackageConfig(
        name="scanner",
        directory=REPO_ROOT / "scannerHelper",
        module_name="fabric_scanner",
        tag_prefix="scanner-v",
        legacy_tag_prefixes=("v",),
    ),
    "downloader": PackageConfig(
        name="downloader",
        directory=REPO_ROOT / "downloaderHelper",
        module_name="fabric_downloader",
        tag_prefix="downloader-v",
    ),
    "mpe": PackageConfig(
        name="mpe",
        directory=REPO_ROOT / "mpeHelper",
        module_name="fabric_mpe",
        tag_prefix="mpe-v",
    ),
}


def get_config(package: str) -> PackageConfig:
    try:
        return PACKAGE_CONFIGS[package]
    except KeyError as exc:
        raise SystemExit(f"unknown package {package!r}") from exc


def parse_version(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise SystemExit(f"version {version!r} does not match X.Y.Z")
    return tuple(int(part) for part in match.groups())


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def format_tag(package: str, version: str) -> str:
    cfg = get_config(package)
    parse_version(version)
    return f"{cfg.tag_prefix}{version}"


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise SystemExit(detail or f"git {' '.join(args)} failed")
    return completed


def git_tag_names(package: str) -> list[str]:
    cfg = get_config(package)
    patterns = [f"{cfg.tag_prefix}*.*.*"]
    patterns.extend(f"{prefix}*.*.*" for prefix in cfg.legacy_tag_prefixes)

    tags: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for tag in run_git("tag", "--list", pattern).stdout.splitlines():
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


def tags_pointing_at_head() -> set[str]:
    return set(run_git("tag", "--points-at", "HEAD").stdout.split())


def tag_exists(tag: str) -> bool:
    return (
        run_git("rev-parse", "--verify", f"refs/tags/{tag}", check=False).returncode == 0
    )


def tag_points_at_head(tag: str) -> bool:
    return tag in tags_pointing_at_head()


def parse_tag(package: str, tag: str, *, allow_legacy: bool = True) -> ParsedTag | None:
    cfg = get_config(package)
    candidate: str | None = None
    is_prefixed = False

    if tag.startswith(cfg.tag_prefix):
        candidate = tag.removeprefix(cfg.tag_prefix)
        is_prefixed = True
    elif allow_legacy:
        for prefix in cfg.legacy_tag_prefixes:
            if tag.startswith(prefix):
                candidate = tag.removeprefix(prefix)
                break

    if candidate is None:
        return None

    match = SEMVER_RE.fullmatch(candidate)
    if not match:
        return None
    return ParsedTag(
        version=tuple(int(part) for part in match.groups()),
        tag=tag,
        is_prefixed=is_prefixed,
    )


def list_version_tags(package: str) -> list[ParsedTag]:
    parsed = [
        parsed_tag
        for tag in git_tag_names(package)
        if (parsed_tag := parse_tag(package, tag)) is not None
    ]
    parsed.sort(key=lambda item: (item.version, item.is_prefixed, item.tag))
    return parsed


def read_file_version(package: str) -> str:
    path = get_config(package).version_file
    text = path.read_text(encoding="utf-8")
    match = VERSION_ASSIGN_RE.search(text)
    if not match:
        raise SystemExit(f"could not find __version__ in {path}")
    version = match.group(2)
    parse_version(version)
    return version


def write_file_version(package: str, version: str) -> None:
    parse_version(version)
    path = get_config(package).version_file
    text = path.read_text(encoding="utf-8")
    new_text, count = VERSION_ASSIGN_RE.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise SystemExit(f"could not replace __version__ in {path}")
    if new_text == text:
        print(f"No version change needed for {path.relative_to(REPO_ROOT)} (already {version})")
        return
    path.write_text(new_text, encoding="utf-8")
    print(f"Wrote {path.relative_to(REPO_ROOT)} = {version}")


def bump_version(version: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    if bump == "patch":
        return major, minor, patch + 1
    raise SystemExit(f"unknown bump {bump!r}; expected patch, minor, or major")


def compute_release(
    package: str,
    *,
    bump: str = "patch",
    version_override: str = "",
) -> tuple[str, str]:
    file_version = read_file_version(package)
    file_tuple = parse_version(file_version)
    tags = list_version_tags(package)
    latest = tags[-1] if tags else None
    latest_tuple = latest.version if latest else (0, 0, 0)
    latest_tag = latest.tag if latest else "<none>"

    version_override = (version_override or "").strip()
    if version_override:
        override_tuple = parse_version(version_override)
        desired_tag = format_tag(package, version_override)
        desired_tag_exists = tag_exists(desired_tag)
        if desired_tag_exists and not tag_points_at_head(desired_tag):
            raise SystemExit(f"tag {desired_tag} already exists and does not point at HEAD")
        if override_tuple <= latest_tuple and not desired_tag_exists:
            raise SystemExit(
                f"version {version_override} is not greater than latest tag {latest_tag}"
            )
        return version_override, desired_tag

    head_tags = tags_pointing_at_head()
    matching_head_tags = [
        tag for tag in tags if tag.tag in head_tags and tag.version == file_tuple
    ]
    if matching_head_tags:
        chosen = matching_head_tags[-1]
        print(f"::notice::HEAD already tagged {chosen.tag}; reusing.", file=sys.stderr)
        return file_version, chosen.tag

    next_version = bump_version(max(latest_tuple, file_tuple), bump)
    version = format_version(next_version)
    return version, format_tag(package, version)


def verify_tag(package: str, tag: str) -> None:
    cfg = get_config(package)
    if not tag.startswith(cfg.tag_prefix):
        raise SystemExit(f"tag {tag!r} does not start with {cfg.tag_prefix!r}")
    version = tag.removeprefix(cfg.tag_prefix)
    parse_version(version)
    file_version = read_file_version(package)
    print(f"tag           = {tag}")
    print(f"tag_version   = {version}")
    print(f"file_version  = {file_version}")
    if version != file_version:
        raise SystemExit(
            f"Tag ({version}) does not match _version.py ({file_version})."
        )


def latest_tag(package: str) -> str:
    tags = list_version_tags(package)
    return tags[-1].tag if tags else ""


def regen_notebooks(package: str) -> None:
    cfg = get_config(package)
    builder = cfg.notebook_builder
    if not builder.exists():
        print(f"no notebooks for {package}")
        return
    subprocess.run(
        [sys.executable, str(builder.relative_to(cfg.directory))],
        cwd=cfg.directory,
        check=True,
    )


def add_package_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--package",
        required=True,
        choices=sorted(PACKAGE_CONFIGS),
        help="Package to operate on.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-package release helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compute = subparsers.add_parser("compute", help="Compute the next version and tag")
    add_package_arg(compute)
    compute.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    compute.add_argument("--version", default="", help="Explicit X.Y.Z version override")

    bump = subparsers.add_parser("bump", help="Mutate package _version.py")
    add_package_arg(bump)
    bump.add_argument("--version", required=True, help="X.Y.Z version to write")

    verify = subparsers.add_parser("verify-tag", help="Verify tag matches _version.py")
    add_package_arg(verify)
    verify.add_argument("--tag", required=True, help="Full package tag")

    latest = subparsers.add_parser("latest-tag", help="Print latest package tag")
    add_package_arg(latest)

    regen = subparsers.add_parser("regen-notebooks", help="Regenerate package notebooks")
    add_package_arg(regen)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "compute":
        version, tag = compute_release(
            args.package,
            bump=args.bump,
            version_override=args.version,
        )
        print(f"version={version}")
        print(f"tag={tag}")
        return 0

    if args.command == "bump":
        write_file_version(args.package, args.version)
        return 0

    if args.command == "verify-tag":
        verify_tag(args.package, args.tag)
        return 0

    if args.command == "latest-tag":
        print(latest_tag(args.package))
        return 0

    if args.command == "regen-notebooks":
        regen_notebooks(args.package)
        return 0

    raise SystemExit(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
