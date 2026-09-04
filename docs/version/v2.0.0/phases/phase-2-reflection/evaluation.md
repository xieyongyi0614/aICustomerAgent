# Phase 2 Evaluation — Reflection

> Gate 未全过不得申请开启 `v2_reflection_enabled`。

## 指标与门槛（Eval Gate）

| ID | 指标 | 测法 | 门槛 |
|---|---|---|---|
| E-REF-01 | Insight 质量证据引用率 | 每条 Insight 的 evidence_links 完整性 + Judge 评（结论不超证据范围） | 100% 带引用；Judge 通过率 ≥0.9 |
| E-REF-02 | 证据门槛有效性 | 构造「5 次说累」→产出且带 ≥3 证据；孤立/噪声 →0 产出 | 100% |
| E-REF-03 | 误报率（Reflection 幻觉防线） | 噪声记忆场景集 →0 Insight 0 LLM | 100%（0 误报） |
| E-REF-04 | 反驳失效有效性 | 「其实我不累」→对应 Insight invalidated 且退出 Context 且 DEV 收到事件 | 100%；误失效率=0 |
| E-CTX-01 | Insight 注入合规 | 高置信注入、invalidated 即时退出、预算内 | 100% |

## P2 专属场景

- 压力聚合：10 天内 5 次加班/说累/晚睡/取消出门 → 「用户可能处于持续工作压力中」（带证据引用）。
- 反例护栏：证据中混入反例记忆 → 结论必须降级或拒绝。
- 成本：给定无证据月，反思 LLM 调用 = 0。

## Regression Gate

见 [regression-checklist.md](regression-checklist.md)。
