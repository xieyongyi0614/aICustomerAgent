"""DEV-004：回退与重放。

rollback_for_insight（无受影响 key/有次优提升/无次优 retire/重复事件幂等）、
失效事件 → 回退 job → read_overlay 回退端到端（含 observe_negation 反驳通道）、
verify_replay（重放=在线/漂移检测/原始审计行零改动）、rebuild 重建与
changes_unattributed 归因兜底、Flag OFF 无监听零回退。
"""

from datetime import datetime

import pytest

from app.core.db import BackgroundJobRow, DevelopmentStateRow, InsightRow
from app.models.reflection import Insight
from app.services.development import aggregate
from app.services.development import audit
from app.services.development import policy as development_policy
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.reflection import lifecycle as reflection_lifecycle

pytestmark = pytest.mark.xdist_group("development")

USER = "u-roll"
STATEMENT = "用户偏好简短的回复"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


@pytest.fixture(autouse=True)
def _reset_listeners():
    yield
    reflection_lifecycle.reset_invalidation_listeners()
    reflection_lifecycle.reset_insight_created_listeners()


def _seed_insight(
    session_factory,
    insight_id,
    *,
    statement=STATEMENT,
    confidence=0.8,
    created_at=None,
    status="active",
):
    now = created_at or datetime(2026, 9, 1, 8, 0, 0)
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=USER,
                character_id="asuna",
                statement=statement,
                type="preference",
                confidence=confidence,
                scope="user",
                status=status,
                invalidated_reason="seed" if status == "invalidated" else None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return insight_id


def _compile(session_factory, insight_id):
    from app.core.settings import get_settings as _gs

    with session_factory() as session:
        row = session.get(InsightRow, insight_id)
        insight = Insight(
            id=row.id,
            user_id=row.user_id,
            character_id=row.character_id,
            statement=row.statement,
            type=row.type,
            confidence=row.confidence,
            scope=row.scope,
            status=row.status,
            run_id=row.run_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    return development_policy.compile_insight(insight, _gs())


def _apply(session_factory, insight_id):
    for proposal in _compile(session_factory, insight_id):
        aggregate.upsert_modulation(
            USER,
            proposal.kind,
            proposal.key,
            proposal.value,
            proposal.strength,
            proposal.insight_id,
            source_insight_created_at=proposal.insight_created_at,
            comparator=development_policy.arbitration_comparator,
        )


def _dev_rows(session_factory, statuses=None):
    with session_factory() as session:
        query = session.query(DevelopmentStateRow).filter(
            DevelopmentStateRow.user_id == USER
        )
        if statuses:
            query = query.filter(DevelopmentStateRow.status.in_(statuses))
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


def test_rollback_without_affected_keys(db_session_factory):
    report = audit.rollback_for_insight(USER, "ins-none")
    assert report == {"affected_keys": [], "actions": []}


def test_rollback_promotes_next_best(db_session_factory):
    _seed_insight(
        db_session_factory, "ins-weak", confidence=0.5, created_at=datetime(2026, 9, 1)
    )
    _seed_insight(
        db_session_factory, "ins-strong", confidence=0.9, created_at=datetime(2026, 9, 3)
    )
    _apply(db_session_factory, "ins-weak")
    _apply(db_session_factory, "ins-strong")
    assert reflection_lifecycle.invalidate_insight("ins-strong", "其实我最近话多") is True
    report = audit.rollback_for_insight(USER, "ins-strong")
    assert report["affected_keys"] == [
        "response_style.length",
        "response_style.tone",
    ]
    assert all(
        action["action"] == "promoted" and action["outcome"] == "created"
        for action in report["actions"]
    )
    actives = aggregate.list_active_modulations(USER)
    assert {item.source_insight_id for item in actives} == {"ins-weak"}
    history = aggregate.get_state_history(actives[0].id)
    assert history[-1].reason == "rolled_back"
    assert history[-1].insight_id == "ins-weak"
    with db_session_factory() as session:
        strong_rows = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == USER,
                DevelopmentStateRow.source_insight_id == "ins-strong",
            )
            .all()
        )
        for row in strong_rows:
            session.expunge(row)
    assert {row.status for row in strong_rows} == {"retired"}
    for row in strong_rows:
        retracted = aggregate.get_state_history(row.id)[-1]
        assert retracted.after is None
        assert retracted.insight_id == "ins-strong"


def test_rollback_retries_modulation_without_successor(db_session_factory):
    _seed_insight(db_session_factory, "ins-only", confidence=0.8)
    _apply(db_session_factory, "ins-only")
    assert aggregate.list_active_modulations(USER)
    reflection_lifecycle.invalidate_insight("ins-only", "其实我最近话多")
    report = audit.rollback_for_insight(USER, "ins-only")
    assert all(action["action"] == "retired" for action in report["actions"])
    assert aggregate.list_active_modulations(USER) == []
    assert {row.status for row in _dev_rows(db_session_factory)} == {"retired"}
    retired = _dev_rows(db_session_factory)[0]
    history = aggregate.get_state_history(retired.id)
    assert history[-1].reason == "rolled_back"
    assert history[-1].after is None


def test_rollback_is_idempotent_on_repeat_events(db_session_factory):
    _seed_insight(db_session_factory, "ins-only", confidence=0.8)
    _apply(db_session_factory, "ins-only")
    reflection_lifecycle.invalidate_insight("ins-only", "其实我最近话多")
    first = audit.rollback_for_insight(USER, "ins-only")
    second = audit.rollback_for_insight(USER, "ins-only")
    assert second["affected_keys"] == []
    retired = _dev_rows(db_session_factory)
    assert len(retired) == 2
    assert {row.key for row in retired} == {
        "response_style.length",
        "response_style.tone",
    }


def test_refute_to_rollback_end_to_end(db_session_factory, override_settings):
    override_settings(v2_development_enabled=True, v2_reflection_enabled=True)
    audit.register_rollback_listener()
    _seed_insight(db_session_factory, "ins-e2e", confidence=0.8)
    assert development_policy.compile_insight_by_id("ins-e2e") is True
    overlay = aggregate.read_overlay(USER)
    assert overlay is not None and overlay.sources
    invalidated = reflection_lifecycle.observe_negation(
        USER, "mem-1", STATEMENT, trace=None
    )
    assert invalidated == ["ins-e2e"]
    with db_session_factory() as session:
        jobs = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == audit.JOB_TYPE_ROLLBACK)
            .all()
        )
        assert len(jobs) == 1 and jobs[0].status == "pending"
    memory2_job_worker.run_job_tick()
    assert aggregate.list_active_modulations(USER) == []
    assert aggregate.read_overlay(USER) is None


def test_verify_replay_consistent_and_untouched(db_session_factory):
    _seed_insight(db_session_factory, "ins-a", confidence=0.8)
    _apply(db_session_factory, "ins-a")
    before_rows = _dev_rows(db_session_factory)
    report = audit.verify_replay(USER)
    assert report["consistent"] is True
    assert report["diffs"] == []
    assert report["changes_unattributed"] == 0
    def _snapshot(rows):
        return sorted((row.id, row.status, row.key, str(row.value)) for row in rows)

    assert _snapshot(_dev_rows(db_session_factory)) == _snapshot(before_rows)


def test_verify_replay_detects_drift(db_session_factory):
    _seed_insight(db_session_factory, "ins-a", confidence=0.8)
    _apply(db_session_factory, "ins-a")
    with db_session_factory() as session:
        row = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == USER, DevelopmentStateRow.key
                    == "response_style.length")
            .one()
        )
        row.value = {"max_tokens_delta": -1}
        session.commit()
    report = audit.verify_replay(USER)
    assert report["consistent"] is False
    assert report["diffs"][0]["key"] == "response_style.length"
    assert report["diffs"][0]["online"] == "ins-a"


def test_verify_replay_counts_unattributed_changes(db_session_factory):
    _seed_insight(db_session_factory, "ins-a", confidence=0.8)
    _apply(db_session_factory, "ins-a")
    with db_session_factory() as session:
        row = session.get(InsightRow, "ins-a")
        session.delete(row)
        session.commit()
    report = audit.verify_replay(USER)
    assert report["changes_unattributed"] >= 1


def test_rebuild_reconstructs_state(db_session_factory):
    _seed_insight(db_session_factory, "ins-a", confidence=0.8)
    _apply(db_session_factory, "ins-a")
    with db_session_factory() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(DevelopmentStateRow.user_id == USER)
            .all()
        )
        for row in rows:
            row.value = {"max_tokens_delta": -1}
        session.commit()
    report = audit.verify_replay(USER, rebuild=True)
    assert report["rebuild"] == 2
    rebuilt = aggregate.list_active_modulations(USER)
    assert {item.source_insight_id for item in rebuilt} == {"ins-a"}
    length = [item for item in rebuilt if item.key == "response_style.length"][0]
    assert length.value == {"max_tokens_delta": -160}
    assert report["consistent"] is True


def test_flag_off_no_listener_no_rollback_jobs(db_session_factory):
    _seed_insight(db_session_factory, "ins-x", confidence=0.8)
    _apply(db_session_factory, "ins-x")
    reflection_lifecycle.invalidate_insight("ins-x", "其实我最近话多")
    with db_session_factory() as session:
        jobs = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == audit.JOB_TYPE_ROLLBACK)
            .all()
        )
        assert jobs == []


def test_rollback_listener_registration_is_idempotent():
    audit.register_rollback_listener()
    audit.register_rollback_listener()
    handlers = memory2_job_worker._JOB_HANDLERS
    assert handlers[audit.JOB_TYPE_ROLLBACK] is audit.run_rollback_jobs
    assert (
        reflection_lifecycle._invalidation_listeners.count(audit.on_invalidation) >= 1
    )
    reflection_lifecycle.reset_invalidation_listeners()
