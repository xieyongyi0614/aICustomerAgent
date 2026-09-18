"""AGENT-006 Agent Evaluation 测试。

覆盖：六指标出分（缺材料 None）、快照幂等、趋势越限与演化议题、
Reflection 触发通道联动、Flag off 零行为、enablement 依赖。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.db import DecisionRecordRow
from app.repositories import (
    action_repository,
    agent_metric_repository,
    goal_repository,
)
from app.services import agent_evaluation

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "metric-user"


@pytest.fixture()
def metrics_on(override_settings):
    override_settings(
        AGENT_RUNTIME_ENABLED="true",
        AGENT_METRICS_ENABLED="true",
        GOAL_STACK_ENABLED="true",
    )
    yield


def _action(status, created_at=NOW):
    from app.core.db import ActionRecordRow, SessionLocal

    row = ActionRecordRow(
        id=str(uuid4()),
        user_id=USER,
        session_id=None,
        action_type="query_search",
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    with action_repository.SessionLocal() as session:
        session.merge(row)
        session.commit()
    return row.id


def _decision(candidates=None, outcome=None, created_at=NOW):
    from app.repositories import decision_repository

    record = decision_repository.new_decision_id()
    from app.models.observability import DecisionKind, DecisionRecord

    decision_repository.save(
        DecisionRecord(
            id=record,
            kind=DecisionKind.PROACTIVE_AUTONOMY,
            user_id=USER,
            decision="act",
            outcome=outcome,
            candidates=candidates,
            created_at=created_at,
        )
    )
    return record


class TestSnapshot:
    def test_flag_off_skips(self, db_session_factory, override_settings):
        override_settings(AGENT_METRICS_ENABLED="false")
        result = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert result["status"] == "skipped"

    def test_snapshot_idempotent_per_window(self, db_session_factory, metrics_on):
        first = agent_evaluation.run_daily_snapshot(USER, NOW)
        second = agent_evaluation.run_daily_snapshot(USER, NOW + timedelta(hours=1))
        assert first["status"] == "ok" and second["status"] == "ok"
        rows = agent_metric_repository.list_recent(USER, limit=10)
        assert len(rows) == 1

    def test_metrics_missing_material_is_none(self, db_session_factory, metrics_on):
        result = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert result["metrics"]["action_quality"] is None
        assert result["metrics"]["decision_quality"] is None
        assert result["metrics"]["memory_accuracy"] is None

    def test_action_quality_computed(self, db_session_factory, metrics_on):
        _action("succeeded")
        _action("failed")
        result = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert result["metrics"]["action_quality"] == 0.5

    def test_decision_quality_uses_candidates(self, db_session_factory, metrics_on):
        _decision(
            candidates={"candidates": [{"source": "goal_compile", "won": True}]},
            outcome="delivered",
        )
        result = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert result["metrics"]["decision_quality"] == 1.0

    def test_goal_progress_computed(self, db_session_factory, metrics_on):
        goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "成为信任的伙伴", 3, origin="insight"
        )
        result = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert result["metrics"]["goal_progress"] == 1.0


class TestTrendAndTopics:
    def test_breach_emits_topic_and_reflection_trigger(
        self, db_session_factory, metrics_on, monkeypatch
    ):
        from app.services.reflection import triggers as reflection_triggers

        fired = []
        monkeypatch.setattr(
            reflection_triggers,
            "trigger_for_user",
            lambda user_id, trigger, now=None: fired.append((user_id, trigger)) or "queued",
        )
        _action("failed")
        first = agent_evaluation.run_daily_snapshot(USER, NOW)
        assert first["topics"] == []
        next_day = NOW + timedelta(days=1)
        _action("failed", created_at=next_day)
        second = agent_evaluation.run_daily_snapshot(USER, next_day)
        assert second["trend"]["action_quality"]["breached"] is True
        assert second["topics"] and fired == [(USER, "event")]


class TestEnablement:
    def test_metrics_requires_runtime(self, override_settings):
        from app.core.settings import get_settings
        from app.core.settings.enablement import enablement_violations

        override_settings(AGENT_METRICS_ENABLED="true")
        assert any(
            "agent_metrics_enabled" in v
            for v in enablement_violations(get_settings())
        )
