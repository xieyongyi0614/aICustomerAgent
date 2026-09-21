"""飞书入站编排：收件箱（合并/排队）→ 身份 → 会话串行 → LLM → 既有管线 → TurnOutcome（FEISHU-004）。

管线是唯一对话逻辑（零上下文构建/零落库/零后处理）；本模块只做
"取身份 / 排队 / 取 LLM / 消费事件流 / 组装回复"。出站发送由 FEISHU-005
消费 TurnOutcome（经通道无关 OutboundMessage 契约），不在本模块。

顺序与背压：顺序由 `inbox.SessionInbox` 的 per-session FIFO 批次链显式保证；
背压由 `feishu_session_queue_limit`（排队批次数上限）与
`feishu_max_concurrent_turns`（进程内全局并发闸门）共同承担。
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import openai

from app.application.agent_runtime import inbound as inbound_gateway
from app.channels.base import InboundMessage
from app.channels.feishu import delivery
from app.channels.feishu.events import UnhandledMessage
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.channels.feishu.inbox import SessionInbox
from app.core import llm_factory
from app.core.settings import get_settings
from app.services import agent_service, channel_identity_service, trace_collector
from app.services.agent_service import EmptyLLMResponseError

logger = logging.getLogger(__name__)

_INTERNAL_ERROR_TEXT = "我这边出了点小问题，稍后再试。"

FALLBACK_TEXTS: dict[str, str] = {
    "llm_error": "我这会儿有点走神，等下再说好不好？",
    "empty_response": "我一下子不知道说什么好…你再说一次？",
    "pipeline_error": _INTERNAL_ERROR_TEXT,
    "identity_error": _INTERNAL_ERROR_TEXT,
    "overloaded": "你发得太快了，我一条条慢慢回你～",
    "unsupported": "我目前只能读文字哦～",
}


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    session_id: str
    user_id: str
    outbound_text: str | None
    turn_id: str | None = None
    error_kind: str | None = None
    source_message_ref: str | None = None
    thread_ref: str | None = None
    # RT-013 入站归一（纳管渠道才有值；未纳管恒为 None，行为逐字节不变）
    runtime_input: object | None = None
    session_context: object | None = None


_session_locks: dict[str, asyncio.Lock] = {}
_session_refs: dict[str, int] = {}
_turn_semaphore: asyncio.Semaphore | None = None
_inbox: SessionInbox | None = None


def reset_feishu_adapter() -> None:
    global _turn_semaphore
    _session_locks.clear()
    _session_refs.clear()
    _turn_semaphore = None
    if _inbox is not None:
        _inbox.reset()
    trace_collector.reset_trace_collector()


async def ingest_inbound_message(inbound: InboundMessage) -> None:
    """Webhook 派发入口：进收件箱合并/排队；队列已满则回兜底文案（FEISHU-007）。"""
    if _get_inbox().offer(inbound):
        return
    await _reply_overloaded(inbound)


async def reject_inbound_message(inbound: InboundMessage) -> None:
    """限流命中时的入站处理：不拒收，只回兜底文案。

    上游不得以 429 拒收——飞书对非 2xx 会重投同一个 `event_id`，而该 id 此时
    已落去重表，重投会被静默吞掉（用户既收不到回复、也没有任何留痕）。回兜底
    文案并返回 200 既保住消息，也让用户知道是「发太快」。
    """
    await _reply_overloaded(inbound)


async def reply_unsupported_message(unhandled: UnhandledMessage) -> None:
    """非文本 / 空白私聊消息：不跑管线，只回一句「只能读文字」。

    不回会让用户无法区分「机器人不支持」与「机器人挂了」；且该兜底与普通轮次
    走同一套出站幂等，重投不会重复发送。
    """
    await _deliver_outcome(
        TurnOutcome(
            session_id="",
            user_id="",
            outbound_text=FALLBACK_TEXTS["unsupported"],
            error_kind="unsupported",
            source_message_ref=unhandled.message_id,
            thread_ref=unhandled.chat_id,
        )
    )


async def _reply_overloaded(inbound: InboundMessage) -> None:
    await _deliver_outcome(
        _outcome(
            inbound,
            session_id="",
            user_id="",
            outbound_text=FALLBACK_TEXTS["overloaded"],
            error_kind="overloaded",
        )
    )


async def handle_inbound_message(inbound: InboundMessage) -> TurnOutcome:
    """处理一个批次：同会话严格串行（锁在首个 await 之前取得，保证到达顺序）。"""
    started = time.perf_counter()
    trace = _begin_trace()
    return await _serialized(
        inbound.external_user_id, lambda: _run_inbound(inbound, trace, started)
    )


async def _run_inbound(inbound: InboundMessage, trace, started: float) -> TurnOutcome:
    try:
        resolved = await asyncio.to_thread(_resolve_identity, inbound, trace)
    except Exception:
        return _outcome(
            inbound,
            session_id="",
            user_id="",
            outbound_text=FALLBACK_TEXTS["identity_error"],
            error_kind="identity_error",
        )
    try:
        async with _get_turn_gate():
            outcome = await _run_turn(resolved, inbound, trace, started)
    except Exception:
        logger.exception("feishu inbound handling failed")
        if trace is not None:
            trace.record(
                "feishu_dispatch",
                (time.perf_counter() - started) * 1000,
                status="error",
                error="unhandled",
            )
        outcome = _outcome(
            inbound,
            session_id=resolved.session_id,
            user_id=resolved.internal_user_id,
            outbound_text=FALLBACK_TEXTS["pipeline_error"],
            error_kind="pipeline_error",
        )
    await _deliver_outcome(outcome)
    return outcome


async def _serialized(key: str, runner):
    """按 key 串行执行；空闲且无人等待时回收锁，避免每见一个用户就永久留一个对象。"""
    lock = _session_locks.setdefault(key, asyncio.Lock())
    _session_refs[key] = _session_refs.get(key, 0) + 1
    try:
        async with lock:
            return await runner()
    finally:
        remaining = _session_refs.get(key, 1) - 1
        if remaining <= 0:
            _session_refs.pop(key, None)
            _session_locks.pop(key, None)
        else:
            _session_refs[key] = remaining


async def _deliver_outcome(outcome: TurnOutcome) -> None:
    if not outcome.outbound_text:
        return
    try:
        await delivery.deliver_reply(outcome)
    except Exception:
        logger.exception(
            "feishu delivery failed (ignored): session_id=%s", outcome.session_id
        )


def _outcome(
    inbound: InboundMessage,
    *,
    session_id: str,
    user_id: str,
    outbound_text: str | None,
    error_kind: str | None,
    turn_id: str | None = None,
) -> TurnOutcome:
    runtime_input, session_context = _gateway_projection(inbound)
    return TurnOutcome(
        session_id=session_id,
        user_id=user_id,
        outbound_text=outbound_text,
        turn_id=turn_id,
        error_kind=error_kind,
        source_message_ref=inbound.reply_ref,
        thread_ref=inbound.external_thread_id,
        runtime_input=runtime_input,
        session_context=session_context,
    )


def _gateway_projection(inbound: InboundMessage):
    """RT-013 薄适配：纳管渠道经 Inbound Gateway 归一（**仍调既有 `stream_chat`**）。

    未纳管（默认）→ `(None, None)`，行为逐字节不变；归一异常只记日志、不阻断本轮
    （网关是**附加观测面**，不是执行入口——执行切换属 RT-015）。
    """
    try:
        if not inbound_gateway.is_enabled(FEISHU_CHANNEL):
            return None, None
        return (
            inbound_gateway.normalize_inbound(inbound),
            inbound_gateway.resolve_session(
                FEISHU_CHANNEL,
                inbound.external_user_id,
                thread_id=inbound.external_thread_id,
            ),
        )
    except Exception:
        logger.exception("入站网关归一失败，按未纳管处理：%s", inbound.external_user_id)
        return None, None


def _begin_trace():
    try:
        return trace_collector.get_trace_collector().begin_trace()
    except Exception:
        logger.exception("feishu trace begin failed")
        return None


def _resolve_identity(inbound: InboundMessage, trace):
    try:
        return channel_identity_service.resolve(
            FEISHU_CHANNEL,
            inbound.external_user_id,
            union_id=inbound.metadata.get("union_id"),
            tenant_key=inbound.metadata.get("tenant_key"),
            display_name=None,
        )
    except Exception as exc:
        logger.exception(
            "feishu identity resolve failed: external_user_id=%s", inbound.external_user_id
        )
        if trace is not None:
            trace.record("feishu_dispatch", 0.0, status="error", error=type(exc).__name__)
        raise


async def _run_turn(resolved, inbound: InboundMessage, trace, started: float) -> TurnOutcome:
    session_id = resolved.session_id
    user_id = resolved.internal_user_id
    settings = get_settings()
    try:
        llm = llm_factory.get_llm(settings.feishu_llm_profile or None)
    except Exception:
        logger.exception("feishu llm resolve failed: session_id=%s", session_id)
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=FALLBACK_TEXTS["pipeline_error"],
            error_kind="pipeline_error",
        )
    try:
        chunks, turn_id, saw_done = await _consume_turn(resolved, inbound, llm, trace)
    except EmptyLLMResponseError:
        logger.warning("feishu turn empty response: session_id=%s", session_id)
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=FALLBACK_TEXTS["empty_response"],
            error_kind="empty_response",
        )
    except openai.APIStatusError as exc:
        logger.exception(
            "feishu turn llm error: session_id=%s status=%s",
            session_id,
            getattr(exc, "status_code", None),
        )
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=FALLBACK_TEXTS["llm_error"],
            error_kind="llm_error",
        )
    except Exception:
        logger.exception("feishu turn pipeline failed: session_id=%s", session_id)
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=FALLBACK_TEXTS["pipeline_error"],
            error_kind="pipeline_error",
        )
    reply = "".join(chunks).strip()
    if not reply:
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=FALLBACK_TEXTS["empty_response"],
            error_kind="empty_response",
        )
    if not saw_done:
        logger.error(
            "feishu stream incomplete (no done event): session_id=%s text_len=%d",
            session_id,
            len(reply),
        )
        if trace is not None:
            trace.record("feishu_dispatch", 0.0, status="error", error="incomplete")
        return _outcome(
            inbound,
            session_id=session_id,
            user_id=user_id,
            outbound_text=reply,
            error_kind="incomplete",
            turn_id=turn_id,
        )
    if trace is not None:
        trace.record("feishu_dispatch", (time.perf_counter() - started) * 1000)
    logger.info(
        "feishu turn completed: session_id=%s user_id=%s turn_id=%s "
        "source_message_id=%s elapsed_ms=%.0f text_len=%d",
        session_id,
        user_id,
        turn_id,
        inbound.reply_ref,
        (time.perf_counter() - started) * 1000,
        len(reply),
    )
    return _outcome(
        inbound,
        session_id=session_id,
        user_id=user_id,
        outbound_text=reply,
        error_kind=None,
        turn_id=turn_id,
    )


async def _consume_turn(resolved, inbound: InboundMessage, llm, trace):
    chunks: list[str] = []
    turn_id: str | None = None
    saw_done = False
    async for event in agent_service.stream_chat(
        resolved.session_id,
        resolved.internal_user_id,
        inbound.text,
        llm=llm,
        trace=trace,
    ):
        kind = event.get("kind") if isinstance(event, dict) else None
        if kind == "token":
            text = event.get("text")
            if isinstance(text, str):
                chunks.append(text)
        elif kind == "done":
            turn_id = event.get("turn_id")
            saw_done = True
    return chunks, turn_id, saw_done


def _get_inbox() -> SessionInbox:
    global _inbox
    if _inbox is None:
        _inbox = SessionInbox(handle_inbound_message)
    return _inbox


def _get_turn_gate() -> asyncio.Semaphore:
    """进程内全局并发闸门：让 `feishu_max_concurrent_turns` 真正生效。

    ⚠️ 作用域仅限本进程。多实例下实际并发是 `limit × 实例数`，而 DB 连接池是
    **共享**的，故容量校验按 `feishu_instance_count` 折算。

    当前该折算**只是防御性校验**：`feishu_enabled=true` 且 `feishu_instance_count > 1`
    已被启动期硬闸拦下（FEISHU-011 方案 E）。将来实现跨进程会话串行后硬闸会放开，
    这条折算即恢复为真实保护——届时必须同时把本闸门换成跨进程实现
    （PG advisory lock 计数或 Redis 信号量）。
    """
    global _turn_semaphore
    if _turn_semaphore is None:
        settings = get_settings()
        limit = max(1, settings.feishu_max_concurrent_turns)
        instances = max(1, settings.feishu_instance_count)
        capacity = settings.db_pool_size + settings.db_max_overflow
        if limit * instances > capacity:
            logger.warning(
                "feishu 并发上限 %d × 实例数 %d = %d 超过 DB 连接池容量 %d，"
                "可能出现等待超时（进程内闸门无法跨实例收敛）",
                limit,
                instances,
                limit * instances,
                capacity,
            )
        _turn_semaphore = asyncio.Semaphore(limit)
    return _turn_semaphore
