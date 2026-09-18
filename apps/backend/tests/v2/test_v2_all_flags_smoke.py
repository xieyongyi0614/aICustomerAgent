"""V2.0.0 全总闸 ON 全链路冒烟（R9 缺口 C-3）。

真实 front pipeline + lifespan 一把轮次：六总闸 + 行动闸全开时管线跑通，
V2 消化通道经真实 post_process 落库 memory_candidates（用户关键词可见），
同时覆盖启动边界 enablement 校验在合法全开配置下的通过路径。
前台调用上界由 tests/unit/test_llm_cost_gate.py 守护，本测试不重复计价。
"""

import json

from fastapi.testclient import TestClient

from app.core import llm_factory
from app.core.db import MemoryCandidateRow
from app.main import app
from app.services.memory2 import ingest as memory2_ingest
from tests.conftest import FakeLLM, wait_until

_V2_FLAGS = {
    "action_outbox_enabled": "true",
    "action_enabled": "true",
}


def _structured(candidate_content):
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "celebrate", "reason": "ok"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {"intention": "continue_topic", "confidence": 0.9, "reason": "ok"},
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "ok",
            "inner_state": "平静",
            "current_topic": "日常",
        },
        "MemoryExtraction": {
            "candidates": [
                {
                    "action": "save",
                    "type": "user_preference",
                    "content": candidate_content,
                    "importance": 0.8,
                    "confidence": 0.95,
                    "source": "user_stated",
                }
            ]
        },
    }


def _parse_stream(text):
    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


def _candidate_rows():
    with memory2_ingest.SessionLocal() as session:
        return session.query(MemoryCandidateRow).all()


def test_full_v2_flags_turn_persists_v2_candidate(
    db_session_factory, fake_llm, override_settings
):
    override_settings(**_V2_FLAGS)
    llm = fake_llm(response=["好呀"], structured_responses=_structured("用户喜欢西瓜"))
    llm_factory.set_llm(llm)
    try:
        with TestClient(app) as client:
            resp = client.post("/api/v1/chat/message", json={"content": "我喜欢西瓜"})
            assert resp.status_code == 200
            events = _parse_stream(resp.text)
            deltas = [e for e in events if "delta" in e]
            assert "".join(d["delta"] for d in deltas) == "好呀"
            assert events[-1].get("done") is True
            assert wait_until(
                lambda: any(
                    row.source == "user_stated" and row.content == "用户喜欢西瓜"
                    for row in _candidate_rows()
                )
            )
    finally:
        llm_factory.reset_llm()