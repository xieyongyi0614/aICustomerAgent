# Roleplay V7.8 任务注册表

> **状态（2026-08-31）**：V7.8-001~013、015 完成（全量 1034+ 绿）；**014（P2 Metrics 周期快照）按设计留白未实现**——单机调试台实时派生足够，启动前置条件见 metrics.md §4。V7.8-015 回归清单待人工执行。
> 执行策略：逐 Task 测试 + 全量回归（V1~V7.5 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：观测层是旁路——任何 Task 不得改变聊天 / 主动 / 评估链路的既有行为；观测失败只降级不抛出；一切开关与阈值进 `core/settings.py` observability_* 组；**`tests/golden/` prompt 金样字节不变**；测试默认 `OBSERVABILITY_PERSIST_ENABLED=false`。

## Task 列表

### V7.8-001 Observability 域模型 + 配置组（P0） ✅ 04c9bee

- **目标**：`app/models/observability.py` 全套域模型 + settings `observability_*` 配置组（13 项）+ conftest 默认关持久化。
- **范围**：`app/models/observability.py`（新增）、`app/core/settings.py`、`tests/conftest.py`；不碰任何 service / chain。
- **依赖**：无。
- **实现要点**：RuntimeTrace / TraceStep / TraceEvent / DecisionRecord / PromptSnapshot / LlmCallRecord / MetricReport + 四枚举 + bound_extra / bound_text / deterministic_sample / estimate_cost 纯函数。
- **验收标准**：模型构造与校验（枚举边界、超限截断 + truncated 标记）；配置组默认值、env 覆盖、非法值拒绝；既有测试默认 env 行为不变。
- **测试**：`tests/unit/test_observability_models.py`（18 项）。

### V7.8-002 Runtime Trace 持久化（P0） ✅ f49975b

- **目标**：迁移 0013 `runtime_traces` + `trace_repository` + `ObservabilityFacade`（write-behind）+ chat 挂载 + debug trace DB 回退。
- **范围**：0013 迁移、trace_repository、application/observability.py、chat_pipeline（attach 后 +2 挂载行）、agent_service（错误路径 on_turn_error）、debug.py（内存 miss → DB 回退 + /debug/traces 两端点）。
- **依赖**：001。
- **实现要点**：request_id 确定性采样（**error 必存**；实现修订：degraded 属常规降级路径，参与采样）；事件回填（emotion_history / relationship_events 只读视角）；flush 等待 post_process 任务与后台任务排空。
- **验收标准**：全链 turn 落 1 行 steps 齐备；error 运行在采样 0 时仍必存；内存 miss → DB → 404 三段语义；Facade 负向注入不影响聊天；alembic 往返。
- **测试**：`tests/integration/test_observability_trace_repository.py`、`tests/v7.8/test_trace.py`、`tests/e2e/test_debug_trace_persist.py`。

### V7.8-003 LLM 调用记录（P0） ✅ 06c36da

- **目标**：迁移 0014 `llm_call_records` + 仓储 + structured 统一观测壳 + answer/summary/proactive 返回后采集 + 成本核算 + debug 端点。
- **范围**：0014 迁移、llm_call_repository、services/observability/llm_capture.py（UsageCallbackHandler + _ObservedChain）、chains/structured.py、answer_chain、summary_chain、proactive_chain、core/llm_factory（profile_id_of/provider_of 只读辅助）、debug.py。
- **依赖**：001（flush 复用 002 Facade）。
- **实现要点**：schema 名 → call_site 推断（未知 schema 原样透传）；usage 经 LangChain callbacks 读取，不改请求构造；usage 缺失 token 置 null 行仍落；成本按 observability_llm_cost_json 匹配；contextvar 关联 request_id/turn_id；error 轮缓冲随 error flush 排空。
- **验收标准**：全链 turn 覆盖 answer/router/turn_analysis/scene_intent/intention 等 call_site；answer TTFT 落行；错误行 error_kind 有界；summary 端点聚合 p50/p95。
- **测试**：`tests/unit/test_observability_llm_capture.py`、`tests/integration/test_observability_llm_repository.py`、`tests/integration/test_observability_llm_turn_capture.py`、`tests/e2e/test_debug_llm_calls.py`。

### V7.8-004 Prompt Snapshot（P0） ✅ e92acbc

- **目标**：迁移 0015 `prompt_snapshots` + 仓储 + answer/structured 采集点 + section_budget + 模式/采样/截断/redact 控制 + debug 端点。
- **范围**：0015 迁移、prompt_snapshot_repository、services/observability/prompt_capture.py、answer_chain（build_chain 增可选 prompt 参数）、llm_capture（结构化链格式化后采集）、debug.py；**golden 字节不变硬闸**。
- **依赖**：001。
- **实现要点**：mode disabled/sampled/always + request_id 确定性采样 + 20000 字符上限；section_budget 按 【】标记头分类（identity/emotion/memory/summary/history/user_message/tail…）；judge 快照只记元数据不存 messages；采集在 hot path 仅模式判定，格式化只在命中后发生。
- **验收标准**：快照 messages 与 FakeLLM 实际收到内容逐字节一致；三档模式矩阵；超限截断；golden 全绿。
- **测试**：`tests/unit/test_observability_prompt_capture.py`、`tests/integration/test_observability_prompt_snapshots.py`、`tests/e2e/test_debug_prompts.py`。

### V7.8-005 Decision History：主动行为决策记录（P0） ✅ 9c0bfbd

- **目标**：迁移 0016 `decision_records` + 仓储 + proactive_autonomy 采集（trigger → policy → enqueue/deny → outcome）+ `GET /debug/decisions`。
- **范围**：0016 迁移、decision_repository、autonomy_engine（evaluate 结果侧只读挂点）、proactive_executor（delivered/failed/discarded outcome 补写）、api/v1/proactive.py（ack → acked 补写）、debug.py。
- **依赖**：001。
- **实现要点**：仅在有触发候选的 tick 产记录；deny 记录 reason 含裁决依据；outcome 幂等补写（仅填 NULL）；policy / trigger_evaluator 零改动。
- **验收标准**：act→delivered→（ack）时间线完整；deny 记录回答"为什么不主动"；无触发不记；V7 全部测试零回归。
- **测试**：`tests/integration/test_observability_decision_repository.py`、`tests/v7.8/test_decision_record.py`、`tests/e2e/test_debug_decisions.py`。

### V7.8-006 Metrics 聚合器 + 查询 API（P0） ✅ 3d70cb8

- **目标**：纯计算聚合器（管线 / LLM / 质量 / 业务四视角）+ `GET /api/v1/debug/metrics`。
- **范围**：services/observability/metrics_aggregator.py、debug.py、evaluation/proactive 仓储新增只读 list_since。
- **依赖**：002、003。
- **实现要点**：分位数简单排序法；种子数据 → 期望数字精确断言；空窗口零值结构。
- **验收标准**：分位数 / verdict 分布 / 维度均分 / issue 直方图 / ack 率口径固定；端点只读。
- **测试**：`tests/unit/test_observability_metrics_aggregator.py`、`tests/e2e/test_debug_metrics.py`。

### V7.8-007 Evaluation Correlation + request_id 贯通（P0 收口） ✅ eb7b25d

- **目标**：EvaluationMeta.request_id + turn/proactive correlation bundle API + `x-request-id` 响应头。
- **范围**：models/evaluation.py（EvaluationMeta 增 request_id 可空字段，唯一 V7.5 触碰点）、evaluation_engine（meta 补键）、api/v1/chat.py + agent_service（trace 预创建传参 + 响应头）、decision_repository.search（request_id 参数）。
- **依赖**：002~005。
- **实现要点**：bundle 各部分缺席容忍、全空 404；done 事件与 API 契约不变。
- **验收标准**：全链 turn 后 bundle 五部分齐备且关联键一致；评估缺席可用；**全量回归 1034 绿**。
- **测试**：`tests/e2e/test_debug_correlation.py`。

### V7.8-008 Proactive 全链路 trace + 主动 correlation（P1） ✅ 6e94f6a

- **目标**：kind=proactive / autonomy_tick trace 持久化 + 主动链 LLM/快照挂载 + proactive bundle 补全。
- **范围**：autonomy_engine（contextvar 包裹 executor、deny 落 autonomy_tick trace、act 落 proactive trace）、proactive_chain/summary_chain prompt 快照采集、Facade drain_background 参数。
- **依赖**：002、005。
- **验收标准**：delivered 后 kind=proactive 行 turn_id=message_id、action_id 关联；proactive bundle 决策+trace+评估齐备；deny tick 落 autonomy_tick 行；V7 测试零回归。
- **测试**：`tests/integration/test_observability_proactive_trace.py`、`tests/e2e/test_debug_proactive_correlation.py`。

### V7.8-009 Turn 级决策记录（P1） ✅ 32c36b0

- **目标**：turn_goal / turn_intention / turn_behavior 三类后置只读采集。
- **范围**：observability.record_turn_decisions（chat_pipeline 步骤返回后挂载）。
- **依赖**：005。
- **验收标准**：全链 turn 三类记录 request_id 关联 trace；correlation bundle 可见；persist 关闭零影响。
- **测试**：`tests/integration/test_observability_turn_decisions.py`。

### V7.8-010 保留策略统一清理（P1） ✅ 77e5d0b

- **目标**：prune_all 按 TTL 串行清理四表 + lifespan 低频清理循环。
- **范围**：observability（prune_all / run_retention_loop）、main.py（persist 开启才启动）。
- **依赖**：002~005。
- **验收标准**：过期删、未过期留、空库安全；persist 关闭不启动循环。
- **测试**：`tests/integration/test_observability_retention.py`。

### V7.8-011 Prompt 快照比较 API（P1） ✅ 2f4d4f7（+e505623/bb38e1e 路由顺序修正）

- **目标**：`GET /debug/prompts/compare?a=&b=` 结构化 diff。
- **范围**：prompt_capture.diff_prompt_snapshots 纯函数、debug 端点（置于 {snapshot_id} 参数路由之前）。
- **依赖**：004。
- **测试**：`tests/unit/test_observability_prompt_diff.py`、`tests/e2e/test_debug_prompt_compare.py`。

### V7.8-012 低质量下钻查询（P1） ✅ e8d9cd5

- **目标**：`GET /debug/evaluations?verdict=&dimension=&issue_code=&window_hours=&limit=&include=correlation`。
- **范围**：debug.py（correlation 组装抽 _turn/_proactive 公共函数）。
- **依赖**：007。
- **测试**：`tests/e2e/test_debug_evaluation_search.py`。

### V7.8-013 热路径性能护栏（P1） ✅ d37a2ce

- **目标**：`tests/v7.8/test_performance.py` 四守门断言（无 IO 负向注入 / 开销预算 50ms·轮 / 关闭即现状 / prompt 字节不变）。
- **依赖**：002~006。
- **测试**：即本 Task；后续任何 Task 的常驻回归守门。

### V7.8-014 Metrics 周期快照落库（P2）

- **状态**：**按设计留白**（metrics.md §4：先验证指标口径，再决定长期存储；启动时补迁移 0017 metrics_snapshots + lifespan 6h 落行 + /debug/metrics/history）。

### V7.8-015 真实模型人工回归清单（P2，仅文档） ✅ 见 docs/roleplay-v7.8/regression-checklist.md

- **目标**：开关矩阵核对、debug API 抽查、低分回复 correlation 下钻演练、TTL/体积观察项。
- **测试**：无（人工执行）。

## 依赖图（实际执行序）

```text
001 → 002 → 003 → 004 → 005 → 006 → 007（P0 收口，全量 1034 绿）
002~005 → 008 → 009 → 010 → 011 → 012 → 013 → 015
014（P2 留白）
```

## 附带修复

- fix ea61959：V7 autonomy matrix 测试播种时间回填——既有时钟脆弱性（真实时钟跨过固定 NOW 时 idle 为负），仅测试种子、不涉断言与业务代码。

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V7.8-XXX <中文描述>`；测试/路由修正以 `fix:` 追加。
- V7.8-007 为 P0 收口：全量回归零失败后合并。
