"""飞书会话收件箱：短窗口合并连发消息 + 每会话 FIFO 批次链（FEISHU-007）。

职责边界：本模块只做「合并 / 排队 / 顺序」，不碰身份解析、管线与落库——批次一律
交由注入的 `handler` 处理。

顺序保证：`offer()` 同步入缓冲（无 `await`），flush 时把批次压入该会话的 FIFO
队列，由**唯一**的 per-session worker 顺序消费。因此「处理顺序 = 到达顺序」是显式
构造出来的，不再依赖「同步阻塞恰好不让出事件循环」这一副作用。

实例局部性：合并窗口与批次链都只在**进程内**生效。多实例部署下同一 `open_id` 若
落到不同 worker，连发消息不会被合并（顺序仍须由跨进程锁保证）。跨实例合并需在
ingress 按 `open_id` 做 sticky 路由，见 docs/integrations/feishu/review-v1.1.md。
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field, replace

from app.channels.base import InboundMessage
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

MERGE_SEPARATOR = "\n"


@dataclass(slots=True)
class _Session:
    buffer: list[InboundMessage] = field(default_factory=list)
    timer: asyncio.TimerHandle | None = None
    queue: deque[InboundMessage] = field(default_factory=deque)
    worker: asyncio.Task | None = None
    pending: int = 0


class SessionInbox:
    """按 `open_id` 分桶的连发合并 + 顺序批次链。"""

    def __init__(self, handler) -> None:
        self._handler = handler
        self._sessions: dict[str, _Session] = {}

    def offer(self, inbound: InboundMessage) -> bool:
        """受理一条入站消息。返回 False 表示该会话队列已满（由调用方回兜底文案）。"""
        settings = get_settings()
        key = inbound.external_user_id
        session = self._sessions.get(key)
        if session is None:
            session = _Session()
            self._sessions[key] = session
        if self._inflight(session) >= settings.feishu_session_queue_limit:
            logger.warning(
                "feishu inbox queue full: key=%s inflight=%d", key, self._inflight(session)
            )
            return False
        session.buffer.append(inbound)
        window = settings.feishu_merge_window_ms / 1000.0
        if window <= 0 or self._limits_hit(session, settings):
            self._flush(key)
            return True
        if session.timer is None:
            # 固定窗口：首条到达即起计时，窗口内新消息不重置，避免持续打字导致永不 flush。
            session.timer = asyncio.get_running_loop().call_later(window, self._flush, key)
        return True

    def pending(self, key: str) -> int:
        session = self._sessions.get(key)
        return 0 if session is None else self._inflight(session)

    def reset(self) -> None:
        for session in self._sessions.values():
            if session.timer is not None:
                session.timer.cancel()
                session.timer = None
        self._sessions.clear()

    def _inflight(self, session: _Session) -> int:
        return session.pending + (1 if session.buffer else 0)

    def _limits_hit(self, session: _Session, settings) -> bool:
        if len(session.buffer) >= settings.feishu_merge_max_messages:
            return True
        return sum(len(message.text) for message in session.buffer) >= settings.feishu_merge_max_chars

    def _flush(self, key: str) -> None:
        session = self._sessions.get(key)
        if session is None or not session.buffer:
            return
        if session.timer is not None:
            session.timer.cancel()
            session.timer = None
        session.queue.append(_merge(session.buffer))
        session.buffer.clear()
        if session.worker is None or session.worker.done():
            try:
                session.worker = asyncio.get_running_loop().create_task(self._drain(key))
            except RuntimeError:
                session.worker = None
                logger.error("feishu inbox flush skipped: no running loop key=%s", key)

    async def _drain(self, key: str) -> None:
        session = self._sessions.get(key)
        if session is None:
            return
        try:
            while session.queue:
                batch = session.queue.popleft()
                session.pending += 1
                try:
                    await self._handler(batch)
                except Exception:
                    logger.exception("feishu inbox batch failed: key=%s", key)
                finally:
                    session.pending -= 1
        finally:
            session.worker = None
            if not session.queue and not session.buffer and session.timer is None:
                self._sessions.pop(key, None)


def _merge(messages: list[InboundMessage]) -> InboundMessage:
    """合并为一条：文本按到达顺序拼接，锚点取最后一条（飞书 reply 语义）。"""
    if len(messages) == 1:
        return messages[0]
    last = messages[-1]
    return replace(
        messages[0],
        text=MERGE_SEPARATOR.join(message.text for message in messages),
        reply_ref=last.reply_ref,
        metadata=last.metadata,
    )
