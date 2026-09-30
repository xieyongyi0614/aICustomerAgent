from datetime import datetime

from app.models.goal import GoalRecord
from app.services.goal import service as goal_service

NOW = datetime(2026, 8, 29, 12, 0, 0)


def _goal(
    goal_type: str,
    description: str,
    *,
    priority: int = 3,
    offset_seconds: int = 0,
    goal_id: str = "",
) -> GoalRecord:
    return GoalRecord(
        id=goal_id or f"g-{goal_type}-{description}-{offset_seconds}",
        user_id="u1",
        type=goal_type,
        description=description,
        priority=priority,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=datetime.fromtimestamp(NOW.timestamp() + offset_seconds),
        updated_at=NOW,
    )


def _select(goals, *, tension=0.0, user_emotion="neutral", mood="calm",
            intensity=0.3, scene_pending=False, late_night=False):
    return goal_service.select(
        goals,
        tension=tension,
        user_emotion=user_emotion,
        character_mood=mood,
        character_intensity=intensity,
        scene_pending=scene_pending,
        late_night=late_night,
    )


class TestTierOrder:
    def test_scene_goal_selected_when_pending(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("scene", "完成切西瓜"),
        ]
        selected = _select(goals, scene_pending=True)
        assert selected.goal.type == "scene"
        assert "场景承诺" in selected.reason

    def test_user_care_before_relationship_before_conversation(self):
        goals = [
            _goal("conversation", "延续当前话题"),
            _goal("relationship", "维持日常亲近感"),
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION),
        ]
        selected = _select(goals)
        assert selected.goal.type == "user_care"
        assert len(selected.suppressed) == 2

    def test_same_type_priority_decides(self):
        goals = [
            _goal("user_care", "目标甲", priority=2, offset_seconds=10),
            _goal("user_care", "目标乙", priority=4, offset_seconds=0),
        ]
        selected = _select(goals)
        assert selected.goal.description == "目标乙"

    def test_full_tie_newest_created_at_wins(self):
        goals = [
            _goal("user_care", "目标甲", priority=3, offset_seconds=0),
            _goal("user_care", "目标乙", priority=3, offset_seconds=30),
        ]
        selected = _select(goals)
        assert selected.goal.description == "目标乙"


class TestContextCorrection:
    def test_tension_boosts_repair_goal_to_front(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("relationship", goal_service.GOAL_DESCRIPTION_REPAIR, priority=3),
        ]
        selected = _select(goals, tension=0.6)
        assert selected.goal.type == "relationship"
        assert "修复" in selected.reason
        assert selected.suppressed

    def test_tension_below_threshold_keeps_user_care_first(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("relationship", goal_service.GOAL_DESCRIPTION_REPAIR, priority=3),
        ]
        selected = _select(goals, tension=0.4)
        assert selected.goal.type == "user_care"

    def test_late_night_and_tired_boosts_rest_goal(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("user_care", goal_service.GOAL_DESCRIPTION_REST, priority=4),
        ]
        selected = _select(
            goals, user_emotion="tired", late_night=True
        )
        assert selected.goal.description == goal_service.GOAL_DESCRIPTION_REST
        assert "深夜" in selected.reason

    def test_rest_goal_unchanged_without_late_night(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("user_care", goal_service.GOAL_DESCRIPTION_REST, priority=4),
        ]
        selected = _select(goals, user_emotion="tired", late_night=False)
        assert selected.goal.description == goal_service.GOAL_DESCRIPTION_COMPANION

    def test_strong_negative_emotion_suppresses_conversation(self):
        goals = [
            _goal("conversation", "延续当前话题", priority=5),
            _goal("relationship", "维持日常亲近感", priority=1),
        ]
        selected = _select(goals, mood="sad", intensity=0.7)
        assert selected.goal.type == "relationship"

    def test_scene_pending_without_scene_goal_flags_promise_in_reason(self):
        goals = [_goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION)]
        selected = _select(goals, scene_pending=True)
        assert selected.goal.type == "user_care"
        assert "场景承诺" in selected.reason

    def test_scene_pending_always_beats_boosted_user_care(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("scene", "完成切西瓜", priority=1),
        ]
        selected = _select(
            goals, scene_pending=True, mood="angry", intensity=0.9
        )
        assert selected.goal.type == "scene"


class TestEmptyGoals:
    def test_empty_goal_set_returns_none_with_reason(self):
        selected = _select([])
        assert selected.goal is None
        assert selected.suppressed == []
        assert selected.reason
