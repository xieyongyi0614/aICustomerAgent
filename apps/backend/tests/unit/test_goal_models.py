from datetime import datetime

import pytest
from pydantic import ValidationError

from app.character.asuna import PERSISTENT_GOALS
from app.models.goal import (
    GOAL_DESCRIPTION_MAX_LENGTH,
    GOAL_TIER,
    GoalRecord,
    GoalSeed,
)

NOW = datetime(2026, 8, 29, 12, 0, 0)


def _record(**overrides):
    payload = {
        "user_id": "u1",
        "type": "user_care",
        "description": "陪伴用户放松",
        "priority": 5,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord(**payload)


class TestGoalRecord:
    def test_valid_record_defaults(self):
        record = _record()
        assert record.status == "active"
        assert record.horizon == "current"
        assert record.source == "policy"
        assert record.character_id == "asuna"
        assert record.created_turn == 0
        assert record.expires_at_turn is None
        assert record.id

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            _record(type="task")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            _record(status="paused")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            _record(source="llm")

    def test_invalid_horizon_rejected(self):
        with pytest.raises(ValidationError):
            _record(horizon="immediate")

    @pytest.mark.parametrize("priority", [0, 6, -1])
    def test_priority_out_of_bounds_rejected(self, priority):
        with pytest.raises(ValidationError):
            _record(priority=priority)

    @pytest.mark.parametrize("priority", [1, 5])
    def test_priority_bounds_accepted(self, priority):
        assert _record(priority=priority).priority == priority

    def test_description_over_40_chars_rejected(self):
        with pytest.raises(ValidationError):
            _record(description="长" * (GOAL_DESCRIPTION_MAX_LENGTH + 1))

    def test_description_at_40_chars_accepted(self):
        record = _record(description="长" * GOAL_DESCRIPTION_MAX_LENGTH)
        assert len(record.description) == GOAL_DESCRIPTION_MAX_LENGTH


class TestGoalSeed:
    def test_valid_seed(self):
        seed = GoalSeed(type="conversation", description="延续当前话题", priority=2)
        assert seed.priority == 2

    def test_invalid_seed_priority_rejected(self):
        with pytest.raises(ValidationError):
            GoalSeed(type="scene", description="完成切西瓜", priority=9)

    def test_invalid_seed_type_rejected(self):
        with pytest.raises(ValidationError):
            GoalSeed(type="self", description="自我提升", priority=3)


class TestGoalTier:
    def test_tier_order_scene_first_conversation_last(self):
        assert GOAL_TIER["scene"] < GOAL_TIER["user_care"]
        assert GOAL_TIER["user_care"] < GOAL_TIER["relationship"]
        assert GOAL_TIER["relationship"] < GOAL_TIER["conversation"]

    def test_tier_covers_all_types(self):
        assert set(GOAL_TIER) == {"user_care", "relationship", "conversation", "scene"}


class TestPersistentSeeds:
    def test_seed_matches_design(self):
        assert [(s.type, s.description, s.priority) for s in PERSISTENT_GOALS] == [
            ("user_care", "守护用户的身心状态", 4),
            ("relationship", "与用户建立彼此信赖的陪伴关系", 3),
            ("conversation", "成为用户愿意倾诉的对话伙伴", 2),
        ]

    def test_seeds_have_no_scene_type(self):
        assert all(s.type != "scene" for s in PERSISTENT_GOALS)
