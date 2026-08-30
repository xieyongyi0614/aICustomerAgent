# Roleplay V7.8 任务注册表

> **状态（2026-08-30）**：设计完成，待实现。
> 执行策略：逐 Task 测试 + 全量回归（V1~V7.5 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：观测层是旁路——任何 Task 不得改变聊天 / 主动 / 评估链路的既有行为；观测失败只降级不抛出；一切开关与阈值进 `core/settings.py` observability_* 组；**`tests/golden/` prompt 金样字节不变**；测试默认 `OBSERVABILITY_PERSIST_ENABLED=false`。

## Task 列表

### V7.8-001 Observability 域模型 + 配置组（P0）

- **目标**：`app/models/observability.py` 全套域模型（RuntimeTrace / TraceStep / TraceEvent / DecisionRecord / PromptSnapshot / LlmCallRecord / MetricReport + TraceKind / DecisionKind / CallSite / CaptureMode 枚举与有界规则）+ settings `observability_*` 配置组（13 项）+ conftest 默认关持久化。
- **范围**：`app/models/observability.py`（新增）、`app/core/settings.py`、`tests/conftest.py`（一行 setdefault）；不碰任何 service / chain。
- **依赖**：无。
- **实现要点**：runtime-trace.md §3、decision-history.md §2、prompt-debug.md §1、llm-observability.md §1；有界规则（`observability_step_extra_max_chars`）作为域模型截断函数，供各采集点复用。
- **验收标准**：模型构造与校验（枚举边界、超限截断 + truncated 标记、可空字段）；配置组默认值加载、`override_settings` 可覆盖；既有测试在默认 env 下行为不变。
- **测试**：`tests/unit/test_observability_models.py`、`tests/unit/test_observability_settings.py`。

### V7.8-002 Runtime Trace 持久化（P0）

- **目标**：迁移 0013 `runtime_traces` 表 + `TraceRepository`（save / get_by_turn / get_by_trace_id / list_by_conversation / prune_before）+ `ObservabilityFacade.on_turn_finished` write-behind 持久化 + 既有 `/debug/turns/{id}/trace` 端点内存 miss 后落库回退。
- **范围**：`migrations/versions/0013_runtime_traces.py`、`app/repositories/trace_repository.py`、`app/application/observability.py`（Facade 骨架）、`app/application/chat_pipeline.py`（attach 处 +1 行挂载）、`app/api/v1/debug.py`、`app/services/trace_collector.py`（仅 snapshot→模型映射，不改收集行为）；不改 26 步骤注册表与任何 `trace.record` 调用点。
- **依赖**：V7.8-001。
- **实现要点**：runtime-trace.md §2/§4/§5；采样复用 request_id 确定性哈希口径（独立实现）；error/degraded 必存；事件回填（emotion_history / relationship_events 只读视角）；写库失败 log 不冒泡。
- **验收标准**：全链 turn 落 1 行且 steps 顺序稳定；采样/必存矩阵通过；内存 miss → DB 回退 → 404 三段语义正确；Facade 异常不影响聊天（写函数注入 raise 的负向测试）；alembic 往返。
- **测试**：`tests/unit/test_observability_sampling.py`、`tests/integration/test_observability_trace_repository.py`、`tests/v7.8/test_trace.py`、`tests/e2e/test_debug_trace_persist.py`。

### V7.8-003 LLM 调用记录（P0）

- **目标**：迁移 0014 `llm_call_records` 表 + `LlmCallRepository`（save / list_by_request / list_by_turn / summarize / prune_before）+ 四个采集点（answer / structured / summary / proactive）+ 成本核算（单价表）+ `GET /debug/llm-calls` 明细与 summary 端点。
- **范围**：`migrations/versions/0014_llm_call_records.py`、`app/repositories/llm_call_repository.py`、`app/chains/structured.py`、`app/chains/answer_chain.py`、`app/chains/summary_chain.py`、`app/chains/proactive_chain.py`、`app/api/v1/debug.py`；**不修改任何链的请求构造与调用逻辑**——只在调用返回后读取结果。
- **依赖**：V7.8-001（与 002 并行，flush 复用 Facade）。
- **实现要点**：llm-observability.md §1~§4；usage 缺失 → token null 行仍落；`observability_llm_cost_json` 按 model 匹配、未配置为 null；turn 内记录随 on_turn_finished 批量 flush，judge 等后台调用即时交 Facade。
- **验收标准**：FakeLLM 全链一次 turn 产出全部 call_site 记录（answer 1 + 辅助链 4 + 评估 judge 按采样）；answer 链 token 数与既有 trace.token_usage 一致；错误注入 → status=error 行 + error_kind 有界；单价表命中/未命中两分支。
- **测试**：`tests/integration/test_observability_llm_repository.py`、`tests/integration/test_observability_llm_capture.py`、`tests/e2e/test_debug_llm_calls.py`。

### V7.8-004 Prompt Snapshot（P0）

- **目标**：迁移 0015 `prompt_snapshots` 表 + `PromptSnapshotRepository` + 三个采集点（answer 含 section_budget、structured 统一、summary/proactive）+ 模式/采样/截断控制 + `GET /debug/turns/{id}/prompts`、`GET /debug/prompts/{id}` 端点。
- **范围**：`migrations/versions/0015_prompt_snapshots.py`、`app/repositories/prompt_snapshot_repository.py`、`app/services/observability/prompt_capture.py`、`app/chains/answer_chain.py` / `structured.py`（暂存挂点）、`app/api/v1/debug.py`；**`tests/golden/` 字节不变是本 Task 硬闸**。
- **依赖**：V7.8-001（与 002/003 并行）。
- **实现要点**：prompt-debug.md §1~§4；快照暂存 TraceSession 有界缓冲随收尾 flush；judge call_site 只记元数据不存 messages（V7.5 约束沿用）；section 统计只读提取模板变量，不改 PromptBuilder 返回值。
- **验收标准**：快照 messages 与 FakeLLM.seen_messages 逐字节一致；mode 三档 + 确定性采样矩阵通过；超限截断；golden 全量通过；评估 judge 无 prompt 正文。
- **测试**：`tests/integration/test_observability_prompt_capture.py`、`tests/v7.8/test_prompt_snapshot.py`、`tests/e2e/test_debug_prompts.py`。

### V7.8-005 Decision History：主动行为决策记录（P0）

- **目标**：迁移 0016 `decision_records` 表 + `DecisionRepository`（save / mark_outcome / list_by_user / prune_before）+ `proactive_autonomy` 决策采集（trigger → policy → enqueue/deny → outcome 补写）+ `GET /debug/decisions` 端点。
- **范围**：`migrations/versions/0016_decision_records.py`、`app/repositories/decision_repository.py`、`app/application/autonomy_engine.py`（evaluate 结果侧只读挂点）、`app/services/proactive_executor.py`（delivered/failed 后补 outcome）、`app/api/v1/debug.py`；**不改 autonomy_policy / trigger_evaluator 的任何逻辑**。
- **依赖**：V7.8-001。
- **实现要点**：decision-history.md §2/§3；仅在有触发候选的 tick 产记录；deny 记录 reason 含裁决步骤与关键值；outcome 幂等 UPDATE；turn 级四类 kind 枚举先入模型、采集留 009。
- **验收标准**：allow→enqueue→delivered→acked 全链记录时间线正确；deny 记录可回答"为什么不主动"；无触发不记；policy/executor 既有集成测试零回归；action_id 与 proactive_actions 状态机一致。
- **测试**：`tests/integration/test_observability_decision_repository.py`、`tests/v7.8/test_decision_record.py`、`tests/e2e/test_debug_decisions.py`。

### V7.8-006 Metrics 聚合器 + 查询 API（P0）

- **目标**：`app/services/observability/metrics_aggregator.py` 纯计算聚合器（管线 / LLM / 质量 / 业务四视角）+ `GET /api/v1/debug/metrics?window_hours=&user_id=` 端点。
- **范围**：`app/services/observability/metrics_aggregator.py`（新增）、`app/api/v1/debug.py`；只读消费 runtime_traces / llm_call_records / evaluation_reports / messages / proactive_actions，不建新表、不改 V7.5 口径。
- **依赖**：V7.8-002、V7.8-003（质量视角复用 V7.5-013 口径函数或平行实现）。
- **实现要点**：metrics.md §2/§3；分位数简单排序法；窗口空 → 零值结构；全部数字可由种子数据单测固定。
- **验收标准**：种子数据期望数字精确断言（分位数 / verdict 分布 / issue 直方图 / ack 率）；端点只读无副作用；空库返回合法零值。
- **测试**：`tests/unit/test_observability_metrics_aggregator.py`、`tests/v7.8/test_metrics.py`、`tests/e2e/test_debug_metrics.py`。

### V7.8-007 Evaluation Correlation + request_id 贯通（P0 收口）

- **目标**：评估 meta 补写 request_id + `GET /debug/turns/{turn_id}/correlation` bundle API + `x-request-id` 响应头 middleware。
- **范围**：`app/services/evaluation_engine.py`（落库前 meta 补键，仅此一处触碰 V7.5）、`app/api/v1/debug.py`、`app/main.py`（middleware）；不改 EvaluationReport 域模型与表结构。
- **依赖**：V7.8-002 ~ V7.8-005（bundle 组装各仓储）。
- **实现要点**：evaluation-correlation.md §1/§2/§5；bundle 各部分缺席容忍（null / 空数组），全空 404；middleware 仅回写头、零逻辑。
- **验收标准**：一次 FakeLLM 全链 turn 后 correlation 五部分齐备且关联键一致；评估缺席时 bundle 仍可用；**V7.5 全部评估测试零回归（meta 新增键向后兼容，涉及精确断言的逐条列明）**；done 事件序列不变。
- **测试**：`tests/e2e/test_debug_correlation.py`、`tests/integration/test_observability_evaluation_meta.py`。**本 Task 为 P0 收口：合并前全量回归零失败。**

### V7.8-008 Proactive 全链路 trace + 主动 correlation（P1）

- **目标**：`kind=proactive` trace session（executor 内建立，delivered/failed 后 flush）+ `kind=autonomy_tick` 决策型 trace + `GET /debug/proactive/{action_id}/correlation`。
- **范围**：`app/services/proactive_executor.py`（trace 建立 + flush 挂点）、`app/application/observability.py`、`app/api/v1/debug.py`；不改主动链路控制流。
- **依赖**：V7.8-002、V7.8-005。
- **实现要点**：runtime-trace.md §2（proactive / autonomy_tick 两 kind）；主动链 LLM 调用（proactive_chain 记录）挂到本 trace；决策 outcome 与 trace 状态对齐。
- **验收标准**：delivered 后 runtime_traces 出现 kind=proactive 行且 turn_id=delivered.message_id；主动 correlation 五部分齐备（决策 + trace + 评估 + LLM + prompt）；V7 主动链路既有测试零回归。
- **测试**：`tests/integration/test_observability_proactive_trace.py`、`tests/e2e/test_debug_proactive_correlation.py`。

### V7.8-009 Turn 级决策记录（P1）

- **目标**：`turn_goal / turn_intention / turn_behavior` 三类 DecisionRecord 采集（chat_pipeline 步骤返回后只读提取）。
- **范围**：`app/application/chat_pipeline.py`（三处后置挂点）、`app/application/observability.py`；不改 goal / intention / behavior 引擎。
- **依赖**：V7.8-005。
- **实现要点**：decision-history.md §3 turn 级部分；request_id 关联当轮 trace；input_snapshot 有界（budget 余量、intention 方向、goal 值）。
- **验收标准**：全链 turn 产出三类记录且与 trace 步骤结果一致；采样与开关行为同 M2；chat_pipeline 既有测试零回归。
- **测试**：`tests/integration/test_observability_turn_decisions.py`。

### V7.8-010 保留策略统一清理（P1）

- **目标**：lifespan 低频清理循环（`observability_cleanup_interval_hours`）串行 prune 四表 + 单批上限。
- **范围**：`app/main.py`（lifespan 注册）、`app/application/observability.py`、各仓储 prune 函数补齐；沿用惰性清理先例。
- **依赖**：V7.8-002 ~ V7.8-005。
- **实现要点**：persistence.md §3；清理失败 log 下轮再清；开关关闭时循环不启动。
- **验收标准**：种子过期数据清理幂等；未过期不动；清理不影响并发写；循环异常不终止 lifespan。
- **测试**：`tests/integration/test_observability_retention.py`。

### V7.8-011 Prompt 快照比较 API（P1）

- **目标**：`GET /debug/prompts/compare?a=&b=` 结构化 diff（模型切换 / 总量 / section 差异 / clipped 变化 / 消息数）。
- **范围**：`app/api/v1/debug.py`、`app/services/observability/prompt_capture.py`（diff 纯函数）。
- **依赖**：V7.8-004。
- **实现要点**：prompt-debug.md §5；diff 是纯函数可单测；跨 call_site 比较允许但标注。
- **验收标准**：prompt-debug.md §5 示例结构可复现；缺失快照 404。
- **测试**：`tests/unit/test_observability_prompt_diff.py`、`tests/e2e/test_debug_prompt_compare.py`。

### V7.8-012 低质量下钻查询（P1）

- **目标**：`GET /debug/evaluations?verdict=&dimension=&issue_code=&window_hours=&limit=&include=correlation` 反向查询。
- **范围**：`app/api/v1/debug.py`、`app/repositories/evaluation_repository.py`（补只读列表查询函数）；不改评估写入。
- **依赖**：V7.8-007。
- **实现要点**：evaluation-correlation.md §4；列表轻量 + include 内联 bundle；分页 limit 上限。
- **验收标准**：多条件过滤矩阵通过；include=correlation 时关联键一致；纯只读。
- **测试**：`tests/e2e/test_debug_evaluation_search.py`。

### V7.8-013 热路径性能护栏（P1）

- **目标**：`tests/v7.8/test_performance.py` 四断言固化（热路径无 IO / 开销预算 / 关闭即现状 / golden 字节不变守门）。
- **范围**：`tests/v7.8/test_performance.py`（新增）；预算值进 settings 便于机器差异调整。
- **依赖**：V7.8-002 ~ V7.8-006。
- **实现要点**：testing.md §3。
- **验收标准**：四断言全绿；在后续任何 Task 中持续作为回归守门。
- **测试**：即本 Task。

### V7.8-014 Metrics 周期快照落库（P2）

- **目标**：`metrics_snapshots` 表（迁移 0017）+ lifespan 低频（6h）落 MetricReport 行 + `GET /debug/metrics/history`。
- **范围**：`migrations/versions/0017_metrics_snapshots.py`、聚合器复用 006 产物；TTL 90 天。
- **依赖**：V7.8-006、V7.8-010。
- **实现要点**：metrics.md §4；快照行带 window 元信息；失败只 log。
- **验收标准**：快照往返读写；history 端点时序返回；循环不阻塞 lifespan。
- **测试**：`tests/integration/test_observability_metrics_snapshot.py`。

### V7.8-015 真实模型人工回归清单（P2，仅文档）

- **目标**：`docs/roleplay-v7.8/regression-checklist.md`——开关矩阵核对表、debug API 抽查表、一次低分回复 correlation 下钻演练、TTL/体积观察项。
- **范围**：仅文档；组织方式沿用 V4 / V7.5 回归清单。
- **依赖**：V7.8-001 ~ V7.8-014。
- **实现要点**：testing.md §5。
- **验收标准**：清单文档化。
- **测试**：无（人工执行）。

## 依赖图

```text
001 域模型+配置 ─┬─ 002 Trace 持久化 ──┬─ 008 Proactive Trace（+005）─┐
                 ├─ 003 LLM 调用记录 ──┤                              │
                 ├─ 004 Prompt Snapshot ── 011 Prompt 比较             │
                 └─ 005 Decision History ── 009 Turn 级决策            │
                                        │                              │
                 006 Metrics（←002+003）┤                              │
                                        ▼                              ▼
                              007 Correlation（P0 收口，←002~005）── 012 低质量下钻
                                        │
              010 保留清理（←002~005）──┼─ 013 性能护栏（←002~006，此后常驻守门）
                                        ▼
                              014 Metrics 快照（←006+010）
                                        ▼
                              015 真实回归清单（P2，仅文档，←全部）
```

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V7.8-XXX <中文描述>`。
- V7.8-007 是 P0 收口点：合并前必须全量回归零失败（既有约 963 测试 + 新增），golden 金样字节不变。
- P0 链（001→007）完成后系统即具备持久化观测与关联能力；P1 六项可连续推进；015 最后执行。
