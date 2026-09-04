# Roleplay V7.8：Character Runtime Intelligence Layer

> 状态：**设计完成，待实现**。任务入口 tasks.md。前置：V1~V7.5 全部完成。
> 设计原则：**观测层是旁路**——只读 Runtime，不修改 Goal / Memory / Emotion / Behavior / Autonomy / Evaluation 的任何行为；观测自身失败只降级，绝不影响任何一次已产出的回答。

## 1. V7.8 解决什么问题

V7.5 为止，系统已具备完整的角色能力栈与质量评估闭环，但这条管线仍是**黑盒运行**——出了问题只能靠读代码猜。V7.8 建立 Runtime Intelligence Layer，让以下问题可以被直接回答：

```text
1. 为什么角色这样回复？      → Runtime Trace：完整步骤链 + 每步输入输出摘要
2. 哪个模块导致异常？        → TraceStep status/error 定位到具体步骤
3. 哪个状态发生变化？        → TraceEvent：情绪/模式/目标/关系 before → after
4. 哪个 Prompt 影响模型？    → Prompt Snapshot：最终 messages + 各 section 预算占用
5. 为什么主动行为触发了？    → Decision History：trigger → policy → action 全过程
6. 为什么 Evaluation 分低？  → Evaluation Correlation：报告反查当轮运行现场
```

V7.5 评估回答"这个回复**好不好**"，V7.8 回答"它**为什么**是这样"——评估是质量观测，V7.8 是过程观测；V7.8 不重复评估，只提供过程数据并把两者接起来。

## 2. 硬边界（V7.8 明确不做）

- **不改变任何 Runtime 行为**：Goal / Memory / Emotion / Behavior / Autonomy / Evaluation 六大系统零修改语义；所有挂载点都是"调用返回后的只读记录"。
- **不进入热路径**：一切持久化都是 turn 收尾后的 write-behind 后台任务；聊天关键路径零新增 IO、零新增 await。
- **不改模型调用逻辑**：LLM 记录发生在调用返回之后（读 usage / 结果对象），不包装请求、不改写 messages。
- **不默认保存生产 Prompt**：快照默认 sampled 模式（低采样率），支持关闭；字符上限 + 短 TTL。
- **不做自动调优**：只产出数据与查询，不自动改 prompt / 策略 / 配置（V8+）。
- **不上用户侧**：所有能力只在 `/api/v1/debug/*` 暴露。
- **不引入新机制**：不加 event bus / LangGraph / Workflow Engine / 新 Agent；复用现有 fire-and-forget asyncio task 与 post_process 扩展点形态。

## 3. 核心设计一览

| 模块 | 职责 | 核心载体 | 落点 |
|---|---|---|---|
| M1 Runtime Trace | 一次角色运行的完整步骤链与状态事件 | RuntimeTrace / TraceStep / TraceEvent | 演进现有 `trace_collector`（内存 LRU）+ 新增 `runtime_traces` 持久化 |
| M2 Decision History | 自治与目标决策过程（trigger→policy→action） | DecisionRecord | `decision_records` 表 |
| M3 Prompt Debug | 最终发给 LLM 的上下文快照 | PromptSnapshot | `prompt_snapshots` 表，采样 + 上限 + 短 TTL |
| M4 LLM Observability | 每次模型调用的延迟 / token / 成本 / 错误 | LlmCallRecord | `llm_call_records` 表 |
| M5 Performance Metrics | 管线 / 质量 / 业务三类指标 | MetricReport | **派生不建表**（沿用 V7.5 聚合先例），按需计算 |
| M6 Evaluation Correlation | 评估报告 ↔ 运行现场互查 | CorrelationBundle | 关联键（turn_id 主、request_id 辅）+ bundle API |

六个模块共享同一条纪律：**采集在调用后、持久化在收尾后、失败只降级**。

## 4. 与现状的关系（不重写，只补全）

现有 `app/services/trace_collector.py` 已具备 V7.8 的一半骨架：`TurnTraceSession`（request_id、26 个步骤、token_usage、TTFT）、`TraceCollector`（内存 LRU，容量 20）。V7.8 对它是**演进而非替换**：

```text
现状（V7.5 为止）：
chat_pipeline ──trace= 直调埋点──→ TurnTraceSession ──snapshot──→ 内存 LRU(20) ──→ /debug/turns/{id}/trace
                                                        （重启即失，主动行为无 trace）

V7.8 之后：
chat_pipeline ──trace= 埋点（不变）──→ TurnTraceSession（不变，热路径）
                                        │ turn 收尾（attach 处，+1 行调度）
                                        ▼
                              ObservabilityFacade（采样/开关判定，write-behind）
                                        ├─→ runtime_traces      （M1 持久化）
                                        ├─→ llm_call_records    （M4，随行 flush）
                                        └─→ prompt_snapshots    （M3，随行 flush）
autonomy_engine / proactive_executor ──只读结果──→ decision_records（M2）+ proactive trace（008）
evaluation_reports ──meta.request_id + turn_id 关联──→ /debug/turns/{id}/correlation（M6）
```

## 5. 文档导航

- [architecture.md](architecture.md) — 总体架构：分层归属、挂载点清单、失败契约、开关矩阵（先读这篇）
- [runtime-trace.md](runtime-trace.md) — M1：TraceContext / TraceStep / TraceEvent / TraceStorage 四概念
- [decision-history.md](decision-history.md) — M2：决策记录模型与采集点
- [prompt-debug.md](prompt-debug.md) — M3：快照采集、查看 / 比较 / 定位
- [llm-observability.md](llm-observability.md) — M4：调用记录、token / 成本核算
- [metrics.md](metrics.md) — M5：管线 / 质量 / 业务三类指标口径
- [evaluation-correlation.md](evaluation-correlation.md) — M6：关联键、bundle API、低质量下钻
- [persistence.md](persistence.md) — 数据分类、表结构、TTL / 采样 / 隐私
- [testing.md](testing.md) — 测试分层 + `tests/v7.8/` 五套件
- [tasks.md](tasks.md) — 任务注册表（V7.8-001 ~ 015）

## 6. 关键架构事实

```text
1. 现有 TurnTraceSession 是内存 LRU（容量 20），易失——V7.8 给它加持久化旁路，不重写它。
2. 所有持久化都是 turn 收尾后的后台任务（复用 post_process.background_tasks 形态），
   热路径零新增 IO；测试 teardown 已有等待后台任务的机制可复用。
3. 关联主键天然同源：trace.turn_id = evaluation subject_id = AI 消息 id；
   request_id 已存在于 TurnTraceSession，V7.8 把它补写进评估 meta 形成双键。
4. structured.py 是全部辅助链（7 条）的统一拦截点；answer_chain 是唯一已有
   token 统计的调用点——LLM 记录共 4 个采集点，全部在调用返回之后。
5. 指标按需派生不建表（V7.5 聚合视图先例）；P2 才引入可选周期快照表。
6. 一切阈值与开关进 settings `observability_*` 组（沿用 evaluation_* 惯例）；
   测试默认关闭持久化（setdefault），既有 963 测试零回归是每个 Task 的底线。
```
