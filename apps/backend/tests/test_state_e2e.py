import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_repository,
)
from tests.conftest import wait_until

USER = "default-user"


def _structured(event, behavior, emotion, mood="calm"):
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": emotion, "event": event},
            "behavior": {"behavior": behavior, "reason": "测试"},
        },
        "StateUpdateDecision": {
            "mood": mood,
            "mood_reason": "测试",
            "inner_state": "平稳",
            "current_topic": "测试话题",
        },
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
        },
    }


def _client():
    return TestClient(app)


def test_comfort_path_adjusts_prompt_and_relationship(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["辛苦了"],
        structured_responses=_structured("setback", "comfort", "sad"),
    )
    llm_factory.set_llm(llm)
    with _client() as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我今天压力很大"})
        assert resp.status_code == 200

        assert any("不要急着给建议" in str(m) for m in llm.seen_messages)
        assert wait_until(lambda: len(emotion_history_repository.list_recent(USER, limit=5)) == 1)
    relationship = relationship_repository.get_relationship(USER)
    assert relationship.intimacy == pytest.approx(0.3 + 0.03 + 0.02)
    state = character_state_repository.get_state(USER)
    assert state.energy == pytest.approx(0.9 - 0.05 - 0.05 - 0.05)


def test_celebrate_path_restores_energy_and_keeps_stage(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["好耶"],
        structured_responses=_structured("achievement", "celebrate", "happy", mood="happy"),
    )
    llm_factory.set_llm(llm)
    with _client() as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我今天终于把项目上线了"})
        assert resp.status_code == 200
        assert wait_until(lambda: len(emotion_history_repository.list_recent(USER, limit=5)) == 1)
    state = character_state_repository.get_state(USER)
    assert state.mood == "happy"
    assert state.energy == pytest.approx(0.9 - 0.05 + 0.10)
    relationship = relationship_repository.get_relationship(USER)
    assert relationship.stage == "friend"
    assert relationship.intimacy == pytest.approx(0.3 + 0.04 + 0.02)


def test_stage_upgrade_after_share_goal_turns(
    db_session_factory, fake_llm, override_settings
):
    override_settings(stage_close_intimacy=0.3, stage_close_trust=0.3)
    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured("share_goal", "normal_reply", "calm"),
    )
    llm_factory.set_llm(llm)
    with _client() as client:
        for i in range(2):
            resp = client.post(
                "/api/v1/chat/message", json={"content": f"我想聊聊我的目标{i}"}
            )
            assert resp.status_code == 200
            expected_rows = i + 1
            assert wait_until(
                lambda rows=expected_rows: len(
                    emotion_history_repository.list_recent(USER, limit=5)
                )
                == rows
            )
    relationship = relationship_repository.get_relationship(USER)
    assert relationship.stage == "close_friend"
    assert relationship.trust == pytest.approx(0.35 + 0.06 * 2)
    assert relationship.intimacy == pytest.approx(0.3 + 0.02 * 2)


def test_full_degradation_uses_default_analysis(
    db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured("achievement", "celebrate", "happy"),
        structured_errors={"TurnAnalysis": RuntimeError("analysis boom")},
    )
    llm_factory.set_llm(llm)
    with _client() as client:
        resp = client.post("/api/v1/chat/message", json={"content": "我今天压力很大"})
        assert resp.status_code == 200
        lines = [line for line in resp.text.strip().splitlines() if line]
        assert lines[-1].strip().startswith("{\"done\"")
        assert wait_until(lambda: len(emotion_history_repository.list_recent(USER, limit=5)) == 1)
    relationship = relationship_repository.get_relationship(USER)
    assert relationship.familiarity == pytest.approx(0.31)
    state = character_state_repository.get_state(USER)
    assert state.energy == pytest.approx(0.85)
    assert state.mood == "calm"
