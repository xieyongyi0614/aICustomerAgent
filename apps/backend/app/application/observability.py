"""V7.8 观测层编排入口（architecture.md §2）：只做调度、采样与容错。

所有持久化均为 write-behind 后台任务；任何异常仅 log，绝不影响聊天与主动链路。
"""

import asyncio
import logging
from contextvars import ContextVar

from app.core.settings import get_settings
from app.models.observability import (
    DecisionRecord,
    LlmCallRecord,
    RuntimeTrace,
    TraceEvent,
    TraceKind,
    TraceStep,
    bound_extra,
    bound_text,
    deterministic_sample,
)
from app.repositories import trace_repository

logger = logging.getLogger(__name__)

background_tasks: set = set()

current_trace: ContextVar = ContextVar("observability_current_trace", default=None)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def _derive_status(trace) -> str:
    statuses = {step.status for step in trace.steps}
    if "error" in statuses:
        return "error"
    if "degraded" in statuses:
        return "degraded"
    return "complete" if trace.is_complete else "pending"


def _assemble_steps(trace, max_extra: int) -> list[TraceStep]:
    steps: list[TraceStep] = []
    for step in trace.steps:
        extra, _ = bound_extra(step.extra, max_extra)
        error, _ = bound_text(step.error, max_extra)
        steps.append(
            TraceStep(
                name=step.name,
                status=step.status,
                duration_ms=step.duration_ms,
                first_token_ms=step.first_token_ms,
                error=error,
                extra=extra,
            )
        )
    return steps


def _assemble_trace(
    trace,
    kind: TraceKind,
    user_id: str,
    session_id: str,
    turn_id: str | None = None,
    action_id: str | None = None,
    events: list[TraceEvent] | None = None,
) -> RuntimeTrace:
    snapshot = trace.snapshot()
    return RuntimeTrace(
        trace_id=trace.request_id,
        kind=kind,
        user_id=user_id,
        conversation_id=session_id,
        turn_id=turn_id,
        action_id=action_id,
        status=_derive_status(trace),
        started_at=getattr(trace, "created_at", None),
        duration_ms=snapshot.get("total_ms", 0.0),
        steps=_assemble_steps(trace, get_settings().observability_step_extra_max_chars),
        events=events or [],
        token_usage=dict(trace.token_usage),
        model_name=trace.model_name,
        meta={
            "role_mode": snapshot.get("role_mode"),
            "analysis": snapshot.get("analysis"),
            "behavior": snapshot.get("behavior"),
            "mode": snapshot.get("mode"),
        },
    )


def _in_window(created_at, started_at) -> bool:
    if started_at is None or created_at is None:
        return True
    return created_at >= started_at


def _backfill_events(user_id: str, started_at, max_extra: int) -> list[TraceEvent]:
    """落库视角回填（runtime-trace.md §4）：情绪/关系事件从既有表只读补齐，零业务写入。"""
    events: list[TraceEvent] = []
    try:
        from app.repositories import emotion_history_repository

        for entry in emotion_history_repository.list_recent(user_id, limit=10):
            if not _in_window(getattr(entry, "created_at", None), started_at):
                continue
            payload, _ = bound_extra(
                {
                    "before": entry.mood_before,
                    "after": entry.mood_after,
                    "event": entry.event,
                },
                max_extra,
            )
            events.append(TraceEvent(kind="emotion_change", payload=payload))
    except Exception:
        logger.exception("情绪事件回填失败，跳过")
    try:
        from app.repositories import relationship_event_repository

        for item in relationship_event_repository.list_events(user_id, limit=10):
            if not _in_window(getattr(item, "created_at", None), started_at):
                continue
            payload, _ = bound_extra(
                {"type": item.type, "magnitude": item.magnitude}, max_extra
            )
            events.append(TraceEvent(kind="relationship_change", payload=payload))
    except Exception:
        logger.exception("关系事件回填失败，跳过")
    return events[-10:]


def on_turn_finished(
    trace,
    turn_id: str,
    user_id: str,
    session_id: str,
    post_process_task=None,
    kind: TraceKind = TraceKind.TURN,
    action_id: str | None = None,
) -> None:
    """turn 收尾挂载点（H1）：调度 write-behind 持久化，热路径零 IO。"""
    if not get_settings().observability_persist_enabled:
        return
    _spawn(
        _flush_turn_trace(
            trace,
            kind,
            user_id,
            session_id,
            turn_id=turn_id,
            action_id=action_id,
            post_process_task=post_process_task,
        )
    )


def on_turn_error(trace, user_id: str, session_id: str) -> None:
    """失败运行必存（runtime-trace.md §5）：不采样，直接调度落库。"""
    if not get_settings().observability_persist_enabled:
        return
    _spawn(_flush_error_trace(trace, user_id, session_id))


async def _await_post_process(post_process_task) -> None:
    try:
        if post_process_task is not None:
            await asyncio.gather(post_process_task, return_exceptions=True)
        from app.application import post_process

        pending = [task for task in list(post_process.background_tasks) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except Exception:
        logger.exception("观测 flush 等待后台任务失败，跳过等待")


async def _flush_turn_trace(
    trace,
    kind: TraceKind,
    user_id: str,
    session_id: str,
    turn_id: str | None,
    action_id: str | None,
    post_process_task,
) -> None:
    await _await_post_process(post_process_task)
    trace.obs_flushed = True
    try:
        settings = get_settings()
        status = _derive_status(trace)
        if status != "error" and not deterministic_sample(
            trace.request_id, settings.observability_trace_sample_rate
        ):
            return
        events = _backfill_events(
            user_id,
            getattr(trace, "created_at", None),
            settings.observability_step_extra_max_chars,
        )
        record = _assemble_trace(
            trace,
            kind,
            user_id,
            session_id,
            turn_id=turn_id,
            action_id=action_id,
            events=events,
        )
        trace_repository.save(record)
    except Exception:
        logger.exception("runtime trace 持久化失败，已忽略")
    finally:
        _drain_llm_calls(trace, turn_id)
        _drain_prompt_snapshots(trace, turn_id)


def _drain_llm_calls(trace, turn_id: str | None) -> None:
    try:
        pending = list(getattr(trace, "llm_calls", []) or [])
        if not pending:
            return
        trace.llm_calls.clear()
        from app.repositories import llm_call_repository

        for record in pending:
            if record.turn_id is None and turn_id is not None:
                record = record.model_copy(update={"turn_id": turn_id})
            llm_call_repository.save(record)
    except Exception:
        logger.exception("LLM 调用记录落库失败，已忽略")


def _drain_prompt_snapshots(trace, turn_id: str | None) -> None:
    try:
        pending = list(getattr(trace, "prompt_snapshots", []) or [])
        if not pending:
            return
        trace.prompt_snapshots.clear()
        from app.repositories import prompt_snapshot_repository

        for snapshot in pending:
            if snapshot.turn_id is None and turn_id is not None:
                snapshot = snapshot.model_copy(update={"turn_id": turn_id})
            prompt_snapshot_repository.save(snapshot)
    except Exception:
        logger.exception("prompt 快照落库失败，已忽略")


def record_llm_call(record: LlmCallRecord) -> None:
    """采集路由：有活跃 trace 则随行缓冲（flush 时落库），否则直接后台写。"""
    trace = current_trace.get()
    if trace is not None and hasattr(trace, "llm_calls"):
        if record.request_id is None:
            record = record.model_copy(
                update={"request_id": trace.request_id, "turn_id": trace.turn_id}
            )
        if trace.obs_flushed:
            _spawn(_save_llm_call(record))
        else:
            trace.llm_calls.append(record)
        return
    submit_llm_call(record)


def submit_llm_call(record: LlmCallRecord) -> None:
    if not get_settings().observability_persist_enabled:
        return
    _spawn(_save_llm_call(record))


def record_prompt_snapshot(snapshot) -> None:
    """采集路由（prompt-debug.md §2）：同 record_llm_call。"""
    trace = current_trace.get()
    if trace is not None and hasattr(trace, "prompt_snapshots"):
        if snapshot.request_id is None:
            snapshot = snapshot.model_copy(
                update={"request_id": trace.request_id, "turn_id": trace.turn_id}
            )
        if trace.obs_flushed:
            _spawn(_save_prompt_snapshot(snapshot))
        else:
            trace.prompt_snapshots.append(snapshot)
        return
    submit_prompt_snapshot(snapshot)


def submit_prompt_snapshot(snapshot) -> None:
    if not get_settings().observability_persist_enabled:
        return
    _spawn(_save_prompt_snapshot(snapshot))


async def _save_llm_call(record: LlmCallRecord) -> None:
    try:
        from app.repositories import llm_call_repository

        llm_call_repository.save(record)
    except Exception:
        logger.exception("LLM 调用记录落库失败，已忽略")


async def _save_prompt_snapshot(snapshot) -> None:
    try:
        from app.repositories import prompt_snapshot_repository

        prompt_snapshot_repository.save(snapshot)
    except Exception:
        logger.exception("prompt 快照落库失败，已忽略")


def on_decision(record: DecisionRecord) -> None:
    """决策记录入口（decision-history.md §3）：自治 tick 无 trace 上下文，直接后台写。"""
    if not get_settings().observability_persist_enabled:
        return
    _spawn(_save_decision(record))


def mark_decision_outcome(action_id: str, outcome: str) -> None:
    if not get_settings().observability_persist_enabled:
        return
    _spawn(_mark_decision_outcome(action_id, outcome))


async def _save_decision(record: DecisionRecord) -> None:
    try:
        from app.repositories import decision_repository

        decision_repository.save(record)
    except Exception:
        logger.exception("决策记录落库失败，已忽略")


async def _mark_decision_outcome(action_id: str, outcome: str) -> None:
    try:
        from app.repositories import decision_repository

        decision_repository.mark_outcome(action_id, outcome)
    except Exception:
        logger.exception("决策 outcome 补写失败，已忽略")


async def _flush_error_trace(trace, user_id: str, session_id: str) -> None:
    trace.obs_flushed = True
    try:
        record = _assemble_trace(trace, TraceKind.TURN, user_id, session_id)
        trace_repository.save(record)
    except Exception:
        logger.exception("error trace 持久化失败，已忽略")
    finally:
        _drain_llm_calls(trace, None)
        _drain_prompt_snapshots(trace, None)
