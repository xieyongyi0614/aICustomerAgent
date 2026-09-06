"""Life Loop 周期上下文载体（LIFE-005）。

contextvar 跨层传递周期内产物：Controller 在 memory_retrieval 步骤写入
digest，proactive_executor（编排层）在生成 proactive 时读取并追加到
recent_context；默认 None 回退空串，前台路径零漂移。独立模块避免
proactive_executor ↔ life_loop 循环导入。
"""

import contextvars

memory_digest_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "life_loop_memory_digest", default=None
)
