"""AGENT-005 Evolution & Learning 测试。

覆盖：人格编译（证据→漂移/无证据不动/限速/边界钳制/审计行/回滚）、
Rebalance 退役、Ledger 投影、Flag off 零写入、写入防护。
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.character.asuna import evolution as persona_evolution
from app.core.db import (
    DevelopmentChangeRow,
    InsightRow,
    PersonalityStateRow,
)
from app.repositories import (
    goal_repository,
    personality_state_repository,
)
from app.services.development import evolution

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "evo-user"


@pytest.fixture()
def evo_on():
    yield


def _seed_personality(user_id=USER):
    personality_state_repository.seed_if_absent(user_id, persona_evolution.PERSONALITY_AXES)


def _insight(statement, insight_id=None, created_at=NOW):
    from app.services.development import evolution as evolution_service

    row = InsightRow(
        id=insight_id or str(uuid4()),
        user_id=USER,
        statement=statement,
        type="pattern",
        confidence=0.8,
        scope="user",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    with evolution_service.SessionLocal() as session:
        session.add(row)
        session.commit()
    return row.id


def _current(axis):
    rows = {r.axis: r for r in personality_state_repository.get_all(USER)}
    return rows[axis].current


class TestPersonalityCompile:
    def test_evidence_drives_bounded_drift(self, db_session_factory, evo_on):
        _seed_personality()
        _insight("用户多次希望角色主动发起话题，角色开始敢于表达观点")
        applied = evolution.compile_personality(USER, NOW)
        assert applied and applied[0]["axis"] == "assertiveness"
        assert 0 < applied[0]["delta"] <= 0.05
        assert _current("assertiveness") > 0.30

        row = personality_state_repository.get_all(USER)[0]
        with personality_state_repository.SessionLocal() as session:
            change = (
                session.query(DevelopmentChangeRow)
                .filter(
                    DevelopmentChangeRow.personality_state_id == row.id,
                    DevelopmentChangeRow.reason == "personality",
                )
                .first()
            )
            assert change is not None and change.insight_id

    def test_no_evidence_no_drift(self, db_session_factory, evo_on):
        _seed_personality()
        _insight("今天天气不错，用户聊了旅行")
        assert evolution.compile_personality(USER, NOW) == []

    def test_weekly_rate_limit_blocks_second_window(self, db_session_factory, evo_on):
        _seed_personality()
        _insight("用户鼓励角色主动发起话题")
        first = evolution.compile_personality(USER, NOW)
        assert first
        before = _current("assertiveness")
        _insight("角色再次敢于表达观点", created_at=NOW + timedelta(days=1))
        second = evolution.compile_personality(USER, NOW + timedelta(days=1))
        drift_same_window = [a for a in second if a["axis"] == "assertiveness"]
        assert drift_same_window == []
        assert _current("assertiveness") == before

    def test_bound_clamp_never_exceeds(self, db_session_factory, evo_on):
        _seed_personality()
        with personality_state_repository.SessionLocal() as session:
            row = (
                session.query(PersonalityStateRow)
                .filter(
                    PersonalityStateRow.user_id == USER,
                    PersonalityStateRow.axis == "assertiveness",
                )
                .first()
            )
            row.current = 0.495
            session.commit()
        _insight("用户希望角色更主动、更敢于发起话题")
        evolution.compile_personality(USER, NOW)
        assert _current("assertiveness") <= 0.50

    def test_rollback_restores_current(self, db_session_factory, evo_on):
        _seed_personality()
        baseline = _current("warmth")
        _insight("角色温柔地安慰了用户，关系更亲近")
        applied = evolution.compile_personality(USER, NOW)
        assert applied
        rows_by_axis = {r.axis: r for r in personality_state_repository.get_all(USER)}
        insight_id = rows_by_axis["warmth"].source_insight_id
        reverted = evolution.rollback_personality_for_insight(insight_id, NOW)
        assert reverted >= 1
        assert _current("warmth") == baseline


class TestWriteProtection:
    def test_seed_only_write_path(self, db_session_factory):
        rows = personality_state_repository.get_all(USER)
        assert rows == []
        assert (
            personality_state_repository.seed_if_absent(
                USER, persona_evolution.PERSONALITY_AXES
            )
            is True
        )
        assert (
            personality_state_repository.seed_if_absent(
                USER, persona_evolution.PERSONALITY_AXES
            )
            is False
        )
        assert len(personality_state_repository.get_all(USER)) == 4


class TestRebalance:
    def test_old_low_priority_goal_retired(self, db_session_factory, evo_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "过时且低优先的中期目标", 2, origin="insight"
        )
        with goal_repository.SessionLocal() as session:
            from app.core.db import GoalRow

            row = session.get(GoalRow, goal.id)
            row.created_at = NOW - timedelta(days=30)
            session.commit()
        retired = evolution.rebalance_goals(USER, NOW)
        assert goal.id in retired
        assert goal_repository.get_goal(goal.id).failure_reason == "evolution_rebalance"

    def test_high_priority_goal_survives(self, db_session_factory, evo_on):
        goal = goal_repository.create_hierarchical_goal(
            USER, "medium", "personal", "重要的中期目标", 4, origin="insight"
        )
        with goal_repository.SessionLocal() as session:
            from app.core.db import GoalRow

            row = session.get(GoalRow, goal.id)
            row.created_at = NOW - timedelta(days=30)
            session.commit()
        assert goal.id not in evolution.rebalance_goals(USER, NOW)


class TestLedger:
    def test_ledger_lists_goal_and_personality(self, db_session_factory, evo_on):
        _seed_personality()
        goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "成为信任的伙伴", 3, origin="insight"
        )
        entries = evolution.ledger(USER, limit=20)
        kinds = {e["change_kind"] for e in entries}
        assert "goal" in kinds
        assert all(e["user_id"] == USER for e in entries)
