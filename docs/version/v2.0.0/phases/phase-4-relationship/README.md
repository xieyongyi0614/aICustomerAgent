# Phase 4 — Long-term Relationship

> Flag：`v2_relationship_evolved_enabled`（总闸）
> 依赖：Phase 1（关系叙事记忆）、Phase 3（Pattern 供给）｜被依赖：Phase 5（关系闸门已有）

## 目标

关系从「数值 Current State」升级为：

```text
Relationship State（V8.5 六维+stage，复用）
  + Relationship History（events/milestones/conflicts，已有）
  + Shared Experiences（共同经历投影，新）
  + Patterns（关系模式，来自 Development）
  + 叙事级关系记忆（统一真相源落地）
```

## 解决的问题

1. **关系事实双真相源**（v1 遗留债）：Memory 的 `relationship_event` 类型 vs `relationship_events` 账本。v2 裁决：**数值与增量归账本；叙事事实归 Memory `relationship_fact` 类型；查询在 Relationship 域内收敛**。
2. 关系没有「共同经历」层：知道数值多高，但说不出「我们一起经历过什么」。
3. Trust/Affection 等维度的表达：**保持数值维度为 State**（已有 6 维），不新增 0~1 数值指标；「模式」类洞察走 Insight/Development 通道，不数值化。

## 核心能力

1. **Shared Experience 视图**：对 Memory(experience/relationship_fact) + relationship_events + world_events 的 SQL/服务投影——「第一次旅行」「一起完成的事」，非新表。
2. **叙事记忆转写**：重要关系事件（里程碑达成、冲突解决、首次共同经历）由后台转写为 relationship_fact 记忆（经 P1 摄取通道，幂等）。
3. **Relationship Patterns**：从 Development patterns 中 scope=relationship 的条目读取，注入 Context 关系段与 Autonomy 闸门参考。
4. **里程碑 v2**：V8.5 12 项数值里程碑保留 + Insight 触发的叙事里程碑（如「第一次一起熬夜赶工」），走 P1 milestone_event 类型。

## 明确禁止

- 不改 V8.5 数值引擎数学（D1/D2/D3/D5、限速、迟滞）。
- 不新增 trust/affection 之类的新数值维度。
- 不做 Relationship→Memory→Relationship 的写环（Relationship 永不写 Memory，转写由摄取器完成）。

## 文档

- [tasks.md](tasks.md)（REL-001 ~ REL-004）

## 完成标准

1. 任一关系事实可回答「存在哪张表、为什么存在」（单一真相源审计通过）。
2. Shared Experience 数量随真实交互增长、可检索进 Context（有预算段）。
3. V8.5 数值回归：evolve() 输出与 v1 字节级一致（数学零改动证明）。
4. Flag 关闭时关系行为与 v1 一致。
