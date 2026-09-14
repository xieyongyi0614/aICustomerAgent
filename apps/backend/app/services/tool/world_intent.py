"""V2.4.0 TOOL-007 世界意图接口形状（architecture.md §7.3 / TOOL-007 §2.2、§4.2、§5 Step 3）。

**⚠ 本版本只冻结形状，不实现**：`WorldIntentSubmitter.submit` 恒返回 `unavailable`
占位语义、**零写入**（不落库、不建表、不产生 `world_events`）。

接线（后续版本）时的合法落点已由 architecture §7.3 钉死：写既有 `world_events`
（`type=character_intent`，属世界域合法写入），由 V2.3.0 `DailyPlanRunner` /
`MovementResolver` 在下一维护步消费；**不得为意图新建表**（TOOL-007 §3 反模式红线）。

未接线必须在调试端点可见（`status: not_wired`），防止"看着有其实没有"（§4.2 纪律）：
`status()` 直接供 `/debug/tools` 的 `world_intent` 段投影（见 `api/v1/debug.py`）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from app.services.tool.context import ToolContext

logger = logging.getLogger(__name__)

WORLD_INTENT_TOOL_ID = "world.intent.submit"

SUBMIT_UNAVAILABLE = "unavailable"
"""`submit` 占位返回值（§4.2：本版本恒为 unavailable 占位）。"""

STATUS_NOT_WIRED = "not_wired"

WIRED = False

REASON_MAX_CHARS = 80

INTENT_TYPES: tuple[str, ...] = (
    "tidy_room",
    "move_location",
    "start_activity",
)
"""已冻结的意图类型词表（形状冻结，非行为实现）。"""

NOT_WIRED_NOTE = (
    "接口已冻结、未接线：调用恒返回 unavailable 且零写入；"
    "接线后写既有 world_events(type=character_intent)，不新建表"
)


class WorldIntent(BaseModel):
    """角色向世界侧提交的意图（TOOL-007 §2.2）；本版本不落库、不建表。"""

    user_id: str
    intent_type: str
    reason: str = Field(default="", max_length=REASON_MAX_CHARS)
    target: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    def brief(self) -> dict:
        return {
            "intent_type": self.intent_type,
            "target": self.target,
            "reason": self.reason,
        }


class WorldIntentSubmitter:
    """`world.intent.submit` 占位提交器（未接线，本版本不实现）。

    纪律：`submit` **不做任何写操作**（无仓储调用、无 outbox 投递、无世界事件）；
    返回值 `SUBMIT_UNAVAILABLE` 表示世界侧未接线，调用方按"不可用"处理。
    """

    def submit(self, intent: WorldIntent, ctx: ToolContext) -> str:
        """占位实现：恒返回 `unavailable`，零写入（未接线，本版本不实现）。"""
        logger.info(
            "world.intent.submit 未接线（TOOL-007 仅冻结形状）：user=%s type=%s",
            intent.user_id,
            intent.intent_type,
        )
        return SUBMIT_UNAVAILABLE

    def is_wired(self) -> bool:
        return WIRED

    def status(self) -> dict:
        """调试端点投影（§4.2）：未接线状态必须可见。"""
        return {
            "tool_id": WORLD_INTENT_TOOL_ID,
            "status": STATUS_NOT_WIRED,
            "wired": WIRED,
            "writes": 0,
            "intent_types": list(INTENT_TYPES),
            "note": NOT_WIRED_NOTE,
        }


def get_world_intent_submitter() -> WorldIntentSubmitter:
    """无状态单例工厂：占位提交器不持有任何资源。"""
    return WorldIntentSubmitter()
