"""Sanity tests for the regex PATTERNS / SUSPICIOUS_IMPORTS rule tables."""
from __future__ import annotations

from collections import Counter

from fabric_scanner.engine.patterns import (
    PATTERNS,
    SUSPICIOUS_IMPORTS,
    IMPORT_CATEGORIES,
    URL_PROTOCOL_SCHEMES,
    URL_RE,
    BENIGN_URL_PATTERNS,
)


def test_pattern_tuple_shape():
    """Each pattern row must be (compiled regex, category, severity, msg)."""
    import re
    for row in PATTERNS:
        assert len(row) == 4
        rx, cat, sev, msg = row
        assert isinstance(rx, re.Pattern), f"pattern not compiled: {row}"
        assert isinstance(cat, str) and cat
        assert sev in ("low", "medium", "high", "critical"), f"bad sev: {sev}"
        assert isinstance(msg, str) and msg


def test_pattern_count_and_categories_floor():
    cats = {row[1] for row in PATTERNS}
    assert len(PATTERNS) >= 100
    assert len(cats) >= 16
    assert "credential_access" in cats
    assert "api_key_leak" in cats
    assert "webhook_exfiltration" in cats


def test_url_re_finds_common_schemes():
    samples = [
        "https://example.com/path",
        "abfss://ws@onelake.dfs.fabric.microsoft.com/lh/Files/x.txt",
        "s3://bucket/key",
        "postgresql://user@host/db",
        "redis://h:6379",
    ]
    for s in samples:
        m = URL_RE.search(s)
        assert m is not None, f"URL_RE missed: {s}"


def test_benign_url_filter_drops_localhost():
    benign = ["https://localhost:8080/", "https://127.0.0.1/api"]
    for u in benign:
        assert any(bp.search(u) for bp in BENIGN_URL_PATTERNS), u


def test_no_duplicate_pattern_messages():
    """A duplicate message string usually means an accidental copy-paste."""
    msgs = [row[3] for row in PATTERNS]
    dupes = [m for m, n in Counter(msgs).items() if n > 1]
    assert not dupes, f"Duplicate pattern messages: {dupes}"


def test_import_categories_subset_of_suspicious():
    """Every key in IMPORT_CATEGORIES must also appear in SUSPICIOUS_IMPORTS."""
    missing = set(IMPORT_CATEGORIES) - set(SUSPICIOUS_IMPORTS)
    assert not missing, f"IMPORT_CATEGORIES has unknown imports: {missing}"


def test_url_scheme_list_nontrivial():
    assert len(URL_PROTOCOL_SCHEMES) >= 30
    assert "abfss://" in URL_PROTOCOL_SCHEMES
    assert "s3://" in URL_PROTOCOL_SCHEMES
