# V7.8 架构设计

> 观测层与 Runtime 的关系：**平行的旁路管线**。Runtime 生产事实，观测层在事实发生之后记录事实；观测层永远没有写回 Runtime 的通道。

## 1. 总体架构

```text
                     ┌─────────────────── Character Runtime（V7.8 不改其行为）───────────────────┐
User Request ──→ api/v1/chat ──→ application/chat_pipeline ──→ chains/answer_chain ──→ Response
                                    │            │                │
                              （各步骤 trace= 埋点，现状不变）  （调用返回后记录）
                                    │            │
                                    │      application/post_process（7 步，现状不变）
                                    │            │
                     └──────────────┴────────────┴──────────────────────────────────────────┘
                                                   │  收尾/后台（只读结果对象）
                                                   ▼
                        ┌────────────── Runtime Intelligence Layer ──────────────┐
                        │  ObservabilityFacade（application：调度、采样、降级）      │
                        │      │                                                  │
                        │      ├─ M1 TraceRecorder        → runtime_traces        │
                        │      ├─ M2 DecisionRecorder     → decision_records      │
                        │      ├─ M3 PromptCapture        → prompt_snapshots      │
                        │      ├─ M4 LlmCallRecorder      → llm_call_records      │
                        │      └─ M5 MetricsAggregator    → 按需派生（不建表）        │
                        │                                  （P2 可选快照表）          │
                        │  M6 Correlation：以上全部 + evaluation_reports → bundle API │
                        └─────────────────────────────────────────────────────────┘
                                                   │
                              api/v1/debug/*（全部只读查询，不上用户侧）
```

## 2. 分层归属（Domain / Application / Infrastructure）

沿用后端分层单向依赖 `api → application → services → repositories → core`，观测层的每一块都有明确归属，**禁止全部堆进 Service**：

| 层 | 位置 | 内容 | 约束 |
|---|---|---|---|
| Domain | `app/models/observability.py` | RuntimeTrace / TraceStep / TraceEvent / DecisionRecord / PromptSnapshot / LlmCallRecord / MetricReport + 枚举（TraceKind、DecisionKind、CallSite、CaptureMode）+ 有界规则（字符上限常量） | 纯 Pydantic，零 IO，零行为 |
| Application | `app/application/observability.py` | `ObservabilityFacade`：on_turn_finished / on_proactive_delivered / on_llm_call / on_decision 四个入口；开关与采样判定；write-behind 任务调度；异常吞噬 + log | 只做调度与容错，不做状态计算；所有持久化经它派发 |
| Services | `app/services/observability/` | `sampling.py`（request_id 确定性采样纯函数）、`prompt_capture.py`（快照构造 + section 预算提取）、`metrics_aggregator.py`（指标聚合纯计算） | 纯计算与构造，不碰 DB |
| Infrastructure | `app/repositories/`（trace / llm_call / decision / prompt_snapshot 四个新仓储文件）+ `migrations/versions/0013~0016` + `core/settings.py` | 表读写、prune_before、DDL | 沿用模块级函数仓储惯例；DB 访问只走仓储 |
| Interfaces | `app/api/v1/debug.py` 扩展 | trace / prompts / llm-calls / decisions / metrics / correlation / evaluations 查询端点 | 只读，禁止依赖 chains / langchain |

Facade 的四个入口是观测层唯一的对外写入口；任何模块想"记点什么"，只能调用 Facade，不允许自行开仓储写库。

## 3. 挂载点清单（全部是加法）

| # | 挂载点 | 文件 | 变更形态 | 归属 Task |
|---|---|---|---|---|
| H1 | turn 收尾 | `app/application/chat_pipeline.py`（attach 调用处） | +1 行 `on_turn_finished(...)`（内部 fire-and-forget） | 002 |
| H2 | 结构化链 | `app/chains/structured.py` | 调用返回后：usage 读取 + prompt 暂存（不改请求构造） | 003 / 004 |
| H3 | 生成链 | `app/chains/answer_chain.py` | 既有 usage_metadata 累加外发为记录 + prompt 快照 + TTFT 既有字段复用 | 003 / 004 |
| H4 | 汇总/主动链 | `app/chains/summary_chain.py`、`proactive_chain.py` | 调用返回后记录 | 003 |
| H5 | 自治决策 | `app/application/autonomy_engine.py`（evaluate 结果侧） | 只读决策对象 → `on_decision` | 005 |
| H6 | 主动执行收尾 | `app/services/proactive_executor.py`（delivered/failed 后） | trace session 建立 + 决策 outcome 补写 | 008 |
| H7 | 评估 meta | `app/services/evaluation_engine.py`（落库前） | meta 增加 request_id 键（行为不变，仅多一个字段） | 007 |
| H8 | HTTP 头 | `app/main.py` | 极简 middleware 回写 `x-request-id` 响应头 | 007 |

明确不改的文件：`goal_service` / `memory_service` / `state_service` / `behavior_engine` / `autonomy_policy` / `evaluation_rules` / `prompts/builder.py`（section 统计由 prompt_capture 从 builder 返回的模板变量只读提取，不改 builder 输出）。

## 4. 生命周期与数据流

一次前台 turn 的观测时间线：

```text
t0  begin_trace()（现状）           TurnTraceSession 建立，request_id 生成
t1~tn 各步骤 trace.record()（现状）  steps / events / llm_calls / prompts 在内存累积（有界）
tn+1 save_turn 落库（现状）
tn+2 schedule_post_process（现状）   评估在后台执行（现状）
tn+3 attach(trace, turn_id)（现状）  ← H1 在此之后追加：on_turn_finished(trace, turn_id, ...)
       Facade 判定：持久化开关？trace 采样命中？（request_id sha256，error/degraded 必存）
       → asyncio.create_task 批量写：runtime_traces 1 行 + llm_call_records N 行
         + prompt_snapshots M 行（采样判定各自的，互不耦合）
       后台任务失败 → log + 放弃，不重试不冒泡
```

主动行为（008）与自治 tick 的 trace 同构：`kind=proactive` 的 session 在 executor 内建立，delivered/failed 后 flush；`kind=autonomy_tick` 只在产生决策时记录。

## 5. 失败与降级契约（与 V7.5 同源）

1. 观测层任何异常（采数、判采样、写库）只 log，不冒泡——聊天与主动链路的行为、返回值、延迟分布都不允许出现可观测差异。
2. 单条记录失败不影响同批其余记录（逐条容错，规则引擎先例）。
3. 表不存在 / 迁移未跑 / 持久化开关关闭 → Facade 直接短路，内存 LRU trace 端点继续可用（现状能力不回退）。
4. 字符超限一律截断并打 `truncated` 标记，不抛错、不丢整条。

## 6. 开关矩阵（生产可关闭）

settings `observability_*` 组（完整清单见 persistence.md §5）：

| 开关 | 默认 | 作用 |
|---|---|---|
| `observability_persist_enabled` | true | 总开关：false 时全部持久化短路，回到 V7.5 现状（内存 trace 仍可用） |
| `observability_trace_sample_rate` | 1.0 | trace 落库采样；error/degraded 恒必存 |
| `observability_prompt_capture_mode` | sampled | disabled / sampled / always |
| `observability_prompt_sample_rate` | 0.2 | 快照采样率（满足"禁止默认保存全部生产 Prompt"） |
| `observability_llm_cost_json` | {} | 模型单价表；空则 cost_estimate 为 null |
| `observability_*_retention_days` | 7 / 3 / 14 / 30 | 四表各自的 TTL |

测试默认关闭持久化：`tests/conftest.py` `os.environ.setdefault("OBSERVABILITY_PERSIST_ENABLED", "false")`（与 EVALUATION_ENABLED 同模式）；需要持久化的测试用 `override_settings` 显式开启。

## 7. 验收底线（全局）

- 既有全量测试（963）零回归；`tests/golden/` prompt 金样**字节不变**——这是"没改行为"的机器可证证据。
- 聊天热路径不出现任何新增 await / DB IO（013 性能护栏测试固化）。
- debug API 全部只读；非 debug 端点响应体不出现观测字段。
