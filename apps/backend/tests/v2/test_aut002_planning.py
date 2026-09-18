"""AUT-002 Planning 执行器测试。

供给装配三来源（Development 调制/Relationship Pattern/World 事实与显著度
记忆）、去重幂等、规划 job 入队与幂等键、前置闸（attempt 封顶/在途跳过）、
结构闸（判据白名单/能力对齐/数量封顶）、LLM 失败放弃、版本激活与旧版
superseded、Flag OFF 零行为、life_loop goal_supply 步骤门控。
"""

from datetime import datetime

import pytest

from app.models.goal import GoalPlanRecord
from app.repositories import (
    background_job_repository,
    goal_repository,
)
from app.services import goal_planning as planning
from app.services.memory2 import job_worker as memory2_job_worker

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER = "aut2-user"

VALID_SUB_GOALS = [
    {
        "index": 1,
        "description": "提醒用户休息",
        "capability": "create_reminder",
        "params": {"content": "休息一下"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    },
    {
        "index": 2,
        "description": "查看进展",
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
def aut_on(override_settings, monkeypatch):
    override_settings(
        observability_persist_enabled="false",
        world_enabled="false")
    monkeypatch.setattr(
        planning,
        "_ask_llm_with_retry",
        lambda messages, settings: planning.PlanningProposal(
            sub_goals=[dict(item) for item in VALID_SUB_GOALS]
        ),
    )
    yield


def _stub_overlay(monkeypatch, weights=None):
    from app.models.development import DevelopmentOverlay

    overlay = DevelopmentOverlay()
    overlay.goal_weights = weights or {}
    monkeypatch.setattr(
        planning.development_aggregate, "read_overlay", lambda user_id, character_id="asuna": overlay if overlay.goal_weights else None
    )


def _stub_patterns(monkeypatch, patterns):
    from app.services import relationship_patterns as pattern_service

    monkeypatch.setattr(
        pattern_service, "read_relationship_patterns", lambda user_id, character_id="asuna": (patterns, {})
    )


def _make_goal(layer="long_term", domain="personal", description="养成规律作息"):
    return goal_repository.create_hierarchical_goal(
        USER, layer, domain, description, 3
    )


def _running_job(goal_id: str, trigger: str = "goal_created"):
    background_job_repository.enqueue_job(
        planning.JOB_TYPE_PLANNING,
        {"goal_id": goal_id, "trigger": trigger, "world_facts": {}},
        f"{planning.JOB_TYPE_PLANNING}:{goal_id}:{trigger}:1",
    )
    with background_job_repository.SessionLocal() as session:
        (job,) = background_job_repository.list_jobs(planning.JOB_TYPE_PLANNING)
        job.status = "running"
        session.add(job)
        session.commit()


class TestSupplyCandidates:
    def test_personal_source_via_modulation_weight(self, aut_on, monkeypatch):
        _stub_overlay(monkeypatch, weights={"goal.user_care.weight": 0.4})
        candidates = planning.collect_candidates(USER)
        personal = [c for c in candidates if c["domain"] == "personal"]
        assert len(personal) == 1
        assert personal[0]["layer"] == "long_term"
        assert personal[0]["origin"] == "development_modulation"

    def test_personal_below_threshold_skipped(self, aut_on, monkeypatch):
        _stub_overlay(monkeypatch, weights={"goal.user_care.weight": 0.1})
        candidates = planning.collect_candidates(USER)
        assert [c for c in candidates if c["domain"] == "personal"] == []

    def test_relationship_source_via_pattern(self, aut_on, monkeypatch):
        from app.models.development import RelationshipPattern

        pattern = RelationshipPattern(
            key="narrative:all_nighter",
            value={},
            strength=0.8,
            statement="一起熬夜过",
            source_insight_id="ins-1",
        )
        _stub_patterns(monkeypatch, [pattern])
        candidates = planning.collect_candidates(USER)
        relationship = [c for c in candidates if c["domain"] == "relationship"]
        assert len(relationship) == 1
        assert relationship[0]["origin"] == "relationship_pattern:narrative:all_nighter"

    def test_world_source_via_salient_events(self, aut_on):
        candidates = planning.collect_candidates(
            USER,
            world_facts={
                "salient_events": [
                    {"type": "interview", "title": "下午的面试", "importance": "high"},
                    {"type": "exam", "title": "低重要", "importance": "low"},
                ]
            },
        )
        world = [c for c in candidates if c["domain"] == "world"]
        assert len(world) == 1
        assert world[0]["layer"] == "short_term"
        assert world[0]["description"] == "跟进下午的面试"

    def test_no_sources_no_candidates(self, aut_on, monkeypatch):
        _stub_overlay(monkeypatch)
        _stub_patterns(monkeypatch, [])
        assert planning.collect_candidates(USER) == []


class TestMaterialize:
    def test_creates_goal_and_enqueues(self, aut_on, monkeypatch):
        _stub_overlay(monkeypatch, weights={"goal.user_care.weight": 0.4})
        result = planning.materialize(USER, world_facts={}, now=NOW)
        assert result["status"] == "ok"
        assert len(result["created"]) == 1
        assert result["enqueued"] == 1
        goal = goal_repository.get_goal(result["created"][0])
        assert goal.layer == "long_term"
        assert goal.domain == "personal"

    def test_long_term_dedup_by_layer_domain(self, aut_on, monkeypatch):
        _stub_overlay(monkeypatch, weights={"goal.user_care.weight": 0.4})
        first = planning.materialize(USER, world_facts={}, now=NOW)
        second = planning.materialize(USER, world_facts={}, now=NOW)
        assert len(first["created"]) == 1
        assert second["created"] == []

    def test_world_short_term_content_dedup(self, aut_on):
        facts = {
            "salient_events": [{"title": "面试", "importance": "high"}]
        }
        first = planning.materialize(USER, world_facts=facts, now=NOW)
        second = planning.materialize(USER, world_facts=facts, now=NOW)
        assert len(first["created"]) == 1
        assert second["created"] == []


class TestEnqueueAndGate:
    def test_enqueue_idempotency_key_and_rejects_bad_trigger(self, aut_on):
        goal = _make_goal()
        assert planning.enqueue_planning(USER, goal.id, planning.TRIGGER_CREATED) is True
        assert planning.enqueue_planning(USER, goal.id, planning.TRIGGER_CREATED) is False
        with pytest.raises(ValueError):
            planning.enqueue_planning(USER, goal.id, "whenever")

    def test_plan_goal_flag_off_skipped(self, override_settings):
        override_settings()
        assert planning.plan_goal("ghost", planning.TRIGGER_CREATED)["status"] == "skipped"

    def test_plan_goal_rejects_non_layered_goal(self, aut_on):
        from tests.v2.test_aut001_goal_hierarchy import _v1_record

        v1 = goal_repository.create_goal(_v1_record())
        outcome = planning.plan_goal(v1.id, planning.TRIGGER_CREATED)
        assert outcome["status"] == "skipped"
        assert outcome["skip_reason"] == "goal_not_plannable"

    def test_attempt_cap_rejects_fourth_request_without_llm(self, aut_on, monkeypatch):
        goal = _make_goal()
        for version in range(1, 4):
            now = datetime.now()
            goal_repository.create_plan(
                GoalPlanRecord(
                    goal_id=goal.id,
                    version=version,
                    status="rejected",
                    rejection_reason="gate",
                    created_at=now,
                    updated_at=now,
                )
            )
        calls: list = []
        monkeypatch.setattr(
            planning,
            "_ask_llm_with_retry",
            lambda messages, settings: calls.append(1) or planning.PlanningProposal(),
        )
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_REPLAN)
        assert outcome["status"] == "rejected"
        assert outcome["reason"] == "attempt_cap"
        assert calls == []

    def test_created_trigger_skips_when_plan_in_flight(self, aut_on):
        goal = _make_goal()
        plan = goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="validated",
                sub_goals=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_CREATED)
        assert outcome["skip_reason"] == "plan_exists"
        assert plan.status == "validated"

    def test_success_activates_and_supersedes_old(self, aut_on):
        goal = _make_goal()
        first = goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="active",
                sub_goals=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_REPLAN)
        assert outcome["status"] == "ok"
        assert outcome["version"] == 2
        assert goal_repository.get_plan(first.id).status == "superseded"
        latest = goal_repository.get_latest_plan(goal.id)
        assert latest.status == "active"
        assert [spec.index for spec in latest.sub_goals] == [1, 2]

    def test_gate_rejects_oversize_plan(self, aut_on, override_settings):
        override_settings(v2_autonomy_subgoal_max_count="1")
        goal = _make_goal()
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_CREATED)
        assert outcome["status"] == "rejected"
        assert outcome["reason"] == "subgoal_count_exceeded"
        rejected = goal_repository.get_latest_plan(goal.id)
        assert rejected.status == "rejected"

    def test_gate_rejects_unknown_capability(self, aut_on, monkeypatch):
        goal = _make_goal()
        bad = [dict(VALID_SUB_GOALS[0])]
        bad[0] = {**bad[0], "capability": "travel_to_moon"}
        monkeypatch.setattr(
            planning,
            "_ask_llm_with_retry",
            lambda messages, settings: planning.PlanningProposal(sub_goals=bad),
        )
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_CREATED)
        assert outcome["status"] == "rejected"
        assert outcome["reason"].startswith("capability_unaligned")

    def test_gate_rejects_free_text_criteria(self, aut_on, monkeypatch):
        goal = _make_goal()
        bad = [dict(VALID_SUB_GOALS[0])]
        bad[0] = {**bad[0], "criteria": {"type": "user_happy"}}
        monkeypatch.setattr(
            planning,
            "_ask_llm_with_retry",
            lambda messages, settings: planning.PlanningProposal(sub_goals=bad),
        )
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_CREATED)
        assert outcome["status"] == "rejected"
        assert "user_happy" in outcome["reason"]

    def test_llm_failure_abandons_without_row(self, aut_on, monkeypatch):
        goal = _make_goal()

        def _boom(messages, settings):
            raise RuntimeError("gateway down")

        monkeypatch.setattr(planning, "_ask_llm_with_retry", _boom)
        outcome = planning.plan_goal(goal.id, planning.TRIGGER_CREATED)
        assert outcome["status"] == "llm_failed"
        assert goal_repository.count_plans(goal.id) == 0


class TestJobHandler:
    def test_runtime_registration(self, override_settings):
        override_settings()
        planning.register_runtime()
        assert (
            memory2_job_worker._JOB_HANDLERS[planning.JOB_TYPE_PLANNING]
            is planning.run_planning_jobs
        )

    def test_handler_processes_running_job(self, aut_on):
        goal = _make_goal()
        _running_job(goal.id)
        processed = planning.run_planning_jobs()
        assert processed == 1
        latest = goal_repository.get_latest_plan(goal.id)
        assert latest is not None and latest.status == "active"


class TestLifeLoopSupplyStep:

    def test_step_throttled_within_interval(self, aut_on, monkeypatch):
        from app.application import life_loop

        monkeypatch.setattr(
            planning, "materialize", lambda user_id, world_facts=None, now=None: {"status": "ok"}
        )
        first = life_loop._step_goal_supply(USER, NOW)
        second = life_loop._step_goal_supply(USER, NOW)
        assert first["status"] == "ok"
        assert second["skip_reason"] == "throttled"
        life_loop._supply_last.clear()

    def test_step_wires_world_facts_and_creates(self, aut_on, override_settings, monkeypatch):
        from app.application import life_loop

        override_settings(world_enabled="true")
        captured: dict = {}

        def _fake_materialize(user_id, world_facts=None, now=None):
            captured["world_facts"] = world_facts
            return {"status": "ok", "created": ["g1"], "enqueued": 1}

        monkeypatch.setattr(planning, "materialize", _fake_materialize)
        monkeypatch.setattr(
            life_loop.world_engine, "collect_facts", lambda user_id: {"weather": "rain"}
        )
        detail = life_loop._step_goal_supply(USER, NOW)
        life_loop._supply_last.clear()
        assert detail["created"] == ["g1"]
        assert captured["world_facts"] == {"weather": "rain"}


def test_trace_step_registered():
    from app.services.trace_collector import TRACE_STEP_NAMES

    assert "goal_planning" in TRACE_STEP_NAMES
