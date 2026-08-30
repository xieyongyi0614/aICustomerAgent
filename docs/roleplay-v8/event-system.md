# M6 Event System

> 目标：世界事件——**影响未来**的事实。与 Memory 的分界一句话：Memory 记录过去，Event 影响未来。

## 1. WorldEvent 模型

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | `evt_` 前缀 uuid |
| world_id | str | 归属世界 |
| type | str | interview / exam / appointment / trip / work_session / birthday / reminder / …（开放词表 + 自由 type，资产给常用词表） |
| title | str | "用户的面试"（prompt 渲染用） |
| importance | str | low / normal / high（决定上下文权重与记忆沉淀门槛） |
| status | str | scheduled（已排期未到）/ active（进行中）/ completed / cancelled / expired |
| started_at / due_at | datetime \| None | 世界时间（TimeProvider 域内） |
| completed_at | datetime \| None | |
| payload | dict | 有界扩展（地点、对象引用、备注 ≤ 有界） |
| source | str | user_mention（用户陈述）/ manual / autonomy（V7 产生的预约，预留） |
| created_at / updated_at | datetime | |

## 2. 生命周期

```text
Create      "明天我要面试" → interpreter 确定性提取（明天+面试 → due_at=明日同时刻，importance 规则表）
             提取失败（时间模糊）→ 不建事件，仅 note（宁缺毋滥）；manual 端点兜底
Schedule    status=scheduled，进入 EventTimeline
Trigger     due 检查（每 turn + lifespan 循环）：due_at ≤ now → active（幂等，单次）
             触发即产生 TimeEvent：进入 WorldContext.salient_events → 角色当场"知道事情到了"
Complete    用户明确陈述（"面完了"）→ completed；或 active 超过宽限期（配置）→ auto-expired
             completed + importance≥normal → 记忆候选（M9）
Cancel      用户取消（"面试取消了"）→ cancelled（保留行）
```

## 3. EventTrigger（触发类型）

| 触发 | 机制 | 阶段 |
|---|---|---|
| time trigger | due_at 到期检查（turn 内惰性 + lifespan 循环兜底） | P0 |
| user mention | 解释器从消息识别完结/取消 | P0 |
| condition trigger | 对象状态满足（"西瓜吃完就提醒我买东西"） | P2 预留（依赖对象查询谓词） |
| random/noise trigger | 世界自发生事件（剧情性） | 不做（V8 不做剧情引擎） |

**EventTimeline** = world_events 按 due_at/status 的查询视图（派生，不建表）。

## 4. 事件如何影响 Character（通道表）

| 通道 | 时机 | 内容 |
|---|---|---|
| WorldContext.salient_events | 每轮装配 | due 今日 / active / 刚完结（≤3 条，各 ≤ 有界字符）——角色"知道" |
| world_facts（P1） | 自治 tick | "明天面试（high）" → V7 policy 裁决理由（如主动鼓励/不选深夜打扰） |
| 记忆候选（P1） | completed 时 | 高重要度完结事件 → M9 沉淀为长期记忆 |
| ~~直接写 Goal~~ | —— | **禁止**：V6 Goal 只由既有 goal_service 管理；事件只是上下文，goal review 看不到事件属可接受（P2 预留 note 级建议） |

## 5. 与 V7 trigger_evaluator / followup 的边界（重要）

| | V7 scheduled_followup | V8 world event |
|---|---|---|
| 域 | 主动行为调度（proactive_actions 内部状态） | 世界事实 |
| 语义 | "机器人该不该再开口" | "世界上有什么事" |
| 触发后 | policy → 可能发主动消息 | 进上下文/记忆，**不直接触发任何行为** |

- V8 不新增 V7 trigger 类型、不写 proactive_actions；"雨天提醒带伞"的完整链路是：事件/环境（事实）→ world_facts → V7 policy 决定 → 既有 proactive 链路执行（见 autonomy-integration.md）。
- source=autonomy 预留：V7 未来可把"跟进事项"登记为世界事件——本阶段只留枚举值。

## 6. 边界

- 不做事件因果链/剧情引擎（事件间无依赖图）；不做周期性重复事件（RRULE，YAGNI）。
- 时间模糊的陈述（"改天""有空的时候"）不建事件（提取需要可解析的时间表达；P1 LLM 辅助可提议但同样需可解析时间才入库）。
- 事件 title/payload 有界；单世界活跃事件数上限（配置，默认 20，超出拒新建并 note）——防膨胀。
