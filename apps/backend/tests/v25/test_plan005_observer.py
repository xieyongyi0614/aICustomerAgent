"""PLAN-005 Step 4 / Step 5：观测与终态结算（四源事实 / 判据求值 / 推进裁决 / 单一写面）。

覆盖 Task Detail §9.1 U11~U13、U17 与 §9.2 I5、I6、I13（Flag off 的判据面）。
静态红线（零 world 写面 / 零直调工具执行）见 `test_plan005_static_scan.py`。
"""

import pytest

from app.application import observability
from app.models.goal import CRITERION_FACT_SOURCES, CRITERION_METRIC_PATHS
from app.models.observability import DecisionKind
from app.models.plan import PLAN_ADVANCE_TERMINAL_DECISIONS, PlanAdvance
from app.repositories import action_repository, goal_repository
from app.services import goal_observation
from app.services.planning import observer as observer_mod
from app.services.planning.observer import (
    FACT_SOURCE_MEMORY,
    FACT_SOURCE_STATE,
    FACT_SOURCE_TOOL,
    FACT_SOURCE_WORLD,
    ObservationContext,
    PlanObserver,
)

from . import plan005_support as support
from .conftest import V25_NOW

USER = support.USER_ID
OBSERVER = PlanObserver()

TOOL_STEP = {
    "index": 1,
    "description": "推送提醒",
    "capability": "create_reminder",
    "params": {"content": "该休息了"},
    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    "tool_id": support.REMINDER_CREATE,
    "observation_keys": ["reminder_id"],
}


@pytest.fixture
def observation_on(override_settings):
    """观测用例的既有 Flag 组合（本任务零新增 Flag：门控全用既有自治闸与 PLAN-002 子闸）。"""
    override_settings(
        observability_persist_enabled="false")


def _ctx(*, now=V25_NOW, goal_id=None):
    return ObservationContext(now=now, goal_id=goal_id)


class TestEvaluate:
    """U11 / D10：不可判定一律 `None`（**绝不默认 `True`**）+ 委托既有求值器。"""

    def test_delegates_to_the_existing_evaluator(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            observer_mod.goal_observation,
            "evaluate_criteria",
            lambda criteria, facts: (calls.append(criteria), True)[1],
        )
        assert OBSERVER.evaluate({"type": "action_succeeded", "capability": "x"}, {}) is True
        assert calls == [{"type": "action_succeeded", "capability": "x"}]

    def test_threshold_over_the_tool_source_is_not_supported(self, monkeypatch):
        """Q4 冻结：`threshold_reached` + `source="tool"` 不支持——即便委托会返回 True 也不采用。"""
        monkeypatch.setattr(
            observer_mod.goal_observation, "evaluate_criteria", lambda criteria, facts: True
        )
        criteria = {
            "type": "threshold_reached",
            "source": FACT_SOURCE_TOOL,
            "path": "count",
            "op": ">=",
            "value": 1,
        }
        assert OBSERVER.evaluate(criteria, {FACT_SOURCE_TOOL: {"count": 5}}) is None

    def test_nested_tool_threshold_is_also_refused(self, monkeypatch):
        monkeypatch.setattr(
            observer_mod.goal_observation, "evaluate_criteria", lambda criteria, facts: True
        )
        criteria = {
            "type": "all_of",
            "children": [
                {"type": "action_succeeded", "capability": "create_reminder"},
                {
                    "type": "threshold_reached",
                    "source": FACT_SOURCE_TOOL,
                    "path": "count",
                    "op": ">=",
                    "value": 1,
                },
            ],
        }
        assert OBSERVER.evaluate(criteria, {}) is None

    def test_undeclared_tool_key_is_undecidable(self):
        criteria = {
            "type": "field_equals",
            "source": FACT_SOURCE_TOOL,
            "path": "never_declared",
            "value": "ok",
        }
        assert OBSERVER.evaluate(criteria, {FACT_SOURCE_TOOL: {"declared": "ok"}}) is None

    def test_unknown_criterion_type_is_undecidable(self):
        assert OBSERVER.evaluate({"type": "not_a_type"}, {}) is None

    def test_threshold_over_a_supported_source_still_works(self):
        criteria = {
            "type": "threshold_reached",
            "source": FACT_SOURCE_STATE,
            "path": "tension",
            "op": ">=",
            "value": 0.5,
        }
        assert OBSERVER.evaluate(criteria, {FACT_SOURCE_STATE: {"tension": 0.8}}) is True
        assert OBSERVER.evaluate(criteria, {FACT_SOURCE_STATE: {"tension": 0.2}}) is False

    def test_fourth_criterion_source_is_the_plan_002_freeze(self):
        assert CRITERION_FACT_SOURCES == ("world", "state", "memory", "tool")


class TestCollectFacts:
    """U12 / U13：四源两态 + `tool` 源键受白名单约束。"""

    def test_world_source_available_and_unavailable(self, observation_on, monkeypatch):
        monkeypatch.setattr(
            observer_mod, "_world_facts", lambda settings, user_id: {"part_of_day": "noon"}
        )
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert facts[FACT_SOURCE_WORLD] == {"part_of_day": "noon"}
        monkeypatch.setattr(observer_mod, "_world_facts", lambda settings, user_id: {})
        assert OBSERVER.collect_facts(USER, _ctx(), observation_keys=())[FACT_SOURCE_WORLD] == {}

    def test_state_source_available_and_unavailable(self, observation_on, monkeypatch):
        monkeypatch.setattr(
            observer_mod,
            "_state_facts",
            lambda user_id: {"tension": 0.2, "intimacy": 0.5, "mood": "calm", "intensity": 0.4},
        )
        assert OBSERVER.collect_facts(USER, _ctx(), observation_keys=())[FACT_SOURCE_STATE][
            "mood"
        ] == "calm"
        monkeypatch.setattr(observer_mod, "_state_facts", lambda user_id: {})
        assert OBSERVER.collect_facts(USER, _ctx(), observation_keys=())[FACT_SOURCE_STATE] == {}

    def test_memory_source_available_and_unavailable(self, observation_on, monkeypatch):
        monkeypatch.setattr(
            observer_mod,
            "_memory_facts",
            lambda settings, user_id: ({"salient_memory_count": 2}, ["m1", "m2"]),
        )
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert facts[FACT_SOURCE_MEMORY] == {"salient_memory_count": 2}
        assert facts[observer_mod.FACT_SALIENT_MEMORIES] == ["m1", "m2"]
        monkeypatch.setattr(
            observer_mod, "_memory_facts", lambda settings, user_id: ({}, [])
        )
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert facts[FACT_SOURCE_MEMORY] == {}
        assert observer_mod.FACT_SALIENT_MEMORIES not in facts

    def test_legacy_projection_keys_are_preserved(self, observation_on):
        """既有消费面（`goal_observation` / `goal_arbitration`）依赖的键一个不少。"""
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert set(facts) == {
            "now",
            "world",
            "state",
            "memory",
            "action_results",
            "action_history",
            FACT_SOURCE_TOOL,
            observer_mod.FACT_TOOL_RESULTS,
        }
        assert facts["now"] == V25_NOW

    def test_explicit_empty_whitelist_skips_the_plan_read(
        self, observation_on, monkeypatch
    ):
        """显式空白名单 + 无目标 → 不装配 `tool` 源，零额外读取（Flag off 兼容路径）。"""
        calls: list = []
        monkeypatch.setattr(
            observer_mod.goal_repository,
            "list_active_plans",
            lambda user_id: calls.append(user_id) or [],
        )
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert calls == []
        assert facts[FACT_SOURCE_TOOL] == {}

    def test_tool_source_is_clipped_by_the_declared_keys(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=USER, description="工具事实源")
        make_plan(goal.id, [dict(TOOL_STEP)])
        action_repository.save_record(
            support.action_record(
                user_id=USER,
                goal_id=goal.id,
                dedupe_key=f"plan:{goal.id}:1:1",
                steps=[support.tool_step({"reminder_id": "ev-1", "internal": "x"})],
            )
        )
        facts = OBSERVER.collect_facts(USER, _ctx())
        assert facts[FACT_SOURCE_TOOL] == {"reminder_id": "ev-1"}
        assert "internal" not in facts[FACT_SOURCE_TOOL]
        assert facts[observer_mod.FACT_TOOL_RESULTS] == [
            {
                "capability": "create_reminder",
                "status": "succeeded",
                "tool_id": support.REMINDER_CREATE,
                "action_id": "action-1",
                "at": support.NOW,
            }
        ]

    def test_other_goals_ledger_never_leaks_in(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=USER, description="本目标")
        make_plan(goal.id, [dict(TOOL_STEP)])
        action_repository.save_record(
            support.action_record(
                user_id=USER,
                goal_id="other-goal",
                dedupe_key="plan:other-goal:1:1",
                steps=[support.tool_step({"reminder_id": "ev-other"})],
            )
        )
        facts = OBSERVER.collect_facts(USER, _ctx())
        assert facts[FACT_SOURCE_TOOL] == {}

    def test_goal_scoped_context_narrows_the_ledger(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        first = make_goal(user_id=USER, description="目标甲")
        second = make_goal(user_id=USER, description="目标乙")
        make_plan(first.id, [dict(TOOL_STEP)])
        make_plan(second.id, [dict(TOOL_STEP)])
        action_repository.save_record(
            support.action_record(
                user_id=USER,
                goal_id=second.id,
                dedupe_key=f"goal:{second.id}:1:1",
                steps=[support.tool_step({"reminder_id": "ev-2"})],
            )
        )
        scoped = OBSERVER.collect_facts(USER, _ctx(goal_id=second.id))
        assert scoped[FACT_SOURCE_TOOL] == {"reminder_id": "ev-2"}
        assert OBSERVER.collect_facts(USER, _ctx(goal_id=first.id))[FACT_SOURCE_TOOL] == {}

    def test_tool_field_equals_is_decidable_end_to_end(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=USER, description="工具判据端到端")
        make_plan(goal.id, [dict(TOOL_STEP)])
        action_repository.save_record(
            support.action_record(
                user_id=USER,
                goal_id=goal.id,
                dedupe_key=f"plan:{goal.id}:1:1",
                steps=[support.tool_step({"reminder_id": "ev-1"})],
            )
        )
        facts = OBSERVER.collect_facts(USER, _ctx())
        criteria = {
            "type": "field_equals",
            "source": FACT_SOURCE_TOOL,
            "path": "reminder_id",
            "value": "ev-1",
        }
        assert OBSERVER.evaluate(criteria, facts) is True
        assert (
            OBSERVER.evaluate(dict(criteria, value="ev-404"), facts) is False
        )

    def test_action_succeeded_reads_the_step_level_status(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        goal = make_goal(user_id=USER, description="步级状态判据")
        make_plan(goal.id, [dict(TOOL_STEP)])
        action_repository.save_record(
            support.action_record(
                user_id=USER,
                goal_id=goal.id,
                status="succeeded",
                dedupe_key=f"plan:{goal.id}:1:1",
                steps=[support.tool_step({})],
            )
        )
        facts = OBSERVER.collect_facts(USER, _ctx())
        assert facts["action_results"][0]["status"] == "succeeded"
        assert (
            OBSERVER.evaluate(
                {"type": "action_succeeded", "capability": "create_reminder"}, facts
            )
            is True
        )

    def test_step_level_and_record_level_agree_on_the_succeeded_judgement(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        """两个投影的等价性举证：记录级 succeeded ⇔ 步级 succeeded（其余一律非 succeeded）。"""
        goal = make_goal(user_id=USER, description="投影等价")
        make_plan(goal.id, [dict(TOOL_STEP)])
        cases = (
            ("succeeded", "succeeded"),
            ("failed", "failed"),
            ("cancelled", "skipped"),
            ("cancelled", None),
        )
        for index, (record_status, step_status) in enumerate(cases):
            record = support.action_record(
                user_id=USER,
                goal_id=goal.id,
                record_id=f"action-{index}",
                status=record_status,
                dedupe_key=f"plan:{goal.id}:1:{index + 1}",
                steps=[] if step_status is None else [support.tool_step({}, status=step_status)],
            )
            assert (record_status == "succeeded") == (
                (record.steps[0]["status"] if record.steps else record_status) == "succeeded"
            )

    def test_state_projection_carries_every_metric_path(self, observation_on, monkeypatch):
        monkeypatch.setattr(
            observer_mod,
            "_state_facts",
            lambda user_id: {path: 0.5 for path in CRITERION_METRIC_PATHS} | {"intensity": 0.3},
        )
        facts = OBSERVER.collect_facts(USER, _ctx(), observation_keys=())
        assert set(CRITERION_METRIC_PATHS) <= set(facts[FACT_SOURCE_STATE])
        assert CRITERION_METRIC_PATHS == ("tension", "intimacy", "mood", "salient_memory_count")


class TestObserve:
    """`observe` 的六值归一 + 观测故障隔离（U17 / D13）。"""

    @staticmethod
    def _advance(detail, monkeypatch):
        monkeypatch.setattr(
            observer_mod.goal_observation, "advance_goal", lambda goal, plan, facts, now: detail
        )
        goal = support.goal()
        plan = support.plan([support.spec(1)])
        return OBSERVER.observe(goal, plan, {}, now=V25_NOW)

    def test_decision_mapping_is_the_declared_normalisation(self, monkeypatch):
        mapping = {
            "advanced": "advanced",
            "completed": "completed",
            "failed": "failed",
            "replanning": "replanning",
            "skipped": "skipped",
            "skipped_ahead": "skipped",
            "retrying": "hold",
            "error": "hold",
        }
        for outcome, expected in mapping.items():
            advance = self._advance({"outcome": outcome}, monkeypatch)
            assert advance.decision == expected, outcome

    def test_unknown_outcome_degrades_to_hold(self, monkeypatch):
        assert self._advance({"outcome": "not_an_outcome"}, monkeypatch).decision == "hold"

    def test_reported_reason_is_reused_and_capped(self, monkeypatch):
        advance = self._advance(
            {"outcome": "failed", "reason": "exec_period_exceeded"}, monkeypatch
        )
        assert advance.reason == "exec_period_exceeded"
        long_reason = self._advance(
            {"outcome": "failed", "reason": "长" * 120}, monkeypatch
        )
        assert len(long_reason.reason) == 60

    def test_observation_error_is_logged_as_hold(self, monkeypatch):
        def _boom(goal, plan, facts, now):
            raise RuntimeError("观测故障")

        monkeypatch.setattr(observer_mod.goal_observation, "advance_goal", _boom)
        goal = support.goal()
        plan = support.plan([support.spec(1)])
        advance = OBSERVER.observe(goal, plan, {}, now=V25_NOW)
        assert advance.decision == "hold"
        assert advance.reason == observer_mod.REASON_OBSERVATION_ERROR

    def test_facts_digest_carries_no_content(self, monkeypatch):
        monkeypatch.setattr(
            observer_mod.goal_observation,
            "advance_goal",
            lambda goal, plan, facts, now: {"outcome": "advanced", "criteria_result": True},
        )
        goal = support.goal()
        plan = support.plan([support.spec(1)])
        advance = OBSERVER.observe(goal, plan, {"now": V25_NOW}, now=V25_NOW)
        assert advance.facts_digest["outcome"] == "advanced"
        assert advance.facts_digest["criteria_result"] is True
        assert advance.facts_digest["at"] == V25_NOW.isoformat()
        assert "secret" not in str(advance.facts_digest)

    def test_digest_records_sample_keys_only(self, monkeypatch):
        monkeypatch.setattr(
            observer_mod.goal_observation,
            "advance_goal",
            lambda goal, plan, facts, now: {"outcome": "advanced"},
        )
        goal = support.goal()
        plan = support.plan([support.spec(1)])
        facts = {FACT_SOURCE_TOOL: {"reminder_id": "ev-secret"}, FACT_SOURCE_STATE: {"mood": "x"}}
        advance = OBSERVER.observe(goal, plan, facts, now=V25_NOW)
        assert advance.facts_digest["tool_keys"] == ["reminder_id"]
        assert "ev-secret" not in str(advance.facts_digest)
        assert advance.facts_digest["sources"] == ["state", "tool"]


class TestSettle:
    """I5 / I6 / D11 / D12：单一写面 + 归因一次 + 审计投影。"""

    @staticmethod
    def _advance(goal, plan, decision, reason="goal_completed"):
        return PlanAdvance(
            goal_id=goal.id,
            plan_id=plan.id,
            plan_version=plan.version,
            decision=decision,
            reason=reason,
            at=V25_NOW,
        )

    @staticmethod
    def _spy(monkeypatch) -> list:
        captured: list = []
        monkeypatch.setattr(
            observability, "on_decision", lambda record: captured.append(record)
        )
        return captured

    @staticmethod
    def _rows(captured, trigger):
        return [record for record in captured if record.trigger == trigger]

    def test_completed_settles_through_the_single_write_face(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="完成结算")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(
            goal, plan, self._advance(goal, plan, "completed")
        )
        assert settlement.transitioned is True
        assert settlement.goal_status == "completed"
        assert goal_repository.get_goal(goal.id).status == "completed"
        assert len(self._rows(captured, observer_mod.STEP_NAME)) == 1
        ids = {kind for kind in DecisionKind}
        assert len(ids) == 5

    def test_attribution_happens_exactly_once(self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch):
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="归因一次")
        plan = make_plan(goal.id)
        OBSERVER.settle(goal, plan, self._advance(goal, plan, "completed"))
        assertions = self._rows(captured, "goal_arbitration")
        assert len(assertions) == 1
        assert assertions[0].kind == DecisionKind.GOAL_LIFECYCLE
        assert assertions[0].decision == "completed"

    def test_already_settled_goal_is_not_attributed_twice(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="既有写面已结算")
        plan = make_plan(goal.id)
        goal_repository.complete_goal(goal.id)
        settlement = OBSERVER.settle(goal, plan, self._advance(goal, plan, "completed"))
        assert settlement.transitioned is False
        assert self._rows(captured, "goal_arbitration") == []
        assert len(self._rows(captured, observer_mod.STEP_NAME)) == 1

    def test_failed_settles_with_plan_exhausted(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="失败结算")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(
            goal,
            plan,
            self._advance(goal, plan, "failed", reason="plan_exhausted"),
        )
        assert settlement.transitioned is True
        reloaded = goal_repository.get_goal(goal.id)
        assert (reloaded.status, reloaded.failure_reason) == ("failed", "plan_exhausted")
        assert len(self._rows(captured, "goal_arbitration")) == 1

    def test_non_terminal_decisions_freeze_without_writing(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        for decision, reason in (
            ("advanced", "plan_step_advanced"),
            ("hold", "plan_step_hold"),
            ("replanning", "plan_replanning"),
            ("skipped", "plan_step_skipped"),
        ):
            captured = self._spy(monkeypatch)
            goal = make_goal(user_id=USER, description=f"冻结-{decision}")
            plan = make_plan(goal.id)
            settlement = OBSERVER.settle(
                goal, plan, self._advance(goal, plan, decision, reason=reason)
            )
            assert settlement.transitioned is False, decision
            assert goal_repository.get_goal(goal.id).status == "active", decision
            assert self._rows(captured, "goal_arbitration") == [], decision
            assert len(self._rows(captured, observer_mod.STEP_NAME)) == 1, decision

    def test_plan_advance_is_projectable_from_the_audit_row(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        """I6：`decision_records.input_snapshot` 可完整还原 `PlanAdvance`。"""
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="审计投影")
        plan = make_plan(goal.id)
        advance = self._advance(goal, plan, "advanced", reason="plan_step_advanced")
        OBSERVER.settle(goal, plan, advance)
        row = self._rows(captured, observer_mod.STEP_NAME)[0]
        assert row.kind == DecisionKind.GOAL_LIFECYCLE
        assert row.decision == "advanced"
        assert row.reason == "plan_step_advanced"
        assert PlanAdvance.model_validate(row.input_snapshot) == advance
        assert tuple(row.input_snapshot) == tuple(PlanAdvance.model_fields)

    def test_illegal_transition_is_logged_and_left_alone(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        captured = self._spy(monkeypatch)
        goal = make_goal(user_id=USER, description="非法迁移")
        plan = make_plan(goal.id)
        goal_repository.finish_goal(goal.id, "abandoned")
        settlement = OBSERVER.settle(goal, plan, self._advance(goal, plan, "failed"))
        assert settlement.transitioned is False
        assert goal_repository.get_goal(goal.id).status == "abandoned"
        assert self._rows(captured, "goal_arbitration") == []


class TestObserveUserGoals:
    """Step 8 的接线形态：返回形状与既有 `advance_user_goals` 兼容 + 终态结算计数。"""

    def test_empty_candidate_set(self, db_session_factory, observation_on):
        assert OBSERVER.observe_user_goals(USER, {}, now=V25_NOW) == {
            "status": "ok",
            "goals": 0,
            "results": [],
            "settled": 0,
        }

    def test_advances_and_settles_each_active_plan(
        self, db_session_factory, observation_on, make_goal, make_plan, goal_facts
    ):
        goal = make_goal(user_id=USER, description="编排入口")
        make_plan(goal.id)
        facts = goal_facts(succeeded=["create_reminder"])
        result = OBSERVER.observe_user_goals(USER, facts, now=V25_NOW)
        assert result["goals"] == 1
        assert result["settled"] == 1
        item = result["results"][0]
        assert item["outcome"] == "completed"
        assert item["observations"] == 1
        assert item["settled"] is True
        assert item["advance"]["decision"] == "completed"
        assert goal_repository.get_goal(goal.id).status == "completed"

    def test_retrying_step_stays_a_hold(
        self, db_session_factory, observation_on, make_goal, make_plan, goal_facts
    ):
        goal = make_goal(user_id=USER, description="未达成步")
        make_plan(goal.id)
        result = OBSERVER.observe_user_goals(USER, goal_facts(), now=V25_NOW)
        item = result["results"][0]
        assert item["outcome"] == "hold"
        assert item["settled"] is False
        assert goal_repository.get_goal(goal.id).status == "active"

    def test_observation_error_is_isolated_per_goal(
        self, db_session_factory, observation_on, make_goal, make_plan, monkeypatch
    ):
        goal = make_goal(user_id=USER, description="观测故障隔离")
        make_plan(goal.id)

        def _boom(goal_record, plan, facts, now):
            raise RuntimeError("观测故障")

        monkeypatch.setattr(observer_mod.goal_observation, "advance_goal", _boom)
        result = OBSERVER.observe_user_goals(USER, {}, now=V25_NOW)
        assert result["results"][0]["observations"] == 0
        assert result["results"][0]["outcome"] == "hold"
        assert result["settled"] == 0
        assert goal_repository.get_goal(goal.id).status == "active"

    def test_skipped_ahead_is_frozen_even_though_it_is_terminal(
        self, db_session_factory, observation_on, make_goal, make_plan
    ):
        """`skipped` 在 PLAN-002 的终态集内（不再推进本版本），但**不是目标终态**：冻结不写。"""
        goal = make_goal(user_id=USER, description="跳步不结算")
        make_plan(
            goal.id,
            [
                {
                    "index": 1,
                    "description": "步骤1",
                    "capability": "create_reminder",
                    "params": {},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                    "status": "in_progress",
                    "attempt_count": 2,
                },
                {
                    "index": 2,
                    "description": "步骤2",
                    "capability": "create_reminder",
                    "params": {},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                },
            ],
        )
        result = OBSERVER.observe_user_goals(USER, {}, now=V25_NOW)
        item = result["results"][0]
        assert item["outcome"] == "skipped"
        assert "skipped" in PLAN_ADVANCE_TERMINAL_DECISIONS
        assert item["settled"] is False
        assert goal_repository.get_goal(goal.id).status == "active"

    def test_existing_observation_entry_point_is_untouched(self, db_session_factory, observation_on):
        """Flag off 时既有入口仍在（`advance_user_goals` 零改动）。"""
        assert goal_observation.advance_user_goals(USER, {}, V25_NOW) == {
            "status": "ok",
            "goals": 0,
            "results": [],
        }
