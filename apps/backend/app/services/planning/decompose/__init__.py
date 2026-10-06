"""V2.5.0 PLAN-004 Goal → Task 拆解与工具绑定（Task Detail §4 / §6 / §8；architecture.md §3.5、§7.7、§8.6）。

本包回答两件事：**「一步该用什么工具」**（`TaskDecomposer` 工具绑定）与
**「这算不算一步」**（`PlanValidator` 三闸）。它不执行这一步，也不决定这一步该不该做
（Task Detail §3.3 职责边界）。**零 LLM、零写库、零迁移**：只产出内存态
`DecompositionResult`，落库由 PLAN-003 经 `goal_repository` 计划面函数完成（单一写面）。

包内分工：

| 文件 | 内容 |
|---|---|
| `constants.py` | 理由码 / 预算键 / `PlanStepSpec` 别名 / 轻量助手 |
| `validator.py` | `PlanValidator` 三闸 + 形状 / 绑定 / 预算判定与 `_task_granularity` |
| `decomposer.py` | `TaskDecomposer` 四阶段 + `DecompositionResult` + 绑定 / 派生 / 判据助手 |

四阶段（Task Detail §4.1.3）

| 阶段 | 函数 | 产出 |
|---|---|---|
| ① 结构解析 | `_parse_structure` | `SubGoalSpec[]`（复用 `models/goal.py::validate_sub_goals`） |
| ② 工具绑定 | `_bind_tools` | 绑定列表 + 派生字段写回步骤 + 弱校验 |
| ③ 判据补全 | `_complete_criteria` | `observation_keys` 白名单收敛 + `tool` 源合法性 |
| ④ 预算校验 | `_check_budget` | 步数 / 深度 / 每步尝试上限 / 计划 TTL 四项理由 |

三闸（`PlanValidator`，architecture.md §8.6）：`validate_shape` / `validate_binding` /
`validate_budget` 全部为纯函数——零 IO、零 LLM、零 `get_settings()` 直调（参数注入），
返回**可读理由列表**，**空列表 = 通过**。理由码对齐 PLAN-003 §4.2.4 七道闸：能由七道闸
覆盖的项一律复用其理由码，其余为本任务新增且逐条声明（`constants.py` 的 `REASON_*`）。

契约纪律

- **不新增工具选择逻辑**（architecture.md §7.7 关键裁决）：tiebreak 只调既有
  `ToolSelector.select_with_reason`，与执行期同函数同规则。
- **不新增映射表**：能力 → 动作 → 工具的反查复用 `ACTION_TOOL_MAP`（角色资产）。
- **确定性**：同输入同输出，含 `tool_id` / `binding_reason` / `observation_keys`（§10.1）。
- **本包零写库**：不导入任何仓储（G-WORLD）、不导入 `ToolExecutor` / `Capability.execute`（G-EXEC）。

契约演进留痕（PLAN-004）

`tests/v25/test_plan001_static_scan.py::ALLOWED_CHARACTER_IMPORT_MODULES` 由 PLAN-003 的
1 项扩为 2 项：新增 `app.character.asuna.action`（`ACTION_TOOL_MAP` / `ACTION_CAPABILITY_MAP`
的**唯一声明处**，Task Detail §4.1.1 明确要求复用）。仍按模块逐条枚举，不得扩成前缀。
"""

from __future__ import annotations

from app.character.asuna.action import ACTION_TOOL_MAP
from app.services.tool.surface import ToolSelector

from .constants import (
    BINDING_REASONS,
    BINDING_REASON_CAPABILITY_MAP,
    BINDING_REASON_FALLBACK,
    BINDING_REASON_TOOL_SELECTOR,
    BUDGET_GOAL_WINDOW_HOURS,
    BUDGET_KEYS,
    BUDGET_MAX_DEPTH,
    BUDGET_MAX_STEPS,
    BUDGET_STEP_MAX_ATTEMPTS,
    BUDGET_TTL_HOURS,
    EXTENDED_REASONS,
    GATE_REASONS,
    PLAN_LEVELS,
    REASON_BINDING_MISSING,
    REASON_COUNT_EXCEEDED,
    REASON_CRITERIA_UNSUPPORTED,
    REASON_DEPTH_EXCEEDED,
    REASON_INVALID_BINDING,
    REASON_INVALID_EFFECTS,
    REASON_INVALID_PARAMS,
    REASON_INVALID_SHAPE,
    REASON_PLAN_VERSIONS_INVALID,
    REASON_STEP_ATTEMPTS_EXCEEDED,
    REASON_TOOL_OFF_SURFACE,
    REASON_TOOL_UNRESOLVABLE,
    REASON_TTL_EXCEEDED,
    STEP_KIND_COMPOSITE,
    STEP_KIND_OBSERVE,
    STEP_KIND_TOOL,
    TASK_GRANULARITY_CHECKS,
    PlanStepSpec,
    _ON_FAILURE_BLOCKING,
)
from .decomposer import (
    DecompositionResult,
    TaskDecomposer,
    _bind_tools,
    _binding_enabled,
    _complete_criteria,
    _parse_structure,
    _plan_budget_limits,
)
from .validator import PlanValidator, _task_granularity

__all__ = [
    "BINDING_REASONS",
    "BINDING_REASON_CAPABILITY_MAP",
    "BINDING_REASON_FALLBACK",
    "BINDING_REASON_TOOL_SELECTOR",
    "BUDGET_GOAL_WINDOW_HOURS",
    "BUDGET_KEYS",
    "BUDGET_MAX_DEPTH",
    "BUDGET_MAX_STEPS",
    "BUDGET_STEP_MAX_ATTEMPTS",
    "BUDGET_TTL_HOURS",
    "EXTENDED_REASONS",
    "GATE_REASONS",
    "PLAN_LEVELS",
    "DecompositionResult",
    "PlanStepSpec",
    "PlanValidator",
    "STEP_KIND_COMPOSITE",
    "STEP_KIND_OBSERVE",
    "STEP_KIND_TOOL",
    "TASK_GRANULARITY_CHECKS",
    "TaskDecomposer",
]
