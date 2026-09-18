"""V9 reminder 能力（capability-system.md §4）：V9 价值的锚点。

提醒 = WorldEvent(type=reminder, due_at)；到期触发/完结/记忆沉淀全部继承 V8 事件语义。
世界写失败 = 行动失败（不静默假成功）。
"""

from app.application import world_engine
from app.core.settings import get_settings
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext


def world_gate(ctx: ExecutionContext) -> CapabilityResult | None:
    """依赖世界的行动：世界未启用 → unavailable（world-integration.md §1.3）。"""
    if ctx.settings is not None and not getattr(ctx.settings, "world_enabled", True):
        return CapabilityResult(status="unavailable", error="世界未启用", payload={"failure_kind": "unavailable"})
    return None


def _parse_due(value) -> object | None:
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class ReminderCapability:
    name = "reminder"
    description = "提醒/日程：创建与取消 WorldEvent(type=reminder)"
    actions = {
        "create": ActionSchema(
            required=["content", "due_at"],
            optional={"importance": "low/normal/high"},
        ),
        "cancel": ActionSchema(required=["target"]),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        gate = world_gate(ctx)
        if gate is not None:
            return gate
        if action == "create":
            return await self._create(params, ctx)
        if action == "cancel":
            return await self._cancel(params, ctx)
        return CapabilityResult(status="failed", error=f"未知动作: {action}", payload={"failure_kind": "permanent"})

    async def _create(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        due_at = _parse_due(params.get("due_at"))
        if due_at is None:
            return CapabilityResult(status="failed", error="due_at 无法解析", payload={"failure_kind": "permanent"})
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "create_event",
                        "args": [
                            ctx.user_id,
                            "reminder",
                            str(params.get("content", ""))[:40],
                            str(params.get("importance", "high")),
                            due_at.isoformat(),
                            "autonomy",
                        ],
                    },
                    "failure_kind": None,
                },
            )
        event = world_engine.create_event(
            ctx.user_id,
            event_type="reminder",
            title=str(params.get("content", ""))[:40],
            importance=str(params.get("importance", "high")),
            due_at=due_at,
            source="autonomy",
        )
        if event is None:
            return CapabilityResult(
                status="failed",
                error="世界事件创建失败（容量上限或世界不可用）",
                payload={"failure_kind": "permanent"},
            )
        return CapabilityResult(
            status="succeeded",
            payload={
                "world_event_id": event.id,
                "due_at": due_at.isoformat(),
                "failure_kind": None,
            },
        )

    async def _cancel(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "cancel_events_by_type",
                        "args": [ctx.user_id, "reminder"],
                    },
                    "failure_kind": None,
                },
            )
        cancelled = world_engine.cancel_events_by_type(ctx.user_id, "reminder")
        count = len(cancelled) if isinstance(cancelled, list) else int(cancelled or 0)
        if count == 0:
            return CapabilityResult(
                status="failed",
                error="没有可取消的提醒",
                payload={"failure_kind": "permanent"},
            )
        return CapabilityResult(status="succeeded", payload={"cancelled": count, "failure_kind": None})
