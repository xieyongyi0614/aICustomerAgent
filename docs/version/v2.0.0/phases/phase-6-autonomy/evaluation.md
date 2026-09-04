# Phase 6 Evaluation — Advanced Autonomy

> Gate 未全过不得申请开启 `v2_autonomy_advanced_enabled`（= v2.0.0 全量）。

## 指标与门槛（Eval Gate）

| ID | 指标 | 测法 | 门槛 |
|---|---|---|---|
| E-AUT-01 | 规划质量与封顶 | 产物 100% 过可执行校验、判据可判定；LLM ≤3 次/goal；深度≤2、数量≤5 | 100% |
| E-AUT-02 | 观察/失败语义 | 判据达成自动推进；连续失败→failed 不无限重试；单 goal 最长周期封顶 | 100% |
| E-AUT-03 | Goal Consistency | 目标不无故消失/翻转；冲突仲裁留痕；abandonment 有置信依据 | 100% |
| E-AUT-04 | 追求闭环（剧情） | 长期目标跨 3+ 会话拆解执行并被观察调整 | 剧情通过 |

## P6 专属场景

- 跨会话剧情：长期目标 → Sub-Goal → 执行 → 观察 → 调整 → 完成/失败/放弃三分支。
- 冲突剧情：personal 与 relationship 目标同域冲突 → 优先级仲裁 trace。
- 预算剧情：第 4 次规划请求被拒；Sub-Goal 失败达阈值不再重试。

## Regression Gate

见 [regression-checklist.md](regression-checklist.md)。**V6/V7 checklist 重跑 + 全量 Flag ON/OFF 双态对比。**
