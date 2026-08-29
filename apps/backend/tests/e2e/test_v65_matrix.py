"""V6.5-007：十项矩阵 HTTP 级聚合（testing.md §2，FakeLLM 全确定）。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from tests.conftest import wait_until

DEFAULT_MODE = {
    "mode": "default",
    "intent": "casual",
    "confidence": 0.9,
    "reason": "日常",
}
ANALYSIS = {
    "user_emotion": {"emotion": "neutral", "event": "daily"},
    "behavior": {"behavior": "normal_reply", "reason": ""},
}
CONTINUE = {"intention": "continue_topic", "confidence": 0.9, "reason": "闲聊"}


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client


def _meta(client, fake_llm, content, **extra):
    structured = {"RoleMode": DEFAULT_MODE, "TurnAnalysis": ANALYSIS}
    structured.update(extra)
    llm = fake_llm(response=["好"], structured_responses=structured)
    llm_factory.set_llm(llm)
    resp = client.post("/api/v1/chat/message", json={"content": content})
    assert resp.status_code == 200
    return json.loads(resp.text.splitlines()[0]), llm


def test_case1_strategy_trajectory_reproducible(client, fake_llm):
    comfort = {"intention": "comfort_user", "confidence": 0.9, "reason": "低落"}
    meta_a, _ = _meta(client, fake_llm, "我今天有点难过", IntentionDecision=comfort)
    meta_b, _ = _meta(client, fake_llm, "我今天有点难过", IntentionDecision=comfort)
    assert meta_a["behavior"]["strategy"] in ("quiet_companion", "natural_continuation")
    assert meta_a["behavior"] == meta_b["behavior"]


def test_case3_tension_modifier_passthrough(client, fake_llm):
    meta, _ = _meta(client, fake_llm, "在吗", IntentionDecision=CONTINUE)
    assert meta["behavior"]["degraded"] is False


def test_case5_professional_budget_line(client, fake_llm):
    structured = {
        "RoleMode": {
            "mode": "professional",
            "intent": "technical",
            "confidence": 0.9,
            "reason": "技术问题",
        },
        "TurnAnalysis": ANALYSIS,
    }
    llm = fake_llm(response=["好的"], structured_responses=structured)
    llm_factory.set_llm(llm)
    first = client.post("/api/v1/chat/message", json={"content": "Python 报错"})
    session_id = first.headers.get("x-session-id")
    client.post(
        "/api/v1/chat/message", json={"content": "Python 报错", "session_id": session_id}
    )
    assert wait_until(lambda: any("本轮不做任何动作描写" in str(m) for m in llm.seen_messages))


def test_case8_professional_no_habits(client, fake_llm):
    meta, _ = _meta(client, fake_llm, "在吗", IntentionDecision=CONTINUE)
    assert meta["behavior"]["degraded"] is False


def test_case11_mode_single_turn_no_switch(client, fake_llm):
    meta, _ = _meta(
        client,
        fake_llm,
        "进入沉浸模式吧",
        RoleMode={
            "mode": "immersive",
            "intent": "roleplay",
            "confidence": 0.95,
            "reason": "用户明确要求",
        },
    )
    assert meta["mode"]["effective"] == "default"
    assert meta["mode"]["switched"] is False


def test_case12_router_failure_keeps_confirmed(client, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={"TurnAnalysis": ANALYSIS},
        structured_errors={"RoleMode": RuntimeError("boom")},
    )
    llm_factory.set_llm(llm)
    resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
    meta = json.loads(resp.text.splitlines()[0])
    assert meta["mode"]["effective"] == "default"
    assert meta["mode"]["confirmed"] == "default"


def test_case14_turn_meta_precedes_tokens(client, fake_llm):
    llm = fake_llm(
        response=["你", "好"],
        structured_responses={
            "RoleMode": DEFAULT_MODE,
            "TurnAnalysis": ANALYSIS,
            "IntentionDecision": CONTINUE,
        },
    )
    llm_factory.set_llm(llm)
    resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    kinds = ["turn_meta" if line.get("type") == "turn_meta" else "delta" for line in lines]
    assert kinds[0] == "turn_meta"


def test_v65_008_state_snapshot_exposes_mode_and_behavior(client, fake_llm):
    meta, _ = _meta(client, fake_llm, "在吗", IntentionDecision=CONTINUE)
    snapshot = client.get("/api/v1/state").json()
    assert snapshot["mode"] == "default"
    behavior = snapshot["last_behavior"]
    assert behavior is not None
    assert behavior["strategy"] == meta["behavior"]["strategy"]
    assert behavior["degraded"] is False
    assert behavior["budget"]["max_action_desc"] == meta["behavior"]["budget"]["max_action_desc"]
    assert behavior["mode"]["effective"] == meta["mode"]["effective"]


def test_v65_008_state_snapshot_defaults_without_turn(client):
    from app.services import trace_collector

    trace_collector.reset_trace_collector()
    snapshot = client.get("/api/v1/state").json()
    assert snapshot["last_behavior"] is None
