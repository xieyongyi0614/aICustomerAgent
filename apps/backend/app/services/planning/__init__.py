"""V2.5.0 Planning System 计划编排层（计划=Goal → Task → Action 的编排层）。

本包自 PLAN-001 起建立，按任务逐段落地。**公开面**（Task Detail §6.3：对外只暴露公开面，
模块导入按需进行——本文件不做急切实导入，避免在包级导入时拉起仓储 / LLM / 世界链路）：

| 模块 | 公开面 | 归属 |
|---|---|---|
| `goal_contract` | Goal 域契约常量（只读消费面 / 写回面 / 禁止事项） | PLAN-001 ✅ |
| `context` | `PlanContextAssembler` / `PlanContextProbe` / `PlanUnavailable` | PLAN-003 ✅ |
| `engine` | `PlanningEngine` / `PlanOutcome` / `get_planning_engine` / 七道闸理由码 | PLAN-003 ✅ |
| `decompose` | `TaskDecomposer` / `PlanValidator` / `DecompositionResult` | PLAN-004 ✅ |

后续任务的落点（本任务不实现、不预埋）：

- PLAN-005：`app/services/planning/` 下的 `scheduler.py` / `executor_bridge.py` /
  `observer.py` / `revision.py`（+ `revision_listener.py`）。
- PLAN-006 ~ PLAN-012：工具 / 自治 / 世界 / 记忆 / 反思集成与接口冻结。

对 Goal System 的纪律（本包任何模块都必须遵守，见 `goal_contract` 模块文档）：
Goal System 说「想要什么、谁更重要」；Planning 只说「这件事分几步做」。
Planning 对 Goal 只有两个动作：读它，和请求把它转成合法终态。
"""
