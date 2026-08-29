from datetime import datetime, timedelta

import pytest

from app.models.memory import UserMemory, UserMemoryV4
from app.repositories import memory_repository as repo


def _get_v4(memory_id: str) -> UserMemoryV4:
    memory = repo.get_memory_v4(memory_id)
    assert memory is not None
    return memory


class TestCreateMemoryV4:
    def test_create_with_defaults(self, db_session_factory):
        memory = repo.create_memory_v4(
            user_id="u1",
            character_id="asuna",
            content="用户喜欢西瓜",
            memory_type="user_preference",
            importance=0.8,
            confidence=0.95,
            source="user_stated",
        )
        assert memory.status == "active"
        assert memory.superseded_by is None
        assert memory.last_accessed_at is None
        assert memory.expires_at is None
        stored = _get_v4(memory.id)
        assert stored.content == "用户喜欢西瓜"
        assert stored.type == "user_preference"

    def test_create_user_level_wildcard_character(self, db_session_factory):
        memory = repo.create_memory_v4(
            user_id="u1",
            character_id="*",
            content="用户在深圳工作",
            memory_type="user_fact",
            importance=0.9,
        )
        assert memory.character_id == "*"

    def test_invalid_type_rejected(self, db_session_factory):
        with pytest.raises(ValueError):
            repo.create_memory_v4(
                user_id="u1",
                character_id="asuna",
                content="x",
                memory_type="hobby",
                importance=0.5,
            )

    def test_importance_out_of_range_rejected(self, db_session_factory):
        with pytest.raises(ValueError):
            repo.create_memory_v4(
                user_id="u1",
                character_id="asuna",
                content="x",
                memory_type="user_fact",
                importance=1.5,
            )

    def test_confidence_out_of_range_rejected(self, db_session_factory):
        with pytest.raises(ValueError):
            repo.create_memory_v4(
                user_id="u1",
                character_id="asuna",
                content="x",
                memory_type="user_fact",
                importance=0.5,
                confidence=-0.1,
            )

    def test_invalid_source_rejected(self, db_session_factory):
        with pytest.raises(ValueError):
            repo.create_memory_v4(
                user_id="u1",
                character_id="asuna",
                content="x",
                memory_type="user_fact",
                importance=0.5,
                source="guess",
            )

    def test_expires_at_persisted(self, db_session_factory):
        expires = datetime.now() + timedelta(days=1)
        memory = repo.create_memory_v4(
            user_id="u1",
            character_id="asuna",
            content="临时信息",
            memory_type="user_fact",
            importance=0.3,
            expires_at=expires,
        )
        assert _get_v4(memory.id).expires_at is not None


class TestListActiveV4:
    def test_only_active_returned(self, db_session_factory):
        active = repo.create_memory_v4(
            "u1", "asuna", "活跃记忆", "user_preference", 0.8
        )
        superseded = repo.create_memory_v4(
            "u1", "asuna", "被替代记忆", "user_preference", 0.8
        )
        repo.invalidate_memory(
            repo.create_memory_v4(
                "u1", "asuna", "失效记忆", "user_preference", 0.8
            ).id
        )
        repo.supersede_memory(superseded.id, active.id)
        contents = [m.content for m in repo.list_active_v4("u1", "asuna")]
        assert contents == ["活跃记忆"]

    def test_character_scope_includes_wildcard(self, db_session_factory):
        repo.create_memory_v4("u1", "*", "通用事实", "user_fact", 0.9)
        repo.create_memory_v4("u1", "asuna", "角色事件", "relationship_event", 0.7)
        repo.create_memory_v4("u1", "kirito", "他人事件", "relationship_event", 0.7)
        contents = [m.content for m in repo.list_active_v4("u1", "asuna")]
        assert sorted(contents) == ["他人事件", "角色事件", "通用事实"] or contents == [
            "角色事件",
            "通用事实",
        ]
        assert "他人事件" not in contents

    def test_scoped_by_user(self, db_session_factory):
        repo.create_memory_v4("u1", "asuna", "用户1记忆", "user_fact", 0.8)
        repo.create_memory_v4("u2", "asuna", "用户2记忆", "user_fact", 0.8)
        assert [m.content for m in repo.list_active_v4("u1", "asuna")] == ["用户1记忆"]

    def test_limit_respected(self, db_session_factory):
        for i in range(5):
            repo.create_memory_v4("u1", "asuna", f"记忆{i}", "user_fact", 0.5)
        assert len(repo.list_active_v4("u1", "asuna", limit=3)) == 3


class TestLifecycleOperations:
    def test_update_memory_content(self, db_session_factory):
        memory = repo.create_memory_v4(
            "u1", "asuna", "用户喜欢西瓜", "user_preference", 0.8
        )
        updated = repo.update_memory_content(memory.id, "用户最喜欢吃西瓜", 0.9)
        assert updated is not None
        assert updated.content == "用户最喜欢吃西瓜"
        assert updated.importance == 0.9
        stored = _get_v4(memory.id)
        assert stored.updated_at >= stored.created_at

    def test_update_missing_memory_returns_none(self, db_session_factory):
        assert repo.update_memory_content("no-such-id", "x") is None

    def test_supersede_sets_status_and_pointer(self, db_session_factory):
        old = repo.create_memory_v4("u1", "asuna", "喜欢咖啡", "user_preference", 0.8)
        new = repo.create_memory_v4("u1", "asuna", "喜欢喝茶", "user_preference", 0.8)
        repo.supersede_memory(old.id, new.id)
        superseded = _get_v4(old.id)
        assert superseded.status == "superseded"
        assert superseded.superseded_by == new.id
        assert _get_v4(new.id).status == "active"

    def test_supersede_missing_memory_is_noop(self, db_session_factory):
        repo.supersede_memory("no-such-id", "also-missing")

    def test_invalidate_sets_status(self, db_session_factory):
        memory = repo.create_memory_v4("u1", "asuna", "旧事实", "user_fact", 0.7)
        repo.invalidate_memory(memory.id)
        assert _get_v4(memory.id).status == "invalidated"

    def test_touch_last_accessed(self, db_session_factory):
        m1 = repo.create_memory_v4("u1", "asuna", "甲", "user_fact", 0.5)
        m2 = repo.create_memory_v4("u1", "asuna", "乙", "user_fact", 0.5)
        repo.touch_last_accessed([m1.id, m2.id])
        assert _get_v4(m1.id).last_accessed_at is not None
        assert _get_v4(m2.id).last_accessed_at is not None
        repo.touch_last_accessed([])
        repo.touch_last_accessed(["no-such-id"])

    def test_forget_hard_deletes(self, db_session_factory):
        memory = repo.create_memory_v4("u1", "asuna", "待删除", "user_fact", 0.5)
        repo.forget_memory(memory.id)
        assert repo.get_memory_v4(memory.id) is None


class TestLegacyCompat:
    def test_legacy_create_still_works(self, db_session_factory):
        memory = repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
        assert isinstance(memory, UserMemory)
        assert memory.memory_type == "preference"

    def test_legacy_list_maps_v4_types_back(self, db_session_factory):
        repo.create_memory_v4("u1", "asuna", "喜欢西瓜", "user_preference", 0.8)
        memories = repo.list_by_user("u1")
        assert len(memories) == 1
        assert memories[0].memory_type == "preference"

    def test_legacy_get_memory(self, db_session_factory):
        memory = repo.create_memory("u1", "事实", "fact", 0.7)
        fetched = repo.get_memory(memory.id)
        assert fetched is not None
        assert fetched.memory_type == "fact"
