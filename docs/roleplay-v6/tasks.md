# Roleplay V6 任务注册表

> 开发入口。按依赖顺序执行；P0 = V6 必须，P1 = 推荐，P2 = 延期。
> 策略：一次只执行一个 Task，完成后运行测试、全量回归、提交推送，再进入下一个（沿用既有节奏）。

## Task 列表

### V6-001 Goal 模型（P0）

- **目标**：GoalRecord/GoalSeed/GoalType/GoalStatus/GoalSource 模型 + PERSISTENT_GOALS 角色种子资产。
- **前置**：无。
- **涉及文件**：`app/models/goal.py`（新增）、`app/character/asuna/goals.py`（新增）。
- **实现内容**：4 类类型、4 态状态、两级 horizon、priority 1~5、description ≤40 字；GOAL_TIER 表。
- **验收**：模型校验、非法值拒绝、种子与 goal-model.md 一致。
- **测试**：`tests/unit/test_goal_models.py`。

### V6-002 character_goals 表 + Repository（P0）

- **目标**：建表迁移 0008 + goal_repository（幂等播种/active 查询/创建/complete/expire/cancel）。
- **前置**：V6-001。
- **涉及文件**：`app/core/db.py`、`migrations/versions/0008_character_goals_table.py`、`app/repositories/goal_repository.py`（新增）。
- **实现内容**：表结构见 persistence.md；(user_id, status) 索引；check 约束。
- **验收**：迁移与 ORM 一致；幂等播种零重复。
- **测试**：`tests/integration/test_goal_repository.py` + 迁移一致性测试自动覆盖。

### V6-003 Goal Policy（P0）

- **目标**：生命周期纯代码策略（创建/完成/过期/取消/幂等/单轮 ≤1 创建）。
- **前置**：V6-002。
- **涉及文件**：`app/services/goal_service.py`（新增：seed_if_absent/review）。
- **实现内容**：goal-policy.md 全部规则表驱动；接 V5 信号（emotion/tension/conflict 事件/scene pending）。
- **验收**：14 项矩阵 Case 2~6；用户语言反例零创建。
- **测试**：`tests/integration/test_goal_policy.py`。

### V6-004 Goal Selection + Conflict（P0）

- **目标**：tier 排序 + 上下文修正 + 冲突裁决 + SelectedGoal（含 reason/suppressed）。
- **前置**：V6-003。
- **涉及文件**：`app/services/goal_service.py`（select）。
- **实现内容**：goal-selection.md + goal-conflict.md；永远有确定性输出。
- **验收**：矩阵 Case 7~9；凌晨裁决案例。
- **测试**：`tests/integration/test_goal_selection.py`、`test_goal_conflict.py`。

### V6-005 Intention 模型 + Policy（P0）

- **目标**：IntentionType 12 值 + IntentionDecision schema + IntentionPolicy（有效性表/goal 一致性/scene 压制/降级）。
- **前置**：V6-004。
- **涉及文件**：`app/models/intention.py`（新增）、`app/services/intention_policy.py`（新增）。
- **实现内容**：intention-model.md §2~4 全部规则表驱动。
- **验收**：矩阵 Case 11；Policy 永远输出合法 intention。
- **测试**：`tests/unit/test_intention_models.py`、`test_intention_policy.py`。

### V6-006 Intention Chain（P0）

- **目标**：LLM 候选链（build_intention_chain / decide）。
- **前置**：V6-005。
- **涉及文件**：`app/chains/intention_chain.py`（新增）、`app/prompts/intention.py`（新增）。
- **实现内容**：IntentionDecision 结构化输出（复用 build_structured_chain）；None/非法处理。
- **验收**：FakeLLM 候选透传；None → 空决策交 Policy 降级。
- **测试**：`tests/unit/test_intention_chain.py`。

### V6-007 Goal/Intention Context 注入（P0）

- **目标**：目标段 + 意图段 prompt 渲染（格式/预算/空值兼容/人格优先约束）。
- **前置**：V6-004、V6-005。
- **涉及文件**：`app/prompts/builder.py`、`app/prompts/goal.py`（新增，中文标签表）。
- **实现内容**：goal-context.md 全部规则；计入总预算。
- **验收**：V1 无 analysis 路径不变；golden 快照新增 v6_full。
- **测试**：`tests/unit/test_goal_context.py` + golden。

### V6-008 编排接入（P0）

- **目标**：chat_pipeline 接入（goals 加载、gather 4 链、policy 校验、answer 传 ctx、turn_meta 携带）；post_process 注册 run_goal_review。
- **前置**：V6-003、V6-006、V6-007。
- **涉及文件**：`app/application/chat_pipeline.py`、`app/application/post_process.py`、`app/services/context_builder.py`、`app/api/v1/chat.py`（turn_meta 透传）、`app/services/trace_collector.py`（step 名）。
- **实现内容**：architecture.md §2；失败降级三处（goals 查询/链失败/review 失败）。
- **验收**：SSE 零影响（Case 12）；turn_meta 带 intention/current_goal。
- **测试**：`tests/integration/test_goal_e2e.py`。

### V6-009 十四项必测 + 全量回归（P0）

- **目标**：testing.md 矩阵全绿。
- **前置**：V6-008。
- **涉及文件**：`tests/`（聚合用例 `test_goal_matrix.py`）。
- **验收**：全量 `uv run pytest tests/ -v` 通过；V2~V5 零回归；golden 无意变更零。
- **测试**：同左。

### V6-010 Debug/API 扩展（P1）

- **目标**：/state 快照与前端 Debug 面板展示 current_goal/intention（type/reason/degraded）。
- **前置**：V6-008。
- **涉及文件**：`app/api/v1/state.py`、`app/api/v1/schemas.py`、前端 state-panel/goal 卡片。
- **验收**：面板可见"角色这轮想做什么、为什么"。
- **测试**：API 单测 + 前端 Vitest。

### V6-011 Goal Review LLM 评估 + 记忆联动（P2，可选）

- **目标**：goal_review 引入 LLM 辅助判定完成（在代码规则之外的语义完成）；Goal 完成产生 V4 relationship_event 记忆。
- **前置**：V6-009。
- **涉及文件**：`app/services/goal_service.py`、`app/chains/goal_review_chain.py`（新增）。
- **实现内容**：LLM 输出 goal_review 决策（completed/cancelled/keep + reason），代码仍持最终权；防每轮重复评估（冷却轮次）。
- **验收**：语义完成案例（"聊得很开心，承诺达成了"）能提前完成 conversation 目标。
- **测试**：FakeLLM 注入单测。

## 依赖图

```text
V6-001 → V6-002 → V6-003 → V6-004 ↘
                                     V6-007 → V6-008 → V6-009 → V6-010(P1)
                          V6-005 → V6-006 ↗          V6-011(P2) ↗
```

## 提交节奏

沿用：逐 Task 测试 + 全量回归（V2~V5 零回归）+ commit/push，连续执行，最后统一汇报。
