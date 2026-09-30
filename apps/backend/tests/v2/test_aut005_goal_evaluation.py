"""AUT-005 Goal 评估规则测试。

GoalSlice 采集口径、六条规则正反例（一致性归因/完成失败放弃语义/仲裁留痕/
规划预算/执行封顶/供给形状）、offline_evaluator goal 小节、维度映射。
"""

from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.evaluation import EvaluationDimension, IssueCode
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.repositories import goal_repository
from app.services.goal import arbitration as goal_arbitration
from app.services.evaluation.context import collect_goal_slice
from app.services.evaluation.rules import run_rules
from app.services.evaluation.rules.goal import RULES

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER = "aut5-user"


@pytest.fixture()
def aut_on(override_settings, monkeypatch):
    override_settings(
        observability_persist_enabled="false")
    monkeypatch.setattr(
        "app.services.goal.arbitration.development_aggregate.read_overlay",
        lambda user_id, character_id="asuna": None,
    )
    yield


def _goal(layer="long_term", domain="personal", description="评估目标", priority=3, **kwargs):
    return goal_repository.create_hierarchical_goal(
        USER, layer, domain, description, priority, **kwargs
    )


def _plan(goal_id, version=1, status="active", specs=None, updated_at=NOW):
    return goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=[SubGoalSpec.model_validate(item) for item in (specs or [])],
            created_at=NOW,
            updated_at=updated_at,
        )
    )


def _done_spec(index=1, capability="create_reminder"):
    spec = SubGoalSpec.model_validate(
        {
            "index": index,
            "description": f"步骤{index}",
            "capability": capability,
            "params": {},
            "criteria": {"type": "action_succeeded", "capability": capability},
        }
    )
    spec.status = "done"
    return spec


def _ctx(slice_):
    from app.services.evaluation.context import EvaluationContext

    return EvaluationContext(
        subject="goal",
        subject_id="batch",
        session_id="",
        user_id=USER,
        goal=slice_,
    )


def _issues(slice_):
    return {issue.code for issue in run_rules(_ctx(slice_), get_settings())}


class TestSliceCollection:
    def test_collect_goal_slice_shape(self, db_session_factory, aut_on):
        goal = _goal()
        _plan(goal.id, specs=[_done_spec(1)])
        slice_ = collect_goal_slice(USER, now=NOW)
        assert len(slice_.goals) == 1
        assert slice_.goals[0].horizon == "persistent"
        assert len(slice_.plans) == 1
        assert slice_.plans[0].capabilities == ["create_reminder"]

    def test_slice_excludes_v1_rows(self, db_session_factory, aut_on):
        from tests.v2.test_aut001_goal_hierarchy import _v1_record

        goal_repository.create_goal(_v1_record())
        slice_ = collect_goal_slice(USER, now=NOW)
        assert slice_.goals == []


class TestRules:
    def test_terminal_without_lifecycle_flagged(self, db_session_factory, aut_on):
        goal = _goal()
        goal_repository.complete_goal(goal.id)
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_INCONSISTENT_STATE in issues

    def test_terminal_with_lifecycle_passes(self, db_session_factory, aut_on, monkeypatch):
        import app.application.observability as observability

        monkeypatch.setattr(
            observability, "on_decision", lambda record: None
        )
        goal = _goal()
        _plan(goal.id, specs=[_done_spec(1)])
        slice_before = collect_goal_slice(USER, now=NOW)
        plan_ref = slice_before.plans[0]
        plan_ref.sub_goal_statuses = ["done"]
        goal_arbitration._record_lifecycle(
            goal, "completed", "计划全 done", {"goal_id": goal.id}
        )
        slice_after = collect_goal_slice(USER, now=NOW)
        issues = _issues(slice_after)
        assert IssueCode.GOAL_INCONSISTENT_STATE not in issues
        assert IssueCode.GOAL_INVALID_TERMINATION not in issues

    def test_failed_without_reason_flagged(self, db_session_factory, aut_on, monkeypatch):
        import app.application.observability as observability

        monkeypatch.setattr(observability, "on_decision", lambda record: None)
        goal = _goal()
        goal_repository.set_status(goal.id, "failed")
        from app.core.db import GoalRow
        from app.repositories.goal_repository import SessionLocal

        with SessionLocal() as session:
            row = session.get(GoalRow, goal.id)
            row.failure_reason = None
            session.commit()
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_INVALID_TERMINATION in issues

    def test_suspended_without_arbitration_flagged(self, db_session_factory, aut_on):
        goal = _goal()
        goal_repository.set_status(goal.id, "suspended", None)
        slice_ = collect_goal_slice(USER, now=NOW)
        assert IssueCode.GOAL_ARBITRATION_MISSING in _issues(slice_)

    def test_same_domain_dual_active_flagged(self, db_session_factory, aut_on):
        _goal(description="甲", priority=5)
        _goal(description="乙", priority=2)
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_ARBITRATION_MISSING in issues

    def test_planning_budget_exceeded_flagged(self, db_session_factory, aut_on, override_settings):
        override_settings(autonomy_planning_max_attempts="2")
        goal = _goal()
        for version in range(1, 5):
            _plan(goal.id, version=version, status="rejected")
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_PLANNING_BUDGET_EXCEEDED in issues

    def test_execution_cap_exceeded_flagged(self, db_session_factory, aut_on, override_settings):
        override_settings(autonomy_goal_max_active_hours="1")
        goal = _goal()
        _plan(goal.id, specs=[_done_spec(1)], updated_at=NOW - timedelta(hours=48))
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_EXECUTION_CAP_EXCEEDED in issues

    def test_long_term_non_persistent_flagged(self, db_session_factory, aut_on):
        goal = _goal(layer="short_term", domain="world")
        from app.core.db import GoalRow
        from app.repositories.goal_repository import SessionLocal

        with SessionLocal() as session:
            row = session.get(GoalRow, goal.id)
            row.layer = "long_term"
            row.horizon = "current"
            session.commit()
        issues = _issues(collect_goal_slice(USER, now=NOW))
        assert IssueCode.GOAL_SUPPLY_MALFORMED in issues

    def test_clean_slice_passes_all(self, db_session_factory, aut_on, monkeypatch):
        import app.application.observability as observability

        monkeypatch.setattr(observability, "on_decision", lambda record: None)
        goal = _goal()
        _plan(goal.id, specs=[_done_spec(1)])
        slice_ = collect_goal_slice(USER, now=NOW)
        plan_ref = slice_.plans[0]
        plan_ref.sub_goal_statuses = ["done"]
        goal_arbitration._record_lifecycle(goal, "completed", "全 done", {"goal_id": goal.id})
        assert _issues(collect_goal_slice(USER, now=NOW)) == set()


class TestDimensionMapping:
    def test_goal_codes_map_to_goal_dimension(self):
        from app.models.evaluation import dimension_of

        for code in (
            IssueCode.GOAL_INCONSISTENT_STATE,
            IssueCode.GOAL_SUPPLY_MALFORMED,
        ):
            assert dimension_of(code) == EvaluationDimension.GOAL

    def test_goal_rules_registered(self):
        from app.services.evaluation.rules import RULES

        goal_codes = {rule.code for rule in RULES if rule.dimension == EvaluationDimension.GOAL}
        assert len(goal_codes) == 6


class TestOfflineStats:
    def test_goal_stats_section(self, db_session_factory, aut_on):
        from app.services.evaluation.offline import _goal_stats

        goal = _goal()
        _plan(goal.id, specs=[_done_spec(1)])
        stats = _goal_stats(USER)
        assert stats["goals_total"] == 1
        assert stats["plans_active"] == 1
        assert stats["terminal_attribution_rate"] is None
