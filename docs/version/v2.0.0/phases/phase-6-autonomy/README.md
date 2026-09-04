# Phase 6 — Advanced Autonomy

> Flag：`v2_autonomy_advanced_enabled`（总闸）
> 依赖：Phase 5（调度与执行底座）、Phase 3（Personal Goal 由 Belief/Pattern 供给）

## 目标

角色追求目标：

```text
Goal → Planning → Sub-Goal → Action → Observation → Adjustment
```

## 解决的问题

v1 Goal 是扁平 4 类规则列表（user_care/relationship/conversation/scene），无层级、无规划、无失败语义——角色「有目标」但不会「追求」。

## 核心能力

### 1. Goal 层级与分类

```text
维度一（时间）：short_term / long_term
维度二（域）：personal（源自 Belief/Pattern）/ relationship（源自 Relationship Patterns）
              / world（源自 World 事件）
```
既有 4 类 conversation/scene goal 保留为轮内/场景级；新层级通过 parent_goal_id 挂树。

### 2. 生命周期语义（补齐任务书 §二十三要求的全部裁决）

| 状态 | 语义 |
|---|---|
| Priority | 显式层级优先级 + Development/Relationship 调制；冲突时高优先级抑制低优先级（有 trace，不删除） |
| Conflict | 同域冲突目标并存时仲裁：取优先级高者 active，另一 suspended 留痕 |
| Persistence | long_term 目标跨会话存续，只有显式完成/放弃才终结 |
| Failure | Sub-Goal 连续失败达阈值 → goal 转 failed，记录 failure_reason，可降级重规划 |
| Completion | 观察确认达成 → completed，产出 experience 转写记忆 |
| Abandonment | 长期无进展 + 低相关 → abandoned（需 confidence 判定 + trace），不静默消失 |

### 3. Planning 与观察调整

- Planning（LLM，低频）：仅在 goal 创建/受阻/重规划时调用；产出 Sub-Goal 树（每步有完成判据）。
- Observation（规则）：每周期检查 Sub-Goal 完成判据（复用 Action 结果与 World 状态）。
- Adjustment（规则 + 低频 LLM）：按观察调整顺序/拆分/放弃。

## 明确禁止

- 不做自主无限规划（Sub-Goal 深度 ≤ 2，数量 ≤ 5/树）。
- Goal 不写 Scene/Memory/World（沿 v6 铁律）；对 World 的影响只能通过 Action。
- Planning 结果必须可执行性校验（Capability 是否支持）才入库。

## 文档

- [tasks.md](tasks.md)（AUT-001 ~ AUT-005）

## 完成标准

1. 一个长期目标可跨 3+ 会话拆解执行并被观察调整（离线剧情测试）。
2. 冲突目标按优先级仲裁且全程有 trace；失败/放弃路径状态正确且用户可见影响合理。
3. Planning LLM 频率 ≤ 阈值（默认每 goal 生命周期 ≤ 3 次，可配）。
4. Flag 关闭时 Goal 行为与 v1 一致。
