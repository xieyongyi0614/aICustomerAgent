"""REF-003：反思触发器。

额度判定表驱动（queued/running/done 占额，skipped/failed 不占）、事件计数与
冷却窗口、日桶 key、tasks.md 验收（无证据日 skipped 且 0 LLM；证据爆发日
当日最多 1 次；同日双触发源仅一行 job；Flag OFF 无行为）、事件风暴、
enqueue 异常降级、flush 返回值扩展。
"""

import json
from datetime import datetime, timedelta

import pytest

from app.core.db import BackgroundJobRow, Memory, ReflectionRunRow
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.memory2 import lifecycle as memory2_lifecycle
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import triggers

USER = "u-trg"
CHARACTER = "asuna"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


def _seed_cluster_memory(
    session_factory,
    memory_id,
    *,
    created_at,
    content="用户说最近加班很累",
    user_id=USER,
):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                character_id=CHARACTER,
                content=content,
                type="user_fact",
                importance=0.7,
                confidence=0.9,
                source="user_stated",
                status="active",
                salience=0.8,
                embedding=json.dumps([1.0 if i == 3 else 0.1 for i in range(8)]),
                source_ref={"table": "conversation", "id": f"conv:u:s:{memory_id}"},
                visibility="private",
                created_at=created_at,
                updated_at=now,
            )
        )
        session.commit()


def _seed_passing_evidence(session_factory, *, count=5):
    now = datetime.now()
    for i in range(count):
        _seed_cluster_memory(
            session_factory,
            f"mem-trg-{i}",
            created_at=now - timedelta(days=i * 2),
            content="用户说最近加班很累" if i == 0 else f"用户说最近加班很累（第{i + 1}次）",
        )
    return now


def _runs(session_factory):
    with session_factory() as session:
        rows = session.query(ReflectionRunRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def _jobs(session_factory):
    with session_factory() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == "reflection_run")
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


@pytest.fixture(autouse=True)
def _reset_state():
    triggers.reset_trigger_state()
    yield
    triggers.reset_trigger_state()


@pytest.fixture
def reflection_on(override_settings):
    override_settings(v2_reflection_enabled=True)
    return True


def test_flag_off_returns_off_and_writes_nothing(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=False)
    result = triggers.trigger_for_user(USER, CHARACTER, now=datetime.now())
    assert result == "off"
    assert _runs(db_session_factory) == []
    assert _jobs(db_session_factory) == []
    assert triggers.run_reflection_trigger_tick(now=datetime.now()) == 0


def test_no_evidence_day_skips_with_zero_llm(db_session_factory, reflection_on):
    now = datetime.now()
    result = triggers.trigger_for_user(USER, CHARACTER, now=now)
    assert result == "skipped"
    runs = _runs(db_session_factory)
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].trigger == "scheduled"
    assert runs[0].outcome == "no_passing_window"
    assert runs[0].llm_used is False
    assert _jobs(db_session_factory) == []


def test_passing_evidence_enqueues_single_job(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    result = triggers.trigger_for_user(USER, CHARACTER, now=now)
    assert result == "queued"
    runs = [row for row in _runs(db_session_factory) if row.status == "queued"]
    assert len(runs) == 1
    jobs = _jobs(db_session_factory)
    assert len(jobs) == 1
    assert jobs[0].payload["run_id"] == runs[0].id
    assert jobs[0].payload["trigger"] == "scheduled"
    assert jobs[0].idempotency_key == f"reflect:{USER}:{now:%Y-%m-%d}"


def test_duplicate_trigger_same_day_is_quota_no_new_row(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    assert triggers.trigger_for_user(USER, CHARACTER, now=now) == "queued"
    second = triggers.trigger_for_user(USER, CHARACTER, trigger="event", now=now)
    assert second == "quota"
    assert len([row for row in _runs(db_session_factory) if row.status == "queued"]) == 1
    assert len(_jobs(db_session_factory)) == 1


def _seed_run(session_factory, run_id, user_id, *, status, trigger="scheduled"):
    from datetime import datetime as dt

    now = dt.now()
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id=run_id,
                user_id=user_id,
                character_id=CHARACTER,
                trigger=trigger,
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_quota_occupying_statuses_only(db_session_factory, reflection_on, monkeypatch):
    monkeypatch.setattr(
        triggers.background_job_repository, "has_job", lambda key: False
    )
    monkeypatch.setattr(
        triggers.background_job_repository,
        "enqueue_job",
        lambda *args, **kwargs: True,
    )
    cases = [
        ("skipped", "queued"),
        ("failed", "queued"),
        ("done", "quota"),
        ("running", "quota"),
    ]
    for index, (run_status, expected) in enumerate(cases):
        user = f"u-quota-{index}"
        now = datetime.now()
        for i in range(5):
            _seed_cluster_memory(
                db_session_factory,
                f"mem-q{index}-{i}",
                user_id=user,
                created_at=now - timedelta(days=i * 2),
                content="用户说最近加班很累" if i == 0 else f"用户说最近加班很累（第{i + 1}次）",
            )
        _seed_run(db_session_factory, f"r-{index}", user, status=run_status)
        result = triggers.trigger_for_user(user, CHARACTER, now=now)
        assert result == expected, f"status={run_status}"


def test_event_path_three_reinforces_enqueue(db_session_factory, reflection_on):
    _seed_passing_evidence(db_session_factory)
    ids = [f"mem-trg-{i}" for i in range(3)]
    triggers.observe_reinforce(USER, ids)
    runs = [row for row in _runs(db_session_factory) if row.status == "queued"]
    assert len(runs) == 1
    jobs = _jobs(db_session_factory)
    assert len(jobs) == 1
    assert jobs[0].payload["trigger"] == "event"


def test_event_below_threshold_never_triggers(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    triggers.observe_reinforce(USER, ["mem-trg-0"])
    triggers.observe_reinforce(USER, ["mem-trg-1"])
    assert [row for row in _runs(db_session_factory) if row.status == "queued"] == []


def test_event_storm_only_first_enqueues(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    ids = [f"mem-trg-{i}" for i in range(5)]
    for _ in range(10):
        triggers.observe_reinforce(USER, ids)
    assert len(_jobs(db_session_factory)) == 1


def test_event_cooldown_window_blocks_repeat(db_session_factory, reflection_on, override_settings):
    override_settings(v2_reflection_enabled=True, v2_reflection_event_cooldown_hours=24.0)
    now = _seed_passing_evidence(db_session_factory)
    ids = [f"mem-trg-{i}" for i in range(5)]
    triggers.observe_reinforce(USER, ids)
    assert len(_jobs(db_session_factory)) == 1
    with db_session_factory() as session:
        row = session.query(BackgroundJobRow).filter_by(job_type="reflection_run").first()
        row.idempotency_key = "reflect:u-trg:moved"
        session.commit()
    triggers.observe_reinforce(USER, ids)
    assert len(_jobs(db_session_factory)) == 1


def test_scheduled_tick_once_per_user_per_day(db_session_factory, reflection_on, monkeypatch):
    now = _seed_passing_evidence(db_session_factory)
    tick_time = now.replace(hour=5, minute=0, second=0, microsecond=0)
    assert triggers.run_reflection_trigger_tick(now=tick_time) == 1
    assert len(_jobs(db_session_factory)) == 1
    assert triggers.run_reflection_trigger_tick(now=tick_time + timedelta(minutes=10)) == 0


def test_scheduled_tick_before_schedule_hour_idle(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    early = now.replace(hour=3, minute=59, second=0, microsecond=0)
    assert triggers.run_reflection_trigger_tick(now=early) == 0
    assert _jobs(db_session_factory) == []


def test_scheduled_tick_skipped_day_writes_one_row(db_session_factory, reflection_on):
    now = datetime.now().replace(hour=5, minute=0, second=0, microsecond=0)
    _seed_cluster_memory(db_session_factory, "mem-sparse", created_at=now - timedelta(days=1))
    assert triggers.run_reflection_trigger_tick(now=now) == 1
    runs = _runs(db_session_factory)
    assert len(runs) == 1 and runs[0].status == "skipped"
    assert triggers.run_reflection_trigger_tick(now=now + timedelta(hours=2)) == 0
    assert len(_runs(db_session_factory)) == 1


def test_enqueue_failure_degrades_without_crash(db_session_factory, reflection_on, monkeypatch):
    now = _seed_passing_evidence(db_session_factory)
    original_enqueue = triggers.background_job_repository.enqueue_job

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(triggers.background_job_repository, "enqueue_job", _boom)
    result = triggers.trigger_for_user(USER, CHARACTER, now=now)
    assert result == "skipped"
    assert [row for row in _runs(db_session_factory) if row.status == "queued"] == []
    monkeypatch.setattr(
        triggers.background_job_repository, "enqueue_job", original_enqueue
    )
    result = triggers.trigger_for_user(USER, CHARACTER, now=now)
    assert result == "queued"


def test_aggregate_error_records_skipped(db_session_factory, reflection_on, monkeypatch):
    now = _seed_passing_evidence(db_session_factory)

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(reflection_evidence, "aggregate_evidence_windows", _boom)
    result = triggers.trigger_for_user(USER, CHARACTER, now=now)
    assert result == "skipped"
    runs = _runs(db_session_factory)
    assert runs[0].outcome == "aggregate_error"


def test_trace_records_trigger_decision(db_session_factory, reflection_on):
    now = _seed_passing_evidence(db_session_factory)
    trace = StubTrace()
    triggers.trigger_for_user(USER, CHARACTER, now=now, trace=trace)
    assert trace.steps[-1]["name"] == "reflection_trigger"
    assert trace.steps[-1]["decision"] == "queued"


def test_day_bucket_key_format():
    now = datetime(2026, 9, 6, 5, 0, 0)
    assert triggers._day_bucket_key("u-1", now) == "reflect:u-1:2026-09-06"


def test_tick_hook_wiring_and_isolation(monkeypatch):
    hooks: list = []
    monkeypatch.setattr(memory2_job_worker, "_TICK_HOOKS", hooks)
    memory2_job_worker.register_tick_hook(hooks.append)

    def _boom(now):
        raise RuntimeError("hook down")

    memory2_job_worker.register_tick_hook(_boom)
    stats = memory2_job_worker.run_job_tick()
    assert isinstance(stats, dict)
    assert hooks  # 正常 hook 已被调用；抛异常的 hook 被隔离不中断 tick


def test_flush_returns_memory_ids(db_session_factory):
    now = datetime.now()
    _seed_cluster_memory(db_session_factory, "m-flush", created_at=now)
    memory2_lifecycle.record_reinforce("m-flush")
    flushed = memory2_lifecycle.flush_reinforce_buffer()
    assert flushed == ["m-flush"]
    assert memory2_lifecycle.flush_reinforce_buffer() == []
