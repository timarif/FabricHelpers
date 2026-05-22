"""Tests for ai.prompt."""
from __future__ import annotations

import json

from fabric_scanner.ai.prompt import (
    AI_AUDIT_PROMPT,
    AI_AUDIT_RESPONSE_FORMAT,
    PROMPT_VERSION,
)


def test_prompt_version_set():
    assert PROMPT_VERSION
    assert "-" in PROMPT_VERSION  # year-month-day-N format


def test_prompt_has_required_placeholders():
    """All four placeholders the runner substitutes must be present."""
    for placeholder in ("{file_name}", "{chunk_number}",
                        "{chunk_count}", "{chunk_text}"):
        assert placeholder in AI_AUDIT_PROMPT, (
            f"prompt missing placeholder: {placeholder}")


def test_response_format_is_json_schema():
    assert AI_AUDIT_RESPONSE_FORMAT["type"] == "json_schema"
    js = AI_AUDIT_RESPONSE_FORMAT["json_schema"]
    assert js["strict"] is True
    assert "schema" in js
    schema = js["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_response_format_required_fields():
    schema = AI_AUDIT_RESPONSE_FORMAT["json_schema"]["schema"]
    assert set(schema["required"]) == {
        "external_resource_access_score",
        "exfiltration_risk_score",
        "sources",
        "destinations",
        "rationale",
    }


def test_response_format_score_bounds():
    schema = AI_AUDIT_RESPONSE_FORMAT["json_schema"]["schema"]
    props = schema["properties"]
    for key in ("external_resource_access_score", "exfiltration_risk_score"):
        assert props[key]["type"] == "integer"
        assert props[key]["minimum"] == 0
        assert props[key]["maximum"] == 100


def test_response_format_endpoint_struct():
    """Sources and destinations must use the same endpoint sub-schema."""
    schema = AI_AUDIT_RESPONSE_FORMAT["json_schema"]["schema"]
    src = schema["properties"]["sources"]["items"]
    dest = schema["properties"]["destinations"]["items"]
    assert src == dest
    assert set(src["required"]) == {"endpoint", "type", "deterministic"}
    assert src["additionalProperties"] is False


def test_response_format_serializes_as_json():
    """Whatever we pass to ai.generate_response must be JSON-serializable."""
    s = json.dumps(AI_AUDIT_RESPONSE_FORMAT)
    roundtrip = json.loads(s)
    assert roundtrip == AI_AUDIT_RESPONSE_FORMAT
