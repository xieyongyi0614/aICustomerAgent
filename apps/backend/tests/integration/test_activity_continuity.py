"""V6.5-006 Case 10：活动连续性（切西瓜后问天气）。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.models.scene import SceneState
from app.repositories import scene_state_repository
from app.services import agent_service
from tests.conftest import wait_until

DEFAULT_MODE = {
    "mode": "default",
    "intent": "casual",
    "confidence": 0.9,
    "reason": "日常对话",
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


def _post(client, content, session_id=None):
    body = {"content": content}
    if session_id:
        body["session_id"] = session_id
    resp = client.post("/api/v1/chat/message", json=body)
    assert resp.status_code == 200
    return resp


def test_activity_continuity_injects_section_and_reduces_budget(
    client, fake_llm
):
    llm = fake_llm(
        response=["天上晴着呢"],
        structured_responses={
            "RoleMode": DEFAULT_MODE,
            "TurnAnalysis": ANALYSIS,
            "IntentionDecision": CONTINUE,
        },
    )
    llm_factory.set_llm(llm)
    first = _post(client, "在吗")
    session_id = first.headers.get("x-session-id")
    wait_until(lambda: not agent_service._background_tasks)
    scene_state_repository.upsert_scene_state(
        session_id, SceneState(session_id=session_id, current_activity="切西瓜")
    )
    _post(client, "现在天气怎么样", session_id)

    prompts = [str(m) for m in llm.seen_messages if "【活动延续】" in str(m)]
    assert prompts, "应注入【活动延续】段"
    assert any("切西瓜" in p for p in prompts)
    assert any("本轮不做动作描写" in p for p in prompts)


def test_idle_session_has_no_activity_section(client, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={
            "RoleMode": DEFAULT_MODE,
            "TurnAnalysis": ANALYSIS,
        },
    )
    llm_factory.set_llm(llm)
    _post(client, "在吗")
    assert not any("【活动延续】" in str(m) for m in llm.seen_messages)


def test_pending_scene_no_double_injection(client, fake_llm):
    from app.models.scene import PendingAction

    llm = fake_llm(
        response=["马上来"],
        structured_responses={
            "RoleMode": DEFAULT_MODE,
            "TurnAnalysis": ANALYSIS,
            "IntentionDecision": CONTINUE,
            "SceneIntentResult": {"intent": "request_action", "confidence": 0.9, "reason": "请求动作"},
        },
    )
    llm_factory.set_llm(llm)
    first = _post(client, "在吗")
    session_id = first.headers.get("x-session-id")
    wait_until(lambda: not agent_service._background_tasks)
    scene_state_repository.upsert_scene_state(
        session_id,
        SceneState(
            session_id=session_id,
            pending_action=PendingAction(action="拿西瓜", status="pending"),
        ),
    )
    resp = _post(client, "给我拿西瓜", session_id)
    assert resp.status_code == 200
    scene_prompts = [str(m) for m in llm.seen_messages if "【本轮指令】" in str(m)]
    assert scene_prompts, "pending 场景应有 directive 接管"
    assert not any("【活动延续】" in p for p in scene_prompts)
