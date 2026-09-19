"""V9 world_action 能力：V8 实体操作的行动视角（capability-system.md §4）。

委托性请求（"帮我买牛奶"）而非叙事性话语；先查实体再迁移，不造事实。
"""

from app.application import world_engine
from app.core.settings import get_settings
from app.character.asuna.action import infer_object_category
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext
from app.services.world.locations import resolve_location_alias


from app.services.action.capabilities.reminder import world_gate


def _failure(error: str) -> CapabilityResult:
    return CapabilityResult(status="failed", error=error, payload={"failure_kind": "permanent"})


def _consume_items(params: dict) -> list[dict] | None:
    raw = params.get("items")
    if not isinstance(raw, list) or not raw:
        return None
    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict) or not str(entry.get("object", "")).strip():
            continue
        items.append(
            {"object": str(entry["object"]), "quantity": float(entry.get("quantity") or 1)}
        )
    return items or None


class WorldActionCapability:
    name = "world_action"
    description = "世界实体操作：创建/移动/使用物品（V8 引擎通道）"
    actions = {
        "create": ActionSchema(
            required=["object"],
            optional={"quantity": "数量", "location": "目标地点"},
        ),
        "move": ActionSchema(required=["object", "location"]),
        "use": ActionSchema(required=["object"], optional={"action": "使用动作细分"}),
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
        if action == "move":
            return await self._move(params, ctx)
        if action == "use":
            return await self._use(params, ctx)
        return _failure(f"未知动作: {action}")

    async def _create(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        name = str(params["object"]).strip()
        location_id = resolve_location_alias(str(params.get("location", "") or "")) if params.get("location") else None
        quantity = float(params.get("quantity", 1) or 1)
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "create_object",
                        "args": [
                            ctx.user_id,
                            name,
                            infer_object_category(name),
                            location_id,
                            quantity,
                        ],
                    },
                    "failure_kind": None,
                },
            )
        obj = world_engine.create_object(
            ctx.user_id,
            name=name,
            category=infer_object_category(name),
            location_id=location_id,
            quantity=quantity,
        )
        if obj is None:
            return _failure("物品创建失败（容量上限或世界不可用）")
        return CapabilityResult(
            status="succeeded",
            payload={"object_id": obj.id, "name": obj.name, "location_id": obj.location_id, "failure_kind": None},
        )

    async def _move(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        location_id = resolve_location_alias(str(params["location"]))
        if location_id is None:
            return _failure("目标地点无法识别")
        obj = world_engine.find_object_by_name(ctx.user_id, str(params["object"]))
        if obj is None:
            return _failure("没有这个东西")
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "move_object",
                        "args": [ctx.user_id, obj.id, location_id],
                    },
                    "failure_kind": None,
                },
            )
        moved = world_engine.move_object(ctx.user_id, obj.id, location_id)
        if moved is None:
            return _failure("移动失败（地点不符或物品不可用）")
        return CapabilityResult(
            status="succeeded",
            payload={"object_id": moved.id, "location_id": moved.location_id, "failure_kind": None},
        )

    async def _use(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        items = _consume_items(params)
        if items is not None:
            return self._consume(ctx.user_id, items)
        obj = world_engine.find_object_by_name(ctx.user_id, str(params["object"]))
        if obj is None:
            return _failure("没有这个东西")
        verb = str(params.get("action", "use"))
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "apply_object_action",
                        "args": [ctx.user_id, obj.id, verb, None],
                    },
                    "failure_kind": None,
                },
            )
        used = world_engine.apply_object_action(ctx.user_id, obj.id, verb, None)
        if used is None:
            return _failure("使用动作不合法或物品不可用")
        return CapabilityResult(
            status="succeeded",
            payload={"object_id": used.id, "state": used.state, "quantity": used.quantity, "failure_kind": None},
        )

    def _consume(self, user_id: str, items: list[dict]) -> CapabilityResult:
        for item in items:
            obj = world_engine.resolve_inventory_ref(user_id, str(item["object"]))
            if obj is None or not obj.consumable:
                return _failure(f"没有可消耗的{item['object']}")
            item["object"] = obj.id
        if get_settings().action_outbox_enabled:
            return CapabilityResult(
                status="succeeded",
                payload={
                    "deferred_world_op": {
                        "op": "consume_inventory",
                        "args": [user_id, items],
                    },
                    "failure_kind": None,
                },
            )
        result = world_engine.consume_inventory(user_id, items)
        if result is None:
            return _failure("库存不足或物品不可消耗")
        return CapabilityResult(
            status="succeeded",
            payload={"items": result["items"], "failure_kind": None},
        )
