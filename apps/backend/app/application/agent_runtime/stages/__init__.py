"""六段认知循环的段实现包（RT-007 ~ RT-012）。

`loop.py` 只承载**段序列与段执行原语**；段本体（Observe / Reason / Plan / Act /
Reflect / Update）在此逐任务落位。本包**只读投影**既有域能力，不重造任何器官：

- 允许依赖：`contracts` / `session` / `state` / `context` / `events` 与各域的**只读**读面。
- 禁止依赖：任何写仓储 / 写服务、`app.chains`、`app.prompts`、`llm_gateway`、
  具体渠道实现、`memory2.retriever`（记忆信号复用 RT-004 召回结果，不二次检索）。

**导入约定**：本包只导出**值对象**，段本体按模块路径导入
（`from app.application.agent_runtime.stages.observe import observe`）——若在此再导出同名
函数，会遮蔽同名子模块 `stages.observe`，导致 `stages.observe.observe` 变成
`'function' object has no attribute 'observe'`（实测踩中）。
"""

from app.application.agent_runtime.stages.act import (
    ActOutcome,
    action_source_for,
    intent_to_action_intent,
)
from app.application.agent_runtime.stages.observe import (
    CharacterStateFact,
    MemorySignalFact,
    Observation,
    ObservationDegradation,
    UserInputFact,
    WorldFact,
    observation_dedupe_key,
)
from app.application.agent_runtime.stages.plan import (
    PlanDegradation,
    PlanStepRef,
    PlanValue,
    current_plan_value,
    plan_enabled,
    to_plan_value,
)
from app.application.agent_runtime.stages.reflect import (
    InsightRef,
    ReflectDegradation,
    ReflectOutcome,
    evidence_window_key,
    reflect_enabled,
)
from app.application.agent_runtime.stages.reason import (
    Intention,
    ReasonDegradation,
    build_stack,
    capabilities_for,
)

__all__ = [
    "ActOutcome",
    "CharacterStateFact",
    "InsightRef",
    "Intention",
    "MemorySignalFact",
    "Observation",
    "ObservationDegradation",
    "PlanDegradation",
    "PlanStepRef",
    "PlanValue",
    "ReasonDegradation",
    "ReflectDegradation",
    "ReflectOutcome",
    "UserInputFact",
    "WorldFact",
    "build_stack",
    "capabilities_for",
    "action_source_for",
    "current_plan_value",
    "evidence_window_key",
    "intent_to_action_intent",
    "observation_dedupe_key",
    "plan_enabled",
    "reflect_enabled",
    "to_plan_value",
]
