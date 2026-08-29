# Failure Handling（失败处理）

## 1. 失败面与处置

| 失败 | 处置 | 重试策略 |
|---|---|---|
| Trigger 评估异常（DB 查询失败等） | 本 tick 该用户跳过，日志 + 继续 | 隐式：下一 tick 天然重评 |
| Policy 内部异常 | 视同 WAIT（"宁可不动"），日志 | 同上 |
| LLM 文本生成失败 | action → failed，attempt+1，`next_retry_at = now + backoff` | ≤ `autonomy_max_retries`（默认 2）次 |
| 重试耗尽 | failed 终态，logger.error + trace；**无 DLQ**——MVP 规模下表即审计 | 不再自动重试 |
| 落库失败 | 事务回滚，action 停留 approved，下 tick 重试（幂等：同 id upsert 语义） | 每 tick 一次，无额外计数 |
| Worker tick 整体异常 | 捕获、日志、下轮继续（复用 V4 回收循环模式） | 循环不死 |
| lifespan 启动失败 | `autonomy_enabled=False` 一键关停路径 | — |

## 2. 重试语义细节

- backoff 间隔 = `autonomy_tick_seconds × backoff_multiplier^attempt`（默认 60s × 2^n，分钟级任务无长退避需求）；
- 重试的 action 在每次尝试前**重过一遍 Policy 二次校验**（quiet hours / 生成标记可能已变化）——退避期间跨入静音时段则 discarded；
- 重试不重新走 Goal/Intention 选择（动机已记录在 action 行）——动机消失的情形（目标被 review 完成）在二次校验时发现 → discarded；
- 无限重试在结构上不可能：attempt 字段单调递增，终态单向。

## 3. "宁可错过，不可乱说"原则

所有失败路径的默认方向是**放弃行动**而非带病执行：

- 状态快照读取不全 → WAIT；
- 生成文本为空/超长 → 视同生成失败走重试；
- 文本含明显残留模板符（`{}`）→ 视同失败（复用 REF-001 教训，生成后校验）。

## 4. 可观测

每个失败面都有对应可查证据：
- trace（request_id 独立会话）：autonomy_policy / proactive_generate / proactive_deliver 三 step 的 status/error；
- proactive_actions 行：status/attempt/next_retry_at；
- 日志：全部 `logger.exception`，内容经 REF-002 脱敏（生成的主动消息文本同样走 content_preview）。

## 5. 明确不做

- 不做 DLQ 表/死信告警管道（failed 行即审计，规模不需要）；
- 不做跨进程幂等（单 Worker）；
- 不做半途取消 LLM 生成（超时交给 ChatOpenAI 客户端超时配置）。
