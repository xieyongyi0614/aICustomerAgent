"""Run 模型值对象（AGENT-001 §2.2）：RunKind / 触发源枚举 / RunContext。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

RunKind = Literal["foreground_chat", "autonomous_tick", "event_driven"]

RUN_KIND_FOREGROUND_CHAT = "foreground_chat"
RUN_KIND_AUTONOMOUS_TICK = "autonomous_tick"
RUN_KIND_EVENT_DRIVEN = "event_driven"
RUN_KINDS: tuple[str, ...] = (
    RUN_KIND_FOREGROUND_CHAT,
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
)

TRIGGER_CHANNEL_MESSAGE = "channel_message"
TRIGGER_WORLD_EVENT = "world_event"
TRIGGER_SCHEDULE = "schedule"
TRIGGER_THRESHOLD = "threshold"
TRIGGER_TYPES: tuple[str, ...] = (
    TRIGGER_CHANNEL_MESSAGE,
    TRIGGER_WORLD_EVENT,
    TRIGGER_SCHEDULE,
    TRIGGER_THRESHOLD,
)

TERMINAL_DONE = "done"
TERMINAL_ABORTED = "aborted"
TERMINAL_DEGRADED = "degraded"


@dataclass
class RunContext:
    """单次 Run 的内存载体：台账身份 + 阶段间传递（不落业务表）。"""

    run_id: str
    user_id: str | None
    run_kind: str
    trigger_type: str
    reason: str
    started_at: datetime
    llm_calls: int = 0
    degraded: bool = False
    data: dict = field(default_factory=dict)
