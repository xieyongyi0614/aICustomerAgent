# Concurrency（并发控制）

## 1. 竞争面盘点

| 写入方 | 写什么 | 频率 |
|---|---|---|
| chat_pipeline 前台 | conversation 消息、V5 状态（post_process） | 用户驱动 |
| post_process 后台 | scene/state/summary/memory/goals | 每轮对话 |
| Autonomy Worker | proactive_actions、conversation（主动消息） | 每 tick（默认 60s），实际 ACT 罕见 |

风险点：Worker 的 Executor 与 chat 管线同时写同一用户的 conversation / V5 状态。

## 2. 控制手段（三层，全部复用既有机制）

### L1：per-user asyncio.Lock（REF-010 既有）

Executor 落库前获取与 `post_process` 后台写同一把锁 → 主动消息与状态更新互斥。Worker 是唯一新增持锁方。

### L2：内存生成标记（新增，最小）

```python
# application/chat_pipeline.py
active_generations: dict[str, bool] = {}   # user_id → 流式回答进行中
astream 开始置 True，结束/异常 finally 清除
```

Worker 评估与 Executor 二次校验都检查该标记 → "用户刚发消息、正常回复还在流式输出中"时 Worker 必然 WAIT/回退。

### L3：时序不变式

主动消息永远 append 在用户最后一条消息之后（save_proactive_turn 走同一 conversation 追加语义）；不覆盖、不重排。锁 + 单写者（每 tick 每用户至多一个 Executor）保证。

## 3. 为什么不需要乐观并发/版本号

- 写冲突窗口极小（Worker ACT 罕见 + 锁互斥 + 生成标记）；
- 单进程单 Worker，无分布式竞争；
- REF-010 已裁决"应用层串行化优先于 DB 行锁"——V7 延用该结论，不新增机制。

## 4. 与 V5 状态的交互语义（重申架构边界）

主动消息**不触发 V5 状态更新、不触发 goal_review、不触发 memory 提取**——它不是对话轮，只是单向输出。用户回复后才进入正常 Reactive 轮（此时一切状态演进照旧）。这避免"角色自言自语把自己聊到情绪变化"的语义混乱，也让 Worker 与 post_process 的职责完全正交。

## 5. 死锁风险

per-user 锁的持有方（chat 后台步骤、Executor）都不在持锁期间获取第二把锁 → 无锁序问题。锁泄漏由 conftest teardown 的 `reset_user_write_locks()`（测试）与进程生命周期（生产）兜底。
