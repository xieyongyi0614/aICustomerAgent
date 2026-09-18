"""反思触发器（REF-003）。

周期（每日低峰一次）+ 事件（同主题 reinforce 计数达阈值）双触发；三道闸按序
前置：证据门槛（REF-002 passes_gate）→ 当日额度（queued/running/done 占额，
skipped/failed 不占）→ 幂等入队（job_key=reflect:user:日桶）。门槛拦截写
reflection_runs(skipped) 且 0 LLM；额度拦截不产新行（防行膨胀）。事件计数器为
进程内存态（重启即丢，每日调度兜底），带冷却窗口防事件风暴。

TOOL-009 §2.3：追加工具效能证据源。`trigger_for_user(channel=tool)` 与用户证据走
**同一函数、同一顺序、同一判定**（三道闸零豁免），仅证据源与幂等键不同
（`reflect:tool:user:日桶`，与既有日桶各自独立入队、共享既有额度语义）。
工具证据 reinforce 计数入口独立成桶（同 tool_id 同 failure_kind），复用既有
阈值与冷却窗机制；触发机制本身（周期 + 事件双触发）零改动。

PLAN-010 §4.1.3 ②：追加计划效能证据源（`CHANNEL_PLAN`）。**本函数零改动**——计划通道
不新增分支、不新增闸门、不新增幂等键：计划窗由 `evidence.aggregate_evidence_windows`
在 `v25_plan_reflection_enabled` 开启时**扩源**进既有窗口列表，故它与用户证据走的是
同一个 `channel=memory` 闸门序列（门槛 / 当日额度 / 幂等入队三层一字不差）。
这就是本任务的「三道闸零豁免」：不是「也过一遍闸门」，而是**同一条路径**。
"""

import logging
import time
import uuid
from datetime import datetime, timedelta

from app.core.db import Memory, ReflectionRunRow, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import (
    EVIDENCE_CHANNEL_MEMORY,
    EVIDENCE_CHANNEL_PLAN,
    EVIDENCE_CHANNEL_TOOL,
)
from app.repositories import background_job_repository
from app.services.reflection import evidence as reflection_evidence
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.memory_conflict import same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_trigger"

JOB_TYPE_REFLECTION_RUN = "reflection_run"

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_EVENT = "event"

CHANNEL_MEMORY = EVIDENCE_CHANNEL_MEMORY
CHANNEL_TOOL = EVIDENCE_CHANNEL_TOOL
CHANNEL_PLAN = EVIDENCE_CHANNEL_PLAN
"""三个证据通道的入口别名（PLAN-010 增第三值）。

`CHANNEL_PLAN` 传进 `trigger_for_user` 即走**与 `CHANNEL_MEMORY` 完全相同**的分支
（同一证据源、同一幂等键、同一额度）——计划通道的差别只在证据源（计划窗）本身，不在闸门。
"""

OUTCOME_QUEUED = "queued"
OUTCOME_SKIPPED = "skipped"
OUTCOME_QUOTA = "quota"
OUTCOME_OFF = "off"

DECISION_QUEUED = "queued"
DECISION_SKIPPED = "skipped"
DECISION_QUOTA = "quota_exhausted"
DECISION_OFF = "off"

_REASON_NO_PASSING_WINDOW = "no_passing_window"
_REASON_TOOL_OFF = "tool_reflection_off"

_QUOTA_OCCUPYING_STATUSES = ("queued", "running", "done")
_RUN_ID_PREFIX = "rr"
_TOOL_SEEN_LIMIT = 500

_topic_buckets: dict[str, dict[str, dict]] = {}
_tool_buckets: dict[str, dict[str, dict]] = {}
_tool_evidence_seen: dict[str, dict[str, bool]] = {}


def register_with_job_worker() -> None:
    """编排层接线入口：周期触发挂靠 job_worker tick（执行 handler 由 REF-004 注册）。"""

    memory2_job_worker.register_tick_hook(run_reflection_trigger_tick)


def trigger_for_user(
    user_id: str,
    character_id: str = "asuna",
    trigger: str = TRIGGER_SCHEDULED,
    now: datetime | None = None,
    trace=None,
    *,
    channel: str = CHANNEL_MEMORY,
) -> str:
    """单用户触发判定：门槛预检 → 额度 → 入队；返回 queued|skipped|quota|off。

    `channel` 只切换证据源与幂等键：门槛 / 额度 / 入队顺序与判定逻辑两通道完全一致。
    """
    started = time.perf_counter()
    now = now or datetime.now()
    settings = get_settings()
    if channel == CHANNEL_TOOL and not tool_channel_enabled(settings):
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_OFF,
            reason=_REASON_TOOL_OFF,
            **_channel_field(channel),
        )
        return OUTCOME_OFF

    windows: list = []
    package: reflection_evidence.ToolEvidencePackage | None = None
    try:
        if channel == CHANNEL_TOOL:
            package = reflection_evidence.aggregate_tool_evidence(
                user_id, now=now, trace=trace
            )
            passing = list(package.windows)
        else:
            windows = reflection_evidence.aggregate_evidence_windows(
                user_id, character_id, now=now, trace=trace
            )
            passing = [window for window in windows if window.passes_gate]
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
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_SKIPPED,
            reason=f"aggregate_error:{exc.__class__.__name__}",
            **_channel_field(channel),
        )
        return OUTCOME_SKIPPED

    if not passing:
        if channel == CHANNEL_TOOL:
            evidence_summary = _tool_evidence_summary(
                user_id, character_id, package, now
            )
            outcome = "no_passing_tool_window"
        else:
            evidence_summary = {
                "passing": 0,
                "window_count": len(windows),
                "gate_reasons": sorted(
                    {reason for window in windows for reason in window.gate_reasons}
                ),
                "top_window": _compact_digest(windows[0]) if windows else None,
            }
            outcome = "no_passing_window"
        _record_run(
            user_id,
            character_id,
            trigger,
            status=OUTCOME_SKIPPED,
            evidence_summary=evidence_summary,
            outcome=outcome,
            now=now,
        )
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_SKIPPED,
            reason=_REASON_NO_PASSING_WINDOW,
            **_channel_field(channel),
        )
        return OUTCOME_SKIPPED

    if _quota_used(user_id, now):
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_QUOTA,
            **_channel_field(channel),
        )
        return OUTCOME_QUOTA

    idempotency_key = _channel_bucket_key(user_id, now, channel)
    if background_job_repository.has_job(idempotency_key):
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_QUOTA,
            reason="already_enqueued",
            **_channel_field(channel),
        )
        return OUTCOME_QUOTA

    run_id = _new_run_id()
    if channel == CHANNEL_TOOL:
        summary = _tool_evidence_summary(user_id, character_id, package, now)
        summary["windows"] = [
            _compact_digest(window)
            for window in _order_tool_windows(passing, summary["window_kinds"])
        ]
    else:
        summary = {
            "passing": len(passing),
            "windows": [_compact_digest(window) for window in passing],
        }
    _record_run(
        user_id,
        character_id,
        trigger,
        status="queued",
        evidence_summary=summary,
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
        _trace(
            trace,
            started,
            trigger=trigger,
            decision="enqueue_failed",
            run_id=run_id,
            **_channel_field(channel),
        )
        return OUTCOME_SKIPPED
    if not enqueued:
        _drop_run(run_id)
        _trace(
            trace,
            started,
            trigger=trigger,
            decision=DECISION_QUOTA,
            reason="enqueue_duplicate",
            **_channel_field(channel),
        )
        return OUTCOME_QUOTA
    _trace(
        trace,
        started,
        trigger=trigger,
        decision=DECISION_QUEUED,
        run_id=run_id,
        **_channel_field(channel),
    )
    return OUTCOME_QUEUED


def tool_channel_enabled(settings=None) -> bool:
    """工具证据通道开关：工具反思子闸（默认 off）。"""
    settings = settings or get_settings()
    return bool(getattr(settings, "v24_tool_reflection_enabled", False))


def observe_tool_evidence(
    user_id: str,
    *,
    tool_id: str,
    failure_kind: str | None = None,
    now: datetime | None = None,
    trace=None,
) -> bool:
    """工具证据 reinforce 计数（§2.3）：同 tool_id 同 failure_kind 达阈值 + 冷却 → 触发。

    复用 REF-003 既有机制与冷却窗（阈值 `v2_reflection_event_threshold`、
    冷却 `v2_reflection_event_cooldown_hours`）；触发走同一 `trigger_for_user`（channel=tool）。
    """
    settings = get_settings()
    if not tool_channel_enabled(settings):
        return False
    started = time.perf_counter()
    now = now or datetime.now()
    topic = f"{tool_id}|{failure_kind or ''}"
    bucket = _tool_buckets.setdefault(user_id, {}).get(topic)
    if bucket is None:
        bucket = {"topic": topic, "count": 0, "last_triggered_at": None}
        _tool_buckets[user_id][topic] = bucket
    bucket["count"] += 1
    cooldown = timedelta(hours=settings.v2_reflection_event_cooldown_hours)
    last = bucket.get("last_triggered_at")
    if last is not None and now - last < cooldown:
        _trace(
            trace,
            started,
            trigger=TRIGGER_EVENT,
            decision="observed",
            channel=CHANNEL_TOOL,
            tool_id=tool_id,
            failure_kind=failure_kind,
            fired=False,
            reason="cooldown",
        )
        return False
    if bucket["count"] < settings.v2_reflection_event_threshold:
        _trace(
            trace,
            started,
            trigger=TRIGGER_EVENT,
            decision="observed",
            channel=CHANNEL_TOOL,
            tool_id=tool_id,
            failure_kind=failure_kind,
            fired=False,
            reason="below_threshold",
        )
        return False
    bucket["last_triggered_at"] = now
    bucket["count"] = 0
    fired = False
    try:
        fired = (
            trigger_for_user(
                user_id,
                trigger=TRIGGER_EVENT,
                now=now,
                trace=trace,
                channel=CHANNEL_TOOL,
            )
            == OUTCOME_QUEUED
        )
    except Exception:
        logger.exception("工具证据触发判定异常：%s", user_id)
    _trace(
        trace,
        started,
        trigger=TRIGGER_EVENT,
        decision="observed",
        channel=CHANNEL_TOOL,
        tool_id=tool_id,
        failure_kind=failure_kind,
        fired=fired,
    )
    return fired


def observe_tool_evidence_from_records(
    user_id: str,
    now: datetime | None = None,
    trace=None,
    window_days: int = reflection_evidence.TOOL_EVIDENCE_WINDOW_DAYS,
) -> int:
    """从 `action_records` 投影补扫工具失败证据并喂 reinforce 计数（同证据只计一次）。

    只读投影（不经工具注册表 / 健康度）；失败证据（含 timeout）才计数。
    返回本次真正触发入队的次数。
    """
    settings = get_settings()
    if not tool_channel_enabled(settings):
        return 0
    now = now or datetime.now()
    facts = reflection_evidence.tool_fact_projection(
        user_id, now=now, window_days=window_days
    )
    seen = _tool_evidence_seen.setdefault(user_id, {})
    fired = 0
    for fact in facts:
        if fact.failure_kind is None or fact.evidence_id in seen:
            continue
        seen[fact.evidence_id] = True
        if observe_tool_evidence(
            user_id,
            tool_id=fact.tool_id,
            failure_kind=fact.failure_kind,
            now=now,
            trace=trace,
        ):
            fired += 1
    _trim_seen(seen)
    return fired



def observe_reinforce(user_id: str, memory_ids: list[str], trace=None) -> None:
    """事件计数入口（post_process 喂入）：同主题计数 + 冷却 → 达阈值走触发判定。"""
    if not memory_ids:
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
    """清空事件计数器（测试与运维复位）；含工具证据计数与已见证据集合。"""
    _topic_buckets.clear()
    _tool_buckets.clear()
    _tool_evidence_seen.clear()


def _channel_field(channel: str) -> dict:
    """trace 字段：既有通道零新增字段（逐字节一致），仅工具通道标注来源。"""
    return {"channel": channel} if channel == CHANNEL_TOOL else {}


def _channel_bucket_key(user_id: str, now: datetime, channel: str) -> str:
    """幂等键：用户证据沿用既有日桶；工具证据独立日桶（E14 各自独立入队）。"""
    if channel == CHANNEL_TOOL:
        return f"reflect:tool:{user_id}:{now:%Y-%m-%d}"
    return _day_bucket_key(user_id, now)


def _tool_evidence_summary(
    user_id: str,
    character_id: str,
    package,
    now: datetime,
) -> dict:
    """工具通道证据包（§2.2）：`tool_windows` + `existing_windows` + `passing`。

    达门槛窗口按资产优先序排序后**按日轮转**起点（同一天多窗达门槛时，三天一轮让
    能力 / 交互 / 用量三类认知各得一次主分析机会；未达门槛的窗口不参与轮转）。
    """
    if package is None:
        package = reflection_evidence.ToolEvidencePackage()
    kinds = reflection_evidence.order_tool_window_kinds(
        [window.window_kind for window in package.windows]
    )
    rotated = _rotate(kinds, now.date().toordinal())
    return {
        "channel": CHANNEL_TOOL,
        "passing": package.passing,
        "window_kind": rotated[0] if rotated else None,
        "window_kinds": rotated,
        "tool_windows": package.summary(),
        "existing_windows": _existing_windows_summary(user_id, character_id, now),
    }


def _rotate(kinds: list[str], offset: int) -> list[str]:
    if not kinds:
        return []
    shift = offset % len(kinds)
    return kinds[shift:] + kinds[:shift]


def _order_tool_windows(windows: list, window_kinds: list[str]) -> list:
    order = {kind: index for index, kind in enumerate(window_kinds)}
    return sorted(
        windows,
        key=lambda window: (order.get(window.window_kind, len(order)), window.group_key),
    )


def _existing_windows_summary(
    user_id: str, character_id: str, now: datetime
) -> dict:
    """既有窗口（对话/记忆/世界/关系）只读摘要：零写入、异常降级为空包。"""
    try:
        windows = reflection_evidence.aggregate_evidence_windows(
            user_id, character_id, now=now
        )
    except Exception:
        logger.exception("既有证据窗摘要失败，降级为空包：%s", user_id)
        return {"count": 0, "passing": 0, "degraded": "aggregate_error"}
    return {
        "count": len(windows),
        "passing": sum(1 for window in windows if window.passes_gate),
    }


def _trim_seen(seen: dict[str, bool]) -> None:
    """已见证据集合有界（超出保留最近 `_TOOL_SEEN_LIMIT` 条）。"""
    overflow = len(seen) - _TOOL_SEEN_LIMIT
    for evidence_id in list(seen)[:overflow] if overflow > 0 else []:
        seen.pop(evidence_id, None)


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
