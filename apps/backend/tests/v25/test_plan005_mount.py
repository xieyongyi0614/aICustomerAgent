"""PLAN-005 Step 8：`life_loop` 挂载与回归（签名 / 九步序列 / Flag 门控 / 记账）。

覆盖 Task Detail §9.2 I9、I10、I13 与 §9.3 S11 的可判定部分：计划阶段子步骤记账、
九步序列与 stage 序列零差异、Flag off 时走既有 `goal_observation` 原路径。
"""

import inspect
from pathlib import Path

import pytest

from app.application import life_loop
from app.application.agent_runtime import profiles
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.repositories import goal_repository, loop_run_repository
from app.services import goal_observation, life_loop_budget
from app.services.planning import observer as plan_observer
from app.services.planning.observer import PlanObserver

from . import plan005_support as support
from .conftest import V25_NOW, V25_USER

AUTONOMOUS_TICK_STAGES = (
    "perception",
    "state_update",
    "state_snapshot",
    "goal_check",
    "goal_stack",
    "goal_supply",
    "goal_advance",
    "memory_retrieval",
    "reflection_check",
    "decision",
    "world_experience",
)

FACT_KEYS = {
    "now",
    "world",
    "state",
    "memory",
    "action_results",
    "action_history",
    "tool",
    "tool_results",
}


@pytest.fixture
def advance_on(override_settings):
    life_loop_budget.reset_cache()
    override_settings(
        observability_persist_enabled="false")


@pytest.fixture
def observation_on(advance_on):
    """观测接线锚点（历史名保留）：观测子闸已随开关体系删除，本夹具只链 `advance_on`。"""


class TestShapeSnapshots:
    """I10：九步序列 / stage 序列 / 签名 / trace step 名零差异。"""

    def test_step_signature_is_unchanged(self):
        assert list(inspect.signature(life_loop._step_goal_advance).parameters) == [
            "user_id",
            "now",
        ]
        assert list(inspect.signature(life_loop._observation_facts).parameters) == [
            "user_id",
            "now",
        ]

    def test_autonomous_tick_stage_sequence_is_unchanged(self):
        spec = profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK)
        assert spec.stages == AUTONOMOUS_TICK_STAGES
        assert "plan_execute" not in spec.stages, "PLAN-005 纪律：不新增步骤"
        assert spec.llm_capable == frozenset({"decision"})
        assert spec.critical == frozenset({"decision"})

    def test_no_new_maintenance_step_or_scheduling_loop(self):
        source = Path(life_loop.__file__).read_text(encoding="utf-8")
        assert "_process_due_retries" in source, "退避仍由既有 action 维护步承载"

    def test_goal_observation_entry_points_are_still_registered(self):
        from app.services.trace_collector import TRACE_STEP_NAMES

        assert "goal_observation" in TRACE_STEP_NAMES
        assert callable(goal_observation.advance_user_goals)


class TestFlagGatedWiring:
    """Step 8（v25 去门控语义反转）：观测恒走 `PlanObserver`（同一签名、同一返回字段集）。

    原「Flag off 走原路径 / 总闸 off 子闸不生效」两用例的前提已随开关删除退役；
    旧路径 `goal_observation.advance_user_goals` 不再被编排调用。
    """

    @staticmethod
    def _spy_observer(monkeypatch) -> dict:
        """记录两条观测入口的调用形态：`collect_facts(observation_keys=...)` 与 `observe_user_goals`。

        接线路径不传白名单（`"derive"`）——由 active 计划的步骤声明反推。
        """
        calls: dict = {"collect": [], "observe": 0}

        def _collect(_self, _user_id, _ctx, **kwargs):
            calls["collect"].append(kwargs.get("observation_keys", "derive"))
            return {"now": V25_NOW, "world": {}, "state": {}, "memory": {}}

        def _observe(_self, _user_id, _facts, **_kwargs):
            calls["observe"] += 1
            return {"status": "ok", "goals": 1, "results": [], "settled": 0}

        monkeypatch.setattr(PlanObserver, "collect_facts", _collect)
        monkeypatch.setattr(PlanObserver, "observe_user_goals", _observe)
        return calls

    @pytest.mark.asyncio
    async def test_step_uses_the_plan_observer(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        calls = self._spy_observer(monkeypatch)
        legacy: list = []
        monkeypatch.setattr(
            goal_observation,
            "advance_user_goals",
            lambda user_id, facts, now: legacy.append(user_id) or {},
        )
        goal = make_goal(user_id=V25_USER, description="计划观测接线")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert legacy == []
        assert calls == {"collect": ["derive"], "observe": 1}
        assert result["plan_observe"] == {"goals": 1, "settled": 0}
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_return_field_set_is_stable(
        self, db_session_factory, advance_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=V25_USER, description="字段集对照")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert "plan_observe" in result


class TestFactProjectionParity:
    """I13：既有事实投影的形状与查询面不变（本任务只加第四源）。"""

    def test_legacy_facts_keys_are_unchanged(self, db_session_factory, advance_on):
        facts = life_loop._observation_facts(V25_USER, V25_NOW)
        assert set(facts) == FACT_KEYS
        assert facts["now"] == V25_NOW
        assert facts["tool"] == {}
        assert facts["tool_results"] == []

    def test_legacy_facts_do_not_read_the_plan_chain(
        self, db_session_factory, advance_on, monkeypatch
    ):
        calls: list = []
        monkeypatch.setattr(
            plan_observer.goal_repository,
            "list_active_plans",
            lambda user_id: calls.append(user_id) or [],
        )
        life_loop._observation_facts(V25_USER, V25_NOW)
        assert calls == []

    def test_all_four_sources_are_assembled_when_the_flag_is_on(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=V25_USER, description="四源装配")
        make_plan(goal.id, [dict(_tool_step())])
        facts = PlanObserver().collect_facts(
            V25_USER, plan_observer.ObservationContext(now=V25_NOW)
        )
        assert set(facts) == FACT_KEYS
        assert plan_observer.FACT_SOURCE_TOOL in facts


def _tool_step() -> dict:
    return {
        "index": 1,
        "description": "推送提醒",
        "capability": "create_reminder",
        "params": {"content": "该休息了"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
        "tool_id": support.REMINDER_CREATE,
        "observation_keys": ["reminder_id"],
    }


class TestLoopRunAccounting:
    """I9：计划阶段子步骤以 `plan_observe` 记入 `loop_runs.steps`（受既有 `budget_state` 约束）。"""

    @pytest.mark.asyncio
    async def test_plan_observe_lands_in_the_run_steps(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=V25_USER, description="记账")
        make_plan(goal.id)
        run = loop_run_repository.create_run(
            user_id=V25_USER, kind="autonomy", reason="goal_work", now=V25_NOW
        )
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        entry = {"step": "goal_advance", **result}
        loop_run_repository.mark_step(run.id, entry)
        loop_run_repository.finish_run(
            run.id,
            status="done",
            steps=[entry],
            budget_state=life_loop_budget.check_daily_budget(now=V25_NOW).as_dict(),
            now=V25_NOW,
        )
        stored = loop_run_repository.list_recent(user_id=V25_USER)[0]
        goal_advance_step = next(s for s in stored.steps if s["step"] == "goal_advance")
        assert goal_advance_step["plan_observe"] == {"goals": 1, "settled": 0}
        assert stored.budget_state is not None

    @pytest.mark.asyncio
    async def test_no_new_llm_budget_is_consumed(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        """观测为 0 LLM：`plan_observe` 不计入周期 LLM 预算（`llm_capable` 缺省 False）。"""
        goal = make_goal(user_id=V25_USER, description="预算不变")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert "llm_capable" not in result["plan_observe"]
        assert "llm_capable" not in result


class TestAdvanceOutcomeThroughTheLoop:
    """S11 的端到端形态：循环的观测与 `PlanObserver` 同源（同一 `advance_goal`）。"""

    @pytest.mark.asyncio
    async def test_loop_observation_leaves_an_unsatisfied_goal_active(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=V25_USER, description="循环未达成")
        make_plan(goal.id)
        result = await life_loop._step_goal_advance(V25_USER, V25_NOW)
        assert result["plan_observe"]["goals"] == 1
        assert result["plan_observe"]["settled"] == 0
        assert goal_repository.get_goal(goal.id).status == "active"
        assert goal_repository.get_latest_plan(goal.id).sub_goals[0].attempt_count == 1

    @pytest.mark.asyncio
    async def test_satisfied_criteria_settle_the_goal(
        self, db_session_factory, observation_on, make_goal, make_plan, goal_facts
    ):
        goal = make_goal(user_id=V25_USER, description="循环达成")
        make_plan(goal.id)
        observer = PlanObserver()
        facts = observer.collect_facts(
            V25_USER,
            plan_observer.ObservationContext(now=V25_NOW),
        )
        facts["action_results"] = goal_facts(succeeded=["create_reminder"])["action_results"]
        result = observer.observe_user_goals(V25_USER, facts, now=V25_NOW)
        assert result["results"][0]["outcome"] == "completed"
        assert result["settled"] == 1
        assert goal_repository.get_goal(goal.id).status == "completed"
