"""Provider-specific API-key regex tests (promoted from `_smoketest_api_keys.py`).

Tokens are assembled at runtime from harmless pieces so secret scanners
never see a real-shape literal in source. The scanner must flag every
synthetic token as `api_key_leak` and must NOT flag benign control snippets.
"""
from __future__ import annotations

import json

import pytest

from fabric_scanner import ScannerConfig, scan_notebook_bytes


# Each tuple: (label, token_chunks).  Token chunks are concatenated at test
# time so the literal token never appears in source on a single line.
POSITIVES: list[tuple[str, tuple[str, ...]]] = [
    ("AWS Access Key",        ("AKIA", "A" * 16)),
    ("AWS Session Key",       ("ASIA", "A" * 16)),
    ("AWS Secret 40-char",    ('aws_secret_access_key = "',
                               "A" * 20 + "/" + "A" * 19, '"')),
    ("Google API key",        ("AIza", "A" * 35)),
    ("Google OAuth ya29",     ("ya29.", "A" * 40)),
    ("Google OAuth client",   ("1234567890-", "A" * 32,
                               ".apps.googleusercontent.com")),
    ("GitHub PAT ghp",        ("ghp_", "A" * 36)),
    ("GitHub PAT new",        ("github_pat_", "A" * 82)),
    ("GitLab PAT",            ("glpat-", "A" * 20)),
    ("Anthropic key",         ("sk-ant-", "api03-", "A" * 95)),
    ("OpenAI key",            ("sk-", "A" * 20, "T3BlbkFJ", "A" * 20)),
    ("Hugging Face token",    ("hf_", "A" * 36)),
    ("Stripe sk_live",        ("sk_", "live_", "A" * 24)),
    ("Stripe rk_test",        ("rk_", "test_", "A" * 24)),
    ("Stripe pk_live",        ("pk_", "live_", "A" * 24)),
    ("SendGrid",              ("SG.", "A" * 22, ".", "A" * 43)),
    ("Mailgun key",           ("key-", "a" * 32)),
    ("Slack xoxb",            ("xoxb-", "1" * 10, "-", "1" * 11, "-", "A" * 24)),
    ("Twilio SK",             ("SK", "f" * 32)),
    ("Twilio AC",             ("AC", "f" * 32)),
    ("Square access",         ("sq0", "atp-", "A" * 22)),
    ("npm token",             ("npm_", "A" * 36)),
    ("PyPI token",            ("pypi-", "AgEIcHlwaS5vcmcC", "x" * 60)),
    ("DigitalOcean token",    ("dop_v1_", "a" * 64)),
    ("Shopify access",        ("shpat_", "a" * 32)),
    ("Shopify shared",        ("shpss_", "a" * 32)),
    ("Discord bot token",     ("M", "A" * 23, ".", "a" * 6, ".", "z" * 30)),
]

BENIGN = [
    'msg = "Hello world this is just a normal log line"',
    'url = "https://github.com/example/repo"',
    'note = "AKIA"  # provider prefix only, no key body',
    'comment = "ghp underscore short"  # too short for a real token',
]


def _nb(src: str) -> bytes:
    return json.dumps({
        "cells": [{"cell_type": "code", "source": src, "metadata": {},
                   "execution_count": None, "outputs": []}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }).encode("utf-8")


@pytest.mark.parametrize("name,chunks", POSITIVES)
def test_positives_fire(name, chunks):
    token = "".join(chunks)
    code = f'x = "{token}"'
    cfg = ScannerConfig(min_severity="low")
    findings = scan_notebook_bytes(_nb(code), "fixture.ipynb", cfg)
    cats = {f["category"] for f in findings}
    assert "api_key_leak" in cats, f"{name}: api_key_leak not raised. Got {cats}"


def test_no_false_positives_on_benign_code():
    cfg = ScannerConfig(min_severity="low")
    for code in BENIGN:
        findings = scan_notebook_bytes(_nb(code), "fixture.ipynb", cfg)
        api_key_hits = [f for f in findings if f["category"] == "api_key_leak"]
        assert not api_key_hits, (
            f"benign code triggered api_key_leak: {code}\n{api_key_hits}")
