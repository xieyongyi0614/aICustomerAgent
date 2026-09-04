# Phase 3 — Character Development

> Flag：`v2_development_enabled`（总闸）
> 依赖：Phase 2（唯一合法输入是已验证 Insight）｜被依赖：Phase 4（Pattern 供给）、Phase 5/6（Goal 调制）

## 目标

角色因经历而改变：

```text
Insight → Belief / Preference / Pattern（Development Aggregate，慢变量）
        → DevPolicy 编译 → BehaviorPolicy / Response Style / Goal 权重调制
```

## 解决的问题

1. **三个系统不得混为一谈**（任务书 §十七）：Memory 记「发生过什么」，Reflection 产出「怎么看」，Development 决定「因此变成什么样」。v1 三者皆无；本 Phase 强制分层。
2. 角色行为永不随经历变化：v1 中 BehaviorPolicy/Habit 是静态资产表。

## 核心能力

1. **Development Aggregate**：beliefs / preferences / patterns 三类慢变量，每条带来源 insight_id、生效时间、强度。
2. **DevPolicy（纯函数编译器）**：Insight → 行为参数调制。示例：
   - Insight「用户持续工作压力」→ BehaviorPolicy 关心话题权重↑、主动消息语气软化参数↑、深夜关怀 habit 激活候选。
   - Insight「用户偏好简短回复」→ ResponseStyle 长度预算↓。
3. **变更审计与重放**：development_changes 记录 before/after + insight_id；可按时间序重放重建。
4. **矛盾仲裁**：矛盾 Insight 不并存生效——按 confidence + 时间新者优先，被取代方降级留痕。

## 明确禁止

- Memory 不直接调制行为（必须经 Insight，堵「记忆→行为」捷径）。
- DevPolicy 不修改 Persona 静态资产与 V8.5/V5/V6.5 数学公式（只注入参数）。
- 不做「性格重写」类无约束演化——调制幅度按强度分级封顶。

## 文档

- [architecture.md](architecture.md)
- [tasks.md](tasks.md)（DEV-001 ~ DEV-005）

## 完成标准

1. Insight 入库后，对应行为参数变化在 trace 中可见（before/after + 溯源 insight_id）。
2. 矛盾 Insight 触发仲裁而非并存；被用户反驳后调制自动回退。
3. 0 新增 LLM 调用（DevPolicy 纯函数）。
4. Flag 关闭时 Development 冻结，行为与 v1 一致。
