# Roleplay V7：Autonomous Behavior

> 状态：**设计完成，待实现**。任务入口 `tasks.md`。前置：V1~V6 全部完成。
> 设计原则：**受约束的自主**——Trigger × Motivation × Permission × Cooldown × Action Validity 五条件同时满足才允许主动行动。

## 1. V7 解决什么问题

V6 让角色"知道自己为什么这么回应"，但一切仍由用户消息驱动：

```text
V6：User Message → Goal → Intention → Response     （反应式）
V7：Environment/Time/State → Trigger → Autonomy Policy
    → Goal → Intention → Action                    （受约束的主动式）
```

MVP 验证的唯一命题：**角色能否合理地主动说一句话**（只有 `send_message` 一种 Action）。

## 2. 硬边界（V7 明确不做）

- 不做无限 Agent Loop / 无限 LLM 调用 / 无限发消息（五条件门 + Cooldown + Max Attempts + Backoff 三重防护）。
- 不做 Tool / Browser / Calendar / External API / IoT / 多 Agent / World Simulation（V8+）。
- 不绕过 V6：Trigger 永远经 Autonomy Policy → Goal → Intention → Action，禁止"Trigger → LLM → Message"直通。
- Emotion/Relationship 只影响阈值与表达，**不单独构成行动条件**。

## 3. 设计一览

| 概念 | 职责 | 形态 |
|---|---|---|
| Trigger | 感知"值得评估的时刻"（MVP：不活跃 + 时间到期） | 纯函数评估器 |
| AutonomyPolicy | ACT / WAIT / IGNORE 三值裁决（门槛/冷却/静音时段/重复防护） | 纯函数 |
| AutonomyEngine | Trigger → Policy → Goal → Intention → Action 组装 | application 编排（依赖注入，不做 CRUD/LLM/Prompt/SSE） |
| Action Queue | `proactive_actions` 表（outbox），单用户深度 1 | 表 + repository |
| Executor | 生成文本 → 写会话 → 待投递标记 → 前端拉取 | 复用 per-user 写锁 |
| Scheduler | lifespan 内 asyncio tick 循环（复用 V4 回收循环模式），不引入 Celery | 60s 可配置 |

文档导航：architecture / autonomy-model / trigger-model / autonomy-policy / goal-integration / intention-integration / action-model / action-queue / scheduler / cooldown / quiet-hours / concurrency / failure-handling / testing / tasks。

## 4. 消息到达通道（关键架构事实）

当前前端是"客户端发起 SSE POST"拉模式，没有 WebSocket。主动消息的投递采用**Outbox + 轮询**：

```text
Executor 写入 conversation（is_proactive 标记）+ proactive_actions.status=delivered
前端打开时每 30s GET /api/v1/proactive/pending → 拉取 → POST ack
```

不做 WebSocket（V8 再评估）；轮询间隔/开关可配置。
