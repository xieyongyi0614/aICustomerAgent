"""V2.4.0 ToolContext（architecture.md §4.1 / §7.3、TOOL-004 §2.2；**结构所有者 TOOL-004**）。

工具决策与执行的唯一上下文 = V9 `ExecutionContext` 的超集：前五个字段与其逐字对应
（能力实现体拿到的仍是同一组字段），其余为**可空的世界事实预读快照**。

归属标注（本任务只定义结构，不接任何仓储）：
- 世界事实（`world` / `inventory` / `situations` / `scene`）由 TOOL-007 装配；
- 关系阶段（`relationship`）由 TOOL-007 装配；
- 授权名单（`authorized_recipients`）由 TOOL-005 装配；
- 幂等键（`dedupe_key`）由 TOOL-010 追加，`ToolExecutor` 从 `ToolInvocation.dedupe_key`
  填入（外发类能力直填 `OutboundMessage.idempotency_key`）。

TOOL-007 装配标记：`world[WORLD_ENABLED_KEY]` 恒存在 = 世界事实已装配（见
`world_facts_assembled()` / `world_facts_enabled()`）；装配态下 `inventory=[]` 表示
**确实没有物品**（语义校验器判失败），未装配才是"信息不足 → 降级放行"。

纪律：`ToolContext` 是**只读预读快照**，对齐 V9 `planner.GateSnapshot` 的
"调用方预读、闸门内零 IO" 范式；工具实现体禁止自行读仓储（TOOL-007 静态扫描强制）。
世界事实维度保持默认空值（`{}` / `[]`）且无装配标记即为**未装配**，工具面投影据此降级为
不裁剪、语义校验器据此降级放行（TOOL-003 §2.3），不因装配未完成而误裁或误拒。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DEFAULT_CHARACTER_ID = "asuna"
DEFAULT_RUN_KIND = "foreground_chat"
DEFAULT_SOURCE = "conversation"

WORLD_LOCATIONS_KEY = "locations"
WORLD_PART_OF_DAY_KEY = "part_of_day"
WORLD_ENABLED_KEY = "world_enabled"
SCENE_TONE_BIAS_KEY = "tone_bias"
RELATIONSHIP_STAGE_KEY = "stage"

RUN_SOURCES: tuple[str, ...] = ("conversation", "autonomy", "event_driven")


@dataclass(frozen=True)
class ToolContext:
    """只读快照：调用方预读后注入，闸门与投影内零 IO。"""

    user_id: str
    character_id: str = DEFAULT_CHARACTER_ID
    record_id: str = ""
    now: datetime | None = None
    settings: Any = None
    run_kind: str = DEFAULT_RUN_KIND
    run_id: str | None = None
    source: str = DEFAULT_SOURCE
    dedupe_key: str = ""
    world: dict[str, Any] = field(default_factory=dict)
    inventory: list[str] = field(default_factory=list)
    situations: list[dict[str, Any]] = field(default_factory=list)
    scene: dict[str, Any] = field(default_factory=dict)
    relationship: dict[str, Any] = field(default_factory=dict)
    authorized_recipients: list[str] = field(default_factory=list)

    @classmethod
    def from_execution_context(cls, execution_ctx: Any) -> "ToolContext":
        """V9 `ExecutionContext` → ToolContext（世界事实留空，等 TOOL-007 装配）。"""
        return cls(
            user_id=execution_ctx.user_id,
            character_id=execution_ctx.character_id,
            record_id=execution_ctx.record_id,
            now=execution_ctx.now,
            settings=execution_ctx.settings,
            dedupe_key=str(getattr(execution_ctx, "dedupe_key", "") or ""),
        )

    def world_locations(self) -> Sequence[str] | None:
        """世界地点名集合；未装配返回 None（调用方降级放行）。"""
        return self.world.get(WORLD_LOCATIONS_KEY)

    def part_of_day(self) -> str | None:
        """日时段（V2.3.0 `PartOfDay` 词表）；未装配返回 None。"""
        value = self.world.get(WORLD_PART_OF_DAY_KEY)
        return None if value is None else str(value)

    def scene_tone_bias(self) -> str | None:
        value = self.scene.get(SCENE_TONE_BIAS_KEY)
        return None if value is None else str(value)

    def relationship_stage(self) -> str | None:
        value = self.relationship.get(RELATIONSHIP_STAGE_KEY)
        return None if value is None else str(value)

    def world_enabled(self) -> bool:
        return bool(getattr(self.settings, "world_enabled", True))

    def world_facts_assembled(self) -> bool:
        """世界事实是否已装配（TOOL-007 预读标记）：`world_enabled` 键存在即已装配。"""
        return WORLD_ENABLED_KEY in self.world

    def world_facts_enabled(self) -> bool | None:
        """装配态下的世界可用性；未装配返回 None（消费方降级，不误判）。

        与 `world_enabled()`（读 settings）的区别：本方法读的是**预读快照**，
        供投影规则与语义校验器判定"事实是否可信"，而非"配置是否开启"。
        """
        value = self.world.get(WORLD_ENABLED_KEY)
        return None if value is None else bool(value)
