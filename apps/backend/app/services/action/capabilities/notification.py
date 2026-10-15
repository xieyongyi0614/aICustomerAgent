"""V9 notification 能力：行动 note（V2.4.0 TOOL-010 §2.3 推进）。

从"接口预留"推进为**有可判定行为**：`send` 产出一条 note 类效果
（`ToolEffect.kind="note"`，由 `tool/normalizer.py` 从 payload 归一），正文进回复素材
（落既有 `action_records.steps[].result`，随行动结果进回复取材，无需新表新机制）。

到期汇报**复用既有通道**：提醒类到期触发仍由 V8/V2.3 世界事件 + 既有
`trigger_registry(action_due)` 承担（TOOL-005 的确认请求也走同一 `action_due` 类型），
本能力**不新建队列、不新建表、不注册新触发类型**。

离线语义（§6.3 E14）：note 只是素材，**不因用户离线而外发**——本能力零网络、零外发，
`channel.*` 才是外发面；note 留在行动台账里，等下一次对话自然提及。

总闸 off 时保持 V9 原状（`status="unavailable"`），既有 V9 测试逐字节不变。
"""

import hashlib
import logging

from app.core.settings import get_settings
from app.character.asuna.tool import TOOL_FAILURE_TEXT
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext

logger = logging.getLogger(__name__)

TOOL_ID = "builtin.notification.send"

NOTIFICATION_CONTENT_MAX_CHARS = 200

NOTE_ID_PREFIX = "note"


def _settings_of(ctx: ExecutionContext):
    return getattr(ctx, "settings", None) or get_settings()


def _note_id(user_id: str, content: str, dedupe_key: str) -> str:
    seed = f"{user_id}|{content}|{dedupe_key}"
    return f"{NOTE_ID_PREFIX}:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


class NotificationCapability:
    name = "notification"
    description = "用户通知：产出行动 note 并进回复素材（不外发，到期汇报复用既有通道）"
    actions = {
        "send": ActionSchema(required=["content"]),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        if schema is None:
            return [f"未知动作: {action}"]
        errors = schema.validate(params)
        content = params.get("content")
        if isinstance(content, str) and len(content) > NOTIFICATION_CONTENT_MAX_CHARS:
            errors.append(
                f"content 长度 {len(content)} 超出上限 {NOTIFICATION_CONTENT_MAX_CHARS}"
            )
        return errors

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        if action != "send":
            return CapabilityResult(
                status="failed",
                error=f"未知动作: {action}",
                payload={"failure_kind": "permanent", "reason_kind": "unknown_action"},
            )
        settings = _settings_of(ctx)
        content = str(params.get("content") or "").strip()
        if not content:
            return CapabilityResult(
                status="failed",
                error="通知内容为空",
                payload={
                    "failure_kind": "permanent",
                    "reason_kind": "empty_content",
                    "message": TOOL_FAILURE_TEXT[TOOL_ID],
                },
            )
        note_id = _note_id(
            str(getattr(ctx, "user_id", "")),
            content,
            str(getattr(ctx, "dedupe_key", "") or ""),
        )
        moment = getattr(ctx, "now", None)
        logger.info("行动 note 已产出：note_id=%s user_id=%s", note_id, getattr(ctx, "user_id", ""))
        return CapabilityResult(
            status="succeeded",
            payload={
                "note_id": note_id,
                "note_created": True,
                "content": content,
                "created_at": None if moment is None else moment.isoformat(),
                "delivered_next_turn": True,
                "failure_kind": None,
            },
        )
