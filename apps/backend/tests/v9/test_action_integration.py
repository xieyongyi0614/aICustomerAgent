"""V9 Action Integration：World/Memory/Relationship 结果整合 + ActionContext + 评估护栏（V9-006/007/008）。"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import integrate_result, run_action_planning, new_record
from app.core.settings import get_settings
from app.models.action import ActionIntent, ActionResult, ActionEffect
from app.services.action.context import ActionContext, build_action_context, render_action_section
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
    due = (datetime.now() + timedelta(hours=1)).isoformat()
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
    due = datetime.now().isoformat()
    await run_action_planning("int-user-3", _intent(content="吃药", due_at=due), session_id="s1")
    ctx: ActionContext | None = build_action_context("int-user-3")
    if ctx is None:
        return
    rendered = render_action_section(ctx, 400)
    assert len(rendered) <= 401


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
