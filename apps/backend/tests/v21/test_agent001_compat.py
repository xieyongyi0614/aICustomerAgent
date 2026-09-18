"""AGENT-001 兼容回归测试。

覆盖：前台收编常开后 chat 恒产生 foreground_chat 台账；enablement 无 v21 残留规则。
"""

from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations
from app.repositories import loop_run_repository


class TestEnablement:
    def test_no_v21_enablement_rules_remain(self, override_settings):
        violations = [
            v for v in enablement_violations(get_settings()) if "v21" in v
        ]
        assert violations == []


class TestForegroundAlwaysOn:
    def test_chat_creates_foreground_run_row(self, db_session_factory, fake_llm):
        from fastapi.testclient import TestClient

        from app.core import llm_factory
        from app.main import app

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
        runs = loop_run_repository.list_recent(kind="chat")
        assert len(runs) == 1
        assert runs[0].run_kind == "foreground_chat"
