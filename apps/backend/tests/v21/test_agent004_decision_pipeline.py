"""AGENT-004 Decision Pipeline 测试。

覆盖：五段管线（silence 恒在/优先级铁律/意图映射）、预算闸拒绝→silence 胜出、
管线失败回退、autonomy 接线（flag on 审计落库/flag off 零行为）、
enablement/幂等。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import llm_gateway
from app.services import decision_pipeline, goal_stack

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "decision-user"


def _stack(short_type="user_care"):
    stack = goal_stack.GoalStack()
    stack.short_term = SimpleNamespace(
        id="g1",
        type=short_type,
        domain="personal",
        description="陪伴用户",
        priority=4,
        created_at=NOW,
    )
    return stack


class TestPipeline:
    def test_silence_wins_when_no_candidates(self, override_settings):
        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        result = decision_pipeline.run_pipeline(run=None, now=NOW)
        assert result.winner.source == "silence"
        assert result.intention is None
        sources = [c["source"] for c in result.audit["candidates"]]
        assert sources == ["silence"]

    def test_goal_compile_beats_capability_and_silence(self, db_session_factory, override_settings):
        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        result = decision_pipeline.run_pipeline(
            stack=_stack(), capabilities=["reminder"], run=None, now=NOW
        )
        assert result.winner.source == "goal_compile"
        assert result.winner.priority < 3
        assert result.intention == "comfort_user"
        audit = {c["source"]: c for c in result.audit["candidates"]}
        assert audit["capability"]["priority"] == "P3"
        assert audit["silence"]["priority"] == "P4"

    def test_autonomy_trigger_intention_passthrough(self, override_settings):
        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        result = decision_pipeline.run_pipeline(
            trigger_intention="check_in", trigger_goal_id=None, run=None, now=NOW
        )
        assert result.winner.source == "autonomy_trigger"
        assert result.intention == "check_in"

    def test_budget_denied_falls_to_silence(self, db_session_factory, override_settings, monkeypatch):
        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        monkeypatch.setattr(
            llm_gateway,
            "acquire",
            lambda *a, **k: SimpleNamespace(granted=False, degraded=False, reason="quota_circuit_open"),
        )
        result = decision_pipeline.run_pipeline(stack=_stack(), run=None, now=NOW)
        assert result.winner.source == "silence"
        audit = {c["source"]: c for c in result.audit["candidates"]}
        assert audit["goal_compile"]["gates"][-1]["budget_cooldown"] == "rejected"

    def test_audit_answers_four_questions(self, db_session_factory, override_settings):
        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        result = decision_pipeline.run_pipeline(stack=_stack(), run=None, now=NOW)
        winner_audit = next(
            c for c in result.audit["candidates"] if c["won"]
        )
        assert winner_audit["priority"] and winner_audit["scores"]
        assert winner_audit["gates"] and winner_audit["source"]


class TestAutonomyWiring:
    def test_pipeline_intention_flag_off_noop(self, override_settings):
        from app.application import autonomy_engine

        override_settings(V21_AGENT_RUNTIME_ENABLED="false")
        verdict = SimpleNamespace(intention="check_in", goal_id=None)
        intention, audit = autonomy_engine._pipeline_intention(verdict, USER, NOW)
        assert intention is None and audit is None

    def test_pipeline_intention_flag_on(self, db_session_factory, override_settings):
        from app.application import autonomy_engine

        override_settings(V21_AGENT_RUNTIME_ENABLED="true", V21_GOAL_STACK_ENABLED="true")
        verdict = SimpleNamespace(intention="check_in", goal_id=None)
        intention, audit = autonomy_engine._pipeline_intention(verdict, USER, NOW)
        assert audit is not None and "candidates" in audit
        assert intention is None or isinstance(intention, str)

    def test_pipeline_failure_falls_back(self, db_session_factory, override_settings, monkeypatch):
        from app.application import autonomy_engine

        override_settings(V21_AGENT_RUNTIME_ENABLED="true")
        monkeypatch.setattr(
            decision_pipeline,
            "run_pipeline",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        verdict = SimpleNamespace(intention="check_in", goal_id=None)
        intention, audit = autonomy_engine._pipeline_intention(verdict, USER, NOW)
        assert intention is None and audit is None
