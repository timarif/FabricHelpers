"""``fabric-tenant`` console entrypoint.

Phase 1 scaffold — subcommands are wired in Phases 2+:

* ``snapshot``  — Phase 2 (auth + GET /v1/admin/tenantsettings → JSON file)
* ``diff``      — Phase 3 (normalize + structural compare)
* ``compare``   — Phase 5 (snapshot left + snapshot right + diff, in one step)
* ``drift``     — Phase 7 (compare a profile's current snapshot vs a past one)

Running the CLI before Phase 2 lands prints the planned interface and exits 2
so smoke tests can ``invoke --help`` without an ImportError but CI doesn't
treat the placeholder as a usable tool.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fabric-tenant",
        description=(
            "Snapshot and compare Microsoft Fabric admin tenant settings across "
            "two physically different Fabric tenants. See "
            "https://github.com/timarif/FabricHelpers/issues/44 for status."
        ),
    )
    parser.add_argument("--version", action="version", version=f"fabric-tenant {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{snapshot,diff,compare,drift}")

    sub.add_parser(
        "snapshot",
        help="(Phase 2) GET /v1/admin/tenantsettings for one profile and write a snapshot JSON file.",
    )
    sub.add_parser(
        "diff",
        help="(Phase 3) Compare two snapshot files and produce a risk-tiered diff.",
    )
    sub.add_parser(
        "compare",
        help="(Phase 5) Snapshot two profiles and diff in one step.",
    )
    sub.add_parser(
        "drift",
        help="(Phase 7) Compare one profile's latest snapshot against an older one.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help(sys.stderr)
        return 2

    print(
        f"fabric-tenant {__version__}: subcommand '{args.command}' is not implemented yet "
        f"(scaffolding only — see roadmap in README.md).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
