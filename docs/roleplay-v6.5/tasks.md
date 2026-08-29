# Roleplay V6.5 任务注册表

> 开发入口。按依赖顺序执行；P0 = V6.5 必须，P1 = 推荐，P2 = 延期。
> 策略：一次只执行一个 Task，完成后运行测试、全量回归、提交推送，再进入下一个（沿用既有节奏）。
> 状态（2026-08-29）：V6.5-001~012 全部完成并推送（全量 788 passed）。
> 实现期解释与偏差见 `implementation-notes.md`；真实回归待按 `regression-checklist.md` 执行。

## Task 列表

### V6.5-001 Behavior 模型 + Policy/Habit 角色资产（P0）

- **目标**：`app/models/behavior_strategy.py`（BehaviorStrategyType 12 值、BehaviorStrategy、ActionBudget、BehaviorPolicy、StageBehaviorParams、MoodModifier、HabitRule、BehaviorDirective、ActivityPresence）+ `app/character/asuna/behavior_policy.py`（BEHAVIOR_POLICY + STRATEGY_INSTRUCTIONS）+ `app/character/asuna/habits.py`（HABIT_LIST）。
- **前置**：无。
- **涉及文件**：上述三个新增文件。
- **实现内容**：behavior-policy.md §2~3、behavior-strategy.md §2、habit-system.md §2~3 的全部数据定义；模型层键覆盖校验（mood 8 值/stage 4 档/id 唯一）。
- **验收**：非法值拒绝；资产值与文档一致；无任何 IO/行为逻辑（纯数据）。
- **测试**：`tests/unit/test_behavior_models.py`。

### V6.5-002 Behavior Engine（P0）

- **目标**：`app/services/behavior_engine.py` 纯函数 resolve：INTENTION_STRATEGY_MAP + 修饰规则白名单（6 条）+ ActionBudget 计算（7 步）+ habit 适用域匹配（≤2 条、去重）+ activity 分类。
- **前置**：V6.5-001。
- **涉及文件**：`app/services/behavior_engine.py`（新增）。
- **实现内容**：behavior-strategy.md §3、action-budget.md §4、habit-system.md §4~5、activity-state.md §3~4；每条规则带 rule_id；输出 BehaviorDirective。
- **验收**：任意输入永远输出合法 directive（含 degraded 路径）；修饰/预算规则逐条可测；无 IO 无 LLM。
- **测试**：`tests/unit/test_behavior_engine.py`、`test_action_budget.py`。

### V6.5-003 Response Style Controller（P0）

- **目标**：`app/prompts/behavior.py` 渲染【表现方式】/【活动延续】段 + PromptBuilder 接入（插入 intention 段后、计入 fixed_chars、RHYTHM 动作行替换、V2 行为段降为 fallback）+ golden 快照 v65。
- **前置**：V6.5-001。
- **涉及文件**：`app/prompts/behavior.py`（新增）、`app/prompts/builder.py`、`app/prompts/scene.py`（RHYTHM 动作行参数化）、`tests/golden/prompt_v65_full.txt`。
- **实现内容**：response-controller.md §3~5 全部渲染规则；budget 行「偏离默认才渲染」；habit 同向去重；degraded 渲染 V2 段。
- **验收**：V1 无 analysis 路径不变；V3 现有 rhythm 测试语义等价；golden 人工审 diff。
- **测试**：`tests/unit/test_behavior_context.py` + golden。

### V6.5-004 Mode Service + 迁移 0010（P0）

- **目标**：`app/services/mode_service.py`（stabilize 5 规则 + 候选记账）+ 迁移 `0010_conversation_mode.py`（conversations +mode/+mode_entered_at +CheckConstraint）+ ORM/ConversationState 同步 + ensure_conversation 默认值。
- **前置**：无（可与 V6.5-002 并行）。
- **涉及文件**：`app/services/mode_service.py`（新增）、`migrations/versions/0010_conversation_mode.py`（新增）、`app/core/db.py`、`app/models/conversation.py`、`app/services/conversation_service.py`。
- **实现内容**：conversation-mode.md §2~3、persistence.md §2；阈值进 settings（mode_switch_min_confidence/min_turns/idle_reset_seconds）。
- **验收**：存量行 server_default 生效；stabilize R1~R5 矩阵全绿；R5 故障不跳 default。
- **测试**：`tests/unit/test_mode_stabilizer.py`、`tests/integration/test_mode_persistence.py`。

### V6.5-005 编排接入（P0）

- **目标**：chat_pipeline 接入 behavior_engine（enforce 之后）+ mode stabilize（gather 后）+ save_turn 同事务写回 + turn_meta/trace 增量字段；`_effective_role_mode` 调整为候选产出。
- **前置**：V6.5-002、V6.5-003、V6.5-004。
- **涉及文件**：`app/application/chat_pipeline.py`、`app/services/context_builder.py`（mode 读取）、`app/services/conversation_service.py`（写回）、`app/services/trace_collector.py`（step 名）。
- **实现内容**：architecture.md §2 ①~⑤；失败降级三处（engine 异常→V2 fallback / mode 读失败→default / 写回随 save_turn）；现有 router 降级断言更新。
- **验收**：SSE 零退化（turn_meta 先于 token）；degraded 全链路 answer 不受阻。
- **测试**：`tests/integration/test_behavior_pipeline.py`。

### V6.5-006 一致性/活动/模式集成测试（P0）

- **目标**：`test_behavior_consistency.py`（Case 1~3）、`test_activity_continuity.py`（Case 10）、mode 会话序列集成（Case 11~12 的 integration 版）。
- **前置**：V6.5-005。
- **涉及文件**：`tests/integration/` 三个新文件。
- **实现内容**：testing.md §2 对应 Case；FakeLLM 全确定注入。
- **验收**：矩阵全绿；无对真实 LLM 的依赖。
- **测试**：同左。

### V6.5-007 e2e 十项矩阵 + 全量回归（P0）

- **目标**：`tests/e2e/test_v65_matrix.py`（Case 1~14 HTTP 级聚合）+ 全量 `uv run pytest tests/ -v` 零回归 + golden 既有快照零 diff。
- **前置**：V6.5-006。
- **涉及文件**：`tests/e2e/test_v65_matrix.py`（新增）。
- **实现内容**：testing.md §2 全矩阵 + §4 回归口径。
- **验收**：V2~V6 全绿；新增快照唯一 diff。
- **测试**：同左。

### V6.5-008 Debug/API 扩展（P1）✅ bfad2c5（后端 /state 部分；前端面板待窗口，备注见下）

- **目标**：turn_meta behavior/mode 字段透传至 /state 快照与前端 Debug 面板（strategy/budget/degraded/confirmed→effective）。
- **前置**：V6.5-007。
- **涉及文件**：`app/api/v1/state.py`、`app/api/v1/schemas.py`、前端 state/trace 面板。
- **验收**：面板可见「这轮用什么方式表现、为什么、动作上限多少」。
- **测试**：API 单测 + 前端 Vitest。
- **备注**：turn_meta 数据 V6.5-005 已携带，本任务纯展示层。

### V6.5-009 真实模型回归清单（P1）✅ 3a812ff（清单已交付 `regression-checklist.md`；真人执行待办）

- **目标**：`docs/roleplay-v6.5/regression-checklist.md` 编写并执行：单轮动作数统计、strategy 跨轮稳定观感、mode 跳变频次、活动延续自然度、V4/V5 既有清单并列跑。
- **前置**：V6.5-007。
- **涉及文件**：regression-checklist.md（新增）。
- **验收**：真实模型下单轮动作 ≤ Budget 上限的轮次占比 ≥ 90%；无 mode 每轮跳变。
- **测试**：人工回归（非 pytest）。

### V6.5-010 输出侧动作预算统计器（P2）✅ b65e084

- **目标**：post_process 增加只读统计步骤：正则计数 reply 中 `*...*` 动作段与身体接触词，违规轮次记 trace（budget_violation），不阻塞不重写。
- **前置**：V6.5-007。
- **涉及文件**：`app/application/post_process.py`、`app/services/behavior_engine.py`（统计函数）。
- **实现内容**：action-budget.md §2 的观测半边；统计口径与预算渲染口径对齐（同一正则常量）。
- **验收**：违规计数与人工标注抽查一致率 ≥ 95%；零时延回归（后台步骤）。
- **测试**：`tests/integration/test_budget_observer.py`。

### V6.5-011 动态 Habit 养成（P2）✅ 3789460

- **目标**：从 relationship_events/V4 记忆沉淀 habit 候选（角色自身行为习惯），代码规则预筛 + 配置确认后并入运行时生效集（HABIT_LIST 只读不动，生效集可扩展）。
- **前置**：V6.5-007。
- **涉及文件**：`app/services/behavior_engine.py`、`app/core/db.py`（候选存储或配置）。
- **实现内容**：habit-system.md §6；候选生成走代码规则，禁止 LLM 直写。
- **验收**：候选不自动生效；生效集变更可审计。
- **测试**：FakeLLM/规则注入单测。

### V6.5-012 V2 behavior 层退役评估（P2）✅ behavior-retirement-eval.md（结论：Keep）

- **目标**：V6.5 稳定运行后评估删除 `models/behavior.py` / turn_analysis.behavior 链段的收编终局（fallback 依赖度数据支撑决策）。
- **前置**：V6.5-009（需真实回归数据）。
- **涉及文件**：评估报告，不动代码。
- **验收**：产出 keep/kill 结论与依据。
- **测试**：—。

## 依赖图

```text
V6.5-001 → V6.5-002 ↘
           V6.5-003 → V6.5-005 → V6.5-006 → V6.5-007 → V6.5-008(P1) → V6.5-009(P1)
V6.5-004 ↗/(并行)                        V6.5-010(P2) ↗
                                         V6.5-011(P2) ↗
                                         V6.5-012(P2，依赖 009 数据) ↗
```

## 提交节奏

沿用：逐 Task 测试 + 全量回归（V2~V6 零回归）+ commit/push，连续执行，最后统一汇报。
