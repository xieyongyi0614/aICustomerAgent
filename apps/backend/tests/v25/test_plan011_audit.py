"""PLAN-011 Step 2 / Step 3 单测：审计投影与修订链重建（§4.2.3 / §4.2.4 / §6.2）。

- D5 / I3：`kind` 恒为既有 `goal_lifecycle`；`DecisionKind` 仍五值（零新增 CHECK 值）。
- D6 / D7：`decision` 承载计划迁移名；`input_snapshot` 承载完整 `PlanAdvance` / 六字段。
- I2：可从 `decision_records` 正确投影 `PlanAdvance`（逐值可读、往返相等）。
- I4：修订链六字段（`from_version` / `to_version` / `reason` / `trigger_source` /
  `evidence_refs` / `kept_steps`）逐条可读，链由 `goal_plans` 版本行 + 审计行共同成立。
"""

from datetime import timedelta

import pytest

from app.api.v1 import debug as debug_api
from app.models.goal import GoalPlanRecord
from app.models.observability import DecisionKind, DecisionRecord
from app.models.plan import (
    PLAN_ADVANCE_DECISIONS,
    PLAN_REVISION_REASONS,
    PlanAdvance,
    PlanRevision,
)
from app.repositories import decision_repository, goal_repository
from app.services import life_loop_budget
from app.services.planning import observer as plan_observer

from . import plan011_support as support


@pytest.fixture
def plan_debug_on(override_settings):
    """审计面锚点（历史名保留）：调试子闸已随开关体系删除，只钉行动与世界面。"""
    override_settings(
        world_enabled="false",
        observability_persist_enabled="false")
    life_loop_budget.reset_cache()
    return True


@pytest.fixture
def persisted_audit(monkeypatch):
    """审计采集入口 → 既有决策仓储（写入面 → 行 → 投影三段闭环）。"""
    support.persist_decisions(monkeypatch)
    return decision_repository


def _plan_row(goal_id: str, version: int, status: str):
    goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            created_at=support.NOW,
            updated_at=support.NOW,
        )
    )
    return goal_repository.get_latest_plan(goal_id)


class TestAdvanceAudit:
    """推进审计：列承载（D5 / D6 / D7）与投影重建（I2）。"""

    def test_row_carries_the_frozen_columns(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit, monkeypatch
    ):
        goal = make_goal(user_id=support.USER, description="推进审计列承载")
        plan = _plan_row(goal.id, 1, "active")
        advance = support.advance(goal.id, plan.id, decision="advanced")

        plan_observer.record_plan_advance(advance)

        rows = support.goal_decision_rows(support.USER, decision="advanced")
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == DecisionKind.GOAL_LIFECYCLE
        assert row.user_id == support.USER
        assert row.trigger == plan_observer.STEP_NAME
        assert row.decision == "advanced"
        assert row.reason == "plan_step_advanced"
        assert row.input_snapshot == advance.model_dump(mode="json")
        assert tuple(row.input_snapshot) == tuple(PlanAdvance.model_fields)

    def test_every_decision_value_is_readable(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="逐值可读")
        plan = _plan_row(goal.id, 1, "active")
        written = {
            decision: support.advance(
                goal.id,
                plan.id,
                decision=decision,
                at=support.NOW + timedelta(minutes=index),
            )
            for index, decision in enumerate(PLAN_ADVANCE_DECISIONS)
        }
        for advance in written.values():
            plan_observer.record_plan_advance(advance)

        rows = support.goal_decision_rows(support.USER)
        assert sorted(row.decision for row in rows) == sorted(PLAN_ADVANCE_DECISIONS)
        assert {row.kind for row in rows} == {DecisionKind.GOAL_LIFECYCLE}
        projected = {
            row.decision: plan_observer.project_plan_advance(row) for row in rows
        }
        assert projected == written

    def test_advance_is_projectable_back(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="投影重建")
        plan = _plan_row(goal.id, 1, "active")
        advance = support.advance(goal.id, plan.id, decision="replanning", reason="plan_replanning")

        plan_observer.record_plan_advance(advance)

        row = support.goal_decision_rows(support.USER, decision="replanning")[0]
        assert plan_observer.project_plan_advance(row) == advance
        assert plan_observer.project_plan_revision(row) is None

    def test_decision_kind_is_still_five_values(self):
        assert {kind.value for kind in DecisionKind} == {
            "proactive_autonomy",
            "turn_goal",
            "turn_intention",
            "turn_behavior",
            "goal_lifecycle",
        }

    def test_missing_owner_writes_nothing(
        self, db_session_factory, plan_debug_on, persisted_audit
    ):
        advance = support.advance("plan11-missing-goal", "plan11-missing-plan")
        plan_observer.record_plan_advance(advance)
        assert decision_repository.search(kind=DecisionKind.GOAL_LIFECYCLE.value) == []

    def test_audit_failure_never_blocks_the_plan(
        self, db_session_factory, make_goal, plan_debug_on, monkeypatch
    ):
        from app.application import observability

        monkeypatch.setattr(
            observability, "on_decision", lambda record: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        goal = make_goal(user_id=support.USER, description="审计故障隔离")
        plan = _plan_row(goal.id, 1, "active")
        plan_observer.record_plan_advance(support.advance(goal.id, plan.id))

        settlement = plan_observer.PlanObserver().settle(
            goal,
            plan,
            support.advance(goal.id, plan.id, decision="completed", reason="plan_completed"),
        )
        assert settlement.transitioned is True
        assert goal_repository.get_goal(goal.id).status == "completed"

    def test_lifecycle_attribution_rows_are_not_plan_advances(self, db_session_factory):
        row = DecisionRecord(
            kind=DecisionKind.GOAL_LIFECYCLE,
            user_id=support.USER,
            trigger="goal_observation",
            input_snapshot={"goal_id": "g-1"},
            decision="completed",
            reason="计划步骤全部完成",
        )
        assert plan_observer.project_plan_advance(row) is None
        assert plan_observer.project_plan_revision(row) is None
        assert plan_observer.project_plan_advance(
            DecisionRecord(
                kind=DecisionKind.TURN_GOAL,
                user_id=support.USER,
                input_snapshot={},
                decision="advanced",
            )
        ) is None


class TestRevisionAudit:
    """修订审计：六字段承载（D7 / I4）与链重建。"""

    def test_row_carries_the_six_revision_fields(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="修订审计六字段")
        plan = _plan_row(goal.id, 1, "superseded")
        revision = support.revision(
            1,
            2,
            reason="step_attempt_exhausted",
            evidence_refs=["insight-1"],
            kept_steps=[1],
        )

        plan_observer.record_plan_revision(revision, plan=plan)

        rows = support.goal_decision_rows(support.USER, decision="plan_revised")
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == DecisionKind.GOAL_LIFECYCLE
        assert row.trigger == plan_observer.DECISION_TRIGGER_REVISION
        assert row.reason == revision.reason
        assert plan_observer.project_plan_revision(row) == revision
        assert plan_observer.project_plan_advance(row) is None
        for field in (
            "from_version",
            "to_version",
            "reason",
            "trigger_source",
            "evidence_refs",
            "kept_steps",
        ):
            assert field in row.input_snapshot, field
        assert row.input_snapshot["goal_id"] == goal.id
        assert row.input_snapshot["plan_id"] == plan.id

    def test_missing_owner_writes_nothing(self, db_session_factory, plan_debug_on, persisted_audit):
        plan_observer.record_plan_revision(support.revision(1, 2))
        assert decision_repository.search(kind=DecisionKind.GOAL_LIFECYCLE.value) == []


class TestRevisionChainRebuild:
    """I4：修订链从 `goal_plans`（版本行）+ `decision_records`（`plan_revised`）重建。"""

    @staticmethod
    def _chain(goal_id: str) -> list:
        return debug_api.list_plan_revisions(goal_id).revisions

    def test_three_step_chain_is_readable(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="三次修订链")
        _plan_row(goal.id, 1, "superseded")
        plan_2 = _plan_row(goal.id, 2, "superseded")
        plan_3 = _plan_row(goal.id, 3, "active")
        plan_observer.record_plan_revision(
            support.revision(1, 2, reason="step_attempt_exhausted", kept_steps=[1]),
            plan=plan_2,
        )
        plan_observer.record_plan_revision(
            support.revision(
                2,
                3,
                reason="insight_driven",
                evidence_refs=["insight-9"],
                kept_steps=[1, 2],
            ),
            plan=plan_3,
        )

        chain = self._chain(goal.id)
        assert [(row.from_version, row.to_version) for row in chain] == [(1, 2), (2, 3)]
        assert [row.reason for row in chain] == ["step_attempt_exhausted", "insight_driven"]
        assert [row.trigger_source for row in chain] == [
            "step_attempt_exhausted",
            "insight_driven",
        ]
        assert chain[0].kept_steps == [1]
        assert chain[1].evidence_refs == ["insight-9"]
        assert chain[1].kept_steps == [1, 2]
        assert all(row.at == support.NOW for row in chain)
        assert set(PLAN_REVISION_REASONS) >= {row.reason for row in chain}

    def test_chain_requires_the_version_rows(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        """链行以 `goal_plans` 版本行存在为前提：审计行指向的版本不存在即该步不成立。"""
        goal = make_goal(user_id=support.USER, description="版本行缺一")
        plan = _plan_row(goal.id, 1, "superseded")
        plan_observer.record_plan_revision(support.revision(1, 2), plan=plan)

        assert self._chain(goal.id) == []

    def test_rejected_version_without_audit_adds_no_step(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="被拒版本不进链")
        _plan_row(goal.id, 1, "rejected")
        assert self._chain(goal.id) == []

    def test_chain_is_scoped_by_goal(
        self, db_session_factory, make_goal, plan_debug_on, persisted_audit
    ):
        mine = make_goal(user_id=support.USER, description="链归属")
        theirs = make_goal(user_id=support.USER, description="链归属-另一目标")
        _plan_row(mine.id, 1, "superseded")
        plan_2 = _plan_row(mine.id, 2, "active")
        _plan_row(theirs.id, 1, "superseded")
        theirs_2 = _plan_row(theirs.id, 2, "active")
        plan_observer.record_plan_revision(support.revision(1, 2), plan=plan_2)
        plan_observer.record_plan_revision(
            support.revision(1, 2, reason="criteria_undecidable"), plan=theirs_2
        )

        chain = self._chain(mine.id)
        assert [row.reason for row in chain] == ["step_attempt_exhausted"]
        assert [row.reason for row in self._chain(theirs.id)] == ["criteria_undecidable"]

    def test_missing_goal_returns_404(self, db_session_factory, plan_debug_on):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            debug_api.list_plan_revisions("plan11-no-goal")
        assert excinfo.value.status_code == 404

    def test_revision_projection_ignores_unknown_extra_keys(self):
        """额外归属键（`goal_id` / `plan_id`）对模型投影是安全未知键。"""
        payload = support.revision(1, 2).model_dump(mode="json")
        payload.update({"goal_id": "g-1", "plan_id": "p-1"})
        assert PlanRevision.model_validate(payload) == support.revision(1, 2)
