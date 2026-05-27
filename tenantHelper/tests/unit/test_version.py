"""Sanity tests for the Phase 1 scaffold.

These don't assert behavioral semantics (those come in Phase 2+); they just
verify the wheel is importable, ``__version__`` is well-formed, and the CLI
parser builds without error so the build pipeline has something concrete to
gate on.
"""
from __future__ import annotations

import re

import fabric_tenant
from fabric_tenant import cli


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_semver():
    assert SEMVER_RE.match(fabric_tenant.__version__), (
        f"__version__ must be X.Y.Z, got {fabric_tenant.__version__!r}"
    )


def test_cli_parser_builds_and_help_lists_planned_subcommands(capsys):
    parser = cli.build_parser()
    parser.print_help()
    out = capsys.readouterr().out
    for subcommand in ("snapshot", "diff", "compare", "drift"):
        assert subcommand in out, f"help output missing '{subcommand}': {out!r}"


def test_cli_no_args_returns_2_and_prints_help(capsys):
    rc = cli.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "fabric-tenant" in err


def test_cli_unimplemented_subcommand_returns_2(capsys):
    rc = cli.main(["snapshot"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not implemented yet" in err
