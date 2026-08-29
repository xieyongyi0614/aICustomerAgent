"""V6.5-005/006：chat_pipeline 接入 behavior_engine 的集成验证（FakeLLM 全链路）。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from tests.conftest import wait_until

COMFORT_ANALYSIS = {
    "user_emotion": {"emotion": "sad", "event": "setback"},
    "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
}
COMFORT_INTENTION = {"intention": "comfort_user", "confidence": 0.9, "reason": "用户情绪低落"}
DEFAULT_MODE = {
    "mode": "default",
    "intent": "casual",
    "confidence": 0.9,
    "reason": "日常对话",
}


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client


def _post(client, content, session_id=None):
    body = {"content": content}
    if session_id:
        body["session_id"] = session_id
    resp = client.post("/api/v1/chat/message", json=body)
    assert resp.status_code == 200
    return json.loads(resp.text.splitlines()[0])


def _structured(**extra):
    payload = {
        "RoleMode": DEFAULT_MODE,
        "TurnAnalysis": COMFORT_ANALYSIS,
    }
    payload.update(extra)
    return payload


def test_turn_meta_carries_behavior_fields(client, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["我在这"],
            structured_responses=_structured(IntentionDecision=COMFORT_INTENTION),
        )
    )
    meta = _post(client, "我很难过")
    behavior = meta["behavior"]
    assert behavior["degraded"] is False
    assert behavior["strategy"] == "quiet_companion"
    assert behavior["budget"]["max_action_desc"] == 0
    assert behavior["budget"]["allow_action_desc"] is True


def test_prompt_contains_behavior_section_not_v2(client, fake_llm):
    llm = fake_llm(
        response=["我在这"],
        structured_responses=_structured(IntentionDecision=COMFORT_INTENTION),
    )
    llm_factory.set_llm(llm)
    _post(client, "我很难过")

    def _check():
        return any("【表现方式】" in str(m) for m in llm.seen_messages)

    assert wait_until(_check)
    behavior_prompts = [str(m) for m in llm.seen_messages if "【表现方式】" in str(m)]
    assert any("本轮不做动作描写" in p for p in behavior_prompts)
    assert all("【本轮行为指令】" not in p for p in behavior_prompts)


def test_intention_degraded_falls_back_to_v2_section(client, fake_llm):
    llm = fake_llm(
        response=["我在这"],
        structured_responses=_structured(
            IntentionDecision=COMFORT_INTENTION,
        ),
        structured_errors={"IntentionDecision": RuntimeError("intention boom")},
    )
    llm_factory.set_llm(llm)
    meta = _post(client, "我很难过")
    assert meta["behavior"]["degraded"] is True
    assert meta["behavior"]["strategy"] == "natural_continuation"

    def _check():
        return any("【本轮行为指令】" in str(m) for m in llm.seen_messages)

    assert wait_until(_check)
    assert any("先接住用户的情绪" in str(m) for m in llm.seen_messages)


def test_answer_unblocked_when_behavior_degraded(client, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["嗯"],
            structured_responses=_structured(),
            structured_errors={"IntentionDecision": RuntimeError("boom")},
        )
    )
    meta = _post(client, "在吗")
    deltas = "".join(line.get("delta", "") for line in [])
    assert meta["behavior"]["degraded"] is True
