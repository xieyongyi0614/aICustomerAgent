from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.memory import (
    MemoryCandidate,
    MemoryExtraction,
    UserMemory,
)


def make_candidate(**overrides):
    payload = {
        "action": "save",
        "type": "user_preference",
        "content": "用户喜欢西瓜",
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return MemoryCandidate(**payload)


def make_memory(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "id": "m1",
        "user_id": "u1",
        "character_id": "asuna",
        "type": "user_preference",
        "content": "用户喜欢西瓜",
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return UserMemory(**payload)


class TestMemoryCandidate:
    def test_valid_save_candidate(self):
        candidate = make_candidate()
        assert candidate.action == "save"
        assert candidate.type == "user_preference"
        assert candidate.source == "user_stated"

    def test_all_actions_accepted(self):
        for action in ("save", "update", "invalidate", "forget", "suppress"):
            target = "m-old" if action in ("update", "invalidate") else None
            candidate = make_candidate(action=action, target_memory_id=target)
            assert candidate.action == action

    def test_action_none_without_content_allowed(self):
        candidate = MemoryCandidate(type="user_fact", importance=0.3, confidence=0.2)
        assert candidate.action == "none"
        assert candidate.content is None
        assert candidate.source == "ai_inferred"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(type="hobby")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(source="model_guess")

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(action="delete")

    def test_importance_out_of_range_rejected(self):
        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                make_candidate(importance=bad)

    def test_confidence_out_of_range_rejected(self):
        for bad in (-0.1, 1.5):
            with pytest.raises(ValidationError):
                make_candidate(confidence=bad)

    def test_action_none_with_target_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(action="none", target_memory_id="m-old")

    def test_update_without_target_allowed_for_resolver_matching(self):
        candidate = make_candidate(action="update")
        assert candidate.target_memory_id is None

    def test_invalidate_without_target_allowed_for_resolver_matching(self):
        candidate = make_candidate(action="invalidate")
        assert candidate.target_memory_id is None

    def test_save_with_target_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(target_memory_id="m-old")

    def test_forget_with_target_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(action="forget", target_memory_id="m-old")

    def test_action_without_content_rejected(self):
        with pytest.raises(ValidationError):
            make_candidate(content=None)
        with pytest.raises(ValidationError):
            make_candidate(content="")


class TestMemoryExtraction:
    def test_empty_candidates_allowed(self):
        extraction = MemoryExtraction(candidates=[])
        assert extraction.candidates == []

    def test_multiple_candidates_allowed(self):
        extraction = MemoryExtraction(
            candidates=[
                make_candidate(),
                make_candidate(type="user_fact", content="用户在深圳工作"),
            ]
        )
        assert len(extraction.candidates) == 2

    def test_invalid_candidate_propagates(self):
        with pytest.raises(ValidationError):
            MemoryExtraction(candidates=[{"type": "user_fact", "action": "bogus"}])


class TestUserMemory:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        memory = UserMemory(
            id="m1",
            user_id="u1",
            character_id="asuna",
            type="user_preference",
            content="用户喜欢西瓜",
            importance=0.8,
            created_at=now,
            updated_at=now,
        )
        assert memory.status == "active"
        assert memory.superseded_by is None
        assert memory.last_accessed_at is None
        assert memory.expires_at is None
        assert memory.confidence == 0.0
        assert memory.source == "ai_inferred"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            make_memory(status="deleted")

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            make_memory(type="preference")

    def test_superseded_state(self):
        memory = make_memory(status="superseded", superseded_by="m2")
        assert memory.status == "superseded"
        assert memory.superseded_by == "m2"
