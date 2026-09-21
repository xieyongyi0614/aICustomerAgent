"""Inbound Gateway（RT-013）：入站归一 + 会话解析。

Runtime 的**唯一入站面**（architecture §8.1）：`Web / Feishu / Discord → Inbound Gateway
→ Agent Runtime`。本模块只做两件事——**归一为 `RuntimeInput`** 与**解析 `SessionContext`**；
执行入口的接管（把 `stream_chat` 换成 `AgentLoop.run`）属 RT-015。

边界（RT-013 §3.2 / §4.3）：

- **契约零改动**（D3）：不碰 `channels/base.py` 的 `InboundMessage` / `ChannelAdapter`；
  本模块只 import `app.channels.base`，**不得** import 任何具体渠道实现。
- **不接管执行入口**（D1）：不改 `agent_service.stream_chat` 的调用点。
- **逐渠道切**（D2）：`runtime_inbound_gateway_channels`（csv）控制已纳管渠道；
  未纳管渠道走既有路径、行为逐字节不变。
- **纯函数 + 只读**（D5）：`normalize*` 零 IO 零 DB；`resolve_session` 只派生不写表。
- **fail-closed**（D6）：未知 channel → `ValueError`，避免静默归一成错来源。
- **线程语义不外泄**：`external_thread_id` 只作 `thread_id` 透传，**不参与 `session_id` 计算**。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.application.agent_runtime.contracts import (
    DEFAULT_CHARACTER_ID,
    RuntimeInput,
    SessionContext,
)
from app.application.agent_runtime.models import TRIGGER_CHANNEL_MESSAGE
from app.channels.base import ChannelIdentity, InboundMessage
from app.core.settings import get_settings

CHANNEL_WEB = "web"
CHANNEL_FEISHU = "feishu"

CHANNEL_SOURCES: Mapping[str, str] = {
    CHANNEL_WEB: "rest",
    CHANNEL_FEISHU: "webhook",
}
"""渠道注册表（代码静态注册）：`channel → 入站来源形态`。

Discord 仅留注册位（RT-013 Out of Scope：不实现渠道实现），故**不入表**——未注册渠道
在 `normalize*` 处 fail-closed。
"""

KNOWN_CHANNELS: frozenset[str] = frozenset(CHANNEL_SOURCES)


def enabled_channels() -> frozenset[str]:
    """已纳管入站归一渠道（csv；空白容错，未知项忽略）。"""
    raw = getattr(get_settings(), "runtime_inbound_gateway_channels", "") or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def is_enabled(channel: str) -> bool:
    return channel in enabled_channels()


def _require_known(channel: str) -> str:
    if channel not in KNOWN_CHANNELS:
        raise ValueError(f"未注册的入站渠道：{channel!r}（fail-closed）")
    return channel


def normalize(
    channel: str,
    *,
    text: str,
    received_at: datetime,
    external_user_id: str | None = None,
    thread_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> RuntimeInput:
    """入参 → `RuntimeInput`（纯函数；契约校验由 `RuntimeInput` 自身完成）。"""
    _require_known(channel)
    identity = (
        ChannelIdentity(channel, external_user_id) if external_user_id else None
    )
    body: dict[str, Any] = {**dict(payload or {}), "text": text}
    return RuntimeInput(
        kind=TRIGGER_CHANNEL_MESSAGE,
        source=channel,
        payload=body,
        received_at=received_at,
        channel_identity=identity,
        thread_id=thread_id,
    )


def normalize_inbound(message: InboundMessage) -> RuntimeInput:
    """`channels.base.InboundMessage` → `RuntimeInput`（契约入参形态）。

    `external_thread_id` **只**作 `thread_id` 透传；渠道 `metadata` 并入 payload
    （`text` 恒以消息正文为准）。
    """
    return normalize(
        message.channel,
        text=message.text,
        received_at=message.received_at,
        external_user_id=message.external_user_id,
        thread_id=message.external_thread_id,
        payload=dict(message.metadata or {}),
    )


def resolve_session(
    channel: str,
    external_user_id: str,
    *,
    thread_id: str | None = None,
    character_id: str = DEFAULT_CHARACTER_ID,
    now: datetime | None = None,
) -> SessionContext:
    """渠道身份 → `SessionContext`（只读派生，零写表）。

    `session_id` 一律经既有 `channel_identity_service.build_session_id` 派生（**结果不变**）。
    """
    from app.application.agent_runtime import session as session_module
    from app.services import channel_identity_service

    _require_known(channel)
    session_id = channel_identity_service.build_session_id(channel, external_user_id)
    return session_module.build_session_context(
        session_id,
        character_id=character_id,
        channel=channel,
        external_user_id=external_user_id,
        thread_id=thread_id,
        now=now,
    )
