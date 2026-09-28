"""AUT-005 Eval Gate：追求闭环跨会话剧情（E-AUT-01~04）。

确定性 stub（规划 LLM 脚本化、事实投影注入），三分支剧情全链：
A 完成（跨 3 会话推进→completed+experience 归因）、B 失败（阈值→重规划→
预算耗尽→failed+原因）、C 放弃（双信号置信→abandoned）；冲突剧情（同域
仲裁 suspended 留痕+复活）；预算剧情（第 4 次规划请求拒绝）。终态后 GoalSlice
六规则全量零违例 = E-AUT-03；全链 0 观察类 LLM = E-AUT-02。
"""

from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.evaluation import IssueCode
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.repositories import (
    background_job_repository,
    conversation_repository,
    goal_repository,
)
from app.services import goal_arbitration, goal_observation
from app.services.evaluation_context import collect_goal_slice
from app.services.evaluation_rules import run_rules
from app.services.goal_planning import (
    TRIGGER_CREATED,
    materialize,
    plan_goal,
    run_planning_jobs,
)

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER_A = "gate-user-completed"
USER_B = "gate-user-failed"
USER_C = "gate-user-abandoned"
USER_D = "gate-user-conflict"

TWO_STEP_PLAN = [
    {
        "index": 1,
        "description": "提醒用户休息",
        "capability": "create_reminder",
        "params": {},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    },
    {
        "index": 2,
        "description": "确认状态平稳",
        "capability": "query_environment",
        "params": {},
        "criteria": {
            "type": "threshold_reached",
            "source": "state",
            "path": "tension",
            "op": "<=",
            "value": 0.2,
        },
        "depends_on": [1],
    },
]


@pytest.fixture()
def gate_env(db_session_factory, override_settings, monkeypatch):
    override_settings(
        observability_persist_enabled="true",
        autonomy_subgoal_failure_threshold="3",
        autonomy_planning_max_attempts="3")

    def _overlay(user_id, character_id="asuna"):
        from app.models.development import DevelopmentOverlay

        overlay = DevelopmentOverlay()
        overlay.goal_weights = {"goal.user_care.weight": 0.4}
        return overlay

    from app.repositories import decision_repository

    monkeypatch.setattr(
        "app.services.goal_planning.development_aggregate.read_overlay", _overlay
    )
    monkeypatch.setattr(
        "app.services.goal_arbitration.development_aggregate.read_overlay", _overlay
    )
    monkeypatch.setattr(
        "app.services.goal_planning._ask_llm_with_retry",
        lambda messages, settings: _planning_stub(messages, settings),
    )
    monkeypatch.setattr(
        "app.application.observability.on_decision",
        lambda record: decision_repository.save(record),
    )
    yield
    goal_arbitration.reset_throttle_state()


def _planning_stub(messages, settings):
    import json

    from app.services.goal_planning import PlanningProposal

    payload = json.loads(messages[1][1])
    steps = 1 if payload.get("goal", {}).get("domain") == "relationship" else 2
    if steps == 1:
        return PlanningProposal(
            sub_goals=[
                {
                    "index": 1,
                    "description": "缓和关系",
                    "capability": "create_reminder",
                    "params": {},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                }
            ]
        )
    return PlanningProposal(
        sub_goals=[{**item, "index": item["index"]} for item in TWO_STEP_PLAN]
    )


def _facts(user_id, **overrides):
    facts = {
        "now": NOW,
        "action_results": [],
        "action_history": [],
        "world": {},
        "state": {"tension": 0.5, "intimacy": 0.3, "mood": "calm"},
        "memory": {"salient_memory_count": 0},
        "salient_memories": [],
    }
    facts.update(overrides)
    return facts


def _new_session(user_id: str, index: int) -> str:
    session_id = f"gate-{user_id}-s{index}"
    conversation_repository.get_or_create_conversation(session_id, user_id)
    conversation_repository.save_message(session_id, "human", "剧情消息")
    conversation_repository.save_message(session_id, "ai", "好的")
    return session_id


def _run_issues(user_id: str) -> set:
    slice_ = collect_goal_slice(user_id, now=NOW)
    from app.services.evaluation_context import EvaluationContext

    context = EvaluationContext(
        subject="goal",
        subject_id="gate",
        session_id="",
        user_id=user_id,
        goal=slice_,
    )
    return {issue.code for issue in run_rules(context, get_settings())}


def _claim_and_run_planning() -> int:
    from app.repositories import background_job_repository

    rows = background_job_repository.list_jobs("goal_planning", status="pending")
    with background_job_repository.SessionLocal() as session:
        for row in rows:
            row.status = "running"
            session.merge(row)
        session.commit()
    return run_planning_jobs()


class TestCompletionBranch:
    def test_three_sessions_pursuit_completes(self, gate_env):
        _new_session(USER_A, 0)
        result = materialize(
            USER_A,
            world_facts={},
            now=NOW,
        )
        assert len(result["created"]) == 1
        goal_id = result["created"][0]
        assert _claim_and_run_planning() == 1
        latest = goal_repository.get_latest_plan(goal_id)
        assert latest.status == "active"
        assert [spec.index for spec in latest.sub_goals] == [1, 2]

        goal = goal_repository.get_goal(goal_id)
        plan = latest
        facts_s1 = _facts(USER_A)
        detail_s1 = goal_observation.advance_goal(goal, plan, facts_s1, NOW)
        assert detail_s1["outcome"] == "retrying"

        _new_session(USER_A, 1)
        facts_s2 = _facts(
            USER_A,
            action_results=[
                {
                    "capability": "create_reminder",
                    "status": "succeeded",
                    "created_at": NOW + timedelta(hours=1),
                }
            ],
        )
        detail_s2 = goal_observation.advance_goal(
            goal, goal_repository.get_latest_plan(goal_id), facts_s2, NOW + timedelta(hours=1)
        )
        assert detail_s2["outcome"] == "advanced"

        _new_session(USER_A, 2)
        facts_s3 = _facts(USER_A, state={"tension": 0.1, "intimacy": 0.4, "mood": "calm"})
        detail_s3 = goal_observation.advance_goal(
            goal, goal_repository.get_latest_plan(goal_id), facts_s3, NOW + timedelta(hours=2)
        )
        assert detail_s3["outcome"] == "completed"
        record = goal_repository.get_goal(goal_id)
        assert record.status == "completed"

        from app.core.db import MemoryCandidateRow
        from app.services.memory2 import ingest as memory_ingest

        with memory_ingest.SessionLocal() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter(
                    MemoryCandidateRow.source_table == "character_goals",
                    MemoryCandidateRow.user_id == USER_A,
                )
                .one()
            )
        assert "完成了目标" in row.content

        assert _run_issues(USER_A) == set()


class TestFailureBranch:
    def test_threshold_replan_then_fail(self, gate_env):
        _new_session(USER_B, 0)
        goal = goal_repository.create_hierarchical_goal(
            USER_B, "long_term", "relationship", "缓和关系目标", 3
        )
        assert plan_goal(goal.id, TRIGGER_CREATED)["status"] == "ok"

        goal_record = goal_repository.get_goal(goal.id)
        for cycle in range(3):
            goal_observation.advance_goal(
                goal_record,
                goal_repository.get_latest_plan(goal.id),
                _facts(USER_B),
                NOW + timedelta(hours=cycle),
            )
        detail = goal_observation.advance_goal(
            goal_record,
            goal_repository.get_latest_plan(goal.id),
            _facts(USER_B),
            NOW + timedelta(hours=3),
        )
        assert detail["outcome"] == "replanning"
        assert _claim_and_run_planning() >= 1
        assert goal_repository.count_plans(goal.id) == 2
        assert goal_repository.get_goal(goal.id).status == "active"

        for cycle in range(3, 6):
            goal_observation.advance_goal(
                goal_record,
                goal_repository.get_latest_plan(goal.id),
                _facts(USER_B),
                NOW + timedelta(hours=cycle),
            )
        detail = goal_observation.advance_goal(
            goal_record,
            goal_repository.get_latest_plan(goal.id),
            _facts(USER_B),
            NOW + timedelta(hours=6),
        )
        assert detail["outcome"] == "replanning"
        _claim_and_run_planning()
        assert goal_repository.count_plans(goal.id) == 3

        for cycle in range(6, 9):
            goal_observation.advance_goal(
                goal_record,
                goal_repository.get_latest_plan(goal.id),
                _facts(USER_B),
                NOW + timedelta(hours=cycle),
            )
        final = goal_observation.advance_goal(
            goal_record,
            goal_repository.get_latest_plan(goal.id),
            _facts(USER_B),
            NOW + timedelta(hours=9),
        )
        assert final["outcome"] == "failed"
        record = goal_repository.get_goal(goal.id)
        assert record.status == "failed"
        assert record.failure_reason == "replan_exhausted"

        fourth = plan_goal(goal.id, TRIGGER_CREATED)
        assert fourth["status"] == "rejected"
        assert fourth["reason"] == "attempt_cap"

        assert _run_issues(USER_B) == set()


class TestAbandonmentBranch:
    def test_dual_signal_abandons(self, gate_env):
        _new_session(USER_C, 0)
        goal = goal_repository.create_hierarchical_goal(
            USER_C, "long_term", "personal", "旧追求目标", 3
        )
        goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="active",
                sub_goals=[SubGoalSpec.model_validate(TWO_STEP_PLAN[0])],
                created_at=NOW - timedelta(days=30),
                updated_at=NOW - timedelta(days=30),
            )
        )
        result = goal_arbitration.check_abandonment(
            USER_C, _facts(USER_C), NOW + timedelta(days=15)
        )
        assert len(result["abandoned"]) == 1
        record = goal_repository.get_goal(goal.id)
        assert record.status == "abandoned"
        assert record.arbitration_state["confidence"] >= 0.6
        assert _run_issues(USER_C) == set()


class TestConflictScenario:
    def test_conflict_suspends_then_revives(self, gate_env):
        keeper = goal_repository.create_hierarchical_goal(
            USER_D, "long_term", "personal", "主目标", 5
        )
        loser = goal_repository.create_hierarchical_goal(
            USER_D, "long_term", "personal", "次目标", 2
        )
        result = goal_arbitration.arbitrate_user(USER_D, NOW)
        assert any(change["goal_id"] == loser.id for change in result["changes"])
        assert goal_repository.get_goal(keeper.id).status == "active"
        loser_record = goal_repository.get_goal(loser.id)
        assert loser_record.status == "suspended"
        assert loser_record.arbitration_state["conflict_with"] == keeper.id

        from tests.eval.test_autonomy_eval_gate import TWO_STEP_PLAN

        keeper_plan = goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=keeper.id,
                version=1,
                status="active",
                sub_goals=[SubGoalSpec.model_validate(TWO_STEP_PLAN[0])],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        keeper_plan.sub_goals[0].status = "done"
        goal_repository.update_plan_progress(keeper_plan.id, keeper_plan.sub_goals)
        goal_observation.advance_goal(
            goal_repository.get_goal(keeper.id),
            goal_repository.get_latest_plan(keeper.id),
            _facts(USER_D),
            NOW,
        )
        assert goal_repository.get_goal(keeper.id).status == "completed"

        goal_arbitration.arbitrate_user(USER_D, NOW)
        assert goal_repository.get_goal(loser.id).status == "active"
        assert _run_issues(USER_D) == set()
