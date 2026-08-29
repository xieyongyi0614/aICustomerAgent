# Action Queue & Executor

## 1. Queue 的形态：Outbox 表（不引入 MQ）

单用户单会话、单进程 Worker、每用户深度 1 —— Redis Queue / Celery 属过度设计。`proactive_actions` 表即队列：

```text
入队：AutonomyEngine ACT → INSERT (status=candidate)
出队：Worker 同一 tick 内取出本用户非终态 action → Executor 处理
顺序：单深度队列天然无乱序；到期时间序由 tick 顺序保证
```

未来若多 Action 类型/多消费者出现，表结构（type/priority/next_retry_at）已预留升级位，再评估引入真队列（action-queue 不绑定具体 MQ，Executor 面向 repository 接口）。

## 2. Executor 职责（`app/services/proactive_executor.py`）

```text
输入：approved 状态的 ProactiveAction
1. per-user 写锁（REF-010 既有锁）——与 chat_pipeline 后台写互斥
2. 二次校验（锁内重查，防 TOCTOU）：
   - 生成中标记不存在
   - quiet hours 仍未进入
   - 最后一条消息作者不是"用户刚发言"
   任一失败 → action 回退 candidate（下 tick 再评）或 discarded
3. proactive_chain 生成文本（LLM，失败走 failure-handling.md）
4. 落库：conversation_service.save_proactive_turn(session_id, text)
   （消息行带 is_proactive 标记；不更新 V5 状态——主动消息不是对话轮，状态演进留给用户回应后的正常轮）
5. action 置 delivered + message_id 回填
6. trace 独立会话：proactive_deliver step
```

## 3. 前端投递（Outbox + 轮询）

```text
GET  /api/v1/proactive/pending?user_id=…
     → delivered 且未 acked 的 action 列表（含 text/created_at/intention）
POST /api/v1/proactive/{id}/ack
     → acked_at 置位
```

- 前端轮询建议 30s（`autonomy_poll_seconds` 文档约定值），仅在页面可见时轮询；
- ack 语义是"已展示"，不要求用户回复；用户回复走正常 chat 流程并重置冷却/episode。

## 4. 与 chat_pipeline 的写入互斥（重申）

Executor 落库与 `save_turn` 都拿同一把 per-user 锁；锁内二次校验保证：用户刚发的消息不会被主动消息"插队覆盖"（主动消息永远排在用户最后一条之后，时序一致）。

## 5. 明确不做

- 不做投递重试队列/推送通道（无 WebSocket/Push，轮询丢失即等下一轮询，无丢失风险因为 outbox 状态在库）；
- 不做多 worker 竞争（单 lifespan worker；`FOR UPDATE SKIP LOCKED` 留给 V8 多实例）。
