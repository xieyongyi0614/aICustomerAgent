# Roleplay V3 任务注册表

> 开发入口。按依赖顺序执行；P0 = V3 必须，P1 = 推荐，P2 = 可延期。
> 命令：`uv run pytest tests/ -v`（apps/backend 下执行）。

## Task 列表

### V3-001 Scene 数据模型（P0）

- **目标**：定义 SceneIntent / ActionStatus / PendingAction / SceneState / SceneActionDecision。
- **前置**：无。
- **涉及文件**：`app/models/scene.py`（新增）。
- **实现内容**：Pydantic 模型，SceneState 序列化排除 scene_mood，字段长度约束。
- **验收标准**：模型可导入、可 dump、非法 status 被拒。
- **测试要求**：`tests/test_scene_models.py`。

### V3-002 scene_state 持久化（P0）

- **目标**：session 级场景状态落库。
- **前置**：V3-001。
- **涉及文件**：`app/db/models/`（ORM）、`migrations/`（Alembic）、`app/repositories/scene_state_repository.py`。
- **实现内容**：scene_state 表（session_id 唯一）、upsert、get_or_default。
- **验收标准**：迁移与 ORM metadata 一致。
- **测试要求**：`tests/test_scene_repository.py`、迁移一致性测试。

### V3-003 SceneIntent Router（P0）

- **目标**：识别用户剧情控制意图。
- **前置**：V3-001。
- **涉及文件**：`app/chains/scene_intent_chain.py`、`app/prompts/scene_intent.py`、`app/core/settings.py`（阈值）。
- **实现内容**：structured output 链，复用 `build_structured_chain`；异常/低置信度降级 chat。
- **验收标准**：七类意图正确解析，降级路径生效。
- **测试要求**：`tests/test_scene_intent_chain.py`。

### V3-004 Scene Service 与确定性 Resolver（P0）

- **目标**：状态加载 + interrupt/correct/过期/supersede 确定性迁移。
- **前置**：V3-002、V3-003。
- **涉及文件**：`app/services/scene_service.py`（新增）。
- **实现内容**：load（get_or_default）、resolve(intent, state) → (new_state, prompt_directives)、过 N 轮自动过期（settings 配置）。
- **验收标准**：pending-action.md 生命周期表全部迁移路径正确。
- **测试要求**：`tests/test_scene_resolver.py`（纯代码，无 LLM）。

### V3-005 Scene Updater（P0）

- **目标**：回答后后台更新场景状态。
- **前置**：V3-004。
- **涉及文件**：`app/chains/scene_update_chain.py`、`app/services/scene_service.py`、`app/prompts/scene_update.py`。
- **实现内容**：SceneActionDecision 结构化输出 + 白名单合并 + 截断 + upsert 写回；失败保持原状。
- **验收标准**：state-update.md 全部防错要求落实。
- **测试要求**：`tests/test_scene_updater.py`。

### V3-006 Scene / Rhythm Prompt 注入（P0）

- **目标**：把场景与硬约束注入生成 Prompt。
- **前置**：V3-004。
- **涉及文件**：`app/prompts/scene.py`（新增）、`app/prompts/builder.py`、`app/chains/answer_chain.py`。
- **实现内容**：scene 段 + 本轮指令段（Resolver 生成）+ rhythm 段；无 scene_ctx 时输出与 V2 一致。
- **验收标准**：prompt-design.md 渲染/省略/兼容要求。
- **测试要求**：`tests/test_scene_prompt.py`、既有 answer_chain 测试零回归。

### V3-007 编排接入（P0）

- **目标**：V3 管道接入 agent_service 流式链路。
- **前置**：V3-005、V3-006。
- **涉及文件**：`app/services/agent_service.py`、`app/api/v1/chat.py`、`app/services/trace_collector.py`。
- **实现内容**：scene 加载/路由/Resolver 进入主流程，Updater 进后台；turn_meta 携带 scene_state + scene_intent；trace 三个新 step。
- **验收标准**：SSE 事件结构向后兼容；现有 e2e 零回归。
- **测试要求**：`tests/test_scene_e2e.py`、`tests/test_scene_debug_stream.py`。

### V3-008 七大 Case 测试与真实模型回归（P0）

- **目标**：testing.md 全部 Case 通过。
- **前置**：V3-007。
- **涉及文件**：`tests/test_scene_cases.py`。
- **实现内容**：FakeLLM 脚本化 Case 1~7 断言；整理真实模型人工回归清单（西瓜五轮重放）。
- **验收标准**：FakeLLM Case 全绿 + 真实回归通过。
- **测试要求**：同左。

### V3-009 Debug Panel 展示（P1）

- **目标**：前端展示 Intent / SceneState / PendingAction / Mood / RoleMode / StateUpdate。
- **前置**：V3-007。
- **涉及文件**：`apps/frontend/src/api/chat-stream.ts`、`src/types/backend/`、`src/components/debug/`。
- **实现内容**：turn_meta 扩展解析 + DebugPanel scene 区块；仅开发环境展示。
- **验收标准**：西瓜对话中面板实时显示正确状态。
- **测试要求**：前端 Vitest 解析测试（沿用 MSW）。

### V3-010 Action Queue 评估（P2，仅文档）

- **目标**：评估多 Action Queue 是否引入。
- **前置**：V3-008。
- **涉及文件**：`docs/version/v1.0.0/v3/pending-action.md` 附录。
- **实现内容**：基于真实使用数据评估 superseded 丢失率，给出结论。
- **验收标准**：结论文档化，默认不实现。

## 依赖图

```text
V3-001 → V3-002 → V3-004 → V3-006 ↘
              ↘ V3-003 ↗ V3-005 → V3-007 → V3-008 → V3-010
                                          ↘ V3-009
```
