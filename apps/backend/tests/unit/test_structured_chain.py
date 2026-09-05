import json

from pydantic import BaseModel

from app.chains.structured import (
    _extract_json_text,
    _tolerant_schema,
    _unwrap_json,
)
from app.models.emotion import TurnAnalysis


class _Simple(BaseModel):
    name: str = "x"


def _analysis_payload():
    return {
        "user_emotion": {"emotion": "happy", "event": "daily"},
        "behavior": {"behavior": "normal_reply", "reason": ""},
    }


def test_unwrap_json_takes_first_element_of_list():
    data = _unwrap_json(json.dumps([_analysis_payload(), {"other": 1}]))
    assert data == _analysis_payload()


def test_unwrap_json_empty_list_becomes_empty_object():
    assert _unwrap_json("[]") == {}


def test_unwrap_json_object_passthrough():
    payload = _analysis_payload()
    assert _unwrap_json(json.dumps(payload)) == payload


def test_extract_json_text_keeps_pure_array():
    text = json.dumps([_analysis_payload()])
    assert _extract_json_text(text) == text


def test_extract_json_text_still_slices_object():
    text = '前言 {"a": 1} 后记'
    assert _extract_json_text(text) == '{"a": 1}'


def test_extract_json_text_unfenced_array():
    text = '```json\n[{"a": 1}]\n```'
    assert _extract_json_text(text) == '[{"a": 1}]'


def test_tolerant_schema_accepts_object():
    schema = _tolerant_schema(_Simple)
    parsed = schema.model_validate_json('{"name": "y"}')
    assert isinstance(parsed, _Simple)
    assert parsed.name == "y"


def test_tolerant_schema_unwraps_list():
    schema = _tolerant_schema(_Simple)
    parsed = schema.model_validate_json(json.dumps([{"name": "y"}]))
    assert isinstance(parsed, _Simple)
    assert parsed.name == "y"


def test_tolerant_schema_unwraps_turn_analysis_list():
    schema = _tolerant_schema(TurnAnalysis)
    parsed = schema.model_validate_json(json.dumps([_analysis_payload()]))
    assert isinstance(parsed, TurnAnalysis)
    assert parsed.user_emotion.emotion == "happy"
