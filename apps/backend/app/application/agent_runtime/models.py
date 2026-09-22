"""Run 模型值对象（AGENT-001 §2.2）。

实现已下沉 `app.core.agent_run_types`（R-6 无环契约）；本模块保持既有导入面。
"""

from app.core.agent_run_types import (  # noqa: F401
    RUN_KINDS,
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
    TERMINAL_ABORTED,
    TERMINAL_DEGRADED,
    TERMINAL_DONE,
    TRIGGER_CHANNEL_MESSAGE,
    TRIGGER_SCHEDULE,
    TRIGGER_THRESHOLD,
    TRIGGER_TYPES,
    TRIGGER_WORLD_EVENT,
    RunContext,
    RunKind,
)
