from datetime import datetime

import pytest

from app.models.goal import GoalRecord
from app.services.goal import service as goal_service

NOW = datetime(2026, 8, 29, 12, 0, 0)

DESCRIPTIONS = {
    "scene": "完成切西瓜",
    "user_care": goal_service.GOAL_DESCRIPTION_COMPANION,
    "relationship": "维持日常亲近感",
    "conversation": "延续当前话题",
}


def _goal(goal_type: str, *, priority: int = 3, offset_seconds: int = 0) -> GoalRecord:
    return GoalRecord(
        id=f"g-{goal_type}-{offset_seconds}",
        user_id="u1",
        type=goal_type,
        description=DESCRIPTIONS[goal_type],
        priority=priority,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=datetime.fromtimestamp(NOW.timestamp() + offset_seconds),
        updated_at=NOW,
    )


def _select(goals, **overrides):
    signals = {
        "tension": 0.0,
        "user_emotion": "neutral",
        "character_mood": "calm",
        "character_intensity": 0.3,
        "scene_pending": False,
        "late_night": False,
    }
    signals.update(overrides)
    return goal_service.select(goals, **signals)


class TestConflictMatrix:
    @pytest.mark.parametrize(
        "first,second",
        [
            ("scene", "user_care"),
            ("scene", "relationship"),
            ("scene", "conversation"),
            ("user_care", "relationship"),
            ("user_care", "conversation"),
            ("relationship", "conversation"),
        ],
    )
    def test_higher_tier_wins_regardless_of_priority(self, first, second):
        goals = [
            _goal(first, priority=1),
            _goal(second, priority=5, offset_seconds=30),
        ]
        selected = _select(goals)
        assert selected.goal.type == first

    def test_scene_beats_boosted_relationship(self):
        from datetime import timedelta

        repair = GoalRecord(
            id="g-repair",
            user_id="u1",
            type="relationship",
            description=goal_service.GOAL_DESCRIPTION_REPAIR,
            priority=5,
            horizon="current",
            source="policy",
            created_turn=1,
            expires_at_turn=21,
            created_at=NOW + timedelta(seconds=30),
            updated_at=NOW,
        )
        goals = [_goal("scene", priority=1), repair]
        selected = _select(goals, tension=0.7)
        assert selected.goal.type == "scene"


class TestLateNightAdjudication:
    def test_late_night_tired_rest_beats_higher_priority_companion(self):
        companion = _goal("user_care", priority=5, offset_seconds=0)
        rest = GoalRecord(
            id="g-rest",
            user_id="u1",
            type="user_care",
            description=goal_service.GOAL_DESCRIPTION_REST,
            priority=4,
            horizon="current",
            source="policy",
            created_turn=2,
            expires_at_turn=22,
            created_at=datetime.fromtimestamp(NOW.timestamp() + 60),
            updated_at=NOW,
        )
        selected = _select(
            [companion, rest],
            user_emotion="tired",
            late_night=True,
            character_intensity=0.6,
        )
        assert selected.goal.id == "g-rest"
        assert companion.id in selected.suppressed
        assert "深夜" in selected.reason
        assert selected.reason

    def test_daytime_higher_priority_companion_wins(self):
        companion = _goal("user_care", priority=5, offset_seconds=0)
        rest = GoalRecord(
            id="g-rest",
            user_id="u1",
            type="user_care",
            description=goal_service.GOAL_DESCRIPTION_REST,
            priority=4,
            horizon="current",
            source="policy",
            created_turn=2,
            expires_at_turn=22,
            created_at=datetime.fromtimestamp(NOW.timestamp() + 60),
            updated_at=NOW,
        )
        selected = _select([companion, rest])
        assert selected.goal.id == companion.id
        assert rest.id in selected.suppressed


class TestAdjudicationAlwaysDeterministic:
    def test_equal_user_care_goals_non_late_night_newest_wins(self):
        goals = [
            _goal("user_care", priority=5, offset_seconds=0),
            _goal("user_care", priority=5, offset_seconds=45),
        ]
        selected = _select(goals)
        assert selected.goal.id == "g-user_care-45"

    @pytest.mark.parametrize("tension,user_emotion,mood,intensity,late_night,scene_pending", [
        (0.9, "tired", "angry", 0.9, True, True),
        (0.0, "happy", "calm", 0.1, False, False),
        (0.5, "sad", "sad", 0.6, True, False),
    ])
    def test_selection_never_returns_none(
        self, tension, user_emotion, mood, intensity, late_night, scene_pending
    ):
        goals = [_goal(t, priority=3) for t in DESCRIPTIONS]
        selected = _select(
            goals,
            tension=tension,
            user_emotion=user_emotion,
            character_mood=mood,
            character_intensity=intensity,
            late_night=late_night,
            scene_pending=scene_pending,
        )
        assert selected.goal is not None
        assert selected.reason
