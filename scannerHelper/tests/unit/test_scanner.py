"""End-to-end `scan_notebook_bytes` tests against the four fixture notebooks.

Fixtures live in tests/fixtures/ — generate them with
`python tests/fixtures/build_fixtures.py` if they ever need a refresh.
"""
from __future__ import annotations

from fabric_scanner import ScannerConfig, scan_notebook_bytes


def _scan(content: bytes, label: str, **kw) -> list[dict]:
    cfg = ScannerConfig(**kw)
    return scan_notebook_bytes(content, label, cfg)


def test_clean_notebook_has_no_high_findings(load_fixture):
    content = load_fixture("sample_clean.ipynb")
    findings = _scan(content, "sample_clean.ipynb", min_severity="high")
    assert findings == [], (
        f"clean notebook should produce 0 high+ findings, got:\n"
        f"{[(f['category'], f['severity'], f['message']) for f in findings]}")


def test_secrets_notebook_flags_multiple_providers(load_fixture):
    content = load_fixture("sample_secrets.ipynb")
    findings = _scan(content, "sample_secrets.ipynb", min_severity="low")
    cats = {f["category"] for f in findings}
    api_key_findings = [f for f in findings if f["category"] == "api_key_leak"]
    assert "api_key_leak" in cats
    assert len(api_key_findings) >= 4, (
        f"expected >=4 distinct api_key_leak findings, got {len(api_key_findings)}: "
        f"{[f['message'] for f in api_key_findings]}")


def test_cross_workspace_notebook_marks_dest(load_fixture):
    content = load_fixture("sample_cross_workspace.ipynb")
    findings = _scan(content, "sample_cross_workspace.ipynb", min_severity="low")
    url_findings = [f for f in findings if f["finding_type"] == "url"]
    assert url_findings, "expected at least one URL finding"
    abfss = [f for f in url_findings if f["url"].startswith("abfss://")]
    assert abfss, "expected an abfss URL"


def test_attached_lakehouse_metadata_propagates(load_fixture):
    content = load_fixture("sample_attached_lh.ipynb")
    findings = _scan(content, "sample_attached_lh.ipynb", min_severity="low")
    assert findings, "fixture should produce at least one finding"
    f = findings[0]
    assert f["attached_lakehouse_id"] == "lh-attached-001"
    assert f["attached_lakehouse_name"] == "AttachedBronze"
    assert f["attached_lakehouse_workspace_id"] == "ws-attached-aaa"


def test_min_severity_high_drops_lows(load_fixture):
    content = load_fixture("sample_secrets.ipynb")
    high_only = _scan(content, "sample_secrets.ipynb", min_severity="high")
    assert all(f["severity"] in ("high", "critical") for f in high_only)


def test_part_path_set_for_fabric_item_json(load_fixture):
    """Verify scan over Fabric Item JSON with definition.parts yields
    findings carrying the original part_path."""
    import base64
    import json
    inner = load_fixture("sample_secrets.ipynb")
    outer = json.dumps({"definition": {"parts": [
        {"path": "notebook-content.ipynb",
         "payload": base64.b64encode(inner).decode("ascii")},
    ]}}).encode("utf-8")
    findings = _scan(outer, "item.json", min_severity="low")
    assert findings
    parts = {f["part_path"] for f in findings}
    assert "notebook-content.ipynb" in parts
