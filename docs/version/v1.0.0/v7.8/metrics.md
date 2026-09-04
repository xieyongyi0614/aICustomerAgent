# M5 Performance Metrics

> 目标：管线 / 质量 / 业务三类指标，回答"哪里慢、质量走向、角色活跃度是否健康"。
> 形态：**派生不建表**（P0）——聚合器从 V7.8 四张观测表 + 既有表按需计算；可选周期快照落库是 P2（014）。

## 1. 指标源映射

```text
管线指标 ← runtime_traces.steps（M1）
LLM 指标 ← llm_call_records（M4）
质量指标 ← evaluation_reports（V7.5 既有表，零改动读取）
业务指标 ← conversations / messages / proactive_actions（既有表）+ trace status
```

V7.8 不新增任何业务侧写路径；质量指标直接消费 V7.5 的落库结果。

## 2. 三类指标口径

### Pipeline Metrics（runtime_traces.steps）

| 指标 | 口径 |
|---|---|
| step p50 / p95 | 按 step name 分组的 duration_ms 分位数（memory_retrieval / state_update / behavior_engine / llm / …） |
| e2e turn 延迟 | turn kind trace 的 duration_ms 分位数 |
| 步骤降级率 | 各 step status=degraded/error 占比 |

### LLM Metrics（llm_call_records）

| 指标 | 口径 |
|---|---|
| 延迟 / TTFT | 按 call_site 分组的 latency_ms、ttft_ms 分位数 |
| token / 成本 | sum(input/output/cost)，按 model、call_site 分组 |
| 错误率 | status=error 占比 |

### Quality Metrics（evaluation_reports，口径对齐 V7.5 OfflineEvaluator）

| 指标 | 口径 |
|---|---|
| 维度均分 | 五维 dimension mean（persona / emotion / memory / behavior / autonomy） |
| verdict 分布 | pass / warn / fail 计数与占比 |
| issue 直方图 | IssueCode 计数 top N |
| 主动行为结果 | ack 率与 LOW_OUTCOME 直方图（复用 V7.5-013 既有口径，不重造） |

### Business Metrics

| 指标 | 口径 |
|---|---|
| 会话长度 | 窗口内每会话 turn 数（messages 计数）均值 / 分布 |
| 响应成功率 | turn trace status=complete 占比（含评估降级不计失败） |
| 主动消息活跃率 | proactive_actions 状态机计数：candidate → delivered → acked / failed |

## 3. 聚合器（`app/services/observability/metrics_aggregator.py`）

纯计算模块：输入 = 各仓储查询结果，输出 = `MetricReport`（Pydantic，见下）。不碰 DB、不含时间逻辑，窗口参数由 API 层传入——聚合口径可单测固定（种子数据 → 期望数字）。

```json
GET /api/v1/debug/metrics?window_hours=24&user_id=
{
  "window_hours": 24,
  "pipeline": {"turn_count": 120,
               "step_p50_ms": {"memory_retrieval": 85, "llm": 2100},
               "step_p95_ms": {"memory_retrieval": 240, "llm": 4900},
               "e2e_p95_ms": 5200},
  "llm": {"calls": 640, "tokens_in": 1820000, "tokens_out": 96000,
          "cost_estimate": 1.23, "error_rate": 0.01,
          "by_call_site": {"answer": {...}, "judge": {...}}},
  "quality": {"reports": 118, "verdict_distribution": {"pass": 100, "warn": 15, "fail": 3},
              "dimension_mean": {"persona": 0.93, "emotion": 0.88},
              "issue_top": [{"code": "MISSED", "count": 9}]},
  "business": {"conversation_count": 12, "avg_turns_per_conversation": 10.0,
               "response_success_rate": 0.99,
               "proactive": {"delivered": 8, "ack_rate": 0.5}}
}
```

只读、无副作用、实时计算（调试台数据量级下毫秒级）；分位数用简单排序法（不引统计库）。

## 4. P2：周期快照（014）

若需要跨重启长期趋势：`metrics_snapshots` 表（迁移 0017）+ lifespan 低频循环（如每 6 小时）把 MetricReport 落一行。**P0/P1 不做**——当前单机调试台场景，实时派生足够；先验证指标口径，再决定哪些值得长期存。

## 5. 边界

- 不新增任何采集埋点：M5 是纯消费者，管线/LLM/评估/业务四路数据都来自其他模块的既有产出。
- 质量指标不改 V7.5 任何表与口径；OfflineEvaluator 的聚合函数若可复用则抽公共纯函数（放 services/observability，V7.5 侧 import 之）或平行实现，二选一以"零改动 V7.5 行为"为准。
- 指标不做告警 / 阈值判断——呈现事实，判断留给人（V8+）。
