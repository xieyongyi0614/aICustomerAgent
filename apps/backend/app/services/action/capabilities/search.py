"""V9 search 能力：接口预留占位（MVP unavailable，不接真实第三方 API）。"""

from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext


class SearchCapability:
    name = "search"
    description = "信息检索（接口预留，尚未接入）"
    actions = {
        "query": ActionSchema(required=["query"]),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        return CapabilityResult(status="unavailable", error="该能力尚未接入", payload={"failure_kind": "unavailable"})
