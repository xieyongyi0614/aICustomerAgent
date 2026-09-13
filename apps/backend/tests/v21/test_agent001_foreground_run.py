"""AGENT-001 前台收编集成测试（foreground_chat Run）。

覆盖：unified 开启时 chat 消息产生 run_kind=foreground_chat 台账（profile/
trigger_type/成本汇总）、预算软降级 → degraded 终态、unified 关闭时零台账。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.repositories import loop_run_repository

COMFORT_ANALYSIS = {
    "user_emotion": {"emotion": "sad", "event": "setback"},
    "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
}
COMFORT_INTENTION = {
    "intention": "comfort_user",
    "confidence": 0.9,
    "reason": "用户情绪低落",
}
DEFAULT_MODE = {
    "mode": "default",
    "intent": "casual",
    "confidence": 0.9,
    "reason": "日常对话",
}
SCENE_CHAT = {"intent": "chat", "confidence": 0.9, "reason": "闲聊"}


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client


def _structured_llm(fake_llm):
    return fake_llm(
        response="抱抱你，辛苦了。",
        structured_responses={
            "RoleMode": DEFAULT_MODE,
            "TurnAnalysis": COMFORT_ANALYSIS,
            "SceneIntentResult": SCENE_CHAT,
            "IntentionDecision": COMFORT_INTENTION,
        },
    )


def _post(client, content="我很难过"):
    resp = client.post("/api/v1/chat/message", json={"content": content})
    assert resp.status_code == 200
    return json.loads(resp.text.splitlines()[0])


class TestForegroundRun:
    def test_chat_creates_foreground_run_row(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_UNIFIED_RUN_ENABLED="true",
        )
        llm_factory.set_llm(_structured_llm(fake_llm))

        meta = _post(client)

        assert meta["type"] == "turn_meta"
        runs = loop_run_repository.list_recent(run_kind="foreground_chat")
        assert len(runs) == 1
        run = runs[0]
        assert run.kind == "chat"
        assert run.trigger_type == "channel_message"
        assert run.status == "done"
        assert run.profile["budget_tier"] == "foreground"
        assert run.profile["stages"][0] == "perception"
        assert run.finished_at is not None

    def test_run_budget_soft_degradation_marks_terminal(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_UNIFIED_RUN_ENABLED="true",
            V21_FOREGROUND_RUN_LLM_BUDGET="0",
        )
        llm_factory.set_llm(_structured_llm(fake_llm))

        _post(client)

        run = loop_run_repository.list_recent(run_kind="foreground_chat")[0]
        assert run.status == "degraded"

    def test_unified_off_creates_no_run_row(
        self, db_session_factory, override_settings, client, fake_llm
    ):
        override_settings(V21_AGENT_RUNTIME_ENABLED="false")
        llm_factory.set_llm(_structured_llm(fake_llm))

        _post(client)

        assert loop_run_repository.list_recent(kind="chat") == []
