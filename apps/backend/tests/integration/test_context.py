import pytest

from app.services import context_builder, conversation_service
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.relationship import RelationshipState
from app.repositories import conversation_repository, memory_repository, summary_repository
from app.core.db import Conversation


async def test_build_creates_conversation_record(db_session_factory):
    await context_builder.build("s6", "u1", "你好")
    with conversation_repository.SessionLocal() as session:
        assert session.get(Conversation, "s6") is not None


async def test_build_empty_fallback(db_session_factory):
    state = await context_builder.build("s1", "u1", "你好")
    assert isinstance(state, ConversationState)
    assert state.messages == []
    assert state.summary is None
    assert state.memories == []
    assert state.current_input == "你好"


async def test_build_keeps_window_order(db_session_factory):
    conversation_service.save_turn("s2", "first", "reply")
    conversation_service.save_turn("s2", "second", "answer")
    state = await context_builder.build("s2", "u1", "third")
    assert [m.content for m in state.messages] == ["first", "reply", "second", "answer"]


async def test_build_includes_summary(db_session_factory):
    summary_repository.upsert_summary("s3", "用户是初学者")
    state = await context_builder.build("s3", "u1", "继续")
    assert state.summary == "用户是初学者"


async def test_build_includes_memories(db_session_factory):
    memory_repository.create_memory("u1", "asuna", "用户喜欢寿司", "user_preference", 0.8)
    state = await context_builder.build("s4", "u1", "我想吃寿司")
    assert any(m.content == "用户喜欢寿司" for m in state.memories)


async def test_build_empty_input_rejected(db_session_factory):
    with pytest.raises(ValueError):
        await context_builder.build("s5", "u1", "")


async def test_build_state_read_failure_falls_back_to_default(db_session_factory, monkeypatch):
    def raise_failure(user_id):
        raise RuntimeError("状态读取失败")

    monkeypatch.setattr(context_builder.state_service, "load_states", raise_failure)
    state = await context_builder.build("s7", "u1", "你好")
    assert state.character_state == CharacterState()
    assert state.relationship_state == RelationshipState()
