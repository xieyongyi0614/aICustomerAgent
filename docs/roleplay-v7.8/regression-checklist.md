# Roleplay V7.8 Regression Checklist（真实模型人工回归）

> 前置：V7.8-001~013 已实现。真实模型下验证观测层"只观察不改变行为"，并完成一次低分回复下钻演练。
> 组织方式沿用 V4 / V7.5 回归清单。执行前：`alembic upgrade head`（链尾 0016），`.env` 按 §1 配置。

## 1. 开关准备

| 环境变量 | 取值 | 目的 |
|---|---|---|
| `OBSERVABILITY_PERSIST_ENABLED` | true | 全量启用持久化 |
| `OBSERVABILITY_PROMPT_CAPTURE_MODE` | always（演练期）/ sampled（常态） | 快照全量/采样对照 |
| `OBSERVABILITY_PROMPT_REDACT` | false（本机）/ true（共享演示） | 脱敏对照 |
| `OBSERVABILITY_LLM_COST_JSON` | 按实际模型填单价 | 成本指标 |
| `EVALUATION_ENABLED` | true | 质量指标与 correlation 素材 |

## 2. 不影响行为核对（V2~V7.5 主观回归）

| # | 场景 | 轮次 | 核对点 | 结果 |
|---|---|---|---|---|
| 1 | 日常聊天（V2/V3 人设与场景） | 10 | 回复风格/动作连续性与 V7.5 基线无差异；流式无卡顿 | ☐ |
| 2 | 长程记忆（V4） | 5 | 提及旧事实正常；`/debug/turns/{id}/prompts` 可见记忆段 | ☐ |
| 3 | 情绪/关系（V5） | 6 | 情绪变化自然；trace events 出现 emotion_change before/after | ☐ |
| 4 | 目标/意图（V6） | 4 | 行为有动机；decisions 出现 turn_goal/turn_intention | ☐ |
| 5 | 主动行为（V7） | 闲置 35min+ | 主动消息正常；decisions 有 act→delivered；不影响等待期聊天 | ☐ |
| 6 | 评估（V7.5） | 随 2~5 | 评估报告照常落库；`meta.request_id` 非空 | ☐ |
| 7 | 异常路径 | 拔 key/断网一次 | 聊天错误提示与 V7.5 一致；`runtime_traces` 出现 status=error 行 | ☐ |

## 3. Debug API 抽查

| 端点 | 期望 |
|---|---|
| `GET /api/v1/debug/turns/{turn_id}/trace` | 内存 miss 后可从 DB 回退（重启后端再查同 turn_id） |
| `GET /api/v1/debug/traces/{request_id}` | 与 `x-request-id` 响应头一致 |
| `GET /api/v1/debug/turns/{turn_id}/prompts` | answer 快照 section_budget 合理（total ≤ budget） |
| `GET /api/v1/debug/prompts/compare?a=&b=` | 相邻两轮 diff 反映真实差异（如 memory 段变化） |
| `GET /api/v1/debug/llm-calls?turn_id=` | answer 行有 TTFT；judge 行 status=ok |
| `GET /api/v1/debug/llm-calls/summary?window_hours=24` | 分 call_site 汇总，错误率与实际一致 |
| `GET /api/v1/debug/decisions?user_id=` | deny 记录 reason 可解释"为什么不主动" |
| `GET /api/v1/debug/metrics?window_hours=24` | 四视角数字与体感一致；无 NaN/null 崩溃 |
| `GET /api/v1/debug/evaluations?verdict=fail&include=correlation` | 每行可下钻到 trace/prompts/llm_calls |

## 4. 低分回复下钻演练（V7.8 核心价值）

1. 构造一次低分场景（如：无触发情绪跳变 / 引述未提供过的信息）。
2. `GET /debug/evaluations?verdict=fail&include=correlation` 找到该轮。
3. 沿 bundle 核对：评估 issue → trace steps/events（emotion_update / emotion_change before→after）→ answer 快照 section_budget（是否被裁剪）→ llm_calls（模型与延迟）→ decisions（当轮目标）。
4. 记录：能否在 5 分钟内回答"为什么分低"。☐

## 5. 体量与保留观察

- 运行 1 小时后核对行数：`runtime_traces ≈ turn 数`、`llm_call_records ≈ LLM 调用数`、`prompt_snapshots ≈ 采样比例 × 调用数`。
- 手动把 `observability_*_retention_days` 临时调 0 并触发清理（重启或等待循环），确认过期行被清、当前数据无损。☐

## 6. 已知边界（人工回归时注意）

- trace 行的 `evaluation_judge` 步骤可能在 flush 之后完成，属预期（评估报告本身独立落库）。
- prompt 快照为 sampled 时部分轮次无快照属预期；需要全量时切 `always`。
- 014（Metrics 周期快照落库）未实现，`/debug/metrics` 为实时派生。
