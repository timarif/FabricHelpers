"""Guard: fabric_scanner must not import fabric_downloader."""
import ast
import pathlib

import fabric_scanner

FORBIDDEN_PREFIXES = ("fabric_downloader",)


def _all_python_files(pkg) -> list[pathlib.Path]:
    pkg_dir = pathlib.Path(pkg.__file__).parent
    return sorted(pkg_dir.rglob("*.py"))


def _imports_in_file(py: pathlib.Path) -> list[str]:
    tree = ast.parse(py.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_scanner_does_not_import_downloader():
    offenders: list[tuple[str, str]] = []
    for py in _all_python_files(fabric_scanner):
        for name in _imports_in_file(py):
            if name.startswith(FORBIDDEN_PREFIXES):
                offenders.append((str(py), name))
    assert offenders == [], (
        f"fabric_scanner must not import downloader; offenders: {offenders}"
    )
