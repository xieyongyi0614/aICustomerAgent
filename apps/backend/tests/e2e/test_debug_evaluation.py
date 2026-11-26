import asyncio

from app.core.settings import get_settings
from app.main import app
from app.repositories import evaluation_repository
from app.application import chat_pipeline as agent_service
from tests.conftest import WAIT_TIMEOUT


def _structured():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "daily"},
            "behavior": {"behavior": "normal_reply", "reason": "日常"},
        },
        "StateUpdateDecision": {
            "mood": "calm",
            "mood_reason": "日常",
            "inner_state": "平静",
            "current_topic": "闲聊",
        },
        "TurnJudgeResult": {
            "persona": {"in_character": True, "score": 0.95, "codes": []},
            "emotion": {"score": 0.9, "codes": []},
            "memory": {"score": 1.0, "codes": [], "memory_ids": []},
        },
    }


async def _wait_report(turn_id: str, timeout: float | None = None):
    deadline = asyncio.get_event_loop().time() + (timeout or WAIT_TIMEOUT)
    while asyncio.get_event_loop().time() < deadline:
        report = evaluation_repository.get_by_subject("turn", turn_id)
        if report is not None:
            return report
        await asyncio.sleep(0.02)
    return None


async def test_debug_evaluation_endpoints(db_session_factory, fake_llm, monkeypatch):
    get_settings.cache_clear()
    try:
        llm = fake_llm(response="今天也不错哦。*微笑*", structured_responses=_structured())
        events = []
        async for event in agent_service.stream_chat(
            "s-eval-debug", "default-user", "今天天气不错", llm=llm
        ):
            events.append(event)
        turn_id = events[-1]["turn_id"]
        assert turn_id is not None

        report = await _wait_report(turn_id)
        assert report is not None

        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get(f"/api/v1/debug/turns/{turn_id}/evaluation")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["subject"] == "turn"
        assert "persona" in payload["scores"]
        assert payload["scores"]["persona"]["judge_score"] == 0.95
        assert payload["verdict"] in ("pass", "warn", "fail")

        missing = client.get("/api/v1/debug/turns/999999/evaluation")
        assert missing.status_code == 404

        proactive_missing = client.get("/api/v1/debug/proactive/unknown/evaluation")
        assert proactive_missing.status_code == 404
    finally:
        get_settings.cache_clear()
