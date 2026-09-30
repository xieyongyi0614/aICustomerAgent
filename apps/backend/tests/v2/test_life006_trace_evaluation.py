"""LIFE-006 Goal/Decision Trace 与评估测试。

覆盖：五条 life-loop 评估规则真值表、collect_life_loop_slice 只读采集、
trigger→decision→action 五点连线（溯源完整/断链命中）、offline_evaluator
life_loop 小节、IssueCode 40 收口。
"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import integrate_result
from app.models.action import ActionResult
from app.models.autonomy import ProactiveAction
from app.models.evaluation import (
    DEFAULT_SEVERITY,
    EvaluationDimension,
    IssueCode,
    build_issue,
)
from app.repositories import (
    decision_repository,
    loop_run_repository,
    outbox_repository,
    proactive_repository,
    trigger_registry_repository as trigger_repo,
)
from app.services.evaluation.context import (
    EvaluationContext,
    LifeLoopProactiveRef,
    LifeLoopRunRef,
    LifeLoopSlice,
    LifeLoopTriggerRef,
    collect_life_loop_slice,
)
from app.services.evaluation.rules.autonomy import (
    BUDGET_COMPLIANCE,
    RUN_COMPLETENESS,
    STORM_AND_REPEAT,
    TRIGGER_LIFECYCLE,
    TRIGGER_PROVENANCE,
)

NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "life-eval-user"


def _ctx(loop: LifeLoopSlice | None) -> EvaluationContext:
    return EvaluationContext(
        subject="turn",
        subject_id="t1",
        session_id="s1",
        user_id=USER,
        life_loop=loop,
    )


def _run(
    run_id="r1",
    kind="autonomy",
    status="done",
    step_names=("perception", "goal_check"),
    llm=0,
    degraded=False,
    aborted_with_reason=True,
):
    return LifeLoopRunRef(
        run_id=run_id,
        kind=kind,
        status=status,
        reason="due_trigger",
        step_names=list(step_names),
        llm_call_count=llm,
        budget_degraded=degraded,
        aborted_with_reason=aborted_with_reason,
    )


class TestIssueCodeTable:
    def test_four_new_codes_with_severity(self):
        assert len(IssueCode) == 46
        assert (
            DEFAULT_SEVERITY[IssueCode.LIFE_LOOP_RUN_INCOMPLETE]
            is not None
        )
        issue = build_issue(IssueCode.LIFE_LOOP_BUDGET_OVERRUN)
        assert issue.dimension == EvaluationDimension.AUTONOMY
        assert issue.message


class TestRunCompletenessRule:
    def test_done_without_decision_fires(self):
        issue = RUN_COMPLETENESS.evaluate(_ctx(LifeLoopSlice(runs=[_run()])))
        assert issue is not None
        assert issue.code == IssueCode.LIFE_LOOP_RUN_INCOMPLETE

    def test_done_with_decision_clean(self):
        issue = RUN_COMPLETENESS.evaluate(
            _ctx(LifeLoopSlice(runs=[_run(step_names=("perception", "decision"))]))
        )
        assert issue is None

    def test_maintenance_done_without_decision_clean(self):
        assert RUN_COMPLETENESS.evaluate(_ctx(LifeLoopSlice(runs=[_run()]))) is not None

    def test_aborted_without_reason_fires(self):
        issue = RUN_COMPLETENESS.evaluate(
            _ctx(
                LifeLoopSlice(
                    runs=[
                        _run(status="aborted", step_names=("perception",), aborted_with_reason=False)
                    ]
                )
            )
        )
        assert issue is not None

    def test_maintenance_runs_ignored(self):
        issue = RUN_COMPLETENESS.evaluate(
            _ctx(LifeLoopSlice(runs=[_run(kind="world_maintenance", step_names=())]))
        )
        assert issue is None


class TestBudgetComplianceRule:
    def test_degraded_with_llm_fires(self):
        issue = BUDGET_COMPLIANCE.evaluate(
            _ctx(LifeLoopSlice(runs=[_run(llm=1, degraded=True)]))
        )
        assert issue is not None
        assert issue.code == IssueCode.LIFE_LOOP_BUDGET_OVERRUN

    def test_day_over_limit_fires(self):
        issue = BUDGET_COMPLIANCE.evaluate(
            _ctx(LifeLoopSlice(day_llm_calls=500, day_llm_call_limit=200))
        )
        assert issue is not None

    def test_within_budget_clean(self):
        issue = BUDGET_COMPLIANCE.evaluate(
            _ctx(LifeLoopSlice(day_llm_calls=10, day_llm_call_limit=200))
        )
        assert issue is None


class TestTriggerLifecycleRule:
    def test_stale_trigger_fires(self):
        trigger = LifeLoopTriggerRef(
            trigger_key="action_due:e1",
            trigger_type="action_due",
            status="due",
            stale=True,
        )
        issue = TRIGGER_LIFECYCLE.evaluate(_ctx(LifeLoopSlice(triggers=[trigger])))
        assert issue is not None
        assert issue.code == IssueCode.TRIGGER_REGISTRY_ORPHAN

    def test_cancelled_without_reason_fires(self):
        trigger = LifeLoopTriggerRef(
            trigger_key="action_due:e2",
            trigger_type="action_due",
            status="cancelled",
            cancelled_without_reason=True,
        )
        issue = TRIGGER_LIFECYCLE.evaluate(_ctx(LifeLoopSlice(triggers=[trigger])))
        assert issue is not None

    def test_healthy_triggers_clean(self):
        trigger = LifeLoopTriggerRef(
            trigger_key="action_due:e3",
            trigger_type="action_due",
            status="done",
        )
        assert TRIGGER_LIFECYCLE.evaluate(_ctx(LifeLoopSlice(triggers=[trigger]))) is None


class TestProvenanceAndStorm:
    def test_unprovenanced_delivered_fires(self):
        proactive = LifeLoopProactiveRef(
            action_id="pa-1", trigger_type="inactivity", provenanced=False
        )
        issue = TRIGGER_PROVENANCE.evaluate(
            _ctx(LifeLoopSlice(delivered_proactive=[proactive]))
        )
        assert issue is not None
        assert issue.code == IssueCode.AUTONOMY_TRIGGER_UNPROVENANCED

    def test_provenanced_clean(self):
        proactive = LifeLoopProactiveRef(
            action_id="pa-2", trigger_type="inactivity", provenanced=True
        )
        assert (
            TRIGGER_PROVENANCE.evaluate(
                _ctx(LifeLoopSlice(delivered_proactive=[proactive]))
            )
            is None
        )

    def test_storm_threshold(self, override_settings):
        override_settings(life_loop_storm_daily_limit="3")
        proactive = [LifeLoopProactiveRef(action_id=f"pa-{i}") for i in range(4)]
        issue = STORM_AND_REPEAT.evaluate(
            _ctx(LifeLoopSlice(delivered_proactive=proactive))
        )
        assert issue is not None
        assert issue.code == IssueCode.AUTONOMY_REDUNDANT
        assert (
            STORM_AND_REPEAT.evaluate(
                _ctx(LifeLoopSlice(delivered_proactive=proactive[:3]))
            )
            is None
        )


class TestSliceCollection:
    def test_collect_reflects_runs_and_triggers(self, db_session_factory):
        run = loop_run_repository.create_run(
            user_id=USER, kind="autonomy", reason="due_trigger", now=NOW
        )
        loop_run_repository.finish_run(
            run.id,
            status="done",
            steps=[
                {"step": "perception", "status": "ok"},
                {"step": "decision", "status": "ok"},
            ],
            now=NOW,
        )
        trigger_repo.register(
            USER, "scheduled_followup", "followup:u1:面试:x",
            due_at=NOW, payload={"summary": "面试"}, now=NOW,
        )
        slice_ = collect_life_loop_slice(USER, now=NOW, window_hours=24.0)
        assert [r.run_id for r in slice_.runs] == [run.id]
        assert slice_.runs[0].step_names == ["perception", "decision"]
        assert any(t.trigger_key == "followup:u1:面试:x" for t in slice_.triggers)
        assert slice_.triggers[0].stale is False

    def test_stale_detection(self, db_session_factory):
        key = "action_due:e-stale"
        trigger_repo.register(USER, "action_due", key, due_at=NOW, now=NOW)
        trigger_repo.register_and_claim(USER, "action_due", key, due_at=NOW, now=NOW)
        from app.core.db import TriggerRegistryRow

        with trigger_repo.SessionLocal() as session:
            session.query(TriggerRegistryRow).filter(
                TriggerRegistryRow.trigger_key == key
            ).update({"updated_at": NOW - timedelta(seconds=1800)})
            session.commit()
        slice_ = collect_life_loop_slice(USER, now=NOW, window_hours=24.0)
        assert any(t.stale for t in slice_.triggers)
        issue = TRIGGER_LIFECYCLE.evaluate(_ctx(slice_))
        assert issue is not None


class TestFivePointTrace:
    @pytest.mark.asyncio
    async def test_delivered_proactive_provenance_chain(
        self, db_session_factory, monkeypatch, override_settings
    ):
        """delivered proactive → decision_records 溯源成立；断链 → 规则命中。"""
        from app.services.autonomy import executor as proactive_executor
        from app.models.goal import GoalRecord
        from app.models.observability import DecisionKind, DecisionRecord
        from app.repositories import goal_repository
        from app.models.autonomy import ProactiveAction as PA

        override_settings()

        async def fake_generate(
            goal_description, intention, recent_context, llm=None, trace=None
        ):
            return "在忙吗"

        monkeypatch.setattr(
            proactive_executor.proactive_chain, "generate", fake_generate
        )
        monkeypatch.setattr(
            proactive_executor, "_recent_context", lambda session_id: ""
        )
        goal = goal_repository.create_goal(
            GoalRecord(
                user_id=USER,
                type="user_care",
                description="关心",
                horizon="persistent",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        action = PA(
            id="pa-prov",
            user_id=USER,
            session_id="s-prov",
            trigger_type="conversation_inactivity",
            dedupe_key="d-prov",
            goal_id=goal.id,
            intention="check_in",
            reason="闲置关心",
            created_at=NOW,
            updated_at=NOW,
        )
        assert proactive_repository.enqueue(action) is True
        # engine 决策步（autonomy_engine._record_decision 同款）：trigger→decision 落账
        decision_repository.save(
            DecisionRecord(
                kind=DecisionKind.PROACTIVE_AUTONOMY,
                user_id=USER,
                conversation_id="s-prov",
                action_id="pa-prov",
                trigger="conversation_inactivity",
                input_snapshot={},
                decision="act",
                reason="闲置关心",
            )
        )
        delivered = await proactive_executor.execute(action, llm=None, now=NOW)
        assert delivered is not None and delivered.status == "delivered"

        # 溯源链：decision_records 有 PROACTIVE_AUTONOMY 行（带 action_id + trigger）
        decisions = decision_repository.get_by_action("pa-prov")
        assert any(d.kind == "proactive_autonomy" for d in decisions)

        slice_ = collect_life_loop_slice(USER, now=NOW, window_hours=24.0)
        mine = [p for p in slice_.delivered_proactive if p.action_id == "pa-prov"]
        assert mine and mine[0].provenanced is True
        assert TRIGGER_PROVENANCE.evaluate(_ctx(slice_)) is None


class TestOfflineStats:
    def test_life_loop_stats_section(self, db_session_factory):
        from datetime import datetime as _dt

        from app.services.evaluation.offline import _life_loop_stats

        created_at = _dt.now()
        run = loop_run_repository.create_run(
            user_id=USER, kind="autonomy", reason="due_trigger", now=created_at
        )
        loop_run_repository.finish_run(
            run.id,
            status="done",
            steps=[{"step": "perception", "status": "ok"}, {"step": "decision", "status": "ok"}],
            llm_call_count=1,
            budget_state={"status": "ok"},
            now=created_at,
        )
        stats = _life_loop_stats(USER)
        assert stats["runs_total"] == 1
        assert stats["runs_complete"] == 1
        assert stats["runs_complete_rate"] == 1.0
        assert "proactive_provenance_rate" in stats
        assert "outbox_dead_letters" in stats

    def test_outbox_dead_letter_counted(self, db_session_factory):
        from app.services.evaluation.offline import _life_loop_stats

        outbox_repository.insert(
            {"action_id": "a1"}, idempotency_key="dl-1", now=NOW
        )
        from app.core.db import OutboxEventRow

        with outbox_repository.SessionLocal() as session:
            session.query(OutboxEventRow).filter(
                OutboxEventRow.idempotency_key == "dl-1"
            ).update({"status": "failed", "last_error": "boom"})
            session.commit()
        stats = _life_loop_stats(USER)
        assert stats["outbox_dead_letters"] == 1
