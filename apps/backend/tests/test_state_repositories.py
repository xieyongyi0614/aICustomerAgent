from app.core.db import CharacterStateRow, RelationshipStateRow
from app.models.character_state import CharacterState
from app.models.relationship import RelationshipState
from app.repositories import (
    character_state_repository,
    emotion_history_repository,
    relationship_repository,
)


class TestCharacterStateRepository:
    def test_get_missing_returns_default_without_write(self, db_session_factory):
        state = character_state_repository.get_state("user-a")
        assert state.mood == "calm"
        assert state.energy == 0.9
        assert state.updated_at is None
        with db_session_factory() as session:
            assert session.query(CharacterStateRow).count() == 0

    def test_v5_emotion_fields_roundtrip(self, db_session_factory):
        from datetime import datetime

        event_at = datetime(2026, 8, 29, 12, 0, 0)
        saved = character_state_repository.upsert_state(
            "user-v5",
            CharacterState(
                mood="happy",
                intensity=0.72,
                cause="用户主动关心角色",
                last_event_at=event_at,
            ),
        )
        assert saved.intensity == 0.72
        assert saved.cause == "用户主动关心角色"
        assert saved.last_event_at == event_at
        loaded = character_state_repository.get_state("user-v5")
        assert loaded.intensity == 0.72
        assert loaded.cause == "用户主动关心角色"
        assert loaded.last_event_at == event_at

    def test_get_missing_returns_default_without_write(self, db_session_factory):
        first = character_state_repository.upsert_state(
            "user-a",
            CharacterState(
                mood="happy",
                energy=0.8,
                current_topic="AI Agent",
                inner_state="开心",
            ),
        )
        assert first.updated_at is not None

        second = character_state_repository.upsert_state(
            "user-a", CharacterState(mood="tired", energy=0.4)
        )
        assert second.mood == "tired"
        assert second.energy == 0.4
        assert second.updated_at >= first.updated_at

        with db_session_factory() as session:
            assert session.query(CharacterStateRow).count() == 1

        reloaded = character_state_repository.get_state("user-a")
        assert reloaded.mood == "tired"
        assert reloaded.current_topic == ""
        assert reloaded.updated_at is not None


class TestRelationshipRepository:
    def test_get_missing_returns_default(self, db_session_factory):
        relationship = relationship_repository.get_relationship("user-a")
        assert relationship.stage == "friend"
        assert relationship.intimacy == 0.3

    def test_upsert_updates_single_row(self, db_session_factory):
        relationship_repository.upsert_relationship(
            "user-a", RelationshipState(intimacy=0.5, trust=0.6, stage="close_friend")
        )
        updated = relationship_repository.upsert_relationship(
            "user-a", RelationshipState(intimacy=0.7, trust=0.8, stage="partner")
        )
        assert updated.stage == "partner"
        with db_session_factory() as session:
            assert session.query(RelationshipStateRow).count() == 1
        reloaded = relationship_repository.get_relationship("user-a")
        assert reloaded.intimacy == 0.7
        assert reloaded.stage == "partner"


class TestEmotionHistoryRepository:
    def test_append_and_list_recent_desc_with_user_isolation(
        self, db_session_factory
    ):
        emotion_history_repository.append(
            "user-a", "s1", "sad", "setback", "comfort", "calm", "worried", 0.5, "friend"
        )
        emotion_history_repository.append(
            "user-a",
            "s1",
            "happy",
            "achievement",
            "celebrate",
            "worried",
            "happy",
            0.9,
            "friend",
        )
        emotion_history_repository.append(
            "user-b", "s2", "neutral", "daily", "normal_reply", "calm", "calm", 0.85, "friend"
        )

        entries = emotion_history_repository.list_recent("user-a")
        assert len(entries) == 2
        assert entries[0].event == "achievement"
        assert entries[1].event == "setback"
        assert all(entry.user_id == "user-a" for entry in entries)
        assert all(entry.session_id == "s1" for entry in entries)

        other = emotion_history_repository.list_recent("user-b")
        assert len(other) == 1
        assert other[0].event == "daily"
