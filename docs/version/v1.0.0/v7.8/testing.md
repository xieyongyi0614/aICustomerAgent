# V7.8 Testing 设计

> 分层沿用仓库惯例（unit / integration / e2e 归位既有目录），版本场景套件落 `tests/v7.8/`（沿 `tests/evaluation/` 先例）。

## 1. 测试分层

| 层 | 目录 | 覆盖 |
|---|---|---|
| 单元 | `tests/unit/test_observability_*.py` | 域模型校验与有界规则；采样函数确定性；prompt_capture 构造与截断；metrics_aggregator 纯口径 |
| 集成 | `tests/integration/test_observability_*.py` | 四仓储 CRUD + prune；迁移往返；Facade write-behind（含失败降级）；事件回填（emotion_history 视角） |
| E2E | `tests/e2e/test_debug_*.py` | 新 debug API（correlation / prompts / llm-calls / decisions / metrics）只读语义与 404 |
| 版本套件 | `tests/v7.8/` | 五套件（§2），版本级完整链路验收 |

根 conftest 复用：FakeLLM、`db_session_factory`（StaticPool）、`override_settings`、`wait_until`；`tests/conftest.py` 增 `OBSERVABILITY_PERSIST_ENABLED=false` setdefault。

## 2. tests/v7.8/ 五套件

| 套件 | 归属 Task | 验证 |
|---|---|---|
| `test_trace.py` | 002 | **Trace Test：完整链路**——FakeLLM 全链 turn 后：runtime_traces 落 1 行；26 步骤名全覆盖、顺序稳定；error 注入 → status=error 必存；采样关闭 → 不落但内存端点仍 200；重启语义（清 LRU）后持久层可查 |
| `test_prompt_snapshot.py` | 004 | **Prompt Snapshot Test：上下文正确**——快照 messages 与 FakeLLM.seen_messages 一致（采集不改变发送内容）；section_budget 与构造输入吻合；mode=disabled / sampled 0（确定性 request_id）/ always 三档行为；超限截断 + truncated 标记 |
| `test_decision_record.py` | 005 | **Decision Record Test：主动行为记录**——trigger 命中 + policy allow → enqueue 记录 + executor delivered → outcome 补写；policy deny → deny 记录含 reason；无触发 tick 不产生记录；action_id ↔ proactive_actions 状态机对应 |
| `test_metrics.py` | 006 | **Metrics Test：指标口径**——种子数据（固定 trace/llm/evaluation 行）→ MetricReport 数字精确断言（分位数、分布、直方图、ack 率）；空窗口返回零值结构不抛 |
| `test_performance.py` | 013 | **Performance Test：不明显影响响应**——见 §3 |

声明式与确定性原则沿 `tests/evaluation/`：全 FakeLLM / 固定种子 / 无真实网络 / 单命令可跑 / xdist 安全（write-behind 任务 teardown 等待）。

## 3. Performance Test 设计（013）

四个断言，全部不需要真实压测环境：

1. **热路径无 IO**：monkeypatch 仓储写函数为 raise——完整聊天 turn 仍正常完成（证明持久化在收尾后台任务，异常被 Facade 吞）。
2. **开销预算**：同一 FakeLLM 场景跑 N 轮，对比 `observability_persist_enabled` on/off 的总墙钟，差值预算 < 50ms/轮（FakeLLM 环境下观测自身开销可测；预算进 settings 便于机器差异调整）。
3. **关闭即现状**：persist off 时，行为与 V7.5 基线一致（trace 端点、评估报告、state API 全部不变）。
4. **prompt 字节不变**：`tests/golden/` 全量金样对比通过（挂在本套件作为守门断言，防止后续 Task 无意改动 builder）。

## 4. 全局守恒断言（每个 Task 的验收底线）

- 既有全量测试零回归；涉及 trace 断言变更时**逐条列明**（V7.5-010 先例）。
- 聊天 e2e 既有 NDJSON 事件序列（turn_meta → delta* → done）不变；done 携带的 request_id 语义不变（仅响应头新增）。
- 评估相关测试零改动通过（meta 补 request_id 键不得破坏既有 meta 断言——若有断言精确等于旧 meta，按"新增键向后兼容"原则同步列明修订）。
- pylint 分数不低于基线（7.44+）。

## 5. 手工回归（015，仅文档）

`docs/version/v1.0.0/v7.8/regression-checklist.md`：开关矩阵核对（各开关组合下聊天正常）、五维 debug API 抽查、一次真实低分回复的 correlation 下钻演练、TTL 清理观察项。组织方式沿用 V4 / V7.5 回归清单。
