"""V9 notification 能力：接口预留占位（MVP 通知 = 行动 note + V7 到期主动汇报）。"""

from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext


class NotificationCapability:
    name = "notification"
    description = "用户通知（接口预留，MVP 落行动 note）"
    actions = {
        "send": ActionSchema(required=["content"]),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        return CapabilityResult(status="unavailable", error="该能力尚未接入", payload={"failure_kind": "unavailable"})
