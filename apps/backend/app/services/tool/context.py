"""V2.4.0 ToolContext（architecture.md §4.3 / TOOL-003；结构所有者 TOOL-004）。

工具执行上下文 = V9 `ExecutionContext` 的超集：前五个字段与其逐字对应（能力实现体
拿到的仍是同一组字段），其余为**可空的世界事实预读快照**。

归属标注（本任务只定义结构，不接任何仓储）：
- 世界事实（world_id / locations / inventory / scene）由 TOOL-007 装配；
- 授权名单（authorized_recipients）由 TOOL-005 装配；
- 关系阶段（relationship_stage）由 TOOL-004 / TOOL-007 装配。

纪律：ToolContext 是**只读预读快照**，对齐 V9 `planner.GateSnapshot` 的
"调用方预读、闸门内零 IO" 范式；世界事实字段为 None 表示**未装配**，
语义校验器据此降级放行（TOOL-003 §2.3），不因装配未完成而误拒。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    character_id: str = "asuna"
    record_id: str = ""
    now: datetime | None = None
    settings: Any = None
    world_id: str | None = None
    locations: Sequence[str] | None = None
    inventory: Sequence[str] | None = None
    authorized_recipients: Sequence[str] | None = None
    scene: dict[str, Any] | None = None
    relationship_stage: str | None = None

    @classmethod
    def from_execution_context(cls, execution_ctx: Any) -> "ToolContext":
        """V9 `ExecutionContext` → ToolContext（世界事实留空，等 TOOL-007 装配）。"""
        return cls(
            user_id=execution_ctx.user_id,
            character_id=execution_ctx.character_id,
            record_id=execution_ctx.record_id,
            now=execution_ctx.now,
            settings=execution_ctx.settings,
        )
