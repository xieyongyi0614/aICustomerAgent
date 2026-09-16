"""V2.5.0 Planning System 计划编排层（计划=Goal → Task → Action 的编排层）。

本包自 PLAN-001 起建立，按任务逐段落地。**公开面**（Task Detail §6.3：对外只暴露公开面，
模块导入按需进行——本文件不做急切实导入，避免在包级导入时拉起仓储 / LLM / 世界链路）：

| 模块 | 公开面 | 归属 |
|---|---|---|
| `goal_contract` | Goal 域契约常量（只读消费面 / 写回面 / 禁止事项） | PLAN-001 ✅ |
| `context` | `PlanContextAssembler` / `PlanContextProbe` / `PlanUnavailable` | PLAN-003 ✅ |
| `engine` | `PlanningEngine` / `PlanOutcome` / `get_planning_engine` / 七道闸理由码 | PLAN-003 ✅ |
| `decompose` | `TaskDecomposer` / `PlanValidator` / `DecompositionResult` | PLAN-004 ✅ |
| `scheduler` | `PlanScheduler` / `FailurePropagation` / 阻塞与矩阵常量 | PLAN-005 ✅ |
| `executor_bridge` | `PlanExecutorBridge` / `PlanBridgeDefect` / 归一映射表 | PLAN-005 ✅ |
| `observer` | `PlanObserver` / `PlanSettlement` / `ObservationContext` / 四源常量 | PLAN-005 ✅ |
| `revision` | `PlanRevisionPolicy` / 四个重规划理由码 | PLAN-005 ✅ |
| `memory_policy` | `PlanMemoryPolicy` / `PlanMemoryDecision` / 记忆通道 | PLAN-009 ✅ |

`memory_policy` 的完整公开面：判据 A `should_persist_plan`、判据 B `PlanMemoryPolicy` /
`PlanMemoryDecision`、候选构造 `build_candidate`、投递 `deliver_plan_memory`（终态记忆的
R1~R8 零豁免通道）；终态映射 `TERMINAL_MEMORY_EVENTS` 落在既有 `observer.py`。

后续任务的落点（本任务不实现、不预埋）：

- PLAN-006 ~ PLAN-012：工具 / 自治 / 世界 / 记忆 / 反思集成与接口冻结；
  `revision_listener.py` 属 PLAN-010（本任务只定义 `insight_driven` 理由码与判定入口）。
对 Goal System 的纪律（本包任何模块都必须遵守，见 `goal_contract` 模块文档）：
Goal System 说「想要什么、谁更重要」；Planning 只说「这件事分几步做」。
Planning 对 Goal 只有两个动作：读它，和请求把它转成合法终态。
"""
