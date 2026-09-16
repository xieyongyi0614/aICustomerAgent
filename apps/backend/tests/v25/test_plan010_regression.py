"""PLAN-010 回归与场景：既有三消费者不变 / 无性格类 Insight / Flag off 逐字节一致 / 端到端回环。

覆盖 Task Detail §9.2（I6 / I10 / I11 / I13）与 §9.3（S1 / S6 / S8 / S10）。
"""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.core.db import ActionRecordRow, BackgroundJobRow, InsightRow, ReflectionRunRow
from app.core.settings import get_settings
from app.repositories import (
    action_repository,
    goal_repository,
    relationship_milestone_repository,
)
from app.services import goal_planning
from app.services.development.policy import on_insight_created as development_consumer
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.planning import goal_contract
from app.services.planning import revision_listener as listener_mod
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import reflector, triggers
from app.services.relationship_narrative import on_insight_created as narrative_consumer
from app.services.world.event_bridge import on_insight_created as world_consumer

from .plan010_support import (
    NOW,
    TOOL_REMINDER,
    USER,
    insight_item,
    plan_reflection_env,
    plan_reflection_on,
    planning_jobs,
    registry_snapshot,
    seed_goal,
    seed_plan,
    seed_success_rate_series,
    structure_step,
)
from .test_plan001_flag_regression import FROZEN_PROMPT_DIGEST, _digest

PLAN_CONSUMERS = (
    ("development", development_consumer),
    ("narrative", narrative_consumer),
    ("world", world_consumer),
)

CONSUMER_INSIGHT = dict(
    insight_type="pattern",
    scope="relationship",
    confidence=0.9,
    statement="我给自己定的判据太虚，常判不出来",
)


@pytest.fixture
def scripted_reflection_llm(monkeypatch):
    """反射 LLM 面脚本化（既有 TOOL-009 同款）：只回一个引用三条证据的提案。"""
    from langchain_core.runnables import RunnableLambda

    from app.models.reflection import ReflectionProposal

    proposal = ReflectionProposal.model_validate(
        {
            "insights": [
                {
                    "statement": "这类计划 4 步做不完，实际两步就够",
                    "type": "capability_note",
                    "scope": "user",
                    "evidence_ids": ["E1", "E2", "E3"],
                    "counter_evidence": "无",
                    "self_confidence": 0.9,
                }
            ]
        }
    )

    class _Chain:
        def __init__(self):
            self.calls = 0

        def invoke(self, _payload):
            self.calls += 1
            return proposal

    chain = _Chain()

    def _build(messages, schema, llm):
        return chain

    monkeypatch.setattr(reflector, "build_structured_chain", _build)
    return chain


def _count(session_factory, model) -> int:
    with session_factory() as session:
        return session.query(model).count()


EFFECT_COUNTERS = ("compile_jobs", "milestones", "insights", "actions", "plans")


def _consumer_effects(session_factory, user_id: str = USER) -> dict:
    """三个既有消费者各自的副作用**累计快照**（**不含**本任务新增的 `goal_planning` job）。"""
    with session_factory() as session:
        compile_jobs = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == "development_compile")
            .count()
        )
    return {
        "compile_jobs": compile_jobs,
        "milestones": len(relationship_milestone_repository.list_milestones(user_id)),
        "insights": _count(session_factory, InsightRow),
        "actions": _count(session_factory, ActionRecordRow),
        "plans": _count(session_factory, BackgroundJobRow)
        - len(planning_jobs(session_factory)),
        "registry": registry_snapshot(),
    }


def _effect_delta(before: dict, after: dict) -> dict:
    """两次快照之间的**增量**（I6 的对照口径）。

    上表是累计计数：直接对照「第 1 次通知后」与「第 2 次通知后」的绝对值，比的是
    「一次累计」与「两次累计」——口径不同（既有三消费者按 `insight_id` 入队，逐次通知
    天然累加，属既有语义）。I6 要钉住的是「新增第四个消费者后，**一次通知**造成的副作用
    与新增前逐项相同」，故按增量对照；工具注册表快照按「逐字节未变」对照（非计数）。
    """
    delta = {key: after[key] - before[key] for key in EFFECT_COUNTERS}
    delta["registry_unchanged"] = after["registry"] == before["registry"]
    return delta


def _install_consumer_spies(recorded: list):
    def _spy(name, consumer):
        def _call(user_id, created):
            recorded.append(
                (
                    name,
                    user_id,
                    [
                        {key: value for key, value in item.items() if key != "insight_id"}
                        for item in created
                    ],
                )
            )
            return consumer(user_id, created)

        return _call

    for name, consumer in PLAN_CONSUMERS:
        reflection_lifecycle.register_insight_created_listener(_spy(name, consumer))


class TestExistingConsumersRegression:
    """I6：注册顺序、调用参数、副作用三层对照——新增第四消费者不改前三者。"""

    def test_i6_registration_order_is_unchanged(self, plan_reflection_on):
        reflection_lifecycle.reset_insight_created_listeners()
        for _name, consumer in PLAN_CONSUMERS:
            reflection_lifecycle.register_insight_created_listener(consumer)
        listener_mod.register_runtime()
        registered = list(reflection_lifecycle._insight_created_listeners)
        assert registered[:3] == [consumer for _name, consumer in PLAN_CONSUMERS]
        assert registered[3] == listener_mod.on_insight_created
        assert len(registered) == 4

    def test_i6_call_args_and_effects_are_identical(
        self, db_session_factory, plan_reflection_on
    ):
        """一次通知的调用参数与副作用，在第四个消费者注册前后逐项相同。

        两次通知的 Insight id 不同（`ins-reg-a` / `ins-reg-b`），故「调用参数相同」按
        去 id 后的载荷对照、「副作用相同」按**增量**对照（见 `_effect_delta`）。
        """
        recorded: list = []
        _install_consumer_spies(recorded)
        before = _consumer_effects(db_session_factory)
        reflection_lifecycle.notify_insight_created_listeners(
            USER, [insight_item("ins-reg-a", **CONSUMER_INSIGHT)]
        )
        baseline = (
            list(recorded),
            _effect_delta(before, _consumer_effects(db_session_factory)),
        )
        assert [name for name, _user_id, _items in baseline[0]] == [
            name for name, _consumer in PLAN_CONSUMERS
        ]

        recorded.clear()
        listener_mod.register_runtime()
        before_second = _consumer_effects(db_session_factory)
        reflection_lifecycle.notify_insight_created_listeners(
            USER, [insight_item("ins-reg-b", **CONSUMER_INSIGHT)]
        )
        after = (
            list(recorded),
            _effect_delta(before_second, _consumer_effects(db_session_factory)),
        )

        assert after[0] == baseline[0]
        assert after[1] == baseline[1]
        assert after[1]["registry_unchanged"] is True
        assert after[1]["compile_jobs"] == 1
        assert after[1]["plans"] == 2
        assert after[1]["milestones"] == after[1]["insights"] == after[1]["actions"] == 0

    def test_i6_consumers_do_not_see_plan_specific_payload(self, plan_reflection_on):
        payload = insight_item("ins-reg-c", **CONSUMER_INSIGHT)
        assert set(payload) == {"insight_id", "type", "scope", "confidence", "statement"}
        assert "evidence_refs" not in payload

    def test_i10_reflection_stays_in_the_background_step(self):
        settings = get_settings()
        assert settings.v25_plan_reflection_enabled is False
        from app.application import life_loop

        source = life_loop.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        assert "_step_reflection_check" in text
        assert "aggregate_plan_evidence" not in text


class TestNoPersonalityInsight:
    """I11：计划证据窗只产能力 / 模式类认知，结构上不产性格类 Insight。"""

    def test_i11_plan_window_types_exclude_personality_kinds(self):
        allowed = {
            kind for kinds in reflection_evidence.PLAN_WINDOW_ALLOWED_INSIGHTS.values()
            for kind in kinds
        }
        assert allowed == {"capability_note", "pattern", "usage_preference"}
        assert allowed.isdisjoint({"belief", "preference", "interaction_calibration"})

    def test_i11_reflector_rejects_a_personality_draft_on_a_plan_window(
        self, db_session_factory, plan_reflection_on
    ):
        seed_success_rate_series()
        window = reflection_evidence.aggregate_plan_evidence(USER, now=NOW).windows[0]
        draft = SimpleNamespace(
            evidence_ids=["E1", "E2", "E3"],
            statement="我是个内向的人",
            type="belief",
            scope="user",
            counter_evidence="无",
        )
        reasons = reflector._review_draft(
            draft,
            resolved=["plan:g:1:1", "plan:g:1:2", "plan:g:1:3"],
            invalid=[],
            final=0.9,
            settings=get_settings(),
            allowed_types=window.insight_types,
        )
        assert reflector._REVIEW_TYPE_NOT_ALLOWED in reasons

    def test_i11_reflector_rejects_a_relationship_scope_draft(
        self, db_session_factory, plan_reflection_on
    ):
        seed_success_rate_series()
        window = reflection_evidence.aggregate_plan_evidence(USER, now=NOW).windows[0]
        draft = SimpleNamespace(
            evidence_ids=["E1", "E2", "E3"],
            statement="我们的关系变近了",
            type="pattern",
            scope="relationship",
            counter_evidence="无",
        )
        reasons = reflector._review_draft(
            draft,
            resolved=["plan:g:1:1", "plan:g:1:2", "plan:g:1:3"],
            invalid=[],
            final=0.9,
            settings=get_settings(),
            allowed_types=window.insight_types,
        )
        assert reflector._REVIEW_SCOPE_NOT_ALLOWED in reasons

    def test_i11_plan_windows_declare_the_existing_type_gate_machinery(self):
        source = (
            reflection_evidence.__file__
        )
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        assert "insight_types=PLAN_WINDOW_ALLOWED_INSIGHTS.get(kind, ())" in text
        assert "TOOL_INSIGHT_SCOPES" not in text.split("# --- PLAN-010", 1)[1]


class TestFlagOffRegression:
    """I13 / S10：子闸 off → 证据聚合只有两通道、无监听器、行为与 V2.4.0 一致。"""

    def test_i13_no_plan_reads_when_the_sub_flag_is_off(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(v2_reflection_enabled="true", v25_plan_reflection_enabled="false")

        def _boom(*args, **kwargs):
            raise AssertionError("子闸 off 时不得读取计划数据")

        monkeypatch.setattr(goal_repository, "list_active_plans", _boom)
        monkeypatch.setattr(action_repository, "list_records", _boom)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.windows == []
        assert package.steps == 0 and package.executions == 0
        assert reflection_evidence.aggregate_evidence_windows(USER, now=NOW) == []

    def test_i13_no_listener_is_registered_when_off(
        self, db_session_factory, override_settings
    ):
        override_settings(v2_reflection_enabled="true", v25_plan_reflection_enabled="false")
        reflection_lifecycle.reset_insight_created_listeners()
        listener_mod.register_runtime()
        assert reflection_lifecycle._insight_created_listeners == []

    def test_i13_prompt_bytes_are_unchanged_with_the_plan_gates_off(
        self, db_session_factory, make_goal, autonomy_on, stub_planning_llm, override_settings
    ):
        override_settings(v25_plan_reflection_enabled="false")
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        goal = make_goal(description="prompt 快照目标", priority=4, domain="relationship")
        assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)["status"] == "ok"
        assert _digest(recorder["messages"]) == FROZEN_PROMPT_DIGEST
        assert json.loads(recorder["messages"][1][1]).get("evidence_refs") is None

    def test_i13_plan_window_insight_types_are_not_consulted_when_off(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(v2_reflection_enabled="true", v25_plan_reflection_enabled="false")
        probe_calls = []
        original = reflection_evidence.plan_evidence_enabled

        def _probe(settings=None):
            probe_calls.append(True)
            return original(settings)

        monkeypatch.setattr(reflection_evidence, "_plan_channel_windows", lambda *a: [])
        monkeypatch.setattr(
            reflection_evidence, "aggregate_plan_evidence", lambda *a, **k: pytest.fail("off 时不得聚合计划窗")
        )
        assert reflection_evidence.aggregate_evidence_windows(USER, now=NOW) == []


class TestEndToEndLoop:
    """S1 / S6 / S8：执行结果 → 证据窗 → Insight → 重规划触发（闭环）。"""

    def test_s1_plan_evidence_becomes_an_insight_and_triggers_a_replan(
        self,
        db_session_factory,
        plan_reflection_on,
        scripted_reflection_llm,
    ):
        goal, plan = seed_success_rate_series()
        reflection_lifecycle.reset_insight_created_listeners()
        listener_mod.register_runtime()

        assert triggers.trigger_for_user(USER, now=NOW) == triggers.OUTCOME_QUEUED
        assert reflector.run_queued_reflections(now=NOW) == 1
        rows = _insight_rows(db_session_factory)
        assert len(rows) == 1
        insight = rows[0]
        assert insight.type == "capability_note"
        assert insight.scope == "user"
        assert insight.confidence >= get_settings().v25_plan_replan_min_confidence
        assert scripted_reflection_llm.calls == 1

        jobs = planning_jobs(db_session_factory)
        assert [job.payload["trigger"] for job in jobs] == [
            goal_planning.TRIGGER_REPLAN
        ]
        assert listener_mod.evidence_refs_for(goal.id) == (insight.id,)
        assert plan.id in [
            item.id for item in goal_repository.list_plans(goal.id)
        ]

    @pytest.mark.asyncio
    async def test_s1_next_round_carries_the_insight_into_the_prompt(
        self, db_session_factory, plan_reflection_on, stub_planning_llm
    ):
        goal, _plan = seed_success_rate_series()
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-loop") is True
        refs = listener.evidence_refs_for(goal.id)
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        outcome = await _run_engine(goal, refs)
        assert outcome.plan.evidence_refs == ("ins-loop",)
        constraints = json.loads(recorder["messages"][1][1])
        assert constraints["evidence_refs"] == ["ins-loop"]

    def test_s1_context_digest_covers_the_evidence_refs(
        self, db_session_factory, plan_reflection_on
    ):
        goal, _plan = seed_success_rate_series()
        baseline = plan_context.context_digest(_context(goal, []))
        with_refs = plan_context.context_digest(_context(goal, ["ins-x"]))
        assert baseline != with_refs

    def test_s6_insight_driven_never_fires_when_the_type_is_out_of_scope(
        self, db_session_factory, plan_reflection_on
    ):
        goal, _plan = seed_success_rate_series()
        listener = listener_mod.PlanningRevisionListener()
        listener.on_insight_created(
            USER, [insight_item("ins-s6", insight_type="interaction_calibration", confidence=0.99)]
        )
        assert planning_jobs(db_session_factory) == []
        listener.on_insight_created(
            USER, [insight_item("ins-s6b", insight_type="pattern", confidence=0.99)]
        )
        assert [job.payload["goal_id"] for job in planning_jobs(db_session_factory)] == [
            goal.id
        ]

    def test_s8_isolation_after_the_whole_loop(
        self, db_session_factory, plan_reflection_on
    ):
        goal, plan = seed_success_rate_series()
        before = (
            goal_repository.get_goal(goal.id).model_dump(mode="json"),
            goal_repository.get_latest_plan(goal.id).model_dump(mode="json"),
            registry_snapshot(),
            _count(db_session_factory, ActionRecordRow),
        )
        listener = listener_mod.PlanningRevisionListener()
        assert listener.enqueue_replan(goal.id, "ins-s8") is True
        after = (
            goal_repository.get_goal(goal.id).model_dump(mode="json"),
            goal_repository.get_latest_plan(goal.id).model_dump(mode="json"),
            registry_snapshot(),
            _count(db_session_factory, ActionRecordRow),
        )
        assert before == after
        assert len(planning_jobs(db_session_factory)) == 1
        assert plan.status == "active"

    def test_s10_flag_off_loop_stays_silent(
        self, db_session_factory, override_settings, scripted_reflection_llm
    ):
        from .plan010_support import plan_reflection_env

        plan_reflection_env(override_settings)
        override_settings(v25_plan_reflection_enabled="false")
        seed_success_rate_series()
        reflection_lifecycle.reset_insight_created_listeners()
        listener_mod.register_runtime()
        assert triggers.trigger_for_user(USER, now=NOW) == triggers.OUTCOME_SKIPPED
        assert _count(db_session_factory, ReflectionRunRow) == 1
        assert scripted_reflection_llm.calls == 0
        assert planning_jobs(db_session_factory) == []


class TestFrozenSurfaces:
    """§10.2：既有面零改动（计划面九函数 / 反思闸门 / 三个既有消费者文件）。"""

    def test_plan_repository_face_keeps_its_nine_functions(self):
        """计划面九函数零改动（PLAN-010 冻结）。

        PLAN-011 契约演进留痕：本类原以 `not hasattr(goal_repository,
        "list_terminal_plans_since")` 钉住「PLAN-011 的只读扩展今日不存在」；该扩展已落地
        （Task Detail §6.1 的三个只读函数），故翻转为**正向 + 计数**断言——九函数仍逐条可调用，
        新增的恰好是那三个只读扩展（不多不少）。
        """
        for name in (
            "create_plan",
            "get_plan",
            "get_latest_plan",
            "list_plans",
            "count_plans",
            "set_plan_status",
            "set_plan_rejection",
            "update_plan_progress",
            "list_active_plans",
        ):
            assert callable(getattr(goal_repository, name)), name
        assert goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS[16:] == (
            "list_plans_by_status",
            "count_plan_versions",
            "list_terminal_plans_since",
        )
        assert callable(goal_repository.list_terminal_plans_since)

    def test_trigger_gate_helpers_are_frozen(self):
        assert triggers.OUTCOME_QUEUED == "queued"
        assert triggers.OUTCOME_SKIPPED == "skipped"
        assert triggers.OUTCOME_QUOTA == "quota"
        assert triggers.OUTCOME_OFF == "off"
        assert triggers.JOB_TYPE_REFLECTION_RUN == "reflection_run"

    def test_reflector_review_reason_codes_are_frozen(self):
        assert reflector._REVIEW_TYPE_NOT_ALLOWED == "insight_type_not_allowed"
        assert reflector._REVIEW_SCOPE_NOT_ALLOWED == "insight_scope_not_allowed"
        assert reflector._REVIEW_BELOW_MIN == "evidence_below_min"
        assert reflector._CONFIDENCE_CEILING == 0.95

    def test_plan_evidence_helper_is_not_shadowed_by_a_second_namespace(self):
        assert reflection_evidence.PLAN_EVIDENCE_NAMESPACE == "plan"
        assert reflection_evidence.PLAN_STEP_EVIDENCE_PREFIX == "plan:"
        assert (
            reflection_evidence.PLAN_WINDOW_KINDS
            == reflection_evidence.PLAN_WINDOW_PRIORITY
        )

    def test_prompt_digest_helper_is_reused_from_the_frozen_snapshot(self):
        assert len(FROZEN_PROMPT_DIGEST) == 64
        assert (
            hashlib.sha256(
                json.dumps([["system", "x"], ["human", "y"]], ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest()
            == _digest([("system", "x"), ("human", "y")])
        )


def _context(goal, evidence_refs):
    from app.models.plan import PlanContext
    from app.models.tool import ToolSurface

    return PlanContext(
        goal=goal,
        tool_surface=ToolSurface(run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=(TOOL_REMINDER,)),
        budget=plan_context.plan_budget(get_settings()),
        evidence_refs=list(evidence_refs),
    )


async def _run_engine(goal, evidence_refs):
    """引擎调用走 pytest-asyncio 的逐用例事件循环（本模块其余用例同为 async）。

    不用 `asyncio.get_event_loop()`：同一 worker 内其他用例（或 `asyncio.run`）关闭并
    解绑过事件循环后，该入口在 3.13 会直接抛 `RuntimeError`——那是用例宿主的进程级
    状态问题，与被测语义无关。
    """
    return await plan_engine.PlanningEngine().plan(
        goal, _context(goal, evidence_refs), trigger=goal_planning.TRIGGER_REPLAN
    )


def _insight_rows(session_factory) -> list:
    with session_factory() as session:
        rows = session.query(InsightRow).filter(InsightRow.user_id == USER).all()
        for row in rows:
            session.expunge(row)
        return list(rows)
