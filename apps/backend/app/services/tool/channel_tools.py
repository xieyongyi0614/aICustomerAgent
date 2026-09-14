"""V2.4.0 通道工具包装（architecture.md §7.6 / TOOL-010 §2.1、§2.3、§4.2）。

把既有飞书出站能力包装成工具面可治理的能力，**不新建通道**：

- 出站契约（`OutboundMessage` / `SendResult` / `RecipientRef`）、文本切分
  （`feishu/outbound.split_text`）、身份解析（`channel_identity_service`）全部**原样复用**；
  本模块只做"参数 → `OutboundMessage`"适配与 `ChannelErrorKind → failure_kind` 归一。
- **切分不重写**：本模块不出现任何切片 / 分段 / 折行实现，分段由既有
  `delivery._send` 内部调用既有 `split_text` 完成（不变式 `"".join(parts) == text`
  仍由既有测试持有）。
- **依赖倒置**：边界守门（`tests/unit/test_feishu_boundary.py` R2）禁止 services/ 直接
  import `app.channels.<impl>`，故通道实现按 `proactive_delivery` 同款接缝由组合根注入
  （`register_channel_adapter`，`main.py` lifespan 按 `feishu_enabled` 注册）。
  未注册适配器时执行给出明确 `unavailable`（`reason_kind=adapter_not_registered`），
  不伪造外发结果、不 import 具体通道。
- **幂等直填**：`OutboundMessage.idempotency_key = dedupe_key`（TOOL-003 的
  `ToolInvocation.dedupe_key` 经 `ExecutionContext.dedupe_key` 下传，见 `tool/executor.py`）；
  取不到时按 (user, content, recipient) 派生确定性键并记 warning——通道侧要求幂等键非空，
  缺键会被既有 `delivery` 判 `INVALID_REQUEST`。
- **失败不抛异常**：一切失败形态归一为 `CapabilityResult`（§2.3 映射表逐行落
  `CHANNEL_ERROR_FAILURE_KINDS`）。`AUTH` / `DISABLED` / `NOT_FOUND` / `INVALID_REQUEST`
  为 `permanent`（不重试），`RATE_LIMITED` / `TIMEOUT` / `SERVER_ERROR` / `CLIENT_ERROR` /
  `UNKNOWN` 为可重试（`transient` / `timeout`，与 `action_engine.RETRYABLE_FAILURES` 对齐）。

可用性由 `channel_tools_enabled()` 单点裁决（总闸 + 通道子闸 + `feishu_enabled`）：
声明期（`builtin.py` 的工具状态）与运行时（能力执行）共用同一判据，避免"工具面说可用、
执行说不可用"的双源漂移。能力在全局 `CapabilityRegistry` 中**仅在通道可用时注册**
（`capabilities/__init__.py`），故默认配置下 V9 仍是六个能力。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.channels.base import (
    ChannelAdapter,
    ChannelErrorKind,
    OutboundMessage,
    RecipientRef,
    SendResult,
)
from app.character.asuna.tool import CHANNEL_FAILURE_TEXT, TOOL_FAILURE_TEXT
from app.core.settings import get_settings
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext

logger = logging.getLogger(__name__)

CHANNEL_CAPABILITY_NAME = "channel_feishu"

CHANNEL_NAME = "feishu"

CHANNEL_SEND_TOOL_ID = f"channel.{CHANNEL_NAME}.send"

CHANNEL_SCOPE = f"channel:{CHANNEL_NAME}"

CHANNEL_SEND_ACTION = "send"

CHANNEL_TEXT_MAX_CHARS = 200

IDEMPOTENCY_FALLBACK_LOG = "channel_send_idempotency_key_derived"

ADAPTER_MISSING_REASON = "adapter_not_registered"

CHANNEL_ERROR_FAILURE_KINDS: dict[str, str] = {
    ChannelErrorKind.RATE_LIMITED: "transient",
    ChannelErrorKind.TIMEOUT: "timeout",
    ChannelErrorKind.SERVER_ERROR: "transient",
    ChannelErrorKind.AUTH: "permanent",
    ChannelErrorKind.DISABLED: "permanent",
    ChannelErrorKind.NOT_FOUND: "permanent",
    ChannelErrorKind.INVALID_REQUEST: "permanent",
    ChannelErrorKind.CLIENT_ERROR: "transient",
    ChannelErrorKind.UNKNOWN: "transient",
}

RETRYABLE_FAILURE_KINDS: tuple[str, ...] = ("transient", "timeout")

NON_RETRYABLE_CHANNEL_ERRORS: tuple[str, ...] = ("auth", "disabled")

MISSING_ERROR_CODE = ChannelErrorKind.UNKNOWN.value


def channel_tools_enabled(settings: Any = None) -> bool:
    """通道工具可用性单点判据：总闸 + 通道子闸 + `feishu_enabled` 三者同时成立。"""
    resolved = settings if settings is not None else get_settings()
    if not bool(getattr(resolved, "v24_tool_system_enabled", False)):
        return False
    if not bool(getattr(resolved, "v24_tool_channel_enabled", False)):
        return False
    return bool(getattr(resolved, "feishu_enabled", False))


def failure_kind_for(error: ChannelErrorKind | None) -> str:
    """`ChannelErrorKind → failure_kind`（§2.3 映射表）；缺错误码按 `UNKNOWN` 处理。"""
    if error is None:
        logger.warning("通道失败但未携带错误码，按 %s 处理", MISSING_ERROR_CODE)
        return CHANNEL_ERROR_FAILURE_KINDS[ChannelErrorKind.UNKNOWN]
    return CHANNEL_ERROR_FAILURE_KINDS.get(
        error, CHANNEL_ERROR_FAILURE_KINDS[ChannelErrorKind.UNKNOWN]
    )


def is_retryable(failure_kind: str) -> bool:
    return failure_kind in RETRYABLE_FAILURE_KINDS


def failure_text_for(error: ChannelErrorKind | None) -> str:
    key = MISSING_ERROR_CODE if error is None else str(error)
    return CHANNEL_FAILURE_TEXT.get(key, CHANNEL_FAILURE_TEXT[MISSING_ERROR_CODE])


def idempotency_key_for(ctx: ExecutionContext, content: str, recipient: str) -> str:
    """幂等键：优先取调用方下传的 `dedupe_key`，取不到时按三元组派生确定性键。"""
    declared = str(getattr(ctx, "dedupe_key", "") or "").strip()
    if declared:
        return declared
    logger.warning(
        "%s：dedupe_key 缺失，按 (user, content, recipient) 派生；user_id=%s",
        IDEMPOTENCY_FALLBACK_LOG,
        getattr(ctx, "user_id", ""),
    )
    seed = f"{getattr(ctx, 'user_id', '')}|{content}|{recipient}"
    return "derived:" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


_adapters: dict[str, ChannelAdapter] = {}


def register_channel_adapter(channel: str, adapter: ChannelAdapter) -> None:
    """通道适配器注入（组合根唯一写入面，与 `proactive_delivery` 同款接缝）。"""
    _adapters[channel] = adapter


def reset_channel_adapters() -> None:
    _adapters.clear()


def get_channel_adapter(channel: str | None = None) -> ChannelAdapter | None:
    return _adapters.get(channel or CHANNEL_NAME)


def _failure(
    status: str,
    error: str,
    *,
    failure_kind: str,
    channel_error: ChannelErrorKind | None,
    content: str,
) -> CapabilityResult:
    return CapabilityResult(
        status=status,
        error=error,
        payload={
            "failure_kind": failure_kind,
            "retryable": is_retryable(failure_kind),
            "channel_error": MISSING_ERROR_CODE if channel_error is None else str(channel_error),
            "external_sent": False,
            "content": content,
            "message": failure_text_for(channel_error),
        },
    )


class ChannelCapability:
    """飞书出站能力的工具包装（§4.2 接口）：`send` 单一动作，失败不抛异常。"""

    name = CHANNEL_CAPABILITY_NAME
    description = "飞书通道外发：复用既有出站契约与文本切分（外部可见，高风险）"
    actions = {"send": ActionSchema(required=["content", "recipient"])}

    def __init__(
        self,
        adapter: ChannelAdapter | None = None,
        settings: Any = None,
        channel: str = CHANNEL_NAME,
    ) -> None:
        self._adapter = adapter
        self._settings = settings
        self.channel = channel

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        if schema is None:
            return [f"未知动作: {action}"]
        errors = schema.validate(params)
        content = params.get("content")
        if isinstance(content, str) and len(content) > CHANNEL_TEXT_MAX_CHARS:
            errors.append(
                f"content 长度 {len(content)} 超出上限 {CHANNEL_TEXT_MAX_CHARS}"
            )
        return errors

    async def execute(
        self, action: str, params: dict, ctx: ExecutionContext
    ) -> CapabilityResult:
        if action != CHANNEL_SEND_ACTION:
            return _failure(
                "failed",
                f"未知动作: {action}",
                failure_kind="permanent",
                channel_error=ChannelErrorKind.INVALID_REQUEST,
                content="",
            )
        settings = self._settings if self._settings is not None else getattr(ctx, "settings", None)
        if not channel_tools_enabled(settings):
            return self._unavailable("飞书通道未启用")
        adapter = self._adapter if self._adapter is not None else get_channel_adapter(self.channel)
        if adapter is None:
            return self._unavailable("通道出站适配器未注册（组合根未接缝）")
        content = str(params.get("content") or "").strip()
        recipient = str(params.get("recipient") or "").strip()
        if not content:
            return _failure(
                "failed",
                "消息内容为空",
                failure_kind="permanent",
                channel_error=ChannelErrorKind.INVALID_REQUEST,
                content=content,
            )
        if not recipient:
            return _failure(
                "failed",
                "收件人未绑定",
                failure_kind="permanent",
                channel_error=ChannelErrorKind.NOT_FOUND,
                content=content,
            )
        return await self._send(adapter, content, recipient, ctx)

    def _unavailable(self, error: str) -> CapabilityResult:
        return CapabilityResult(
            status="unavailable",
            error=error,
            payload={
                "failure_kind": "unavailable",
                "retryable": False,
                "reason_kind": ADAPTER_MISSING_REASON,
                "external_sent": False,
                "message": TOOL_FAILURE_TEXT[CHANNEL_SEND_TOOL_ID],
            },
        )

    async def _send(
        self,
        adapter: ChannelAdapter,
        content: str,
        recipient: str,
        ctx: ExecutionContext,
    ) -> CapabilityResult:
        message = OutboundMessage(
            channel=self.channel,
            recipient=RecipientRef(channel=self.channel, external_id=recipient),
            text=content,
            idempotency_key=idempotency_key_for(ctx, content, recipient),
        )
        try:
            result = await adapter.send(message)
        except Exception as exc:
            logger.exception("通道工具外发异常，归一为 %s", ChannelErrorKind.UNKNOWN)
            return _failure(
                "failed",
                f"{exc.__class__.__name__}: {exc}",
                failure_kind=failure_kind_for(ChannelErrorKind.UNKNOWN),
                channel_error=ChannelErrorKind.UNKNOWN,
                content=content,
            )
        if not isinstance(result, SendResult) or not result.ok:
            error = getattr(result, "error", None)
            kind = failure_kind_for(error)
            return _failure(
                _status_for(kind),
                _error_text(error),
                failure_kind=kind,
                channel_error=error,
                content=content,
            )
        if not result.external_message_id:
            logger.info(
                "通道外发成功但响应缺 external_message_id（不视为失败）：recipient=%s",
                recipient,
            )
        return CapabilityResult(
            status="succeeded",
            payload={
                "external_sent": True,
                "external_message_id": result.external_message_id or "",
                "content": content,
                "recipient": recipient,
                "idempotency_key": message.idempotency_key,
                "failure_kind": None,
            },
        )


def _status_for(failure_kind: str) -> str:
    return "timeout" if failure_kind == "timeout" else "failed"


def _error_text(error: ChannelErrorKind | None) -> str:
    if error is None:
        return "通道返回失败但未携带错误码"
    return f"通道发送失败: {error}"


_channel_capability: ChannelCapability | None = None


def get_channel_capability() -> ChannelCapability:
    """模块级单例：声明期校验与运行时执行共用同一实现体（无外部资源构造）。"""
    global _channel_capability
    if _channel_capability is None:
        _channel_capability = ChannelCapability()
    return _channel_capability
