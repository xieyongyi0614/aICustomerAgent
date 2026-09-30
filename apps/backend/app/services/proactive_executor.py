"""V7 Proactive Executor（action-queue.md §2 / concurrency.md L1~L3 / failure-handling.md）。

approved 状态的 ProactiveAction → 锁内二次校验 → 生成文本 → save_proactive_turn
→ send_proactive → delivered（AUTO-005 两阶段投递：生成可重试；Channel 失败
仅重发，不重生成、不重新裁决）。delivered 语义 = Channel 已成功投递；
未注册 outbound（纯 Web 部署）时退化为内部落库完成。
主动消息不是对话轮：不触发 V5 状态更新 / goal_review / memory 提取。
"""

import logging
import time
from datetime import datetime, timedelta

from app.application import observability
from app.application.autonomy_bridge import (
    coordinate_delivery,
    emit_proactive_triggered,
)
from app.application.post_process import get_user_write_lock
from app.channels.base import ChannelErrorKind, SendResult
from app.chains import proactive_chain
from app.core.settings import get_settings
from app.application.life_loop_context import memory_digest_var
from app.models.autonomy import ProactiveAction
from app.repositories import (
    conversation_repository,
    goal_repository,
    proactive_repository,
)
from app.services import conversation_service
from app.services.delivery import outbound as proactive_delivery
from app.services.autonomy_policy import in_quiet_hours
from app.services.trace_collector import TurnTraceSession
from app.application.chat_pipeline import active_generations
from app.services.evaluation_engine import schedule_proactive_evaluation

logger = logging.getLogger(__name__)


def _mark_outcome(action_id: str, outcome: str) -> None:
    try:
        observability.mark_decision_outcome(action_id, outcome)
    except Exception:
        logger.exception("主动决策 outcome 补写失败，已忽略")


def _recheck_failed_reason(
    action: ProactiveAction, user_id: str, session_id: str, now: datetime
) -> str | None:
    settings = get_settings()
    if active_generations.get(user_id):
        return "generating"
    if in_quiet_hours(
        now, settings.autonomy_quiet_hours_start, settings.autonomy_quiet_hours_end
    ):
        return "quiet_hours"
    recent = conversation_repository.get_recent_messages(session_id, limit=1)
    if recent:
        last = recent[-1]
        if (
            last.role == "human"
            and last.created_at is not None
            and (now - last.created_at).total_seconds() / 60
            < settings.autonomy_min_user_reply_gap_minutes
        ):
            return "user_active"
    return None


def _backoff_seconds(attempt: int) -> float:
    settings = get_settings()
    return settings.autonomy_tick_seconds * (
        settings.autonomy_backoff_multiplier**attempt
    )


async def _fail_for_retry(
    action: ProactiveAction,
    trace: TurnTraceSession | None,
    error: str,
    now: datetime,
    **fields,
) -> ProactiveAction:
    settings = get_settings()
    attempt = action.attempt + 1
    if attempt >= settings.autonomy_max_retries:
        updated = proactive_repository.transition(
            action.id, "failed", now=now, attempt=attempt, next_retry_at=None, **fields
        )
        logger.error("主动消息重试耗尽：%s（终态 failed）", action.id)
        _mark_outcome(action.id, "failed")
    else:
        updated = proactive_repository.transition(
            action.id,
            "failed",
            now=now,
            attempt=attempt,
            next_retry_at=now + timedelta(seconds=_backoff_seconds(attempt)),
            **fields,
        )
    if trace is not None:
        trace.record("proactive_deliver", 0.0, "error", error=error)
    return updated if updated is not None else action


def _goal_description(action: ProactiveAction) -> str | None:
    """动机消失（目标被 review 完成/取消）→ None，视同生成失败（failure-handling.md §2）。"""
    if action.goal_id is None:
        return action.reason or None
    try:
        goal = goal_repository.get_goal(action.goal_id)
    except Exception:
        logger.exception("主动目标读取失败：%s", action.goal_id)
        return None
    if goal is None or goal.status != "active":
        return None
    return goal.description


def _generation_artifacts(action: ProactiveAction) -> tuple[str, int] | None:
    """生成阶段的已持久化产物（重发路径复用，不重生成）；不完整返回 None。"""
    if not action.payload_text or action.message_id is None:
        return None
    try:
        return action.payload_text, int(action.message_id)
    except ValueError:
        return None


async def _send_via_outbound(
    outbound,
    action: ProactiveAction,
    text: str,
    trace: TurnTraceSession | None,
) -> SendResult:
    """投递出口（RT-017）：统一经 `coordinate_delivery`（网关优先 / 未纳管回落）。"""
    return await coordinate_delivery(
        getattr(action, "id", None) or action.dedupe_key,
        dedupe_key=action.dedupe_key,
        user_id=action.user_id,
        text=text,
        outbound=outbound,
        trace=trace,
    )


async def _send_phase(
    action: ProactiveAction,
    text: str,
    message_id: int,
    llm,
    trace: TurnTraceSession | None,
    now: datetime,
    started: float,
) -> ProactiveAction | None:
    """发送阶段：Channel 失败仅重发（产物随 failed 行持久化），不重生成、不重新裁决。"""
    outbound = proactive_delivery.get_proactive_outbound()
    result: SendResult | None = None
    if outbound is not None:
        result = await _send_via_outbound(outbound, action, text, trace)
        if not result.ok:
            error = result.error.value if result.error else ChannelErrorKind.UNKNOWN.value
            return await _fail_for_retry(
                action,
                trace,
                f"send_{error}",
                now,
                payload_text=text,
                message_id=str(message_id),
            )
    delivered = proactive_repository.transition(
        action.id,
        "delivered",
        delivered_at=now,
        message_id=str(message_id),
        payload_text=text,
        external_message_id=result.external_message_id if result else None,
    )
    if trace is not None:
        trace.record(
            "proactive_deliver",
            (time.perf_counter() - started) * 1000,
            external_message_id=result.external_message_id if result else None,
            channel=outbound.channel if outbound else None,
        )
    _mark_outcome(action.id, "delivered")
    _schedule_evaluation(delivered, llm)
    logger.info(
        "主动消息已投递：action=%s message=%s external=%s channel=%s 预览=%s",
        action.id,
        message_id,
        result.external_message_id if result else None,
        outbound.channel if outbound else None,
        text[: get_settings().log_content_preview_chars or 12],
    )
    return delivered


async def execute(
    action: ProactiveAction,
    llm=None,
    trace: TurnTraceSession | None = None,
    now: datetime | None = None,
) -> ProactiveAction | None:
    started = time.perf_counter()
    now = now or datetime.now()

    lock = get_user_write_lock(action.user_id)
    async with lock:
        fresh = proactive_repository.get_by_id(action.id)
        if fresh is None or fresh.status not in ("candidate", "failed", "approved"):
            return fresh
        approved = proactive_repository.transition(action.id, "approved", now=now)
        if approved is None:
            return None
        reason = _recheck_failed_reason(action, action.user_id, action.session_id, now)
        if reason == "generating":
            rolled_back = proactive_repository.transition(
                action.id, "candidate", now=now
            )
            if trace is not None:
                trace.record("proactive_deliver", 0.0, "degraded", error=reason)
            return rolled_back
        if reason is not None:
            discarded = proactive_repository.transition(
                action.id, "discarded", now=now
            )
            if trace is not None:
                trace.record("proactive_deliver", 0.0, "degraded", error=reason)
            _mark_outcome(action.id, "discarded")
            return discarded
        emit_proactive_triggered(
            action.dedupe_key,
            reason=action.reason,
            trigger_type=getattr(action, "trigger_type", None),
            user_id=action.user_id,
            trace=trace,
        )

        artifacts = _generation_artifacts(approved)
        if artifacts is not None:
            text, message_id = artifacts
        else:
            goal_description = _goal_description(action)
            if goal_description is None:
                return await _fail_for_retry(action, trace, "goal_vanished", now)
            recent = _recent_context(action.session_id)
            digest = memory_digest_var.get()
            if digest:
                recent = f"{recent}\n{digest}" if recent else digest
            text = await proactive_chain.generate(
                goal_description,
                action.intention,
                recent,
                llm=llm,
                trace=trace,
            )
            if not text:
                return await _fail_for_retry(action, trace, "generate_failed", now)
            try:
                message_id = conversation_service.save_proactive_turn(
                    action.session_id, text
                )
            except Exception:
                logger.exception("主动消息落库失败，action 停留 approved 下 tick 重试")
                proactive_repository.transition(action.id, "candidate")
                if trace is not None:
                    trace.record("proactive_deliver", 0.0, "error", error="persist_failed")
                return None
        return await _send_phase(
            approved, text, message_id, llm, trace, now, started
        )


def _schedule_evaluation(delivered, llm) -> None:
    if delivered is None:
        return
    try:
        schedule_proactive_evaluation(delivered, llm)
    except Exception:
        logger.exception("主动行为评估调度失败，不影响发送链路")


def _recent_context(session_id: str, turns: int = 2) -> str:
    messages = conversation_service.load_window(session_id, max_messages=turns * 2)
    lines = [
        f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
        for m in messages[-turns * 2 :]
    ]
    return "\n".join(lines)
