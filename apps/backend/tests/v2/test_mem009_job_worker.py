import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import timeutil
from app.core.db import Base, BackgroundJobRow, Memory as MemoryRow
from app.core.settings import get_settings
from app.repositories import background_job_repository, memory_repository
from app.services.memory import embeddings, job_worker, lifecycle


@pytest.fixture
def job_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (
        background_job_repository,
        job_worker,
        lifecycle,
        memory_repository,
    ):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    lifecycle.reset_reinforce_buffer()
    embeddings.reset_queue()
    monkeypatch.setattr(embeddings, "EMBED_RETRY_BACKOFF_SECONDS", 0)
    yield
    lifecycle.reset_reinforce_buffer()
    embeddings.reset_queue()


def _enqueue(job_type="memory_decay", key="k1", payload=None, status="pending",
             run_at=None, attempts=0):
    with job_worker.SessionLocal() as session:
        session.add(
            BackgroundJobRow(
                id=f"job-{key}",
                job_type=job_type,
                payload=payload or {},
                status=status,
                attempts=attempts,
                run_at=run_at or timeutil.now(),
                idempotency_key=key,
                created_at=timeutil.now(),
            )
        )
        session.commit()


def _job(key):
    with job_worker.SessionLocal() as session:
        row = session.get(BackgroundJobRow, f"job-{key}")
        if row is None:
            return None
        session.refresh(row)
        session.expunge(row)
        return row


class TestEnqueue:
    def test_decay_daily_bucket_enqueued_once(self, job_db):
        assert job_worker._enqueue_due_decay(datetime.datetime(2026, 9, 5, 10, 0)) is True
        assert job_worker._enqueue_due_decay(datetime.datetime(2026, 9, 5, 18, 0)) is False
        jobs = background_job_repository.list_jobs("memory_decay")
        assert len(jobs) == 1
        assert jobs[0].idempotency_key == "memory_decay:2026-09-05"

    def test_duplicate_key_rejected(self, job_db):
        assert background_job_repository.enqueue_job("x", {}, "same") is True
        assert background_job_repository.enqueue_job("x", {}, "same") is False
        assert len(background_job_repository.list_jobs("x")) == 1


class TestStateMachine:
    def test_pending_claimed_to_running_then_done(self, job_db, monkeypatch):
        executed = []
        monkeypatch.setitem(
            job_worker._JOB_HANDLERS, "memory_decay", lambda: executed.append(1)
        )
        _enqueue(key="k1")
        done, retried, failed = job_worker._claim_and_execute(timeutil.now())
        assert (done, retried, failed) == (1, 0, 0)
        assert executed == [1]
        assert _job("k1").status == "done"

    def test_exception_retries_with_backoff(self, job_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "job_retry_backoff_seconds", 10)
        calls = {"n": 0}

        def _boom():
            calls["n"] += 1
            raise RuntimeError("handler down")

        monkeypatch.setitem(job_worker._JOB_HANDLERS, "memory_decay", _boom)
        _enqueue(key="k1")
        now = timeutil.now()
        done, retried, failed = job_worker._claim_and_execute(now)
        assert (done, retried, failed) == (0, 1, 0)
        job = _job("k1")
        assert job.status == "pending"
        assert job.attempts == 1
        assert "RuntimeError" in job.last_error
        assert job.run_at >= now + datetime.timedelta(seconds=10)

    def test_max_attempts_dead_letter(self, job_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "job_max_attempts", 5)
        monkeypatch.setattr(get_settings(), "job_retry_backoff_seconds", 0)

        def _boom():
            raise RuntimeError("always")

        monkeypatch.setitem(job_worker._JOB_HANDLERS, "memory_decay", _boom)
        now = timeutil.now()
        _enqueue(key="k1")
        for _ in range(5):
            with job_worker.SessionLocal() as session:
                row = session.get(BackgroundJobRow, "job-k1")
                if row.status == "pending":
                    row.run_at = now - datetime.timedelta(seconds=1)
                session.commit()
            job_worker._claim_and_execute(now)
        job = _job("k1")
        assert job.status == "failed"
        assert job.attempts == 5
        assert "RuntimeError" in job.last_error

    def test_unknown_job_type_fails_via_retry(self, job_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "job_retry_backoff_seconds", 0)
        _enqueue(job_type="mystery", key="k1")
        job_worker._claim_and_execute(timeutil.now())
        job = _job("k1")
        assert job.status == "pending"
        assert "未知 job_type" in job.last_error

    def test_future_run_at_not_claimed(self, job_db):
        future = timeutil.now() + datetime.timedelta(hours=1)
        _enqueue(key="k1", run_at=future)
        done, retried, failed = job_worker._claim_and_execute(timeutil.now())
        assert (done, retried, failed) == (0, 0, 0)
        assert _job("k1").status == "pending"


class TestZombieRecovery:
    def test_running_timeout_reset_and_rerun(self, job_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "job_running_timeout", 600)
        monkeypatch.setattr(get_settings(), "job_retry_backoff_seconds", 0)
        executed = []
        monkeypatch.setitem(
            job_worker._JOB_HANDLERS, "memory_decay", lambda: executed.append(1)
        )
        stale = timeutil.now() - datetime.timedelta(seconds=700)
        _enqueue(key="k1", status="running", run_at=stale)
        recovered = job_worker._recover_zombies(timeutil.now())
        assert recovered == 1
        assert _job("k1").status == "pending"
        done, _, _ = job_worker._claim_and_execute(timeutil.now())
        assert done == 1
        assert _job("k1").status == "done"
        assert executed == [1]

    def test_zombie_attempts_respect_max(self, job_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "job_max_attempts", 5)
        monkeypatch.setattr(get_settings(), "job_running_timeout", 600)
        stale = timeutil.now() - datetime.timedelta(seconds=700)
        _enqueue(key="k1", status="running", run_at=stale, attempts=4)
        job_worker._recover_zombies(timeutil.now())
        job = _job("k1")
        assert job.status == "failed"
        assert job.last_error == "zombie_recovered_max_attempts"

    def test_fresh_running_not_recovered(self, job_db):
        _enqueue(key="k1", status="running", run_at=timeutil.now())
        assert job_worker._recover_zombies(timeutil.now()) == 0
        assert _job("k1").status == "running"


class TestKillRecovery:
    def test_kill9_simulation_no_loss_no_duplicate(self, job_db, monkeypatch):
        """kill -9 演练模拟：job 认领后进程死亡（running 遗留）→ 重启回收 → 幂等重跑。"""
        monkeypatch.setattr(get_settings(), "job_running_timeout", 600)
        monkeypatch.setattr(get_settings(), "job_retry_backoff_seconds", 0)
        now = timeutil.now()
        with job_worker.SessionLocal() as session:
            session.add(
                MemoryRow(
                    id="m1", user_id="u1", character_id="asuna",
                    content="用户喜欢吃辣", type="user_preference",
                    importance=0.6, status="active", salience=0.6,
                    created_at=now, updated_at=now,
                )
            )
            session.commit()

        def _crashing_decay():
            job_worker._recover_zombies(timeutil.now())
            raise RuntimeError("process killed mid-run")

        monkeypatch.setitem(job_worker._JOB_HANDLERS, "memory_decay", _crashing_decay)
        _enqueue(key="k1")
        job_worker._claim_and_execute(now)
        assert _job("k1").status == "pending"

        monkeypatch.setitem(
            job_worker._JOB_HANDLERS, "memory_decay", lifecycle.run_decay_cycle
        )
        stale = timeutil.now() - datetime.timedelta(seconds=700)
        with job_worker.SessionLocal() as session:
            row = session.get(BackgroundJobRow, "job-k1")
            row.status = "running"
            row.run_at = stale
            session.commit()

        recovered = job_worker._recover_zombies(timeutil.now())
        assert recovered == 1
        done, _, _ = job_worker._claim_and_execute(timeutil.now())
        assert done == 1
        assert _job("k1").status == "done"
        with job_worker.SessionLocal() as session:
            assert session.query(MemoryRow).filter_by(user_id="u1").count() == 1
        assert memory_repository.get_memory("m1").status == "active"


class TestHandlerIntegration:
    def test_embedding_backfill_handler(self, job_db, monkeypatch):
        now = timeutil.now()
        with job_worker.SessionLocal() as session:
            session.add(
                MemoryRow(
                    id="m1", user_id="u1", character_id="asuna",
                    content="待向量", type="user_fact",
                    importance=0.6, status="active", salience=0.6,
                    created_at=now, updated_at=now,
                )
            )
            session.commit()
        monkeypatch.setattr(embeddings, "get_embedding_client", lambda: None)
        _enqueue(job_type="embedding_backfill", key="e1")
        job_worker._claim_and_execute(timeutil.now())
        assert _job("e1").status == "done"

    def test_reinforce_and_embedding_flush_in_tick(self, job_db):
        now = timeutil.now()
        with job_worker.SessionLocal() as session:
            session.add(
                MemoryRow(
                    id="m1", user_id="u1", character_id="asuna",
                    content="内容", type="user_fact",
                    importance=0.6, status="active", salience=0.6,
                    created_at=now, updated_at=now,
                )
            )
            session.commit()
        lifecycle.record_reinforce("m1")
        job_worker.run_job_tick()
        with job_worker.SessionLocal() as session:
            salience = session.get(MemoryRow, "m1").salience
        assert salience == pytest.approx(0.7)
