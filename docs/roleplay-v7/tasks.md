# Roleplay V7 任务注册表

> 开发入口。按依赖顺序执行；P0 = V7 必须，P1 = 推荐，P2 = 延期。
> 策略沿用：逐 Task 测试 + 全量回归（V2~V6 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：Worker 默认 `autonomy_enabled=False` 注入测试环境；V2~V6 行为在开关关闭时逐字节一致。

## Task 列表

### V7-001 Autonomy 域模型（P0）

- **目标**：TriggerType/TriggerSignal/ProactiveActionType/ProactiveAction/AutonomyVerdict 模型 + PROACTIVE_INTENTION_MAP + IntentionType 注册 check_in。
- **前置**：V6-005（IntentionType 枚举）。
- **涉及文件**：`app/models/autonomy.py`（新增）、`app/models/intention.py`（注册 check_in）、`app/core/settings.py`（autonomy 配置组）。
- **实现内容**：autonomy-model.md / action-model.md 全部 Schema 与白名单。
- **验收**：模型校验、非法值拒绝、配置组完整。
- **测试**：`tests/unit/test_autonomy_models.py`。

### V7-002 proactive_actions 表 + Repository（P0）

- **目标**：迁移 0009 + proactive_repository（入队/取非终态/状态迁移/聚合查询 last_proactive+attempt）。
- **前置**：V7-001。
- **涉及文件**：`app/core/db.py`、`migrations/versions/0009_proactive_actions_table.py`、`app/repositories/proactive_repository.py`（新增）。
- **实现内容**：persistence 式表结构（V7 补篇，对齐 character_goals 风格）；(user_id, status) 索引。
- **验收**：状态机迁移合法路径全覆盖；深度 1 查询正确。
- **测试**：`tests/integration/test_proactive_repository.py`。

### V7-003 AutonomyPolicy 纯函数（P0）

- **目标**：evaluate() 八步裁决流水（生成标记/静音/冷却/上限/关系门槛/场景压制/动机/放行）+ 冷却退避计算。
- **前置**：V7-001。
- **涉及文件**：`app/services/autonomy_policy.py`（新增）。
- **实现内容**：autonomy-policy.md §1 流水 + cooldown.md 修正表；纯函数无 IO。
- **验收**：矩阵 Case 4~7 全部表驱动通过；永远输出三值之一。
- **测试**：`tests/unit/test_autonomy_policy.py`。

### V7-004 TriggerEvaluator（P0）

- **目标**：conversation_inactivity 判定 + episode/attempt 记账 + dedupe_key；scheduled_followup 接口预留。
- **前置**：V7-001。
- **涉及文件**：`app/services/trigger_evaluator.py`（新增）。
- **实现内容**：trigger-model.md §2~3；Reactive/Proactive 互斥信号接入。
- **验收**：矩阵 Case 1~3。
- **测试**：`tests/unit/test_trigger_evaluator.py`。

### V7-005 Proactive Chain（P0）

- **目标**：LLM 主动文本生成链（goal/intention 驱动，无用户消息）。
- **前置**：V6-006（结构化链模式复用）。
- **涉及文件**：`app/chains/proactive_chain.py`（新增）、`app/prompts/proactive.py`（新增）。
- **实现内容**：goal-integration.md §3 的 Prompt 结构；输出纯文本（非结构化）；空文本/模板符校验。
- **验收**：FakeLLM 生成；文本含 `{}` → 视同失败。
- **测试**：`tests/unit/test_proactive_chain.py`。

### V7-006 AutonomyEngine + Executor（P0）

- **目标**：trigger→policy→goal select→intention 映射→入队；Executor 锁内二次校验→生成→落库→delivered。
- **前置**：V7-002~005。
- **涉及文件**：`app/application/autonomy_engine.py`（新增）、`app/services/proactive_executor.py`（新增）、`app/services/conversation_service.py`（save_proactive_turn）。
- **实现内容**：architecture.md §2、action-queue.md §2、concurrency.md L1~L3。
- **验收**：矩阵 Case 8~10；全程 trace 三 step。
- **测试**：`tests/integration/test_proactive_executor.py`。

### V7-007 Worker + API（P0）

- **目标**：lifespan tick 循环（autonomy_enabled 开关）+ `GET /proactive/pending` + `POST /proactive/{id}/ack` + chat_pipeline 生成标记/冷却重置挂接。
- **前置**：V7-006。
- **涉及文件**：`app/application/autonomy_worker.py`（新增）、`app/main.py`、`app/api/v1/proactive.py`（新增 router）、`app/application/chat_pipeline.py`（active_generations + 用户发言复位钩子）。
- **实现内容**：scheduler.md、action-queue.md §3。
- **验收**：开关关闭时零启动；pending/ack 端点契约。
- **测试**：`tests/unit/test_autonomy_worker.py`、`tests/e2e/test_proactive_api.py`。

### V7-008 十五项必测 + 全量回归（P0）

- **目标**：testing.md 矩阵全绿 + Scenario 1/2/3/5 全链。
- **前置**：V7-007。
- **涉及文件**：`tests/integration/test_autonomy_matrix.py`（新增聚合）。
- **实现内容**：15 项 Case 聚合 + 时间注入工具（freezegun 式 now 参数已有模式）。
- **验收**：全量 `uv run pytest tests/ -v` 通过；V2~V6 零回归；关闭开关后行为与 V6 一致。
- **测试**：同左。

### V7-009 前端轮询与展示（P1）

- **目标**：前端 30s 轮询 pending → 主动消息气泡展示 → ack 上报。
- **前置**：V7-007。
- **涉及文件**：`apps/frontend/src/api/rest.ts`、chat 相关组件、Vitest。
- **验收**：主动消息以角色气泡自然呈现；Vitest 覆盖轮询/去重/ack。
- **测试**：Vitest。

### V7-010 scheduled_followup（P1，Memory Trigger）

- **目标**：V4 记忆事件时间到期触发（Scenario 4："今天有面试"→傍晚 check_in）。
- **前置**：V7-008。
- **涉及文件**：`app/services/trigger_evaluator.py`（followup 评估）、登记表（内存）、memory 管线挂接登记点。
- **实现内容**：trigger-model.md §4。
- **验收**：Scenario 4 全链；静音不豁免。
- **测试**：时间注入单测。

### V7-011 真实模型人工回归清单（P2，仅文档）

- **目标**：docs/roleplay-v7/regression-checklist.md——主动行为自然度/打扰度/人格一致性/关闭开关对照。
- **前置**：V7-009。
- **验收**：清单文档化。

## 依赖图

```text
V7-001 → V7-002 → V7-003 ↘
   │        ↘ V7-004   V7-005 ↘
   │                      V7-006 → V7-007 → V7-008 → V7-009(P1) → V7-011(P2)
   └（V6-005 前置）                     V7-010(P1) ↗
```

## 提交节奏

沿用：逐 Task 测试 + 全量回归 + commit/push，连续执行，最后统一汇报。
