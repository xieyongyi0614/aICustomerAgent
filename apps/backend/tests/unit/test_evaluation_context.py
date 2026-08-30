from datetime import datetime

import pytest

from app.application.post_process import PostProcessContext
from app.models.behavior_strategy import (
    ActionBudget,
    BehaviorDirective,
    BehaviorStrategy,
)
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import EmotionEvent, TurnAnalysis
from app.models.memory import UserMemory
from app.models.relationship import RelationshipState
from app.services.evaluation_context import (
    build_digest,
    collect_turn_context,
)


@pytest.fixture(autouse=True)
def stub_repos(monkeypatch):
    """单测无 DB：切片读取打桩，验证收集器容错路径之外的正常装配。"""
    from app.repositories import (
        character_state_repository,
        emotion_history_repository,
        relationship_repository,
    )
    from app.services import conversation_service

    monkeypatch.setattr(conversation_service, "load_window", lambda *a, **k: [])
    monkeypatch.setattr(
        emotion_history_repository, "list_recent", lambda *a, **k: []
    )
    monkeypatch.setattr(
        character_state_repository, "get_state", lambda *a, **k: CharacterState()
    )
    monkeypatch.setattr(
        relationship_repository, "get_relationship", lambda *a, **k: RelationshipState()
    )


def make_memory(content: str = "用户喜欢寿司", memory_id: str = "m1") -> UserMemory:
    now = datetime.now()
    return UserMemory(
        id=memory_id,
        user_id="default-user",
        character_id="asuna",
        type="user_preference",
        content=content,
        importance=0.8,
        created_at=now,
        updated_at=now,
    )


def make_state(memories=None) -> ConversationState:
    return ConversationState(
        session_id="conv-1",
        user_id="default-user",
        messages=[
            ChatMessage(role="human", content="今天有点累"),
            ChatMessage(role="ai", content="辛苦了，*递上一杯热茶*休息一下吧"),
        ],
        summary=None,
        memories=memories or [],
        current_input="最近怎么样？",
        character_state=CharacterState(mood="calm", intensity=0.2),
        relationship_state=RelationshipState(stage="friend", intimacy=0.4),
    )


def make_ctx(state=None, behavior=None) -> PostProcessContext:
    return PostProcessContext(
        session_id="conv-1",
        user_id="default-user",
        user_input="最近怎么样？",
        ai_reply="我很好呀，谢谢关心。*微微一笑*你那边今天顺利吗？",
        state=state or make_state(),
        analysis=TurnAnalysis(
            emotion_event=EmotionEvent(type="warm_moment", magnitude="normal", cause="关心问候")
        ),
        behavior=behavior,
    )


def test_collect_turn_context_slices():
    context = collect_turn_context(make_ctx())
    assert context.subject == "turn"
    assert context.session_id == "conv-1"
    assert context.user_message == "最近怎么样？"
    assert "微微一笑" in context.reply
    assert context.mode == "default"
    assert context.stage == "friend"
    assert context.emotion.event == "warm_moment"
    assert context.emotion.magnitude == "normal"


def test_collect_injected_memories_clips_content():
    context = collect_turn_context(make_ctx(make_state(memories=[make_memory("很长的描述" * 20)])))
    assert len(context.injected_memories) == 1
    ref = context.injected_memories[0]
    assert ref.id == "m1"
    assert len(ref.content) == 40


def test_collect_behavior_slice():
    directive = BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="natural_continuation", base_strategy="natural_continuation"
        ),
        budget=ActionBudget(max_action_desc=1, physical_contact="light"),
    )
    ctx = make_ctx(behavior=directive)
    ctx.ai_reply = "辛苦了。*递上一杯热茶*"
    context = collect_turn_context(ctx)
    assert context.behavior is not None
    assert context.behavior.max_action_desc == 1
    assert context.behavior.physical_contact == "light"
    assert context.behavior.observed_action_count == 1
    assert context.behavior.observed_contact_level == "light"


def test_collect_without_behavior_skips_slices():
    context = collect_turn_context(make_ctx())
    assert context.behavior is None
    assert context.behavior_history == []


def test_digest_shape():
    directive = BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="natural_continuation", base_strategy="natural_continuation"
        ),
        budget=ActionBudget(),
    )
    context = collect_turn_context(make_ctx(behavior=directive))
    digest = build_digest(context)
    assert set(digest.keys()) >= {
        "user_message",
        "reply",
        "recent_messages",
        "injected_memories",
        "emotion",
        "state",
        "behavior",
        "proactive",
    }
    assert digest["proactive"] is None
    assert digest["behavior"]["observed_action_count"] == 1


def test_digest_respects_char_budget(monkeypatch):
    import json

    from app.core.settings import get_settings

    monkeypatch.setenv("EVALUATION_MAX_DIGEST_CHARS", "400")
    get_settings.cache_clear()
    try:
        context = collect_turn_context(make_ctx(make_state(memories=[make_memory("很长的记忆内容" * 30)])))
        digest = build_digest(context)
        assert len(json.dumps(digest, ensure_ascii=False)) <= 400
        assert digest["injected_memories"] == []
    finally:
        get_settings.cache_clear()
