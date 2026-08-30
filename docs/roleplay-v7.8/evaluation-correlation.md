# M6 Evaluation Correlation

> 目标：把 V7.5 评估报告接回运行现场——低分回复不再只是分数，而是可下钻的完整案卷。
> V7.5 评估是观察者，V7.8 也不改变它：关联只做两件事——补一个关联键、加一组只读查询。

## 1. 关联键

```text
主键：turn_id（= AI 消息 id）
  trace.turn_id == evaluation_reports.subject_id（subject=turn）
  == prompt_snapshots.turn_id == llm_call_records.turn_id
辅键：request_id
  trace.trace_id 天生持有；007 把它补写进 evaluation_reports.meta["request_id"]
  （meta 是 JSON 列，不加列不改约束，评估行为零变化）
主动侧：action_id（= proactive_actions.id）
  决策记录 / proactive trace / subject=proactive_action 报告三方同源
```

补写 request_id 进 meta（`evaluation_engine.py` 落库前一处）是 V7.5 侧唯一触碰点：多一个 JSON 键，不改变分数、verdict、采样与任何既有读取方。

## 2. CorrelationBundle：一次拿全运行现场

`GET /api/v1/debug/turns/{turn_id}/correlation`（007）：

```json
{
  "turn_id": "4182",
  "request_id": "9f3c…",
  "trace":       { "…runtime_traces 最新一条…": "steps/events/token/model" },
  "evaluation":  { "…evaluation_reports 最新一条…": "scores/issues/verdict/digest" },
  "prompts":     [ {"call_site": "answer", "section_budget": {}, "…": "…" } ],
  "llm_calls":   [ {"call_site": "answer", "latency_ms": 2100, "…": "…"} ],
  "decisions":   [ {"kind": "turn_goal", "decision": "…", "reason": "…"} ]
}
```

各部分缺席则 null / 空数组（持久化各自独立采样，不要求齐备）；全部缺席 404（与既有 debug 端点语义一致）。`GET /debug/proactive/{action_id}/correlation`（008）同构。

## 3. 正向用例：为什么 emotion_score 0.4

```text
1. GET /debug/turns/{id}/correlation
2. evaluation.issues = [TEXT_STATE_CONFLICT]（emotion 维）
3. trace.events → emotion_change: before=neutral, after=sadness(0.9), trigger=weak
4. trace.steps → state_update 410ms ok；turn_analysis 310ms ok
5. prompts[answer].section_budget → emotion section 220 字符，未裁剪
6. llm_calls[answer] → 输入 8.2k token，模型 glm-4.7
→ 结论链完整可见：分析产出弱触发 → 状态引擎允许切换 → judge 判定过度。
   V7.8 只呈现链条，是否调整规则/钳制留给 V8+。
```

## 4. 反向用例：找出所有低质量回复（012）

`GET /debug/evaluations?verdict=fail&dimension=emotion&window_hours=168&limit=20`
`GET /debug/evaluations?issue_code=FABRICATION_CONFIRMED&include=correlation`

- 列表页轻量（subject_id / scores / verdict / issue codes / created_at）；
- `include=correlation` 时逐条内联 bundle（或返回 correlation 链接按需取）；
- 服务于回归复盘："最近一周 fail 的轮次，trace 都卡在哪个步骤 / prompt 都裁掉了什么"——把 V7.5 报告变成可批量分析的数据集。

## 5. request_id 的端到端贯通（007）

```text
TurnTraceSession.request_id（既有，生成于 t0）
  ├─ done 事件已携带（现状）→ 前端可显示
  ├─ H8 middleware：响应头 x-request-id（新增，日志/抓包对账）
  ├─ runtime_traces.trace_id（002）
  ├─ llm_call_records / prompt_snapshots / decision_records.request_id（002~005）
  └─ evaluation_reports.meta["request_id"]（007 补写）
```

一份 request_id 串起评估报告、trace、prompt、LLM 调用、决策五类记录；评估的 judge 确定性采样（request_id 哈希）也由此可复盘"这轮为什么被采样"。

## 6. 边界

- 不改 EvaluationReport 域模型、不改表结构（meta 补键除外）、不改分数与采样语义。
- correlation API 是纯拼装：按 turn_id/action_id 各仓储各查最新/列表，聚合逻辑不建立新的派生表。
- 评估缺席（未采样 / 未开评估）时 bundle 照常返回其余部分——关联不依赖评估存在。
