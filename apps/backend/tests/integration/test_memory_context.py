from datetime import datetime, timezone

import pytest

from app.models.conversation import ChatMessage, ConversationState
from app.models.memory import UserMemory
from app.prompts.builder import PromptBuilder
from app.services.context_builder import build as build_context


def make_v4_memory(id: str, content: str, type: str = "user_preference", **overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "id": id,
        "user_id": "u1",
        "character_id": "asuna",
        "type": type,
        "content": content,
        "importance": 0.8,
        "confidence": 0.9,
        "source": "user_stated",
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return UserMemory(**payload)


def make_state(memories) -> ConversationState:
    return ConversationState(
        session_id="s",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=memories,
        current_input="在吗",
    )


class TestPromptMemorySection:
    def test_section_format_with_type_label(self):
        state = make_state(
            [make_v4_memory("m1", "用户喜欢西瓜"), make_v4_memory("m2", "用户在深圳工作", type="user_fact")]
        )
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        system_texts = [m.content for m in rendered if m.type == "system"]
        memory_sections = [t for t in system_texts if "你记得关于用户的事" in t]
        assert len(memory_sections) == 1
        section = memory_sections[0]
        assert "- (偏好) 用户喜欢西瓜" in section
        assert "- (事实) 用户在深圳工作" in section
        assert "不要主动罗列" in section

    def test_internal_fields_not_exposed(self):
        state = make_state([make_v4_memory("m1", "用户喜欢西瓜")])
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        section = next(m.content for m in rendered if "你记得关于用户的事" in m.content)
        for leaked in ("confidence", "source", "status", "user_stated", "active"):
            assert leaked not in section

    def test_empty_memories_omits_section(self):
        state = make_state([])
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        assert all("你记得关于用户的事" not in m.content for m in rendered)

    def test_v1_layout_without_memories_unchanged(self):
        state = make_state([])
        prompt = PromptBuilder.build("default", state)
        rendered = prompt.format_messages()
        assert rendered[-1].type == "human"
        assert rendered[-1].content == "在吗"
        assert any("你好" == m.content for m in rendered)
        assert all("你记得关于用户的事" not in m.content for m in rendered)


class TestContextBuilderIntegration:
    @pytest.mark.asyncio
    async def test_build_recalls_v4_memories(self, db_session_factory):
        from app.repositories import memory_repository as repo

        repo.create_memory("u1", "asuna", "用户喜欢西瓜", "user_preference", 0.9, 0.95)
        repo.create_memory("u1", "asuna", "旧偏好", "user_preference", 0.9, 0.9)
        rows = repo.list_active("u1", "asuna")
        old_row = next(r for r in rows if r.content == "旧偏好")
        repo.supersede_memory(old_row.id, next(r.id for r in rows if r.content == "用户喜欢西瓜"))
        state = await build_context("s1", "u1", "我喜欢吃西瓜")
        assert all(isinstance(m, UserMemory) for m in state.memories)
        assert [m.content for m in state.memories] == ["用户喜欢西瓜"]

    @pytest.mark.asyncio
    async def test_build_without_memories(self, db_session_factory):
        state = await build_context("s1", "u1", "随便聊聊")
        assert state.memories == []

    @pytest.mark.asyncio
    async def test_build_memory_failure_degrades(self, db_session_factory, monkeypatch):
        from app.repositories import memory_repository as repo
        from app.services.memory import retriever as memory_retriever

        repo.create_memory("u1", "asuna", "用户喜欢西瓜", "user_preference", 0.9, 0.95)

        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(memory_retriever, "retrieve", boom)
        state = await build_context("s1", "u1", "我喜欢吃西瓜")
        assert state.memories == []
