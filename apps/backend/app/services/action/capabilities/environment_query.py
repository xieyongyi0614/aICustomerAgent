"""V9 environment_query 能力：环境只读切片（simulated 数据源，零写）。"""

from app.application import world_engine
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext


class EnvironmentQueryCapability:
    name = "environment_query"
    description = "环境查询：时间/天气/温度/光照切片（只读，simulated）"
    actions = {
        "query": ActionSchema(optional={"dimension": "weather/temperature/time/lighting"}),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        if action != "query":
            return CapabilityResult(status="failed", error=f"未知动作: {action}", payload={"failure_kind": "permanent"})
        from app.services.action.capabilities.reminder import world_gate

        gate = world_gate(ctx)
        if gate is not None:
            return gate
        world = world_engine.get_world(ctx.user_id)
        if world is None:
            return CapabilityResult(
                status="failed",
                error="世界不可用",
                payload={"failure_kind": "permanent"},
            )
        time_ctx = world_engine.build_time_context(ctx.user_id)
        payload = {
            "time": time_ctx.now.isoformat() if time_ctx is not None else None,
            "weekday": time_ctx.weekday if time_ctx is not None else None,
            "part_of_day": time_ctx.part_of_day if time_ctx is not None else None,
            "weather": world.environment.weather,
            "temperature_c": world.environment.temperature_c,
            "lighting": world.environment.lighting,
            "simulated": True,
            "failure_kind": None,
        }
        return CapabilityResult(status="succeeded", payload=payload)
