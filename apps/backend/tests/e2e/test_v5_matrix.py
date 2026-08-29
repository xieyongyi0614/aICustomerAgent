"""V5 测试矩阵聚合用例：testing.md 17 项必测中 Case 1~16 的管线级断言。

Case 17（V2/V3/V4 全量回归零破坏）由全量 pytest 运行本身覆盖。
"""

from datetime import datetime, timedelta

import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import EmotionEvent, TurnAnalysis
from app.models.memory import UserMemoryV4
from app.models.relationship import RelationshipDelta, RelationshipState
from app.repositories import (
    character_state_repository,
    relationship_event_repository,
    relationship_repository,
)
from app.services import scene_service, state_engine, state_service
from tests.conftest import FakeLLM

NOW = datetime(2026, 8, 29, 12, 0, 0)

DECISION = {"inner_state": "平静", "current_topic": "日常"}


def make_conversation_state(memories=None, relationship=None):
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=memories or [],
        current_input="在吗",
        character_state=CharacterState(mood="calm", intensity=0.3),
        relationship_state=relationship or RelationshipState(),
    )


def analysis_with(emotion_event=None, relationship_event=None, event="daily", behavior="normal_reply"):
    payload = {
        "user_emotion": {"emotion": "neutral", "event": event},
        "behavior": {"behavior": behavior, "reason": "测试"},
    }
    if emotion_event is not None:
        payload["emotion_event"] = emotion_event
    if relationship_event is not None:
        payload["relationship_event"] = relationship_event
    return TurnAnalysis(**payload)


async def run(analysis, state=None):
    llm = FakeLLM(structured_responses={"StateUpdateDecision": DECISION})
    await state_service.apply_and_save(
        "u1", "s1", state or make_conversation_state(), analysis, "x", "y", llm=llm
    )
    return character_state_repository.get_state("u1")


def emotion_event(event_type, magnitude="normal", confidence=0.9, cause="测试成因"):
    return {"type": event_type, "magnitude": magnitude, "confidence": confidence, "cause": cause}


class TestEmotionCases:
    async def test_case_1_praise_raises_happy_with_cause(self, db_session_factory):
        state = await run(analysis_with(emotion_event("praise")))
        assert state.mood == "happy"
        assert state.intensity == pytest.approx(0.3 + 0.3 * 0.2)
        assert state.cause == "测试成因"

    async def test_case_2_comforted_makes_happy(self, db_session_factory):
        state = await run(analysis_with(emotion_event("comforted")))
        assert state.mood == "happy"
        assert state.intensity > 0.3

    async def test_case_2b_positive_care_consumes_tension(self, db_session_factory):
        state = make_conversation_state(
            relationship=RelationshipState(tension=0.3)
        )
        await run(
            analysis_with(
                relationship_event={"type": "user_care", "magnitude": "normal", "confidence": 0.9, "cause": "关心"}
            ),
            state=state,
        )
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.tension == pytest.approx(0.3 - 0.02)

    async def test_case_3_criticized_makes_sad_with_cap(self, db_session_factory):
        state = await run(analysis_with(emotion_event("criticized", magnitude="strong")))
        assert state.mood == "sad"
        assert state.intensity <= 0.3 + 0.4

    async def test_case_4_decay_and_floor_reset(self, db_session_factory):
        real_now = datetime.now()
        character_state_repository.upsert_state(
            "u1",
            CharacterState(
                mood="happy",
                intensity=0.55,
                cause="夸奖",
                last_event_at=real_now - timedelta(hours=1.5),
            ),
        )
        character, _ = state_service.load_states("u1")
        assert character.intensity == pytest.approx(0.25, abs=0.05)
        character_state_repository.upsert_state(
            "u1",
            CharacterState(
                mood="happy",
                intensity=0.5,
                last_event_at=real_now - timedelta(hours=4),
            ),
        )
        character, _ = state_service.load_states("u1")
        assert character.mood == "calm"
        assert character.intensity == 0.3

    async def test_case_5_strong_protection_and_inertia(self, db_session_factory):
        state = CharacterState(mood="happy", intensity=0.7)
        blocked = state_engine.update_emotion(
            state,
            EmotionEvent(type="criticized", magnitude="normal", confidence=0.5),
            NOW,
        )
        assert blocked.mood == "happy"
        switched = state_engine.update_emotion(
            state,
            EmotionEvent(type="criticized", magnitude="normal", confidence=0.9),
            NOW,
        )
        assert switched.mood == "sad"
        assert switched.intensity == pytest.approx(0.3 + 0.7 * 0.2)


class TestRelationshipCases:
    async def test_case_6_trust_growth_with_ledger_row(self, db_session_factory):
        await run(analysis_with(relationship_event={"type": "user_care", "magnitude": "normal", "confidence": 0.9, "cause": "关心"}))
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.trust == pytest.approx(0.35 + 0.04)
        assert relationship_event_repository.count_events("u1") == 1

    async def test_case_7_intimate_moment_raises_intimacy(self, db_session_factory):
        await run(analysis_with(relationship_event={"type": "intimate_moment", "magnitude": "normal", "confidence": 0.9, "cause": "亲密互动"}))
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.intimacy == pytest.approx(0.3 + 0.06)

    async def test_case_8_conflict_raises_tension(self, db_session_factory):
        impact = state_engine.build_relationship_impact("conflict", "normal")
        assert impact.tension == pytest.approx(0.20)
        await run(analysis_with(relationship_event={"type": "conflict", "magnitude": "normal", "confidence": 0.9, "cause": "冲突"}))
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.tension == pytest.approx(0.15)

    async def test_case_9_strong_conflict_caps(self, db_session_factory):
        await run(analysis_with(relationship_event={"type": "conflict", "magnitude": "strong", "confidence": 0.9, "cause": "激烈冲突"}))
        relationship = relationship_repository.get_relationship("u1")
        for dim in ("intimacy", "trust", "familiarity", "tension"):
            delta = getattr(relationship, dim) - getattr(RelationshipState(), dim)
            assert abs(delta) <= 0.15 + 1e-9
        await run(analysis_with(relationship_event={"type": "conflict", "magnitude": "strong", "confidence": 0.9, "cause": "激烈冲突"}))
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.tension <= 0.30 + 1e-9

    async def test_case_10_thirty_day_accumulation_ledger_consistent(self, db_session_factory):
        for _ in range(30):
            relationship = relationship_repository.get_relationship("u1")
            await run(
                analysis_with(relationship_event={"type": "user_care", "magnitude": "normal", "confidence": 0.9, "cause": "关心"}),
                make_conversation_state(relationship=relationship),
            )
        events = relationship_event_repository.list_events("u1", limit=100)
        ledger_trust = sum(e.impact.trust for e in events)
        relationship = relationship_repository.get_relationship("u1")
        assert relationship.trust == pytest.approx(0.35 + ledger_trust, abs=1e-6)
        assert relationship.trust >= 0.6

    async def test_case_11_stage_thresholds_hysteresis_freeze(self, db_session_factory):
        assert state_engine.next_stage(0.56, 0.56, 0.4, "friend") == "close_friend"
        assert state_engine.next_stage(0.5, 0.5, 0.4, "close_friend") == "close_friend"
        assert state_engine.next_stage(0.4, 0.4, 0.4, "close_friend") == "friend"
        assert state_engine.next_stage(0.6, 0.6, 0.4, "friend", tension=0.55) == "friend"


class TestIntegrationCases:
    async def test_case_12_scene_state_unaffected_by_v5(self, db_session_factory):
        from app.models.scene import SceneState
        from app.repositories import scene_state_repository

        scene_state_repository.upsert_scene_state(
            "s1", SceneState(session_id="s1", turn_id=3, location="客厅")
        )
        await run(analysis_with(emotion_event("praise"), relationship_event={"type": "user_care", "magnitude": "normal", "confidence": 0.9, "cause": "关心"}))
        scene = scene_service.load("s1")
        assert scene.location == "客厅"
        assert scene.turn_id == 3

    async def test_case_13_memory_extraction_and_replay(self, db_session_factory):
        memory = UserMemoryV4(
            id="m1",
            user_id="u1",
            character_id="asuna",
            type="relationship_event",
            content="用户在角色难过时安慰过她",
            importance=0.8,
            confidence=0.9,
            source="user_stated",
            created_at=NOW,
            updated_at=NOW,
        )
        await run(
            analysis_with(event="setback"),
            state=make_conversation_state(memories=[memory]),
        )
        events = [
            e for e in relationship_event_repository.list_events("u1")
            if e.source == "memory_replay"
        ]
        assert len(events) == 1
        assert events[0].impact.trust == pytest.approx(0.04 * 0.6 * 0.5)
        await run(
            analysis_with(event="setback"),
            state=make_conversation_state(memories=[memory]),
        )
        assert relationship_event_repository.count_events("u1") == 1

    async def test_case_14_emotion_failure_does_not_break_pipeline(self, db_session_factory, monkeypatch):
        def boom(state, event, now):
            raise RuntimeError("emotion down")

        monkeypatch.setattr(state_engine, "update_emotion", boom)
        state = await run(analysis_with(emotion_event("praise")))
        assert relationship_event_repository.count_events("u1") == 1

    async def test_case_15_relationship_failure_does_not_break_pipeline(self, db_session_factory, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("rel down")

        monkeypatch.setattr(state_service.relationship_event_repository, "create_event", boom)
        state = await run(analysis_with(emotion_event("praise")))
        assert state.mood == "happy"

    def test_case_16_prompt_sections_order_and_compat(self):
        from app.prompts.builder import PromptBuilder

        state = make_conversation_state(
            relationship=RelationshipState(tension=0.6)
        )
        prompt = PromptBuilder.build("default", state, analysis=TurnAnalysis())
        rendered = [m.content for m in prompt.format_messages()]
        emotion_idx = next(i for i, s in enumerate(rendered) if "【角色当前情绪】" in s)
        rel_idx = next(i for i, s in enumerate(rendered) if "【与用户的关系】" in s)
        assert emotion_idx < rel_idx
        assert any("保持一点距离感" in s for s in rendered)
        v1 = PromptBuilder.build("default", state)
        v1_rendered = [m.content for m in v1.format_messages()]
        assert all("【角色当前情绪】" not in s for s in v1_rendered)
