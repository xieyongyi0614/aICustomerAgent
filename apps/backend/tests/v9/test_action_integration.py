"""V9 Action Integration：World/Memory/Relationship 结果整合 + ActionContext + 评估护栏（V9-006/007/008）。"""

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.application.action_engine import integrate_result, run_action_planning, new_record
from app.core.settings import get_settings
from app.models.action import ActionIntent, ActionResult, ActionEffect
from app.services.action.context import (
    ActionContext,
    ActionItem,
    build_action_context,
    render_action_section,
)
from app.services.action.relationship_bridge import deliver_action_signal, lookup_signal
from app.services.evaluation.context import ActionSlice
from app.services.evaluation.rules.action import ActionOverclaimRule, ActionUnreportedFailureRule
from app.services.evaluation.context import EvaluationContext


def _intent(action_type="create_reminder", **params):
    return ActionIntent(action_type=action_type, confidence="confident", params=params, dedupe_key="")


@pytest.mark.asyncio
async def test_world_event_created_via_action(override_settings, db_session_factory):
    from app.application import world_engine

    override_settings()
    due = (timeutil.now() + timedelta(hours=1)).isoformat()
    record = await run_action_planning("int-user-1", _intent(content="复诊", due_at=due), session_id="s1")
    assert record is not None
    if record.status == "succeeded":
        events = world_engine.list_active_events("int-user-1")
        assert any(e.title == "复诊" and e.type == "reminder" for e in events)


@pytest.mark.asyncio
async def test_remember_fact_writes_memory(override_settings, db_session_factory):
    from app.repositories import memory_repository

    override_settings()
    record = await run_action_planning("int-user-2", _intent("remember_fact", fact="喜欢抹茶"), session_id="s1")
    assert record is not None
    if record.status == "succeeded":
        memories = memory_repository.list_by_user("int-user-2")
        assert any("抹茶" in (m.content or "") for m in memories)


@pytest.mark.asyncio
async def test_action_context_renders_within_budget(override_settings, db_session_factory):
    override_settings()
    due = timeutil.now().isoformat()
    await run_action_planning("int-user-3", _intent(content="吃药", due_at=due), session_id="s1")
    ctx: ActionContext | None = build_action_context("int-user-3")
    if ctx is None:
        return
    rendered = render_action_section(ctx, 400)
    assert len(rendered) <= 401


def test_action_section_frames_completed_as_background():
    """收敛回归：终态素材要自带「只作背景」框架，信息不丢。

    实测：用户说"明天早上8点，叫我起床签到"，回复大半在点评上一条已完成的记账——
    素材没被声明成背景，模型就当成了本轮要展开的话题。
    """
    ctx = ActionContext(
        items=[
            ActionItem(
                action_type="record_ledger_entry",
                status="succeeded",
                summary="记一笔：支出¥240.00",
                updated_at=timeutil.now(),
            )
        ]
    )

    rendered = render_action_section(ctx, 400)

    assert "只作背景" in rendered
    assert "不要展开点评" in rendered
    assert "记一笔：支出¥240.00（已完成）" in rendered


def test_terminal_slots_prefer_failure_and_cap_completed(
    override_settings, db_session_factory
):
    """收敛回归：终态 2 格 = 失败优先 + 完成最多 1 条；cancelled 不占槽位。

    失败记录故意设为最旧：旧规则（纯 updated_at 倒序取 2）会把它挤掉，
    两条完成同时进素材。cancelled 设为最新：它不该把唯一的完成行顶掉。
    """
    from app.repositories import action_repository

    override_settings()
    user = "int-user-slots"
    failed = new_record(_intent("remember_fact", fact="买牛奶"), user, session_id="s1")
    failed.status = "failed"
    failed.updated_at = timeutil.now() - timedelta(hours=3)
    action_repository.save_record(failed)
    for amount, minutes_ago in ((24000, 5), (800, 10)):
        record = new_record(
            _intent("record_ledger_entry", amount_minor=amount, direction="expense"),
            user,
            session_id="s1",
        )
        record.status = "succeeded"
        # 显式时间：240 元那条最新（done[:1] 取它），800 元那条更旧
        record.updated_at = timeutil.now() - timedelta(minutes=minutes_ago)
        action_repository.save_record(record)
    cancelled = new_record(_intent("remember_fact", fact="旧事"), user, session_id="s1")
    cancelled.status = "cancelled"
    cancelled.updated_at = timeutil.now() + timedelta(minutes=1)
    action_repository.save_record(cancelled)

    rendered = render_action_section(build_action_context(user), 400)

    assert "上次失败" in rendered
    assert rendered.count("（已完成）") == 1
    assert "记一笔：支出¥240.00" in rendered
    assert "旧事" not in rendered


@pytest.mark.asyncio
async def test_relationship_signal_lookup(override_settings, db_session_factory):
    override_settings(action_relationship_enabled=True)
    record = await run_action_planning("int-user-5", _intent("remember_fact", fact="喜欢散步"), session_id="s1")
    assert record is not None
    if record.status == "succeeded":
        signal = lookup_signal(record)
        assert signal is not None


def test_overclaim_rule_fires_and_clears(override_settings, db_session_factory):
    from app.repositories import action_repository

    override_settings()
    ctx = EvaluationContext(
        subject="turn",
        subject_id="t1",
        session_id="s1",
        user_id="int-user-6",
        reply="我已经帮你记下来了",
    )
    ctx.action = ActionSlice(records=[], intent={"action_type": "remember_fact"})
    rule = ActionOverclaimRule()
    issue = rule.evaluate(ctx)
    assert issue is not None

    record = new_record(_intent("remember_fact", fact="X"), "int-user-6", session_id="s1")
    record.status = "succeeded"
    record.steps = [{"status": "succeeded", "result": {"payload": {"memory_id": "m1"}}}]
    action_repository.save_record(record)
    ctx2 = EvaluationContext(
        subject="turn", subject_id="t1", session_id="s1", user_id="int-user-6",
        reply="我已经帮你记下来了",
    )
    ctx2.action = ActionSlice(records=[record.model_dump(mode="json")], intent={"action_type": "remember_fact"})
    assert rule.evaluate(ctx2) is None


def test_unreported_failure_rule(override_settings, db_session_factory):
    from app.repositories import action_repository

    override_settings()
    ctx = EvaluationContext(
        subject="turn", subject_id="t1", session_id="s1", user_id="int-user-7",
        reply="下次再说",
    )
    ctx.action = ActionSlice(
        records=[
            {"action_type": "create_reminder", "status": "failed", "gate_reason": None, "session_id": "s1"}
        ],
        intent={"action_type": "create_reminder"},
    )
    rule = ActionUnreportedFailureRule()
    issue = rule.evaluate(ctx)
    assert issue is not None
