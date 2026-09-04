# V7 Architecture

## 1. 当前真实架构（V6 设计完成后的形态）

```text
chat_pipeline（前台）: context → gather(router‖turn_analysis‖scene_intent‖intention)
                       → policy → answer 流式 → save_turn → schedule_post_process
post_process（后台注册表）: scene_update ‖ state_update ‖ summary ‖ memory_extract ‖ goal_review
lifespan: memory reclaim 循环（asyncio tick 模式先例）
V6: goals 表 + goal_service(seed/review/select) + intention_chain/policy
REF-010: per-user asyncio.Lock 串行后台写
```

## 2. V7 总体架构

```text
┌────────────────────────── Character Runtime ──────────────────────────┐
│                                                                        │
│   Chat Request ──► chat_pipeline ──► Response ──► (重置冷却/活跃标记)   │
│                                                                        │
│   Autonomous Worker（lifespan tick 循环，默认 60s）                     │
│        │                                                               │
│        ▼                                                               │
│   TriggerEvaluator ──► 触发候选（inactivity / time-due）               │
│        │                                                               │
│        ▼                                                               │
│   AutonomyPolicy  ──► ACT / WAIT / IGNORE                              │
│        │ ACT                                                           │
│        ▼                                                               │
│   AutonomyEngine                                                       │
│        ├─ goal_service.select（复用 V6，零改动）                        │
│        ├─ intention：proactive 白名单确定性映射（MVP 不走 LLM 决策）     │
│        └─ ActionCandidate → proactive_actions 表（status=candidate）   │
│        │                                                               │
│        ▼                                                               │
│   Executor（同 tick 内，二次 policy 校验后执行）                        │
│        ├─ proactive_chain 生成文本（LLM，intention 驱动）               │
│        ├─ 取 per-user 写锁 → 写 conversation + delivered 标记          │
│        └─ 失败 → failed + retry_count/backoff（上限内重试）             │
│                                                                        │
│   前端轮询 GET /proactive/pending → 展示 → POST ack                    │
└────────────────────────────────────────────────────────────────────────┘
```

## 3. 与 Chat Request 的隔离

- Worker 是独立 lifespan 任务，与 chat_pipeline 无调用关系；两者只通过**数据**（conversation/goals/state 表）和 **per-user 写锁**（REF-010 既有锁，Executor 写入时获取）交汇。
- 生成中互斥：chat_pipeline 流式回答期间置内存 `active_generations[user]` 标记；Worker 评估时若标记存在 → WAIT（防"正常回复+主动消息"双轰炸）。
- 用户刚发言 → last_message 是用户且未超最短间隔 → Trigger 不成立（见 trigger-model.md）。

## 4. 与 V6 的关系（严格复用，不绕行）

```text
Trigger → AutonomyPolicy(ACT) → goal_service.select（V6 零改动）
        → proactive 白名单 intention 映射（V6 IntentionType 子集）
        → Action → Executor 用 proactive_chain 生成文本
```

MVP 阶段主动行为的 intention 由 Goal 类型**确定性映射**（user_care→check_in、relationship→repair_rapport），不经 LLM 决策——主动场景没有用户输入，LLM 决策的收益低于失控风险；V8 再评估引入决策链。

## 5. 失败与降级

- Worker tick 任何异常：记日志，本轮跳过，下轮继续（复用 V4 回收循环容错模式）。
- LLM 生成失败：action 置 failed，retry_count+1，≤ `autonomy_max_retries`（默认 2）次按 backoff 重试；超限 failed 终态。
- goals/state 查询失败：本轮 WAIT（宁可错过，不可乱说）。
- Worker 整体可由 `autonomy_enabled=False` 一键关闭（默认开启但 MVP 期默认保守参数）。
