"""V5 测试矩阵保留用例：testing.md 17 项中仅此两例具备独立断言价值。

Case 1~11、13~15 的断言由细粒度文件承载（test_emotion_update / test_emotion_decay /
test_relationship_update / test_relationship_stage / test_state_engine /
test_memory_replay / test_v5_e2e）；Case 17（V2/V3/V4 全量回归零破坏）
由全量 pytest 运行本身覆盖。
"""

import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipState
from app.repositories import character_state_repository
from app.services import scene_service, state_service
from tests.conftest import FakeLLM

DECISION = {"inner_state": "平静", "current_topic": "日常"}


def make_conversation_state(relationship=None):
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=[],
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


async def test_case_12_scene_state_unaffected_by_v5(db_session_factory):
    from app.models.scene import SceneState
    from app.repositories import scene_state_repository

    scene_state_repository.upsert_scene_state(
        "s1", SceneState(session_id="s1", turn_id=3, location="客厅")
    )
    await run(
        analysis_with(
            emotion_event("praise"),
            relationship_event={"type": "user_care", "magnitude": "normal", "confidence": 0.9, "cause": "关心"},
        )
    )
    scene = scene_service.load("s1")
    assert scene.location == "客厅"
    assert scene.turn_id == 3


def test_case_16_prompt_sections_order_and_compat():
    from app.prompts.builder import PromptBuilder

    state = make_conversation_state(relationship=RelationshipState(tension=0.6))
    prompt = PromptBuilder.build("default", state, analysis=TurnAnalysis())
    rendered = [m.content for m in prompt.format_messages()]
    emotion_idx = next(i for i, s in enumerate(rendered) if "【角色当前情绪】" in s)
    rel_idx = next(i for i, s in enumerate(rendered) if "【与用户的关系】" in s)
    assert emotion_idx < rel_idx
    assert any("保持一点距离感" in s for s in rendered)
    v1 = PromptBuilder.build("default", state)
    v1_rendered = [m.content for m in v1.format_messages()]
    assert all("【角色当前情绪】" not in s for s in v1_rendered)
