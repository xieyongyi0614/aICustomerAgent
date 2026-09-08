"""反思触发器（REF-003）。

周期（每日低峰一次）+ 事件（同主题 reinforce 计数达阈值）双触发；三道闸按序
前置：证据门槛（REF-002 passes_gate）→ 当日额度（queued/running/done 占额，
skipped/failed 不占）→ 幂等入队（job_key=reflect:user:日桶）。门槛拦截写
reflection_runs(skipped) 且 0 LLM；额度拦截不产新行（防行膨胀）。事件计数器为
进程内存态（重启即丢，每日调度兜底），带冷却窗口防事件风暴。
"""

import logging
import time
import uuid
from datetime import datetime, timedelta

from app.core.db import Memory, ReflectionRunRow, SessionLocal
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.reflection import evidence as reflection_evidence
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.memory_conflict import same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_trigger"

JOB_TYPE_REFLECTION_RUN = "reflection_run"

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_EVENT = "event"

OUTCOME_QUEUED = "queued"
OUTCOME_SKIPPED = "skipped"
OUTCOME_QUOTA = "quota"
OUTCOME_OFF = "off"

DECISION_QUEUED = "queued"
DECISION_SKIPPED = "skipped"
DECISION_QUOTA = "quota_exhausted"
DECISION_OFF = "off"

_QUOTA_OCCUPYING_STATUSES = ("queued", "running", "done")
_RUN_ID_PREFIX = "rr"

_topic_buckets: dict[str, dict[str, dict]] = {}


def register_with_job_worker() -> None:
    """编排层接线入口：周期触发挂靠 job_worker tick（执行 handler 由 REF-004 注册）。"""

    memory2_job_worker.register_tick_hook(run_reflection_trigger_tick)


def trigger_for_user(
    user_id: str,
    character_id: str = "asuna",
    trigger: str = TRIGGER_SCHEDULED,
    now: datetime | None = None,
    trace=None,
) -> str:
    """单用户触发判定：门槛预检 → 额度 → 入队；返回 queued|skipped|quota|off。"""
    started = time.perf_counter()
    now = now or datetime.now()
    settings = get_settings()
    if not settings.v2_reflection_enabled:
        _trace(trace, started, trigger=trigger, decision=DECISION_OFF)
        return OUTCOME_OFF

    try:
        windows = reflection_evidence.aggregate_evidence_windows(
            user_id, character_id, now=now, trace=trace
        )
    except Exception as exc:
        logger.exception("证据聚合异常，按门槛未过处理：%s", user_id)
        _record_run(
            user_id,
            character_id,
            trigger,
            status=OUTCOME_SKIPPED,
            evidence_summary={"passing": 0, "reason": "aggregate_error"},
            outcome="aggregate_error",
            now=now,
        )
        _trace(trace, started, trigger=trigger, decision=DECISION_SKIPPED, reason=f"aggregate_error:{exc.__class__.__name__}")
        return OUTCOME_SKIPPED

    passing = [window for window in windows if window.passes_gate]
    if not passing:
        _record_run(
            user_id,
            character_id,
            trigger,
            status=OUTCOME_SKIPPED,
            evidence_summary={
                "passing": 0,
                "window_count": len(windows),
                "gate_reasons": sorted(
                    {reason for window in windows for reason in window.gate_reasons}
                ),
                "top_window": _compact_digest(windows[0]) if windows else None,
            },
            outcome="no_passing_window",
            now=now,
        )
        _trace(trace, started, trigger=trigger, decision=DECISION_SKIPPED, reason="no_passing_window")
        return OUTCOME_SKIPPED

    if _quota_used(user_id, now):
        _trace(trace, started, trigger=trigger, decision=DECISION_QUOTA)
        return OUTCOME_QUOTA

    idempotency_key = _day_bucket_key(user_id, now)
    if background_job_repository.has_job(idempotency_key):
        _trace(trace, started, trigger=trigger, decision=DECISION_QUOTA, reason="already_enqueued")
        return OUTCOME_QUOTA

    run_id = _new_run_id()
    _record_run(
        user_id,
        character_id,
        trigger,
        status="queued",
        evidence_summary={
            "passing": len(passing),
            "windows": [_compact_digest(window) for window in passing],
        },
        run_id=run_id,
        now=now,
    )
    enqueued = False
    try:
        enqueued = background_job_repository.enqueue_job(
            JOB_TYPE_REFLECTION_RUN,
            {"run_id": run_id, "trigger": trigger},
            idempotency_key,
        )
    except Exception:
        logger.exception("反思任务入队异常，回滚 run 行待下轮重试：%s", user_id)
        _drop_run(run_id)
        _trace(trace, started, trigger=trigger, decision="enqueue_failed", run_id=run_id)
        return OUTCOME_SKIPPED
    if not enqueued:
        _drop_run(run_id)
        _trace(trace, started, trigger=trigger, decision=DECISION_QUOTA, reason="enqueue_duplicate")
        return OUTCOME_QUOTA
    _trace(trace, started, trigger=trigger, decision=DECISION_QUEUED, run_id=run_id)
    return OUTCOME_QUEUED


def observe_reinforce(user_id: str, memory_ids: list[str], trace=None) -> None:
    """事件计数入口（post_process 喂入）：同主题计数 + 冷却 → 达阈值走触发判定。"""
    if not memory_ids or not get_settings().v2_reflection_enabled:
        return
    started = time.perf_counter()
    now = datetime.now()
    settings = get_settings()
    contents = _memory_contents(memory_ids)
    buckets = _topic_buckets.setdefault(user_id, {})
    affected: list[dict] = []
    for memory_id, content in contents.items():
        if not content:
            continue
        bucket = _match_bucket(buckets, content)
        if bucket is None:
            bucket = {"topic_content": content, "count": 0, "last_triggered_at": None}
            buckets[content] = bucket
            affected.append(bucket)
        elif bucket not in affected:
            affected.append(bucket)
        if len(content) > len(bucket["topic_content"]):
            bucket["topic_content"] = content
        bucket["count"] += 1
    cooldown = timedelta(hours=settings.v2_reflection_event_cooldown_hours)
    for bucket in affected:
        last = bucket.get("last_triggered_at")
        if last is not None and now - last < cooldown:
            continue
        if bucket["count"] < settings.v2_reflection_event_threshold:
            continue
        bucket["last_triggered_at"] = now
        bucket["count"] = 0
        try:
            trigger_for_user(user_id, trigger=TRIGGER_EVENT, now=now, trace=trace)
        except Exception:
            logger.exception("事件触发判定异常：%s", user_id)
    _trace(
        trace,
        started,
        trigger=TRIGGER_EVENT,
        decision="observed",
        memory_ids=list(memory_ids),
        topics=len(buckets),
    )


def run_reflection_trigger_tick(now: datetime | None = None) -> int:
    """周期触发入口：job_worker tick 挂靠；每用户每日一次判定（Flag OFF 空转）。"""
    now = now or datetime.now()
    settings = get_settings()
    if not settings.v2_reflection_enabled:
        return 0
    if now.hour < settings.v2_reflection_schedule_hour:
        return 0
    judged = 0
    for user_id in _users_with_memories():
        try:
            if _scheduled_already_handled(user_id, now):
                continue
            trigger_for_user(user_id, trigger=TRIGGER_SCHEDULED, now=now)
            judged += 1
        except Exception:
            logger.exception("周期触发判定异常，下一 tick 重试：%s", user_id)
    return judged


def reset_trigger_state() -> None:
    """清空事件计数器（测试与运维复位）。"""
    _topic_buckets.clear()


def _match_bucket(buckets: dict[str, dict], content: str) -> dict | None:
    for bucket in buckets.values():
        if same_topic(content, bucket["topic_content"]):
            return bucket
    return None


def _memory_contents(memory_ids: list[str]) -> dict[str, str]:
    with SessionLocal() as session:
        rows = session.query(Memory.id, Memory.content).filter(Memory.id.in_(memory_ids)).all()
        return {row_id: (content or "").strip() for row_id, content in rows}


def _quota_used(user_id: str, now: datetime) -> bool:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as session:
        return (
            session.query(ReflectionRunRow.id)
            .filter(
                ReflectionRunRow.user_id == user_id,
                ReflectionRunRow.status.in_(_QUOTA_OCCUPYING_STATUSES),
                ReflectionRunRow.created_at >= day_start,
                ReflectionRunRow.created_at < day_start + timedelta(days=1),
            )
            .first()
            is not None
        )


def _scheduled_already_handled(user_id: str, now: datetime) -> bool:
    """周期路每日一次：日桶 job 或当日任一 run 行（含 skipped）已存在即视为已处理。"""
    if background_job_repository.has_job(_day_bucket_key(user_id, now)):
        return True
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as session:
        return (
            session.query(ReflectionRunRow.id)
            .filter(
                ReflectionRunRow.user_id == user_id,
                ReflectionRunRow.created_at >= day_start,
                ReflectionRunRow.created_at < day_start + timedelta(days=1),
            )
            .first()
            is not None
        )


def _users_with_memories() -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory.user_id)
            .filter(Memory.status == "active")
            .distinct()
            .all()
        )
        return [row[0] for row in rows]


def _day_bucket_key(user_id: str, now: datetime) -> str:
    return f"reflect:{user_id}:{now:%Y-%m-%d}"


def _new_run_id() -> str:
    return f"{_RUN_ID_PREFIX}:{uuid.uuid4().hex}"


def _record_run(
    user_id: str,
    character_id: str,
    trigger: str,
    *,
    status: str,
    evidence_summary: dict,
    outcome: str | None = None,
    run_id: str | None = None,
    now: datetime,
) -> str:
    run_id = run_id or _new_run_id()
    with SessionLocal() as session:
        session.add(
            ReflectionRunRow(
                id=run_id,
                user_id=user_id,
                character_id=character_id,
                trigger=trigger,
                status=status,
                evidence_summary=evidence_summary,
                outcome=outcome,
                llm_used=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return run_id


def _drop_run(run_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(ReflectionRunRow, run_id)
        if row is not None and row.status == "queued":
            session.delete(row)
            session.commit()


def _compact_digest(window) -> dict:
    return {
        "topic": window.topic_digest[:20],
        "member_count": window.stats.member_count,
        "distinct_source_refs": window.stats.distinct_source_refs,
        "span_hours": window.stats.span_hours,
        "coherence": window.stats.coherence,
    }


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
