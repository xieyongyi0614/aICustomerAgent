# V6 Architecture

## 1. 当前真实架构（重构后，依据代码而非旧文档）

```text
POST /api/v1/chat/message
  → api/v1/chat.py（SSE 装配）
  → application/chat_pipeline.py        ★ 前台关键路径
      ├─ context_builder.build          （states/memory/summary/history）
      ├─ asyncio.gather：role_router ‖ turn_analysis ‖ scene_intent
      ├─ scene_service.resolve（纯函数）
      ├─ answer_chain.astream（流式）
      └─ schedule_post_process(...)
  → application/post_process.py         ★ 后台注册表 STEP_HANDLERS
      ├─ run_scene_update
      ├─ run_state_update（V5 情绪/关系引擎 + 账本）
      ├─ run_summary
      └─ run_memory_extract（V4 四段管线）
```

纯函数规则层：`core/constants.py`（数值表）、`services/state_engine.py`、`services/memory_policy.py`、`services/memory_conflict.py`。
LLM 全部在 `chains/*`，Provider 在 `core/llm_factory`。trace 带 request_id/token_usage。

## 2. V6 接入点（不新增 God Object，走既有缝）

```text
前台（chat_pipeline.run_chat_pipeline 内，两处改动）：
  ① context_builder.build        → 增查 active goals（goal_service.load_active）
  ② asyncio.gather 增加第 4 条链：intention_chain（与现有 3 链并行，零额外时延）
       输入：user_message + state 快照 + selected goal + memory 摘要
       输出：IntentionDecision（候选）
  ③ gather 后：intention_policy.enforce(...)（纯代码校验/降级）
  ④ answer_chain 输入增加 intention_ctx（goal + intention + reason 段）

后台（post_process 注册表追加一项）：
  └─ run_goal_review：goal_service.review(ctx)
       按 goal-policy.md 规则做 创建/完成/过期/无操作（纯代码，可选 LLM 评估为 P1 任务）
```

```text
                              ┌────────────┐
 User Message ───────────────►│ chat       │
 State(scene/emotion/rel/mem) │ pipeline   │
 Active Goals ◄── goals 表 ───│  ①②③④     │
                              └─────┬──────┘
                     IntentionDecision → IntentionPolicy → Intention
                                        │
                                        ▼
                                answer_chain（Prompt 含 Goal/Intention 段）
                                        │
                                        ▼
                              post_process.run_goal_review
                              （Goal 生命周期变更 → goals 表）
```

## 3. 与既有 State 的边界

| 系统 | 回答的问题 | 与 Goal 关系 |
|---|---|---|
| V3 Scene | 现在在做什么 | Pending Action 优先级高于一切表达类 Goal（goal-selection.md §3） |
| V4 Memory | 过去发生了什么 | Goal 评估的只读输入；Goal 不回写 Memory |
| V5 Emotion | 现在感觉怎样 | Goal 选择的修正信号（强情绪时表达类 Goal 让位） |
| V5 Relationship | 和用户什么关系 | Goal 选择的修正信号 + repair 类 Goal 的触发源 |
| V6 Goal | 想要什么 | 动机层；只被 scene/action 硬约束压制 |

禁止：Goal 写入 SceneState / PendingAction；Memory 记录 Goal 内部状态（Memory 只在 Goal 完成时产生 narrative 事件记忆，走 V4 管线，属 P2 可选）。

## 4. 关键时序（SSE 零退化论证）

现有 gather 已是 3 链并行、answer 等全部结果。V6 把 intention_chain 加入同一 gather（4 链并行），wall time 不变；goal 加载为 1 次索引查询（goals 表按 (user_id, status) 索引）。后台 goal_review 是注册表新步骤，独立容错。

## 5. 失败降级

- intention_chain 失败/非法 → IntentionPolicy 降级 `intention="continue_topic"`，trace 标 degraded，answer 不受阻。
- goals 表查询失败 → 空目标集，intention 仍可由 turn_analysis 的 V2 behavior 兜底（行为退化到 V5 语义）。
- goal_review 失败 → 目标保持原状，下一轮重评。
