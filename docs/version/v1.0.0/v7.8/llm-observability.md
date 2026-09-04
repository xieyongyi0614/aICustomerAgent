# M4 LLM Observability

> 目标：记录每次模型调用的 Model / Provider / Latency / TTFT / Tokens / Cost / Error，支持 Router / Generation / Judge 多模型分视角。
> 边界：记录发生在**调用返回之后**（读结果对象的 usage），不包装请求、不改写 messages、不新增重试——模型调用逻辑零修改。

## 1. LlmCallRecord 域模型

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | uuid hex |
| request_id | str \| None | 关联 trace；后台任务（judge / 主动评估）可为空 |
| turn_id | str \| None | 关联评估主体 |
| call_site | CallSite | 与 M3 同枚举：answer / router / turn_analysis / … / judge |
| profile_id | str | `LLM_PROFILES_JSON` 中的 profile id（如 longcat） |
| model | str | ChatOpenAI 实际模型名 |
| provider | str | 从 profile `base_url` 提取 host（openrouter / longcat / minimax / …） |
| status | str | ok / error |
| latency_ms | int | 调用总耗时 |
| ttft_ms | int \| None | 仅 answer 流式链路（chat_pipeline 既有 `first_token_ms` 复用） |
| input_tokens / output_tokens / total_tokens | int \| None | usage_metadata；链路拿不到就为 null，不估算 |
| cost_estimate | float \| None | 单价表计算；无单价配置则 null |
| error_kind | str \| None | 异常类型名（有界 200 字符），不存堆栈 |
| started_at / created_at | datetime | |

## 2. 采集点清单（全部调用点覆盖）

| 调用点 | 文件 | 现状 | V7.8 采集方式 |
|---|---|---|---|
| 生成（流式） | `app/chains/answer_chain.py:27` | **已读** `usage_metadata` 累加进 trace（:42-50） | 同一数据外发一份构造记录；TTFT 复用 chat_pipeline 既有 `first_token_ms` |
| 全部结构化链（7 条：router / turn_analysis / scene_intent / intention / scene_update / state_update / extractor）+ judge | `app/chains/structured.py::build_structured_chain` | judge 在 trace.extra 记了 model_name，其余不记 | **统一拦截点**：主链与降级链返回后读 `usage_metadata`（AIMessage 标准字段），构造记录 |
| 汇总链 | `app/chains/summary_chain.py:14` | 不记 | 调用返回后读 usage |
| 主动生成链 | `app/chains/proactive_chain.py:38` | 不记 | 同上 |

`build_structured_chain` 一个点覆盖 8 类调用，是本模块低成本的关键；answer/summary/proactive 三处是普通链各自补一个"返回后读取"调用。

## 3. 成本核算

```text
settings.observability_llm_cost_json（默认 {}）：
{
  "glm-4.7":  {"input_per_mtok": 0.6, "output_per_mtok": 2.2},
  "minimax-m3": {"input_per_mtok": 0.3, "output_per_mtok": 1.1}
}

cost_estimate = input_tokens × input_per_mtok / 1e6
              + output_tokens × output_per_mtok / 1e6
```

- 按 `model` 名匹配（profile 可换 key 不换模型）；未配置的模型 → null，绝不猜测单价。
- 单价表是配置不是代码；cost_estimate 字段名带 estimate，明确它不是账单。

## 4. 持久化与查询

- 表：`llm_call_records`（迁移 0014），**每次调用一行**（行小，~300B，不采样全量记，TTL 30 天——这是四张观测表里唯一"全量 + 长寿"的，因为它同时是 M5 成本/延迟指标的原料）。
- turn 内调用随 `on_turn_finished` 批量 flush（后台 judge 调用在调用点直接交 Facade）。
- 查询：
  - `GET /debug/llm-calls?request_id=` / `?turn_id=` / `?window_hours=&call_site=&model=` — 明细
  - `GET /debug/llm-calls/summary?window_hours=24` — 按 call_site / model 聚合（次数、token、成本、错误率、p50/p95 延迟）——M5 的 LLM 视角即由本端点承载聚合逻辑

## 5. 多模型视角

LLM_PROFILES 已支持多模型（请求级 profile 切换 + judge 独立 profile）。记录按 `(call_site, model)` 天然分组：

```text
answer      生成模型（用户请求指定或默认 profile）
judge       评估裁判模型（evaluation_judge_profile，V7.5 既有配置）
router / turn_analysis / …   辅助分析模型（随请求 profile）
```

回答"judge 比生成模型贵多少 / 换模型后延迟变化"只需按此分组聚合，无需新字段。

## 6. 边界

- usage 拿不到（某些 provider / 降级链路）→ token 字段 null，记录行仍落（错误率与延迟同样是观测目标）。
- 不记录 prompt 内容（那是 M3 的事，且有采样纪律）；本模块只有数值与元数据。
- 不做基于记录的任何自动动作（限流 / 换模型 / 重试都是 V8+ 的事）。
