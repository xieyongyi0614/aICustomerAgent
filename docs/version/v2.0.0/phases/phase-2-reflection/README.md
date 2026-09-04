# Phase 2 — Reflection

> Flag：`v2_reflection_enabled`（总闸）
> 依赖：Phase 1（Evidence 全部来自 Memory 2.0 检索）｜被依赖：Phase 3（唯一 Insight 来源）

## 目标

角色能从记忆中形成认知：

```text
Experience(已沉淀记忆) → Evidence → Reflection → Insight
（带 confidence / source / scope / created_at，可 invalidated / superseded）
```

## 解决的问题

1. v1 无任何「经历→认知」通道，角色没有「看法」，只有阈值数值。
2. 任务书红线的「AI 自嗨」风险：无证据结论直写角色真相——本 Phase 的核心设计就是防这个。

## 核心能力

1. **Evidence Window**：按主题聚合时间窗内的相关记忆（数量、时间跨度、来源多样性、相互印证度）。
2. **反思触发**：周期（每日低频）+ 事件触发（同主题记忆强化达阈值）；证据不足直接跳过，0 LLM。
3. **Insight 模型**：statement + type（belief/preference/pattern）+ confidence + evidence_links + scope（user/relationship/world）+ 生命周期（active/superseded/invalidated）。
4. **防幻觉三闸**：证据数量门槛（默认 ≥3 独立来源）、置信度阈值、结论类型约束（结论不得超出证据可支撑范围——prompt 层约束 + Judge 抽查）。
5. **Insight 生命周期**：被新证据反驳 → invalidated；被更强结论替代 → superseded；反驳走反思通道本身。

## 明确禁止

- Insight 不得直写 CharacterState/Relationship 数值（数值域只被 Development 在 P3 调制）。
- 反思不得写 Memory（认知与记忆分层，防止反思自我强化）。
- 不得用单条记忆生成 Insight（最少证据数是硬闸）。

## 文档

- [architecture.md](architecture.md)
- [tasks.md](tasks.md)（REF-001 ~ REF-006）

## 完成标准

1. 构造重复证据（用户 10 天内 5 次说累）→ 产出正确 Insight 且带 ≥3 条证据引用。
2. 证据不足/噪声场景 → 0 Insight 产出、0 LLM 调用（门槛前拦截）。
3. 用户澄清反驳后 Insight 被 invalidated，后续不再影响任何域。
4. Flag 关闭时全链路旁路，v1 行为不变。
