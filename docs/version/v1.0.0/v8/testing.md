# V8 Testing 设计

> 分层沿用仓库惯例（unit / integration / e2e 归位既有目录），版本场景套件落 `tests/v8/`（沿 tests/evaluation、tests/v7.8 先例）。

## 1. 测试分层

| 层 | 目录 | 覆盖 |
|---|---|---|
| 单元 | `tests/unit/test_world_*.py` | 域模型校验与有界规则；物品状态机纯函数；选择器切片与预算；时间模式推导；事件时间解析规则 |
| 集成 | `tests/integration/test_world_*.py` | 四仓储 CRUD + ensure 幂等 + prune；WorldEngine 生命周期；解释器→迁移→下轮可见闭环；memory_bridge 投递与幂等 |
| E2E | `tests/e2e/test_world_*.py` | chat 全链（世界段出现/不出现）；/debug/world 端点；world_facts 进 policy 裁决 |
| 版本套件 | `tests/v8/` | 五套件（§2） |
| 回归守门 | `tests/unit/test_prompt_golden.py` + 既有全量 | golden 字节不变 + 1050+ 零回归 |

根 conftest 复用（FakeLLM / StaticPool / override_settings）；world_* 键加入 override_settings env_map；时间冻结用注入 TimeProvider。

## 2. tests/v8/ 五套件

| 套件 | 归属 Task | 验证 |
|---|---|---|
| `test_world_state.py` | 002 | **World State Test：状态保存**——ensure_world 幂等；实体/环境/事件写读往返；world_enabled=false 全链短路；降级（仓储注入 raise → chat 正常、world_ctx=None） |
| `test_object_lifecycle.py` | 005/006 | **Object Lifecycle Test：物品变化**——西瓜全链（Created→Moved→cut→eaten 0.8→expired→empty）跨会话持久；非法迁移被拒（不造事实）；数量精度与下限 |
| `test_time_simulation.py` | 003 | **Time Simulation Test：时间推进**——real_sync 零存储；simulated 速率推进；story 显式步进；part_of_day 边界（5/11/14/18/23）；due 触发幂等 |
| `test_event_trigger.py` | 008 | **Event Trigger Test：事件触发**——scheduled→active（due 到期单次触发）；completed→记忆候选（幂等 materialized）；cancelled 不沉淀；活跃上限拒新建 |
| `test_context_builder.py` | 007 | **Context Builder Test：正确注入**——切片选择规则矩阵（谁进谁不进）；预算裁剪优先级；渲染段 ≤ 预算；**空世界 → 渲染 None → golden 字节不变**；同状态渲染确定性 |
| `test_performance.py` | 012 | 世界装配开销预算（<10ms/轮）；热路径无解释器写（第 8 步才写）；world_facts 失败零影响自治 |

## 3. 集成与行为断言（跨套件底线）

1. **零行为变更**：无世界数据时既有全量测试零回归（1050+）；golden prompt 字节不变。
2. **零写回**：World 全链路不写 character_state / relationship_state / emotion_history / memories 直写路径（memory_bridge 经既有仓储入口除外）——专项断言。
3. **宁缺毋滥**：解释器对模糊输入零迁移、零建事件；LLM 辅助提议必须过确定性校验。
4. **幂等**：ensure_world、事件触发、记忆投递、清理，全部幂等可重放。

## 4. 场景化设计（沿 tests/evaluation 声明式先例）

- `tests/v8/scenarios/`：JSON 场景（世界初始态 + 用户消息序列 + 期望世界终态 + 期望渲染段片段），参数化 runner——西瓜全链、面试全链、雨天自治三条主线各一组正/反例。
- 时间冻结：场景声明 `time`（固定时钟）或 `advance`（步进序列）；runner 注入 FakeTimeProvider。

## 5. 手工回归（014，仅文档）

`docs/version/v1.0.0/v8/regression-checklist.md`：开关矩阵、西瓜/面试/雨天三条真实模型演练、世界段 prompt 抽查、快照恢复演练、体积观察项。
