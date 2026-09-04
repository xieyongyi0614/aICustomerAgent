# Phase 3 Evaluation — Character Development

> Gate 未全过不得申请开启 `v2_development_enabled`。

## 指标与门槛（Eval Gate）

| ID | 指标 | 测法 | 门槛 |
|---|---|---|---|
| E-DEV-01 | 编译一致性与归因 | 同 Insight 重复编译幂等；development_changes 100% 可溯 insight_id | 100% |
| E-DEV-02 | 调制可见性与封顶 | Insight 生效后行为参数 before/after 在 trace 可见；幅度不超强度×预设封顶 | 100% |
| E-DEV-03 | 矛盾仲裁与回退 | 矛盾 Insight 只一个生效；反驳后回退基线；重放=在线 | 100% |
| E-DEV-04 | 成长闭环归因（DEV-006） | 三周期剧情：调制→新经历→再反思→调制演进，全程归因链完整 | 闭环成立且无越级影响 |

## P3 专属场景

- 「用户偏好简短回复」→ ResponseStyle 长度预算下降（对话可感知）。
- 「用户持续工作压力」→ 关心话题权重↑、深夜关怀 habit 候选激活。
- 过度调制防护：同主题 10 条强化 Insight → 调制幅度仍封顶。
- Flag OFF：Development 冻结，行为与 v1 字节级一致。

## Regression Gate

见 [regression-checklist.md](regression-checklist.md)。
