"""通道无关契约：入站基元 + 出站协议。

本模块是全部层允许依赖的最底层契约（R2/R4）：
仅标准库、零第三方依赖、零 `app.*` 依赖；不含任何渠道特有概念与行为实现。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

TEXT_MAX_CHARS = 20000


@dataclass(frozen=True, slots=True)
class InboundMessage:
    channel: str
    external_user_id: str
    text: str
    received_at: datetime
    external_thread_id: str | None = None
    reply_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.channel:
            raise ValueError("channel 不能为空")
        if not self.external_user_id:
            raise ValueError("external_user_id 不能为空")
        if not self.text.strip():
            raise ValueError("text 不能为空")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at 必须为时区感知时间")
        if len(self.text) > TEXT_MAX_CHARS:
            object.__setattr__(self, "text", self.text[:TEXT_MAX_CHARS])
            object.__setattr__(
                self, "metadata", {**self.metadata, "truncated": True}
            )


@dataclass(frozen=True, slots=True)
class ChannelIdentity:
    channel: str
    external_user_id: str
    tenant: str | None = None
    display_name: str | None = None

    def __post_init__(self):
        if not self.channel:
            raise ValueError("channel 不能为空")
        if not self.external_user_id:
            raise ValueError("external_user_id 不能为空")


@dataclass(frozen=True, slots=True)
class ChannelReply:
    text: str
    reply_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.text.strip():
            raise ValueError("text 不能为空")
        if len(self.text) > TEXT_MAX_CHARS:
            object.__setattr__(self, "text", self.text[:TEXT_MAX_CHARS])
            object.__setattr__(
                self, "metadata", {**self.metadata, "truncated": True}
            )


@dataclass(frozen=True, slots=True)
class RecipientRef:
    channel: str
    external_id: str


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    channel: str
    recipient: RecipientRef
    text: str
    reply_ref: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SendResult:
    ok: bool
    external_message_id: str | None = None
    error: ChannelErrorKind | None = None


class ChannelErrorKind(StrEnum):
    NOT_FOUND = "not_found"
    AUTH = "auth"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    DISABLED = "disabled"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"


@runtime_checkable
class ChannelAdapter(Protocol):
    async def send(self, message: OutboundMessage) -> SendResult: ...
