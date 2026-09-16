"""V2.5.0 Planning System 计划编排层（计划=Goal → Task → Action 的编排层）。

本包自 PLAN-001 起建立。PLAN-001 阶段**只承载 Goal 域契约声明**
（`app.services.planning.goal_contract`）：零业务逻辑、零函数、零 IO、零落库。

后续任务的落点（本任务不实现、不预埋）：

- PLAN-002：计划域运行期值对象（`app/models/plan.py`）与 `v25_*` Flag（`app/core/settings/plan.py`）。
- PLAN-003：`app/services/planning/context.py`（六源装配）与 `engine.py`（规划引擎）。
- PLAN-004：`app/services/planning/decompose.py`（Goal → Task → Action 拆解与三闸）。
- PLAN-005：`app/services/planning/` 下的 `scheduler.py` / `executor_bridge.py` /
  `observer.py` / `revision.py`。
- PLAN-006 ~ PLAN-011：工具 / 自治 / 世界 / 记忆 / 反思集成与接口冻结。

对 Goal System 的纪律（本包任何模块都必须遵守，见 `goal_contract` 模块文档）：
Goal System 说「想要什么、谁更重要」；Planning 只说「这件事分几步做」。
Planning 对 Goal 只有两个动作：读它，和请求把它转成合法终态。
"""
