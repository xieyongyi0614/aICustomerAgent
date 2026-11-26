"""PLAN-010 Step 4 ~ Step 6：`PlanningRevisionListener` / 三门槛 / 幂等 / Q8 / 证据引用。

覆盖 Task Detail §9.1（U9 ~ U13）与 §9.2（I3 ~ I9）。

口径：监听器**唯一动作**是 `goal_planning.enqueue_planning(goal_id, trigger=TRIGGER_REPLAN)`，
其余全是只读判定；「隔离断言（G-REFLECT）」在本模块同时以运行时快照与静态扫描两侧落地。
"""

import json
from types import SimpleNamespace

import pytest

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK, RunContext
from app.core.db import ActionRecordRow, BackgroundJobRow, InsightRow
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import goal_repository
from app.services.goal import planning as goal_planning
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.planning import goal_contract
from app.services.planning import revision as plan_revision
from app.services.planning import revision_listener as listener_mod
from app.services.reflection import lifecycle as reflection_lifecycle

from . import _plan_scan as scan
from .plan010_support import (
    NOW,
    TOOL_REMINDER,
    USER,
    EnqueueProbe,
    evidence_id,
    insight_item,
    listener_with_probe,
    plan_reflection_env,
    plan_reflection_on,
    planning_jobs,
    registry_snapshot,
    seed_action_series,
    seed_goal,
    seed_plan,
    seed_success_rate_series,
    structure_step,
)

ON_SURFACE_TOOL = "builtin.reminder.create"


@pytest.fixture
def planning_reflection_on(override_settings):
    """计划反思 + 规划面（引擎 / 装配）常开（子闸已删），只钉世界与观测面。"""
    plan_reflection_env(override_settings)


def _context(goal, *, tool_ids=(ON_SURFACE_TOOL,), evidence_refs=()) -> PlanContext:
    from app.core.settings import get_settings

    return PlanContext(
        goal=goal,
        tool_surface=ToolSurface(
            run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=tuple(tool_ids)
        ),
        budget=plan_context.plan_budget(get_settings()),
        evidence_refs=list(evidence_refs),
    )


def _count(session_factory, model) -> int:
    with session_factory() as session:
        return session.query(model).count()


class TestThreeGates:
    """Step 4 / U9 ~ U11：三门槛的负例与正例（任一不过即零动作）。"""

    def test_u9_type_gate_blocks_other_insight_types(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="类型门槛目标")
        seed_plan(goal.id, [structure_step(1)])
        listener, probe = listener_with_probe()
        listener.on_insight_created(
            USER, [insight_item("ins-u9", insight_type="usage_preference")]
        )
        listener.on_insight_created(
            USER, [insight_item("ins-u9b", insight_type="belief")]
        )
        assert probe.calls == []
        assert listener_mod.PLAN_INFLUENCE_INSIGHT_TYPES == ("capability_note", "pattern")

    def test_u10_confidence_gate_blocks_low_confidence(self, db_session_factory, plan_reflection_on):
        from app.core.settings import get_settings

        goal = seed_goal(description="置信度门槛目标")
        seed_plan(goal.id, [structure_step(1)])
        threshold = get_settings().plan_replan_min_confidence
        listener, probe = listener_with_probe()
        listener.on_insight_created(
            USER, [insight_item("ins-u10", confidence=threshold - 0.01)]
        )
        assert probe.calls == []
        listener.on_insight_created(USER, [insight_item("ins-u10b", confidence=threshold)])
        assert len(probe.calls) == 1

    def test_u11_goal_gate_blocks_when_no_mappable_goal(self, db_session_factory, plan_reflection_on):
        listener, probe = listener_with_probe()
        # 无任何活跃计划目标
        listener.on_insight_created(USER, [insight_item("ins-u11a")])
        # 只有 world 域目标，而洞察是 user 域
        world_goal = seed_goal(domain="world", description="世界目标")
        seed_plan(world_goal.id, [structure_step(1)])
        listener.on_insight_created(USER, [insight_item("ins-u11b", scope="user")])
        # 未知 scope（值集之外）
        listener.on_insight_created(USER, [insight_item("ins-u11c", scope="unknown")])
        assert probe.calls == []

    def test_u11_goal_gate_matches_scope_to_domain(self, db_session_factory, plan_reflection_on):
        personal = seed_goal(domain="personal", description="个人目标")
        world = seed_goal(domain="world", description="世界目标")
        seed_plan(personal.id, [structure_step(1)])
        seed_plan(world.id, [structure_step(1)])
        listener, probe = listener_with_probe()
        listener.on_insight_created(USER, [insight_item("ins-u11d", scope="world")])
        assert [call[1] for call in probe.calls] == [world.id]
        listener.on_insight_created(USER, [insight_item("ins-u11e", scope="user")])
        assert [call[1] for call in probe.calls] == [world.id, personal.id]
        assert {call[2] for call in probe.calls} == {goal_planning.TRIGGER_REPLAN}

    def test_mappable_goal_picks_the_latest_one_deterministically(
        self, db_session_factory, plan_reflection_on
    ):
        first = seed_goal(domain="personal", description="较早目标")
        seed_plan(first.id, [structure_step(1)])
        second = seed_goal(domain="personal", description="较晚目标")
        seed_plan(second.id, [structure_step(1)])
        listener, _probe = listener_with_probe()
        assert listener.mappable_goal_id(USER, "user") in (first.id, second.id)
        assert listener.mappable_goal_id(USER, "user") == listener.mappable_goal_id(
            USER, "user"
        )

    def test_gate_values_reuse_existing_settings(self, db_session_factory, plan_reflection_on):
        from app.core.settings import get_settings

        settings = get_settings()
        assert settings.plan_replan_min_confidence == 0.7
        assert settings.plan_reflection_min_samples == 3
        assert listener_mod.SCOPE_GOAL_DOMAINS == {
            "user": ("personal",),
            "relationship": ("relationship",),
            "world": ("world",),
        }
        assert set(listener_mod.PLANNABLE_LAYERS) == {"short_term", "medium", "long_term"}


class TestIdempotency:
    """Step 4 / U12 ~ U13、I8：本任务层幂等键 + 既有 job 层幂等的双重保障。"""

    def test_u12_idempotency_key_form_is_frozen(self):
        assert (
            listener_mod.replan_idempotency_key("g-1", "ins-1")
            == "plan_replan:g-1:ins-1"
        )
        assert listener_mod.REPLAN_IDEMPOTENCY_TEMPLATE == (
            "plan_replan:{goal_id}:{insight_id}"
        )
        assert listener_mod.replan_idempotency_key("", "ins-1") == ""
        assert listener_mod.replan_idempotency_key("g-1", "") == ""

    def test_u13_first_trigger_true_then_false(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="幂等目标")
        seed_plan(goal.id, [structure_step(1)])
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-u13") is True
        assert listener.enqueue_replan(goal.id, "ins-u13") is False
        assert len(planning_jobs(db_session_factory)) == 1
        assert listener.enqueue_replan(goal.id, "ins-u13-other") is False
        assert len(planning_jobs(db_session_factory)) == 1

    def test_u13_repeat_insight_does_not_enqueue_twice(
        self, db_session_factory, plan_reflection_on
    ):
        goal = seed_goal(description="重复洞察目标")
        seed_plan(goal.id, [structure_step(1)])
        listener = listener_mod.PlanningRevisionListener()
        payload = [insight_item("ins-u13b", confidence=0.9)]
        listener.on_insight_created(USER, payload)
        listener.on_insight_created(USER, payload)
        assert len(planning_jobs(db_session_factory)) == 1

    def test_i8_job_layer_keeps_a_single_job_per_goal(self, db_session_factory, plan_reflection_on):
        """既有 job 层（`enqueue_planning` 的 `idempotency_key`）是第二重幂等。"""
        goal = seed_goal(description="双重幂等目标")
        seed_plan(goal.id, [structure_step(1)])
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-i8-a") is True
        assert listener.enqueue_replan(goal.id, "ins-i8-b") is False
        jobs = planning_jobs(db_session_factory)
        assert len(jobs) == 1
        assert jobs[0].payload["trigger"] == goal_planning.TRIGGER_REPLAN
        assert jobs[0].payload["goal_id"] == goal.id

    def test_unknown_goal_is_not_triggered(self, db_session_factory, plan_reflection_on):
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan("missing-goal", "ins-x") is False


class TestQ8Deduplication:
    """Step 6 / I7：四判据同时命中 → 一个理由码 + 一个重规划触发。"""

    def _all_four(self):
        goal = seed_goal(description="四判据目标")
        plan = seed_plan(
            goal.id,
            [
                structure_step(
                    1, status="failed", attempt_count=1, on_failure="replan"
                ),
            ],
        )
        outcome = SimpleNamespace(
            step_index=1, status="failed", failure_kind="transient"
        )
        ctx = SimpleNamespace(
            step_max_attempts=1,
            off_surface_streak=2,
            undecidable_streak=2,
            insight_driven=True,
        )
        return goal, plan, outcome, ctx

    def test_i7_priority_is_fact_before_advice(self):
        assert listener_mod.REVISION_REASON_PRIORITY == (
            "step_attempt_exhausted",
            "criteria_undecidable",
            "tool_persistently_unavailable",
            "insight_driven",
        )
        assert set(listener_mod.REVISION_REASON_PRIORITY) == set(
            plan_revision.REVISION_REASONS
        )

    def test_i7_all_four_hits_collapse_to_one_reason_code(self):
        reason = listener_mod.dominant_revision_reason(
            listener_mod.REVISION_REASON_PRIORITY
        )
        assert reason == plan_revision.REASON_STEP_ATTEMPT_EXHAUSTED
        assert (
            listener_mod.dominant_revision_reason(
                [plan_revision.REASON_INSIGHT_DRIVEN]
            )
            == plan_revision.REASON_INSIGHT_DRIVEN
        )
        assert listener_mod.dominant_revision_reason([]) is None
        assert listener_mod.dominant_revision_reason(["unknown_reason"]) is None

    def test_i7_should_replan_is_untouched_by_this_task(self):
        """Q8 的归一资产在本任务；PLAN-005 的判定实现一字未改（Non-Scope）。"""
        source = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
        assert "should_replan" not in scan.code_text(source)
        assert plan_revision.REVISION_REASONS == (
            "step_attempt_exhausted",
            "tool_persistently_unavailable",
            "criteria_undecidable",
            "insight_driven",
        )

    def test_i7_all_four_hits_produce_exactly_one_trigger(
        self, db_session_factory, plan_reflection_on
    ):
        goal, plan, outcome, ctx = self._all_four()
        reason = plan_revision.PlanRevisionPolicy().should_replan(outcome, plan, ctx)
        assert reason == listener_mod.dominant_revision_reason(
            listener_mod.REVISION_REASON_PRIORITY
        )
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-q8") is True
        assert listener.enqueue_replan(goal.id, "ins-q8") is False
        assert len(planning_jobs(db_session_factory)) == 1

    def test_revision_record_carries_reason_kept_steps_and_evidence(self):
        goal = seed_goal(description="修订记录目标")
        plan = seed_plan(
            goal.id,
            [
                structure_step(1, status="done"),
                structure_step(2, status="failed", attempt_count=2),
            ],
        )
        record = listener_mod.plan_revision_record(plan, ["ins-1", "ins-2"], at=NOW)
        assert record.reason == plan_revision.REASON_INSIGHT_DRIVEN
        assert record.trigger_source == plan_revision.REASON_INSIGHT_DRIVEN
        assert record.from_version == plan.version
        assert record.to_version == plan.version + 1
        assert record.kept_steps == [1]
        assert record.evidence_refs == ["ins-1", "ins-2"]


class TestIsolation:
    """I3 / I4：隔离断言（G-REFLECT）——触发不改变计划、目标与工具注册表。"""

    def test_i3_on_insight_created_changes_nothing_but_the_job(
        self, db_session_factory, plan_reflection_on
    ):
        goal, plan = seed_success_rate_series()
        seed_action_series(goal_id=goal.id, count=1, tool_id=TOOL_REMINDER)
        listener = listener_mod.PlanningRevisionListener()

        def _snapshot():
            return {
                "goal": goal_repository.get_goal(goal.id).model_dump(),
                "plan": goal_repository.get_latest_plan(goal.id).model_dump(),
                "plans": [item.model_dump() for item in goal_repository.list_plans(goal.id)],
                "registry": registry_snapshot(),
                "actions": _count(db_session_factory, ActionRecordRow),
                "insights": _count(db_session_factory, InsightRow),
                "job_rows": _count(db_session_factory, BackgroundJobRow),
            }

        before = _snapshot()
        listener.on_insight_created(USER, [insight_item("ins-i3", confidence=0.9)])
        after = _snapshot()
        assert after["goal"] == before["goal"]
        assert after["plan"] == before["plan"]
        assert after["plans"] == before["plans"]
        assert after["registry"] == before["registry"]
        assert after["actions"] == before["actions"]
        assert after["insights"] == before["insights"]
        assert after["job_rows"] == before["job_rows"] + 1
        assert plan.id == after["plan"]["id"]

    def test_i4_listener_touches_only_the_planning_enqueue(self):
        source = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
        calls = scan.goal_repository_call_names(source)
        assert calls == {"get_goal", "list_active_plans"}
        assert calls & set(goal_contract.PLANNING_WRITE_FUNCTION_NAMES) == set()
        assert calls <= set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
        text = scan.code_text(source)
        for fragment in scan.FORBIDDEN_CODE_FRAGMENTS:
            assert fragment not in text, fragment
        assert "enqueue_planning" in text
        assert "goal_planning.TRIGGER_REPLAN" in text
        assert "create_plan" not in text
        assert "set_plan_status" not in text
        assert "finish_goal" not in text

    def test_i4_listener_has_no_tool_registry_surface(self):
        source = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
        imports = scan.imported_modules(source)
        assert not [
            module for module in imports if module.startswith("app.services.tool")
        ]
        text = scan.code_text(source)
        for token in ("ToolRegistry", "get_tool_registry", "health", "trip", "disable"):
            assert token not in text, token

    def test_i4_listener_has_no_prompt_or_llm_surface(self):
        source = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
        text = scan.code_text(source)
        for token in ("build_structured_chain", "get_llm", "ChatPromptTemplate"):
            assert token not in text, token

    def test_i3_enqueue_exception_is_swallowed(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="入队异常目标")
        seed_plan(goal.id, [structure_step(1)])

        def _boom(*args, **kwargs):
            raise RuntimeError("enqueue down")

        listener = listener_mod.PlanningRevisionListener(enqueue=_boom)
        assert listener.enqueue_replan(goal.id, "ins-boom") is False
        assert planning_jobs(db_session_factory) == []


class TestRegistration:
    """I5（语义反转）：第四个注册点恒注册（子闸已随开关体系删除）。"""

    def test_i5_registered_as_the_fourth_consumer(self, db_session_factory, plan_reflection_on):
        reflection_lifecycle.reset_insight_created_listeners()
        listener_mod.register_runtime()
        registered = list(reflection_lifecycle._insight_created_listeners)
        assert registered == [listener_mod.on_insight_created]
        assert registered[0].__module__ == "app.services.planning.revision_listener"

    def test_i5_registered_lambda_receives_the_notification(
        self, db_session_factory, plan_reflection_on
    ):
        goal = seed_goal(description="注册回调目标")
        seed_plan(goal.id, [structure_step(1)])
        reflection_lifecycle.reset_insight_created_listeners()
        listener_mod.register_runtime()
        reflection_lifecycle.notify_insight_created_listeners(
            USER, [insight_item("ins-i5", confidence=0.9)]
        )
        assert len(planning_jobs(db_session_factory)) == 1
        assert listener_mod.evidence_refs_for(goal.id) == ("ins-i5",)

    def test_i5_main_lifespan_registers_unconditionally(self):
        from pathlib import Path

        from app import main

        source = Path(main.__file__).read_text(encoding="utf-8")
        assert "    register_plan_revision_listener()" in source
        assert "plan_reflection_enabled" not in source
        assert (
            "from app.services.planning.revision_listener import (\n"
            "    register_runtime as register_plan_revision_listener,\n)" in source
        )

    def test_i5_listener_errors_do_not_break_other_consumers(
        self, db_session_factory, plan_reflection_on, monkeypatch
    ):
        observed: list[str] = []
        reflection_lifecycle.reset_insight_created_listeners()
        reflection_lifecycle.register_insight_created_listener(
            lambda user_id, created: observed.append("other")
        )
        monkeypatch.setattr(
            listener_mod, "on_insight_created", lambda user_id, created: observed.append("plan")
        )
        reflection_lifecycle.register_insight_created_listener(listener_mod.on_insight_created)
        reflection_lifecycle.notify_insight_created_listeners(USER, [insight_item()])
        assert observed == ["other", "plan"]


class TestEvidenceRefsClosure:
    """Step 5 / I9：`evidence_refs` 从触发源 → 上下文 → prompt → 计划记录。"""

    def test_i9_trigger_records_the_evidence_refs(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="证据引用目标")
        seed_plan(goal.id, [structure_step(1)])
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-i9-a") is True
        assert listener.enqueue_replan(goal.id, "ins-i9-b") is False
        assert listener.evidence_refs_for(goal.id) == ("ins-i9-a",)
        assert listener.evidence_refs_for("other-goal") == ()

    def test_i9_default_listener_is_reachable_and_resettable(
        self, db_session_factory, plan_reflection_on
    ):
        goal = seed_goal(description="默认监听器目标")
        seed_plan(goal.id, [structure_step(1)])
        assert listener_mod.get_revision_listener() is listener_mod.get_revision_listener()
        assert listener_mod.enqueue_replan(goal.id, "ins-i9-c") is True
        assert listener_mod.evidence_refs_for(goal.id) == ("ins-i9-c",)
        listener_mod.reset_revision_state()
        assert listener_mod.evidence_refs_for(goal.id) == ()
        # 复位只清本任务层账：既有 job 层（持久）仍持有该目标的 job，故重复触发依旧 False。
        assert listener_mod.enqueue_replan(goal.id, "ins-i9-c") is False
        assert listener_mod.evidence_refs_for(goal.id) == ()

    @pytest.mark.asyncio
    async def test_i9_evidence_refs_land_on_prompt_and_plan_record(
        self, db_session_factory, planning_reflection_on, stub_planning_llm
    ):
        goal = seed_goal(description="证据引用落盘目标")
        planner = listener_mod.PlanningRevisionListener()
        assert planner.enqueue_replan(goal.id, "ins-i9-d") is True
        refs = planner.evidence_refs_for(goal.id)
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        outcome = await plan_engine.PlanningEngine().plan(
            goal,
            _context(goal, evidence_refs=refs),
            trigger=goal_planning.TRIGGER_REPLAN,
        )
        assert outcome.validated is True
        assert outcome.plan.evidence_refs == ("ins-i9-d",)
        constraints = json.loads(recorder["messages"][1][1])
        assert constraints["evidence_refs"] == ["ins-i9-d"]
        assert constraints[goal_planning.EVIDENCE_NOTE_KEY] == goal_planning.EVIDENCE_NOTE
        assert "换一种做法" in constraints[goal_planning.EVIDENCE_NOTE_KEY]

    @pytest.mark.asyncio
    async def test_i9_empty_evidence_keeps_the_prompt_untouched(
        self, db_session_factory, planning_reflection_on, stub_planning_llm
    ):
        goal = seed_goal(description="空证据目标")
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        outcome = await plan_engine.PlanningEngine().plan(
            goal, _context(goal), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.validated is True
        assert outcome.plan.evidence_refs == ()
        constraints = json.loads(recorder["messages"][1][1])
        assert goal_planning.EVIDENCE_REFS_KEY not in constraints
        assert goal_planning.EVIDENCE_NOTE_KEY not in constraints

    @pytest.mark.asyncio
    async def test_i9_assembler_carries_run_evidence_refs_into_the_context(
        self, db_session_factory, planning_reflection_on
    ):
        goal = seed_goal(description="装配透传目标")
        context = await plan_context.PlanContextAssembler().assemble(
            goal,
            run=RunContext(
                run_id="run-plan10",
                user_id=USER,
                run_kind=RUN_KIND_AUTONOMOUS_TICK,
                trigger_type="schedule",
                reason="goal_work",
                started_at=NOW,
                data={"evidence_refs": ["ins-i9-e"]},
            ),
            now=NOW,
        )
        assert isinstance(context, plan_context.PlanContext)
        assert context.evidence_refs == ["ins-i9-e"]

    def test_i9_probe_and_seed_helpers_stay_in_the_evidence_module(self):
        """证据窗与门控的落点：`services/reflection/evidence.py`（不在计划包内）。"""
        source = scan.PLANNING_PACKAGE_DIR / "revision_listener.py"
        text = scan.code_text(source)
        assert "aggregate_plan_evidence" not in text
        assert "aggregate_evidence_windows" not in text


class TestPlanNamespacing:
    """Step 6：Q8 归一与触发不引入新命名空间 / 新 job 类型。"""

    def test_evidence_id_of_plan_steps_is_reused_by_the_listener(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="证据 id 复用目标")
        seed_plan(goal.id, [structure_step(1, status="done")])
        assert evidence_id(goal.id, 1, 1) == f"plan:{goal.id}:1:1"
        assert goal_contract.PLANNING_TRIGGER_VALUES == ("goal_created", "goal_blocked", "goal_replan")

    def test_new_probe_defaults_do_not_leak_between_instances(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="探针隔离目标")
        seed_plan(goal.id, [structure_step(1)])
        probe = EnqueueProbe()
        first, _ = listener_with_probe(probe=probe)
        second, second_probe = listener_with_probe()
        assert first.enqueue_replan(goal.id, "ins-z") is True
        assert second.enqueue_replan(goal.id, "ins-z") is True
        assert len(probe.calls) == 1
        assert len(second_probe.calls) == 1
        assert planning_jobs(db_session_factory) == []
