from app.character.asuna.behavior_instructions import BEHAVIOR_INSTRUCTIONS
from app.models.behavior_strategy import (
    ActionBudget,
    BehaviorDirective,
    BehaviorStrategy,
    HabitRule,
)
from app.prompts.behavior import build_activity_section, build_behavior_section


def _directive(**kwargs):
    return BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="direct_support",
            base_strategy="direct_support",
            instruction="明确说出关心。",
        ),
        budget=ActionBudget(),
        **kwargs,
    )


def test_normal_section_contains_strategy_and_anchor():
    text = build_behavior_section(_directive())
    assert text.startswith("【表现方式】")
    assert "这一轮：明确说出关心。" in text
    assert "以上是表达方式约束" in text


def test_budget_line_rendered_only_when_not_default():
    directive = _directive()
    assert "动作描写" not in build_behavior_section(directive)
    directive.budget = ActionBudget(max_action_desc=0)
    assert "本轮不做动作描写" in build_behavior_section(directive)
    directive.budget = ActionBudget(max_action_desc=2)
    assert "不超过 2 处" in build_behavior_section(directive)


def test_professional_budget_line():
    directive = _directive()
    directive.budget = ActionBudget(max_action_desc=0, allow_action_desc=False)
    text = build_behavior_section(directive)
    assert "本轮不做任何动作描写" in text


def test_contact_line_rendered():
    directive = _directive()
    directive.budget = ActionBudget(max_action_desc=1, physical_contact="light")
    text = build_behavior_section(directive)
    assert "轻度的身体动作" in text


def test_habits_rendered_max_two():
    habits = [
        HabitRule(id=f"h{i}", domain="pace", priority=1, instruction=f"习惯{i}")
        for i in range(3)
    ]
    text = build_behavior_section(_directive(habits=habits))
    assert text.count("表达习惯：") == 2


def test_degraded_renders_v2_fallback():
    directive = _directive(fallback_directive=BEHAVIOR_INSTRUCTIONS["comfort"])
    text = build_behavior_section(directive)
    assert "【本轮行为指令】" in text
    assert BEHAVIOR_INSTRUCTIONS["comfort"] in text
    assert "【表现方式】" not in text


def test_literal_braces_safe():
    directive = _directive(
        fallback_directive=None,
        activity_text="整理{奇怪}的收藏",
    )
    directive.activity = "ambient_activity"
    text = build_activity_section(directive)
    assert "{奇怪}" in text


def test_activity_section_idle_none():
    assert build_activity_section(_directive()) is None
    assert build_activity_section(None) is None


def test_activity_section_pending_suppressed():
    directive = _directive()
    directive.activity = "pending_obligation"
    directive.activity_text = "拿西瓜"
    assert build_activity_section(directive) is None


def test_activity_section_ambient_rendered():
    directive = _directive()
    directive.activity = "ambient_activity"
    directive.activity_text = "切西瓜"
    text = build_activity_section(directive)
    assert text.startswith("【活动延续】")
    assert "切西瓜" in text
    assert "不要凭空停下" in text
