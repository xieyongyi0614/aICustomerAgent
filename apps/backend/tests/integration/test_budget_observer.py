"""V6.5-010：输出侧动作预算统计器（只读观测，不阻塞不重写）。"""

import pytest

from app.application.post_process import PostProcessContext, run_budget_observer
from app.models.behavior_strategy import ActionBudget
from app.engines import behavior as behavior_engine
from app.services.observability.collector import TurnTraceSession


@pytest.mark.parametrize(
    "reply,budget,expected",
    [
        ("好的，我明白了。", ActionBudget(max_action_desc=0), False),
        ("*笑了笑* 好。", ActionBudget(max_action_desc=1), False),
        ("*笑了笑* *点头* 好。", ActionBudget(max_action_desc=1), True),
        ("*握住你的手* 别怕。", ActionBudget(max_action_desc=1), True),
        ("*握住你的手* 别怕。", ActionBudget(max_action_desc=1, physical_contact="light"), True),
        ("*把西瓜递给你* 给。", ActionBudget(max_action_desc=1, physical_contact="light"), False),
        ("*牵起你的手* 走吧。", ActionBudget(max_action_desc=1, physical_contact="light"), True),
        ("*牵起你的手* 走吧。", ActionBudget(max_action_desc=1, physical_contact="moderate"), False),
    ],
)
def test_observe_budget_branches(reply, budget, expected):
    observation = behavior_engine.observe_budget(reply, budget)
    assert observation["violated"] is expected
    assert observation["action_count"] == len(behavior_engine.ACTION_DESC_PATTERN.findall(reply))


def test_observe_budget_counts_star_segments():
    observation = behavior_engine.observe_budget(
        "*脸红* 你说什么呢 *移开视线* *小声嘀咕*", ActionBudget(max_action_desc=2)
    )
    assert observation["action_count"] == 3
    assert observation["action_violated"] is True
    assert observation["contact_level"] == "none"


async def test_run_budget_observer_records_violation():
    trace = TurnTraceSession()
    ctx = PostProcessContext(
        session_id="s1",
        user_id="u1",
        user_input="hi",
        ai_reply="*握住你的手* *摸摸头* 没事的。",
        state=None,
        analysis=None,
        trace=trace,
        behavior=type(
            "Directive",
            (),
            {"budget": ActionBudget(max_action_desc=0, physical_contact="light")},
        )(),
    )
    await run_budget_observer(ctx)
    steps = [s for s in trace.steps if s.name == "budget_observer"]
    assert len(steps) == 1
    assert steps[0].status == "violation"
    assert steps[0].extra["action_count"] == 2
    assert steps[0].extra["contact_violated"] is True


async def test_run_budget_observer_skips_without_behavior():
    trace = TurnTraceSession()
    ctx = PostProcessContext(
        session_id="s1",
        user_id="u1",
        user_input="hi",
        ai_reply="好",
        state=None,
        analysis=None,
        trace=trace,
        behavior=None,
    )
    await run_budget_observer(ctx)
    assert trace.steps == []
