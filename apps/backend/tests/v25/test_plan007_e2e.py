"""PLAN-007 §9.3 场景集：自治 tick 与计划推进的竞争（S1 ~ S6；S7 随开关删除退役）。

| # | 场景 | 判定 |
|---|---|---|
| S1 | 计划推进中且与本 intent 同动作 | 自治抑制为 `wait`，额度未被重复消耗，计划步骤不被抢走 |
| S2 | 计划推进中但动作不同 | 自治正常主动（不抑制） |
| S3 | P0 / P1 触发源 | 仍越过计划抑制（`HIGH_PRIORITY_OVERRIDE` 语义不变） |
| S4 | 装配失败（`list_active_plans` 抛错） | `plan_facts == {}`、tick 正常完成 |
| S5 | 额度耗尽 | 见 `test_plan007_quota.py`（计划步骤执行入口即执行桥，已在彼处判定） |
| S6 | 计划全部步骤终态 | `plan_facts` 仍可存在但 `current_step=None` → 自治不受抑制 |

v25 去门控（批次 6）：原 S7「子闸 off 回到 V2.4.0」的前提（`plan_autonomy_enabled`
可关）已不存在——事实段采集恒发生，抑制语义即生产语义，S7 对照面整体退役。
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.character.asuna import PERSISTENT_GOALS
from app.core.db import Message
from app.models.observability import DecisionKind
from app.repositories import (
    action_repository,
    conversation_repository,
    decision_repository,
    goal_repository,
    proactive_repository,
)
from app.services import conversation_service, trigger_evaluator

from . import plan007_support as support

USER = "plan7-e2e-user"
SESSION_ID = "plan7-e2e-session"
NOW = datetime(2026, 9, 16, 14, 0, 0)
TICK_AT = NOW + timedelta(minutes=35)

CARE_GOALS = tuple(goal for goal in PERSISTENT_GOALS if goal.type == "user_care")
"""只播 `user_care` 种目标：让自治选择确定（intention = `check_in` → `create_reminder`）。"""

SUPPRESSION_NOTE = "计划推进中，暂不抢同一动作"


@pytest.fixture(autouse=True)
def _clear_followups():
    trigger_evaluator._followup_registry.clear()
    yield
    trigger_evaluator._followup_registry.clear()


@pytest.fixture
def autonomy_env(override_settings):
    """自治通路默认开闸（既有 V2.0.0 / V7 Flag），本任务的子闸由各用例显式开关。"""
    override_settings(
        observability_persist_enabled="true")
    return True


def _seed_conversation(tail_minutes: int = 40) -> None:
    goal_repository.seed_goals(USER, CARE_GOALS)
    conversation_repository.get_or_create_conversation(SESSION_ID, USER)
    conversation_service.save_turn(SESSION_ID, "我去忙了", "好的，去吧，我等你回来")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=tail_minutes)
        session.commit()


def _care_goal():
    return next(
        goal
        for goal in goal_repository.list_active(USER)
        if goal.type == "user_care" and goal.layer is None
    )


def _seed_advancing_plan(capability: str = support.REMINDER_ACTION):
    goal = _care_goal()
    support.seed_plan(goal.id, [support.spec(1, capability=capability)])
    return goal


def _tick(llm=None):
    return asyncio.run(
        autonomy_engine.tick(user_ids=[USER], llm=llm, now=TICK_AT)
    )


def _decisions():
    return decision_repository.search(user_id=USER, kind=DecisionKind.PROACTIVE_AUTONOMY)


def _proactive_actions():
    return proactive_repository.list_since(NOW)


class TestS1SameActionIsNotContested:
    """S1：计划推进到某步且自治 intent 与当前步同动作 → 抑制、额度不重复消耗。"""

    def test_the_autonomy_yields_to_the_planning_step(
        self, autonomy_env, db_session_factory, fake_llm, override_settings
    ):
        _seed_conversation()
        goal = _seed_advancing_plan()
        llm = fake_llm(response=["忙完了吗？"])

        delivered = _tick(llm)

        assert delivered == [], "计划正在推进同一动作：自治不得抢"
        assert _proactive_actions() == []
        assert action_repository.list_records(USER, limit=10) == [], "额度未被消耗"

        records = _decisions()
        assert records, "抑制同样必须落决策审计"
        assert all(record.decision == "wait" for record in records)
        assert SUPPRESSION_NOTE in records[0].reason
        facts = records[0].input_snapshot["plan_facts"]
        assert facts["active_goal_id"] == goal.id
        assert facts["current_step"] == 1
        assert facts["current_action_type"] == support.REMINDER_ACTION

    def test_the_plan_step_itself_is_untouched(
        self, autonomy_env, db_session_factory, fake_llm, override_settings
    ):
        _seed_conversation()
        goal = _seed_advancing_plan()
        before = goal_repository.get_latest_plan(goal.id)
        _tick(fake_llm(response=["忙完了吗？"]))
        after = goal_repository.get_latest_plan(goal.id)
        assert after.model_dump() == before.model_dump(), "自治不得改写计划"


class TestS2DifferentActionIsNotSuppressed:
    """S2：计划当前步为别的动作 → 自治正常主动。"""

    def test_the_autonomy_still_acts(
        self, autonomy_env, db_session_factory, fake_llm, override_settings
    ):
        _seed_conversation()
        _seed_advancing_plan(capability=support.OTHER_ACTION)
        llm = fake_llm(response=["忙完了吗？记得喝口水。"])

        delivered = _tick(llm)

        assert len(delivered) == 1
        records = _decisions()
        assert records[0].decision == "act"
        assert SUPPRESSION_NOTE not in records[0].reason
        assert (
            records[0].input_snapshot["plan_facts"]["current_action_type"]
            == support.OTHER_ACTION
        )


class TestS3HighPriorityCrosses:
    """S3：P0 / P1 触发源仍越过计划抑制。"""

    def test_a_scheduled_followup_still_acts(
        self, autonomy_env, db_session_factory, fake_llm, override_settings
    ):
        _seed_conversation()
        _seed_advancing_plan()
        assert trigger_evaluator.register_followup(
            USER,
            due_at=TICK_AT - timedelta(minutes=1),
            summary="面试提醒",
            dedupe_key="followup:plan7:interview",
        )
        llm = fake_llm(response=["面试要开始了，加油。"])

        delivered = _tick(llm)

        assert len(delivered) == 1, "P0 触发源必须越过计划抑制"
        records = _decisions()
        assert records[0].trigger == "scheduled_followup"
        assert records[0].decision == "act"
        assert SUPPRESSION_NOTE not in records[0].reason


class TestS4AssemblyFailureDoesNotBlockTheTick:
    """S4：`list_active_plans` 抛异常 → `plan_facts == {}`，tick 正常完成。"""

    def test_the_tick_completes_with_an_empty_packet(
        self,
        autonomy_env,
        db_session_factory,
        fake_llm,
        override_settings,
        monkeypatch,
    ):
        _seed_conversation()
        _seed_advancing_plan()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("plans down")

        monkeypatch.setattr(goal_repository, "list_active_plans", _boom)
        llm = fake_llm(response=["忙完了吗？记得喝口水。"])

        delivered = _tick(llm)

        assert len(delivered) == 1, "装配失败不得阻塞 tick"
        records = _decisions()
        assert records[0].decision == "act"
        assert "plan_facts" not in records[0].input_snapshot


class TestS6FinishedPlanDoesNotSuppress:
    """S6：计划步骤全部终态（`current_step=None`）→ 自治不受抑制。"""

    def test_a_terminal_plan_leaves_the_autonomy_free(
        self, autonomy_env, db_session_factory, fake_llm, override_settings
    ):
        _seed_conversation()
        goal = _care_goal()
        support.seed_plan(
            goal.id,
            [support.spec(1, status="done"), support.spec(2, status="done")],
        )
        llm = fake_llm(response=["忙完了吗？记得喝口水。"])

        delivered = _tick(llm)

        assert len(delivered) == 1
        records = _decisions()
        assert records[0].decision == "act"
        facts = records[0].input_snapshot["plan_facts"]
        assert facts["current_step"] is None
        assert facts["steps_total"] == 2


class TestPacketAssembly:
    """原 S7 对照面的保留半边：采集函数在有 active 计划时产出七键包（off 半边随开关退役）。"""

    def test_the_packet_is_assembled_from_the_active_plan(
        self, autonomy_env, db_session_factory, override_settings
    ):
        _seed_conversation()
        goal = _seed_advancing_plan()

        override_settings(
            observability_persist_enabled="true")
        facts = autonomy_engine._collect_plan_facts(USER, TICK_AT)
        assert facts["active_goal_id"] == goal.id
        assert facts["current_step"] == 1
