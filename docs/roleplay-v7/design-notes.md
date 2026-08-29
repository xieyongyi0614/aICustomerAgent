# V7 Architecture 设计说明（补充：关键取舍记录）

> 设计过程中的关键决策与被否方案，供实现期对照。

## 1. 主动意图为何用确定性映射而非 LLM 决策

主动行为的风险不对称：反应式回答错一次只是语气问题，主动打扰一次伤害的是关系本身。V6 的 intention_chain 输入是用户消息（信号充分），主动场景没有用户消息（信号不足）——让 LLM 在信号不足处决策是失控点。确定性映射（user_care→check_in、relationship→repair_rapport）把"是否行动"锁在 Policy、把 LLM 限定在"说什么"。

## 2. 为什么消息通道选轮询而非 WebSocket

现状：前端纯拉模式（SSE POST），无长连接基础设施。为单一主动消息引入 WS 服务端 + 前端连接管理，成本远超收益；Outbox 表 + 30s 轮询是 30 行代码级别的实现，且 outbox 状态在库（轮询错过不丢消息）。WS 列为 V8 评估项。

## 3. 为什么 Worker 不触发 V5 状态/goal_review

主动消息是角色的单向输出，不是对话轮。若它驱动状态演进，会出现"角色自言自语把自己聊累"的语义混乱，且 Worker 与 post_process 的并发面扩大一倍。用户回应后进入正常 Reactive 轮，状态演进照旧——这是并发面最小化的关键切割。

## 4. 防轰炸的四道闸（纵深防御）

```text
Trigger 幂等键（同一闲置不重复评估）
  → 冷却 + 指数退避（全局最小间隔 + episode 内倍增）
    → episode 上限（用户不回应最多 2 次主动）
      → 队列深度 1（上一条没消化完不再入队）
```

任一层独立成立即可防住 Scenario 3；参数全部入 settings（含关闭总开关）。

## 5. 调度不引入新依赖

复用 V4-011 回收循环的 lifespan asyncio tick 模式：60s 粒度对"关心类主动"绰绰有余；Celery/APScheduler 的能力（分布式、秒级精度、任务编排）全部用不上。拒绝理由已记录在 scheduler.md §4。

## 6. 与 V6 的复用清单（实现时验收）

goal_service.select 零改动、IntentionPolicy 有效性子集复用、IntentionType 仅新增 check_in 一个值、人格/语言风格资产原样用于 proactive prompt——V7 对 V6 的修改面必须为"一个枚举值 + 一个白名单常量"。

## 7. 时间语义

全部时间判定（闲置/冷却/静音/到期）走 `now` 参数注入的纯函数——测试不需要 freezegun，直接传构造时间（与 V5 情绪衰减测试同一模式）。
