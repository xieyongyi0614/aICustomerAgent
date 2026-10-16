"""background_jobs 通用执行器（MEM-009）。

调度与执行分离：周期入队器只负责到点 INSERT（幂等键拦截重复），执行统一走
认领（pending+due → running，PG 下 FOR UPDATE SKIP LOCKED 为 P5 多执行器预留）
→ 分发 job_type 处理器 → done；异常 attempts+1 指数退避重试，达上限转 failed
死信；running 超 job_running_timeout 视为崩溃回收重跑（处理器幂等保证安全，
MEM-004 条件回填 / MEM-005 日桶衰减均已幂等）。同轮附带 flush reinforce 缓冲与
embedding 攒批窗口，补齐两个内存态通道的周期驱动。
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import or_

from app.core import timeutil
from app.core.db import BackgroundJobRow, SessionLocal
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.memory import embeddings as memory_embeddings
from app.services.memory import episodic as memory_episodic
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import semantic as memory_semantic
logger = logging.getLogger(__name__)

STEP_NAME = "memory_job_worker"

JOB_TYPE_MEMORY_DECAY = "memory_decay"
JOB_TYPE_EMBEDDING_BACKFILL = "embedding_backfill"

_JOB_HANDLERS = {
    JOB_TYPE_MEMORY_DECAY: memory_lifecycle.run_decay_cycle,
    JOB_TYPE_EMBEDDING_BACKFILL: memory_embeddings.backfill_scan,
    # 情景聚合（MEV-006）：同域 job 直接列在此处；门控在 handler 内（mode=off → 零动作）
    memory_episodic.JOB_TYPE_MEMORY_EPISODIC_AGGREGATE: memory_episodic.run_aggregate_job,
    # 语义抽象（MEV-007）：同上；门控在 handler 内（mode=off → 零动作、零 LLM）
    memory_semantic.JOB_TYPE_MEMORY_SEMANTIC_ABSTRACT: memory_semantic.run_semantic_job,
}

_TICK_HOOKS: list = [memory_episodic.run_aggregate_tick, memory_semantic.run_semantic_tick]
"""周期挂靠点：默认挂情景聚合（MEV-006）与语义抽象（MEV-007）入队 hook，
门控在各自 hook 内（mode=off → 零动作、不查库）。"""

_CLAIM_BATCH_LIMIT = 20


def register_job_type(job_type: str, handler) -> None:
    """新处理器一行注册；处理器必须幂等（P5 Life Loop 复用同一协议）。"""
    _JOB_HANDLERS[job_type] = handler


def register_tick_hook(hook) -> None:
    """周期 tick 挂靠点（每轮 run_job_tick 末尾调用，异常隔离）；REF-003 周期触发入口。"""
    _TICK_HOOKS.append(hook)


_worker_loop_runner = None


def register_worker_loop(runner) -> None:
    """组合根注册通用循环执行器（application.worker_loop），消除反向依赖。"""
    global _worker_loop_runner
    _worker_loop_runner = runner


async def run_job_worker_loop() -> None:
    if _worker_loop_runner is None:
        raise RuntimeError("worker_loop 未注册（app.main lifespan / 测试 conftest）")
    await _worker_loop_runner(
        "memory job worker",
        run_job_tick,
        get_settings().job_poll_interval,
        offload=True,
    )


def run_job_tick(trace=None) -> dict:
    started = time.perf_counter()
    now = timeutil.now()
    stats = {
        "enqueued": 1 if _enqueue_due_decay(now) else 0,
        "recovered": _recover_zombies(now),
        "done": 0,
        "retried": 0,
        "failed": 0,
    }
    memory_lifecycle.flush_reinforce_buffer()
    memory_embeddings.flush_if_due()
    for hook in _TICK_HOOKS:
        try:
            hook(now)
        except Exception:
            logger.exception("tick hook 异常，继续下一轮")
    stats["done"], stats["retried"], stats["failed"] = _claim_and_execute(now)
    _trace(trace, started, **stats)
    return stats


def _enqueue_due_decay(now: datetime) -> bool:
    idempotency_key = f"{JOB_TYPE_MEMORY_DECAY}:{now:%Y-%m-%d}"
    return background_job_repository.enqueue_job(
        JOB_TYPE_MEMORY_DECAY, {}, idempotency_key, run_at=now
    )


def _claim(session, now: datetime, limit: int) -> list:
    rows = (
        session.query(BackgroundJobRow)
        .filter(
            BackgroundJobRow.status == "pending",
            or_(
                BackgroundJobRow.run_at.is_(None),
                BackgroundJobRow.run_at <= now,
            ),
        )
        .order_by(BackgroundJobRow.run_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for row in rows:
        row.status = "running"
        row.run_at = now
    return rows


def _claim_and_execute(now: datetime) -> tuple[int, int, int]:
    with SessionLocal() as session:
        claimed = _claim(session, now, _CLAIM_BATCH_LIMIT)
        job_ids = [row.id for row in claimed]
        session.commit()
    done = retried = failed = 0
    for job_id in job_ids:
        outcome = _execute_job(job_id, now)
        if outcome == "done":
            done += 1
        elif outcome == "retried":
            retried += 1
        else:
            failed += 1
    return done, retried, failed


def _execute_job(job_id: str, now: datetime) -> str:
    with SessionLocal() as session:
        job = session.get(BackgroundJobRow, job_id)
        if job is None or job.status != "running":
            return "gone"
        job_type = job.job_type
    handler = _JOB_HANDLERS.get(job_type)
    try:
        if handler is None:
            raise ValueError(f"未知 job_type: {job_type}")
        handler()
    except Exception as exc:
        return _reschedule_or_fail(job_id, exc, now)
    return _mark_done(job_id)


def _mark_done(job_id: str) -> str:
    with SessionLocal() as session:
        job = session.get(BackgroundJobRow, job_id)
        if job is not None and job.status == "running":
            job.status = "done"
            session.commit()
        return "done"


def _reschedule_or_fail(job_id: str, exc: Exception, now: datetime) -> str:
    settings = get_settings()
    with SessionLocal() as session:
        job = session.get(BackgroundJobRow, job_id)
        if job is None or job.status != "running":
            return "gone"
        job.attempts += 1
        job.last_error = f"{exc.__class__.__name__}: {exc}"[:500]
        if job.attempts >= settings.job_max_attempts:
            job.status = "failed"
            outcome = "failed"
        else:
            delay = settings.job_retry_backoff_seconds * (2 ** (job.attempts - 1))
            job.status = "pending"
            job.run_at = now + timedelta(seconds=delay)
            outcome = "retried"
        session.commit()
        return outcome


def _recover_zombies(now: datetime) -> int:
    settings = get_settings()
    threshold = now - timedelta(seconds=settings.job_running_timeout)
    recovered = 0
    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.status == "running",
                BackgroundJobRow.run_at.isnot(None),
                BackgroundJobRow.run_at < threshold,
            )
            .all()
        )
        for job in rows:
            job.attempts += 1
            if job.attempts >= settings.job_max_attempts:
                job.status = "failed"
                job.last_error = "zombie_recovered_max_attempts"
            else:
                job.status = "pending"
                job.run_at = now
            recovered += 1
        session.commit()
    if recovered:
        logger.warning("僵尸 job 回收重置：%d 个", recovered)
    return recovered


def _trace(trace, started: float, **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, "ok", **extra)
