"""V9 memory 能力：显式记忆委托（capability-system.md §4）。

唯一记忆写入口；只走既有 policy（R1~R8）+ memory_repository 通道，source=user_stated。
类型一律经 `normalize_type` 归一：参数由 LLM 给出，遗留类型名与表外取值都不得落库
（表外取值 fail-closed 返回 permanent 失败，不放行到仓储的 ValueError）。
"""

from app.models.action import ActionSchema, CapabilityResult
from app.models.memory import MemoryCandidate
from app.repositories import memory_repository
from app.services.action.registry import ExecutionContext
from app.services.memory.types import DEFAULT_MEMORY_TYPE, normalize_type
from app.engines import memory_policy


class MemoryCapability:
    name = "memory"
    description = "显式记忆委托：经 R1~R8 政策校验后落库（source=user_stated）"
    actions = {
        "save": ActionSchema(
            required=["fact"],
            optional={"memory_type": "user_fact/preference/event", "importance": "0~1"},
        ),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        return schema.validate(params) if schema else [f"未知动作: {action}"]

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        if action != "save":
            return CapabilityResult(status="failed", error=f"未知动作: {action}", payload={"failure_kind": "permanent"})
        fact = str(params.get("fact", "")).strip()
        memory_type = normalize_type(
            str(params.get("memory_type", DEFAULT_MEMORY_TYPE))
        )
        if memory_type is None:
            return CapabilityResult(
                status="failed",
                error=f"未知记忆类型: {params.get('memory_type')}",
                payload={"failure_kind": "permanent"},
            )
        importance = float(params.get("importance", 0.8))
        candidate = MemoryCandidate(
            action="save",
            type=memory_type,
            content=fact,
            importance=importance,
            confidence=0.9,
            source="user_stated",
        )
        report = memory_policy.apply_policy([candidate])
        saved = report.saved
        if not saved:
            return CapabilityResult(
                status="failed",
                error="记忆候选未通过既有政策校验",
                payload={"failure_kind": "permanent", "policy": [o.rule for o in report.discarded]},
            )
        memory = memory_repository.create_memory(
            ctx.user_id,
            ctx.character_id,
            content=fact,
            memory_type=memory_type,
            importance=importance,
            confidence=0.9,
            source="user_stated",
        )
        return CapabilityResult(
            status="succeeded",
            payload={"memory_id": memory.id, "failure_kind": None},
        )
