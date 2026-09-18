"""AGENT-001 兼容回归测试（Flag off = v2.0.0 行为）。

覆盖：enablement 依赖校验（unified 依赖总闸）、总闸关闭时 tick 走
v2.0.0 原路径（run_kind 为 NULL 的旧形态台账）、前台不产生 loop_runs 行。
"""

from datetime import datetime, timedelta

import pytest

from app.application import life_loop
from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations
from app.repositories import (
    conversation_repository,
    loop_run_repository,
)
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "compat-user"
SESSION = "compat-s1"


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings( world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


class TestEnablement:
    def test_unified_requires_runtime(self, override_settings):
        override_settings(V21_UNIFIED_RUN_ENABLED="true")
        violations = enablement_violations(get_settings())
        assert any("v21_unified_run_enabled" in v for v in violations)

    def test_legal_combo_has_no_v21_violations(self, override_settings):
        override_settings(
            V21_AGENT_RUNTIME_ENABLED="true",
            V21_UNIFIED_RUN_ENABLED="true",
        )
        violations = [
            v for v in enablement_violations(get_settings()) if "v21" in v
        ]
        assert violations == []


class TestFlagOffBehavior:
    @pytest.mark.asyncio
    async def test_tick_uses_legacy_run_shape(
        self, db_session_factory, life_loop_on, monkeypatch
    ):
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )
        from app.application import autonomy_engine

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(autonomy_engine, "tick", fake_tick)
        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.kind == "autonomy"
        assert run.run_kind is None
        assert run.profile is None
        assert run.status == "done"
        assert [s["step"] for s in run.steps][-1] == "world_experience"

    def test_chat_without_unified_creates_no_run_row(
        self, db_session_factory, override_settings, fake_llm
    ):
        from fastapi.testclient import TestClient

        from app.core import llm_factory
        from app.main import app

        override_settings(V21_AGENT_RUNTIME_ENABLED="false")
        llm = fake_llm(
            response="好的。",
            structured_responses={
                "RoleMode": {
                    "mode": "default",
                    "intent": "casual",
                    "confidence": 0.9,
                    "reason": "日常对话",
                },
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "sad", "event": "setback"},
                    "behavior": {"behavior": "comfort", "reason": "接住情绪"},
                },
                "IntentionDecision": {
                    "intention": "comfort_user",
                    "confidence": 0.9,
                    "reason": "情绪低落",
                },
            },
        )
        llm_factory.set_llm(llm)
        with TestClient(app) as test_client:
            resp = test_client.post(
                "/api/v1/chat/message", json={"content": "我很难过"}
            )
            assert resp.status_code == 200
        assert loop_run_repository.list_recent(kind="chat") == []
