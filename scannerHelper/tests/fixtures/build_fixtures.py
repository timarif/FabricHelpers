"""Generates the four `.ipynb` test fixtures next to this script.

Run once after cloning, or whenever the fixture content needs to change:

    python tests/fixtures/build_fixtures.py

This script intentionally produces *plain* .ipynb documents — no Fabric
Item JSON wrapping — to keep the diffs review-friendly. The scanner already
covers Fabric Item JSON via `test_extract.py::test_extract_fabric_item_*`.
"""
from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).parent


def _nb(cells: list[dict], metadata: dict | None = None) -> bytes:
    return json.dumps({
        "cells": cells, "metadata": metadata or {},
        "nbformat": 4, "nbformat_minor": 5,
    }, indent=2).encode("utf-8")


def _code(src: str) -> dict:
    return {"cell_type": "code", "source": src, "metadata": {},
            "execution_count": None, "outputs": []}


def _md(src: str) -> dict:
    return {"cell_type": "markdown", "source": src, "metadata": {}}


def build_clean() -> bytes:
    return _nb([
        _md("# Clean sample\n\nThis notebook only references benign URLs."),
        _code('print("hello world")\n'
              'x = sum(range(10))\n'
              '# docs: https://docs.python.org/3/library/sum.html\n'),
        _code('import math\n'
              'print(math.pi)\n'),
    ])


def build_secrets() -> bytes:
    # Tokens are concatenated from harmless chunks so secret scanners
    # don't flag this file. The total token still matches the regex
    # because the *final concatenated bytes* are what the scanner sees.
    aws    = "AKIA"        + "A" * 16
    secret = "A" * 20 + "/" + "A" * 19
    ghp    = "ghp_"        + "A" * 36
    oai    = "sk-"         + "A" * 20 + "T3BlbkFJ" + "A" * 20
    stripe = "sk_"         + "live_" + "A" * 24
    slack  = "xoxb-"       + "1" * 10 + "-" + "1" * 11 + "-" + "A" * 24
    google = "AIza"        + "A" * 35
    code = (
        '# Provider tokens - synthetic; tests/fixtures/build_fixtures.py '
        'assembles them at fixture-build time so no real-shape literal '
        'ever appears in source.\n'
        f'AWS_ACCESS_KEY_ID = "{aws}"\n'
        f'AWS_SECRET_ACCESS_KEY = "{secret}"\n'
        f'GITHUB_PAT = "{ghp}"\n'
        f'OPENAI_KEY = "{oai}"\n'
        f'STRIPE = "{stripe}"\n'
        f'SLACK = "{slack}"\n'
        f'GOOGLE = "{google}"\n'
    )
    return _nb([
        _md("# Secrets sample\n\n**Do not** commit these - they exist purely "
            "for regex coverage testing."),
        _code(code),
        _code(
            'import requests\n'
            'r = requests.post("https://hooks.slack.com/services/T00/B00/XXX",\n'
            '                  json={"text": "hi"})\n'
        ),
    ])


def build_cross_workspace() -> bytes:
    return _nb([
        _md("# Cross-workspace sample"),
        _code(
            'src = "abfss://22222222-2222-2222-2222-222222222222@onelake.dfs'
            '.fabric.microsoft.com/33333333-3333-3333-3333-333333333333/Files/data.parquet"\n'
            'df = spark.read.parquet(src)\n'
            'df.write.mode("overwrite").parquet("abfss://44444444-4444-4444-4444-444444444444'
            '@onelake.dfs.fabric.microsoft.com/55555555-5555-5555-5555-555555555555/Files/out")\n'
        ),
    ])


def build_attached_lh() -> bytes:
    return _nb(
        [_code(
            'import requests\n'
            'r = requests.post("https://example.com/api/upload", json={"x": 1})\n'
            'df = spark.read.table("bronze.transactions")\n'
        )],
        metadata={
            "dependencies": {
                "lakehouse": {
                    "default_lakehouse": "lh-attached-001",
                    "default_lakehouse_name": "AttachedBronze",
                    "default_lakehouse_workspace_id": "ws-attached-aaa",
                    "known_lakehouses": [{"id": "lh-attached-001"}],
                },
            },
        },
    )


def main() -> None:
    fixtures = {
        "sample_clean.ipynb": build_clean(),
        "sample_secrets.ipynb": build_secrets(),
        "sample_cross_workspace.ipynb": build_cross_workspace(),
        "sample_attached_lh.ipynb": build_attached_lh(),
    }
    for name, content in fixtures.items():
        path = HERE / name
        path.write_bytes(content)
        print(f"wrote {path.relative_to(HERE.parent.parent)} "
              f"({len(content):,} bytes)")


if __name__ == "__main__":
    main()
