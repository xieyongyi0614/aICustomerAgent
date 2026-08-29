from datetime import datetime, timedelta

import pytest

from app.models.conversation import ChatMessage, ConversationState
from app.models.character_state import CharacterState
from app.models.memory import UserMemory
from app.models.relationship import RelationshipState
from app.repositories import (
    relationship_event_repository,
    relationship_repository,
)
from app.services import state_service


NOW = datetime(2026, 8, 29, 12, 0, 0)

MEMORY_CONTENT = "用户在角色难过时安慰过她"


def make_state(memories) -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[ChatMessage(role="human", content="还记得吗")],
        summary=None,
        memories=memories,
        current_input="你还记得那次安慰吗",
        character_state=CharacterState(),
        relationship_state=RelationshipState(),
    )


def make_memory(content=MEMORY_CONTENT):
    now = datetime.now()
    return UserMemory(
        id="m1",
        user_id="u1",
        character_id="asuna",
        type="relationship_event",
        content=content,
        importance=0.8,
        confidence=0.9,
        source="user_stated",
        created_at=now,
        updated_at=now,
    )


def run(memories, relationship=None):
    state = make_state(memories)
    if relationship is not None:
        state = state.model_copy(update={"relationship_state": relationship})
    updated, events = state_service._replay_relationship_memories(
        "u1", "s1", state, state.relationship_state, NOW
    )
    relationship_repository.commit_relationship_update("u1", updated, events)


class TestMemoryReplay:
    def test_replay_creates_discounted_event(self, db_session_factory):
        run([make_memory()])
        events = relationship_event_repository.list_events("u1")
        assert len(events) == 1
        event = events[0]
        assert event.source == "memory_replay"
        assert event.magnitude == "weak"
        assert event.cause == MEMORY_CONTENT
        assert event.impact.trust == pytest.approx(0.04 * 0.6 * 0.5)

    def test_replay_updates_state_consistently(self, db_session_factory):
        run([make_memory()])
        relationship = relationship_repository.get_relationship("u1")
        event = relationship_event_repository.list_events("u1")[0]
        assert relationship.trust == pytest.approx(0.35 + event.impact.trust, abs=1e-9)

    def test_replay_only_once_per_memory(self, db_session_factory):
        run([make_memory()])
        run([make_memory()])
        assert relationship_event_repository.count_events("u1") == 1

    def test_non_relationship_memories_ignored(self, db_session_factory):
        memory = make_memory()
        memory = memory.model_copy(update={"type": "user_preference"})
        run([memory])
        assert relationship_event_repository.count_events("u1") == 0

    def test_no_memories_no_writes(self, db_session_factory):
        run([])
        assert relationship_event_repository.count_events("u1") == 0

    def test_recent_interaction_blocks_replay(self, db_session_factory):
        relationship_event_repository.create_event(
            __import__(
                "app.models.relationship", fromlist=["RelationshipEvent"]
            ).RelationshipEvent(
                user_id="u1",
                session_id="s0",
                type="user_care",
                magnitude="normal",
                impact=__import__(
                    "app.models.relationship", fromlist=["RelationshipDelta"]
                ).RelationshipDelta(trust=0.04),
                confidence=0.9,
                created_at=NOW - timedelta(hours=1),
            )
        )
        run([make_memory()])
        replays = [
            e
            for e in relationship_event_repository.list_events("u1")
            if e.source == "memory_replay"
        ]
        assert replays == []

    def test_replay_keyword_type_mapping(self, db_session_factory):
        run([make_memory("用户吵架后主动和好，化解了冲突")])
        event = relationship_event_repository.list_events("u1")[0]
        assert event.type == "conflict"

    def test_replay_failure_does_not_crash(self, db_session_factory, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("replay down")

        monkeypatch.setattr(
            state_service.relationship_event_repository, "list_events", boom
        )
        run([make_memory()])
        assert relationship_repository.get_relationship("u1").trust == pytest.approx(0.35)
