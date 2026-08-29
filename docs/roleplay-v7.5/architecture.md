# Architecture

> V7.5 总体架构：Character Runtime 保持 V7 形态完全不动，评估引擎作为**只读旁路**挂在出链。本文定义挂载点、数据流、隔离边界与降级路径。

## 1. 当前真实架构（V7 完成后的形态）

```text
User Message
  → chat_pipeline.run_chat_pipeline
      context_builder → 四链并行(router/turn_analysis/scene_intent/intention)
      → mode_stabilize → scene_resolver → intention_policy → behavior_engine
      → yield turn_meta → answer_chain.astream（流式）
      → save_turn → reset_proactive_on_user_message
      → schedule_post_process（异步后台，六步串行）
          scene_update → state_update → goal_review → summary
          → memory_extract → budget_observer
      → yield done

V7 主动链路（独立于对话轮）：
autonomy tick → TriggerEvaluator → AutonomyPolicy → 入队
  → proactive_executor：candidate → approved → proactive_chain.generate
  → save_proactive_turn(is_proactive=True) → delivered
```

两个现成的质量观测点，V7.5 直接继承为评估信号源：

- `budget_observer`——`observe_budget(reply, budget)` 已经在用正则统计 `*动作*` 数量与接触词等级，只读进 trace；
- trace step 的 `degraded / error / violation` 状态——管线自健康度已是质量信号。

**当前缺口**：TraceCollector 纯内存 LRU（20 条）无持久化；除 budget_observer 外没有任何质量判定；主动行为发送后无任何回看。

## 2. V7.5 总体架构

```text
┌─────────────────────────────────────────────────────────────────┐
│              Character Runtime（V1~V7 现状，一行不改）           │
│                                                                 │
│  User Message ──▶ ... ──▶ Response ──▶ 落库 ──▶ post_process    │
└──────────────────────────────────────┬──────────────────────────┘
                                       │ 出链末端（新增第 7 步）
                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Evaluation Engine（只读旁路）                  │
│                                                                 │
│  ① ContextCollector：PostProcessContext + 仓储切片              │
│        → EvaluationContext + 有界 context digest                │
│  ② Rule Engine（纯函数，每轮必跑）        ← 锁内第 7 步         │
│        → 各维 rule issues + rule scores                         │
│  ③ LLM Judge（按 sample_rate 采样；单次合并调用，可整体降级）     │
│        → persona / emotion / memory 语义判定   ← 锁外任务       │
│  ④ Merge：维度分 = min(rule, judge)；issues 去重合并             │
│        → EvaluationReport → evaluation_reports 表               │
│   未采样/禁用 judge：③④ 在第 7 步内直接完成；                   │
│   采样命中：③④ 派发为锁外 fire-and-forget 任务                  │
│                                                                 │
│  五维 Check：Persona │ Emotion │ Memory │ Behavior │ Autonomy    │
│    （behavior 几乎纯规则；autonomy 仅主动主体触发）              │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼  只读消费
  GET /api/v1/debug/turns/{turn_id}/evaluation        （实时调试）
  GET /api/v1/debug/proactive/{action_id}/evaluation  （主动审计）
  offline_evaluator.evaluate_window(...)              （离线批量）

挂载点 A：chat_pipeline.post_process 第 7 步 run_evaluation（对话轮主体：
          规则阶段在 per-user 写锁内；judge 采样命中时派发锁外任务合并落库）
挂载点 B：proactive_executor delivered 后 fire-and-forget 任务（主体=主动行为）
入口   C：offline evaluator 从 DB 重建上下文批量评估（历史回归）
```

三个入口汇聚到**同一个 EvaluationEngine.evaluate(EvaluationCase)**：实时与离线的差别只在 EvaluationCase 由谁构造，判定与合并逻辑完全复用。

## 3. 与 Chat Request 的隔离

- **时机**：`run_evaluation` 是 STEP_HANDLERS 的最后一员，此时 `done` 事件早已 yield，回答已落库——评估耗时与用户感知延迟无关。
- **无写回**：评估链路对 conversations / messages / character_state / memories / character_goals / scene_state **零写入**，唯一写目标是 `evaluation_reports` 自身。
- **无阻断**：`run_evaluation` 内部全量容错（与 post_process 其余步骤同级），任何异常只 trace + log。
- **开关即拔**：`evaluation_enabled=False` 时第 7 步直接跳过，系统回到 V7 行为，无需其他改动。
- **采样不影响规则**：规则层零成本每轮必跑；只有 LLM judge 走采样（按 request_id 确定性哈希，保证同轮重复评估结果一致、测试可复现）。
- **写锁两阶段**：`run_post_process` 全程持 per-user 写锁，第 7 步在锁内只做规则判定（纯函数，毫秒级）；judge 是 LLM 调用，采样命中时派发为锁外任务——**评估绝不延长写锁持有时间**。

## 4. 与 V1~V7 的关系（严格复用，不绕行）

| 复用点 | 来源 | V7.5 用法 |
|---|---|---|
| `observe_budget` 与 ActionBudget | V6.5 budget_observer / behavior_engine | Behavior 维规则直接消费其观测结果，不重写正则 |
| `emotion_history`（mood_before/after、event、magnitude） | V5 | Emotion 维规则的跳变判定事实源 |
| 注入记忆列表（ConversationState.memories） | V4 | Memory 维判"有无支撑"的对照集 |
| proactive_actions 七态 + reason/intention/trigger_type | V7 | Autonomy 维审计的事实源 |
| IDENTITY/PERSONALITY/BEHAVIOR 等角色资产 | V2 起累积 | Persona 维的评审基准，不复制、不改写 |
| `build_structured_chain`（structured output + 一层降级） | 后端约定 | Judge 链沿用同一套结构化输出范式 |
| trace 机制（TRACE_STEP_NAMES / mark_status） | 后端既有 | 新增 `evaluation` step，评估健康度可见 |
| per-user 写锁 | post_process | 规则阶段随第 7 步在锁内（纯函数）；judge 与落库派发锁外，不延长锁持有 |

不新增第二套人格描述、不重复实现情绪引擎的钳制逻辑（引擎已保证的单轮 Δ上限，评估只审计**结果**是否合理，不重复算过程）。

## 5. 失败与降级

```text
ContextCollector 失败        → 本轮不出报告，trace.evaluation = error
单条规则异常                 → 跳过该规则，其余规则照常（注册表内隔离）
judge 调用/解析失败          → 一层降级后仍失败 → 报告只含规则结果，
                               维度缺席不填 0，trace.evaluation = degraded
锁外 judge 任务异常          → 同上降级，仅 log，不重投
报告落库失败                 → 仅 log，绝不向上抛
evaluation_enabled=False     → 第 7 步记 skipped step 后跳过，等价 V7
```

**总原则**：评估永远失败得"安静"——它最有价值的时刻是发现角色质量缺陷，但它自己是唯一不允许制造新故障的模块。
