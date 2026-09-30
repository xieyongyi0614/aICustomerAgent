"""V6.5-011：动态 Habit 候选生成（代码规则）与配置确认生效集。"""

import pytest

from app.engines import habit as habit_runtime
from app.engines.behavior import match_habits
from app.engines.habit import derive_habit_candidates, load_effective_habits


class _Event:
    def __init__(self, type: str, source: str = "conversation"):
        self.type = type
        self.source = source


def test_derive_empty_below_threshold():
    events = [_Event("conflict"), _Event("conflict")]
    assert derive_habit_candidates(events) == []


def test_derive_candidates_at_threshold():
    events = [_Event("conflict") for _ in range(3)] + [_Event("praise") for _ in range(2)]
    candidates = derive_habit_candidates(events)
    assert [c.id for c in candidates] == ["auto_conflict_cool_down"]
    assert candidates[0].id.startswith("auto_")


def test_derive_ignores_memory_replay_events():
    events = [_Event("conflict"), _Event("conflict", source="memory_replay")]
    assert derive_habit_candidates(events) == []


def test_effective_habits_default_is_asset_only():
    habits = load_effective_habits()
    assert habits == habit_runtime.HABIT_LIST


def test_effective_habits_merge_configured_extra(monkeypatch):
    monkeypatch.setenv(
        "HABIT_EXTRA_JSON",
        '[{"id":"auto_care_followup","domain":"relate","priority":3,'
        '"instruction":"关心过的事之后主动跟进一句近况"}]',
    )
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        habits = load_effective_habits()
        assert any(h.id == "auto_care_followup" for h in habits)
        assert len(habits) == len(habit_runtime.HABIT_LIST) + 1
    finally:
        get_settings.cache_clear()


def test_effective_habits_reject_duplicate_id(monkeypatch):
    monkeypatch.setenv(
        "HABIT_EXTRA_JSON",
        '[{"id":"habit_care_action_first","domain":"relate","priority":1,'
        '"instruction":"重复 id 应被拒绝"}]',
    )
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            load_effective_habits()
    finally:
        get_settings.cache_clear()


def test_effective_habits_reject_invalid_json(monkeypatch):
    monkeypatch.setenv("HABIT_EXTRA_JSON", "{bad json")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            load_effective_habits()
    finally:
        get_settings.cache_clear()


def test_match_habits_uses_effective_set(monkeypatch):
    monkeypatch.setenv(
        "HABIT_EXTRA_JSON",
        '[{"id":"auto_pace_first","domain":"pace","priority":1,'
        '"instruction":"生成测试：先回应最后那个点"}]',
    )
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        matched = match_habits("curious_inquiry")
        assert matched[0].id == "auto_pace_first"
        assert all(h.domain == "pace" for h in matched)
        assert len(matched) <= 2
    finally:
        get_settings.cache_clear()


def test_match_habits_focused_assistance_empty():
    assert match_habits("focused_assistance") == []
