"""CHAR-005：习惯运行时触发与优先级合成单测（纯函数，无 IO / 无 LLM）。"""

from app.character.asuna.habits import HABIT_LIST
from app.character.asuna.habit_triggers import HABIT_TRIGGER_SPECS
from app.models.emotion import TurnAnalysis, UserEmotion
from app.services.experience.habit_trigger import (
    HabitTriggerContext,
    trigger_habits,
)


def _context(message: str = "", emotion: str = "neutral", conflict: str = "none", **kwargs):
    analysis = TurnAnalysis(user_emotion=UserEmotion(emotion=emotion))
    return HabitTriggerContext(
        analysis=analysis, conflict_status=conflict, user_message=message, **kwargs
    )


def _ids(habits):
    return [habit.rule_id for habit in habits]


def test_work_tired_message_triggers_care_and_comfort_habits():
    context = _context(message="最近工作很累", emotion="tired")
    habits = trigger_habits(context)
    assert set(_ids(habits)) == {
        "habit_care_action_first",
        "habit_comfort_companion_first",
    }
    assert all(habit.priority == 1 for habit in habits)


def test_priority_ordering_across_levels():
    context = _context(message="都怪你，我好难过")
    habits = trigger_habits(context)
    assert _ids(habits) == ["habit_comfort_companion_first", "habit_angry_restrained"]
    assert [habit.priority for habit in habits] == [1, 2]


def test_same_priority_resolved_by_keyword_specificity():
    context = _context(message="我好难过，压力好大，最近好累")
    habits = trigger_habits(context)
    assert habits[0].rule_id == "habit_comfort_companion_first"
    assert habits[1].rule_id == "habit_care_action_first"


def test_same_priority_resolved_by_domain_order():
    context = _context(conflict="conflict", emotion="angry")
    habits = trigger_habits(context)
    assert _ids(habits) == ["habit_angry_restrained", "habit_listen_before_speak"]


def test_cap_limits_matched_habits():
    context = _context(message="我好难过，压力好大，好累，怎么办？")
    habits = trigger_habits(context)
    assert len(habits) == 2
    assert _ids(habits) == ["habit_comfort_companion_first", "habit_care_action_first"]


def test_no_match_returns_empty():
    assert trigger_habits(_context(message="今天天气不错")) == []


def test_memory_light_touch_triggered_by_memory_signal():
    context = _context(message="今天天气不错", memory_present=True)
    habits = trigger_habits(context)
    assert _ids(habits) == ["habit_memory_light_touch"]
    assert habits[0].instruction == HABIT_LIST[-1].instruction


def test_memory_habit_not_triggered_without_signal():
    assert trigger_habits(_context(message="今天天气不错")) == []


def test_triggering_is_deterministic():
    context = _context(message="我好难过，压力好大，好累，怎么办？")
    assert trigger_habits(context) == trigger_habits(context)


def test_instruction_is_behavior_directive_not_scripted_reply():
    context = _context(message="最近工作很累")
    for habit in trigger_habits(context):
        assert habit.instruction == next(
            rule.instruction for rule in HABIT_LIST if rule.id == habit.rule_id
        )
        assert len(habit.instruction) <= 40


def test_extra_habit_without_spec_is_skipped(monkeypatch):
    monkeypatch.setenv(
        "HABIT_EXTRA_JSON",
        '[{"id":"auto_help_concrete","domain":"relate","priority":3,'
        '"instruction":"帮忙时给具体可执行的第一步，不给空泛建议"}]',
    )
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        context = _context(message="帮帮我，这个怎么办")
        habits = trigger_habits(context)
        assert "auto_help_concrete" not in _ids(habits)
        assert _ids(habits) == ["habit_question_bounded"]
    finally:
        get_settings.cache_clear()


def test_spec_asset_only_covers_known_habits():
    known_ids = {habit.id for habit in HABIT_LIST}
    assert set(HABIT_TRIGGER_SPECS.specs) <= known_ids
    assert HABIT_TRIGGER_SPECS.specs
