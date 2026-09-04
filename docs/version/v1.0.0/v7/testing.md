# V7 Testing

## 1. 约定

沿用既有约定；Worker 不随 TestClient 启动（`autonomy_enabled=False` 默认注入），单测直接调用 `autonomy_engine.tick()` / `autonomy_policy.evaluate()` 并以 `now` 参数注入时间（对齐 V5 情绪衰减测试的时间注入模式）。

## 2. 测试矩阵（15 项必测）

### Trigger（1~3）

| # | Case | 断言 |
|---|---|---|
| 1 | 闲置触发 | 最后消息 ≥ 阈值 → inactivity 信号成立；< 阈值 → 无信号 |
| 2 | 用户刚回复 | 最后一条是用户且 < 2 分钟 → 无信号（Reactive 优先） |
| 3 | 空会话 | 无消息记录 → 无信号 |

### Policy（4~7）

| # | Case | 断言 |
|---|---|---|
| 4 | 五条件全过 → ACT | verdict=act + goal_id + 白名单 intention + reason |
| 5 | 冷却/退避 | 间隔未到 → WAIT；backoff 倍增后仍未到 → WAIT；episode 计数=2 → IGNORE |
| 6 | Quiet Hours | 23:30 → IGNORE；08:00 → 放行；start==end 无静音 |
| 7 | 动机缺口 | 仅 conversation 目标 → IGNORE；状态修正（亲密 ×0.5 / 角色 tired IGNORE / scene 睡觉 IGNORE） |

### Action（8~11）

| # | Case | 断言 |
|---|---|---|
| 8 | 入队与深度 | ACT → candidate 行落库；已有非终态 action → WAIT（深度 1） |
| 9 | 生成与投递 | proactive_chain 文本回填 → save_proactive_turn → delivered + message_id + is_proactive 标记 |
| 10 | 二次校验回退 | 锁内发现生成中标记/进入静音 → candidate 回退，不落消息 |
| 11 | 轮询与 ack | pending 只含 delivered 未 acked；ack 后转 acked；用户发言自动 ack + candidate discarded |

### Failure & Concurrency（12~13）

| # | Case | 断言 |
|---|---|---|
| 12 | LLM 失败重试 | 生成失败 → failed + attempt=1 + next_retry_at；第 3 次失败 → 终态；重试跨静音 → discarded |
| 13 | 并发互斥 | Executor 与 save_turn 并发：消息顺序一致、V5 状态无损、无重复主动消息 |

### Integration（14~15）

| # | Case | 断言 |
|---|---|---|
| 14 | Scenario 全链 | "我去忙了"→时间注入闲置→ACT(check_in)→主动消息落库→pending 可拉→ack；goal/intention/reason 全程可解释 |
| 15 | 回归 | `uv run pytest tests/ -v` 全绿；V2~V6 零回归；Worker 默认关闭不影响既有测试 |

## 3. 核心验收 Scenario 对应

| Scenario | 测试 |
|---|---|
| S1 用户离开→主动关心 | Case 14 全链 |
| S2 睡觉→不主动 | Case 6 + 集成静音用例 |
| S3 连续主动防护 | Case 5（attempt 上限 + backoff） |
| S4 Memory Trigger | V7-011 实现时补（follow-up 到期 → ACT） |
| S5 Chat 冲突 | Case 13 + Case 11 的 discarded 分支 |

## 4. 附加单测文件

- `test_autonomy_models.py`：枚举/字段校验/dedupe_key
- `test_autonomy_policy.py`：裁决流水逐条短路正反例（表驱动，纯函数）
- `test_trigger_evaluator.py`：闲置/刚回复/空会话/episode 重置
- `test_proactive_repository.py`：状态机迁移/深度 1/聚合查询
- `test_proactive_chain.py`：FakeLLM 文本生成/空文本失败/模板符校验
- `test_proactive_executor.py`：锁内二次校验/落库/退避
- `test_autonomy_worker.py`：tick 循环容错/开关
- `test_proactive_api.py`：pending/ack 端点
- `test_goal_matrix` 式聚合：`tests/integration/test_autonomy_matrix.py`（Case 1~13）

## 5. 验收标准

15 项必测全绿 + V2~V6 零回归 + `autonomy_enabled=False` 时行为与 V6 完全一致（回归护栏）。
