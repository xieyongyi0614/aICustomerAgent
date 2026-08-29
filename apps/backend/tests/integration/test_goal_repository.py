from datetime import datetime

import pytest

from app.character.asuna import PERSISTENT_GOALS
from app.models.goal import GoalRecord
from app.repositories import goal_repository

NOW = datetime(2026, 8, 29, 12, 0, 0)


def _record(**overrides):
    payload = {
        "user_id": "u-goal",
        "type": "user_care",
        "description": "陪伴用户放松",
        "priority": 5,
        "source": "policy",
        "horizon": "current",
        "created_turn": 3,
        "expires_at_turn": 23,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord(**payload)


@pytest.fixture
def user(db_session_factory):
    return "u-goal"


class TestSeedGoals:
    def test_first_seed_creates_all_persistent(self, user):
        created = goal_repository.seed_goals(user, PERSISTENT_GOALS)
        assert created == 3
        active = goal_repository.list_active(user)
        assert len(active) == 3
        assert all(g.horizon == "persistent" for g in active)
        assert all(g.source == "definition" for g in active)
        assert all(g.created_turn == 0 for g in active)
        assert all(g.expires_at_turn is None for g in active)

    def test_reseed_is_idempotent(self, user):
        goal_repository.seed_goals(user, PERSISTENT_GOALS)
        assert goal_repository.seed_goals(user, PERSISTENT_GOALS) == 0
        assert len(goal_repository.list_active(user)) == 3

    def test_seed_scoped_by_user(self, user):
        goal_repository.seed_goals(user, PERSISTENT_GOALS)
        assert goal_repository.seed_goals("other-user", PERSISTENT_GOALS) == 3
        assert len(goal_repository.list_active(user)) == 3


class TestCreateAndList:
    def test_create_goal_roundtrip(self, user):
        record = goal_repository.create_goal(_record())
        loaded = goal_repository.get_goal(record.id)
        assert loaded == record

    def test_list_active_filters_status(self, user):
        goal_repository.create_goal(_record(description="仍在进行的目标"))
        done = goal_repository.create_goal(_record(description="已完成目标"))
        goal_repository.complete_goal(done.id)
        active = goal_repository.list_active(user)
        assert len(active) == 1
        assert active[0].status == "active"
        assert active[0].description == "仍在进行的目标"

    def test_list_active_scoped_by_character(self, user):
        goal_repository.create_goal(_record(character_id="asuna"))
        other = goal_repository.create_goal(_record(character_id="ren"))
        active_asuna = goal_repository.list_active(user, character_id="asuna")
        assert [g.id for g in active_asuna] != [other.id]
        assert all(g.character_id == "asuna" for g in active_asuna)
        active_ren = goal_repository.list_active(user, character_id="ren")
        assert [g.id for g in active_ren] == [other.id]


class TestFinishGoal:
    def test_complete_goal(self, user):
        record = goal_repository.create_goal(_record())
        finished = goal_repository.complete_goal(record.id)
        assert finished.status == "completed"

    def test_expire_goal(self, user):
        record = goal_repository.create_goal(_record())
        assert goal_repository.expire_goal(record.id).status == "expired"

    def test_cancel_goal(self, user):
        record = goal_repository.create_goal(_record())
        assert goal_repository.cancel_goal(record.id).status == "cancelled"

    def test_finish_non_active_goal_is_noop(self, user):
        record = goal_repository.create_goal(_record())
        goal_repository.complete_goal(record.id)
        again = goal_repository.complete_goal(record.id)
        assert again.status == "completed"
        assert goal_repository.expire_goal(record.id).status == "completed"

    def test_finish_unknown_goal_returns_none(self, user):
        assert goal_repository.complete_goal("missing-id") is None

    def test_finish_invalid_status_rejected(self, user):
        record = goal_repository.create_goal(_record())
        with pytest.raises(ValueError):
            goal_repository.finish_goal(record.id, "active")
