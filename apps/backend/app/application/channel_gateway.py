"""通道面向契约门面（R-7'）：channels 唯一可依赖的 Runtime 入出站叶子面。

不包含 Agent / Memory / World 逻辑，零仓储、零 chains；调用时迟绑定转发
`agent_runtime.inbound` / `outbound`，渠道实现不绑定 Runtime 包内路径。
"""

from __future__ import annotations

from typing import AsyncIterator

from app.application import chat_pipeline as _chat_pipeline
from app.application.agent_runtime import inbound as _inbound
from app.application.agent_runtime import outbound as _outbound

CHANNEL_WEB = _inbound.CHANNEL_WEB
CHANNEL_FEISHU = _inbound.CHANNEL_FEISHU

EmptyLLMResponseError = _chat_pipeline.EmptyLLMResponseError


async def stream_chat(
    session_id: str, user_id: str, content: str, llm=None, trace=None
) -> AsyncIterator[dict]:
    """前台对话流（T-33 收编）：通道经本门面消费，不直连 chat_pipeline。"""
    async for event in _chat_pipeline.stream_chat(session_id, user_id, content, llm, trace):
        yield event


def is_enabled(channel: str) -> bool:
    return _inbound.is_enabled(channel)


def normalize_inbound(message):
    return _inbound.normalize_inbound(message)


def resolve_session(*args, **kwargs):
    return _inbound.resolve_session(*args, **kwargs)


def is_routable(channel: str) -> bool:
    return _outbound.is_routable(channel)


async def deliver_reply(*args, **kwargs):
    return await _outbound.deliver_reply(*args, **kwargs)


async def deliver_proactive(*args, **kwargs):
    return await _outbound.deliver_proactive(*args, **kwargs)


def register_adapter(channel: str, adapter) -> None:
    _outbound.register_adapter(channel, adapter)


def resolve_adapter(channel: str):
    return _outbound.resolve_adapter(channel)


def registered_channels() -> frozenset[str]:
    return _outbound.registered_channels()


def clear_adapters() -> None:
    _outbound.clear_adapters()


def enabled_channels() -> frozenset[str]:
    return _outbound.enabled_channels()


__all__ = [
    "CHANNEL_FEISHU",
    "CHANNEL_WEB",
    "EmptyLLMResponseError",
    "clear_adapters",
    "deliver_proactive",
    "deliver_reply",
    "enabled_channels",
    "is_enabled",
    "is_routable",
    "normalize_inbound",
    "register_adapter",
    "registered_channels",
    "resolve_adapter",
    "resolve_session",
    "stream_chat",
]
