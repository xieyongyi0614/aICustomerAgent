# Roleplay V6：Character Goal & Intention

> 状态：**设计完成，待实现**。任务入口 `tasks.md`。前置：V1~V5 + Backend Refactor 全部完成。

## 1. V6 解决什么问题

V1~V5 已让角色知道「自己是谁（Character）、现在发生什么（Scene）、过去发生什么（Memory）、现在感觉怎样（Emotion）、和用户关系如何（Relationship）」。

V6 补上缺失的两块：

```text
Goal       角色想要什么（动机层，跨轮次）
Intention  角色这一轮打算做什么（决策层，单轮次）
```

核心升级：

```text
V5：User Message + State → Response          （反应式）
V6：State + Goal + Intention → Response      （动机式）
```

回答的不再是"我没事呀"，而是基于「当前目标 + 这一轮意图 + 自身状态」的"为什么这么回应"。

## 2. 设计边界（V6 明确不做）

- 不做 Autonomous Behavior / Scheduler / Background Agent / Tool Calling / World Simulation / NPC / 复杂 Action Execution（V7+）。
- 不做"角色主动发消息"。
- 不做完整思维链输出——只保存结构化 decision reason（见 intention-model.md §6）。

## 3. 核心设计一览

| 概念 | 层级 | 生命周期 | 持久化 | 决策者 |
|---|---|---|---|---|
| Persistent Goal | 动机层 | 长期，随版本/角色定义 | goals 表，source=definition | 代码种子（角色资产） |
| Current Goal | 动机层 | 小时~天级 | goals 表，horizon=current | 代码策略（事件触发创建/完成/过期） |
| Intention | 决策层 | 单轮 | trace + turn_meta（不建表） | LLM 候选 + 代码 Policy 校验 |

文档导航：

- `architecture.md` — 接入点与数据流（基于重构后 application 编排层）
- `goal-model.md` — Goal 类型/字段/层级
- `goal-policy.md` — 生命周期规则（何时创建/完成/失效）
- `goal-selection.md` — 多 Goal 选择策略（tier + 上下文修正）
- `goal-conflict.md` — 冲突消解（陪伴 vs 劝休的裁决）
- `intention-model.md` — Intention 枚举与有效性规则
- `intention-selection.md` — Selector（LLM）+ Policy（代码）双阶段
- `goal-context.md` — Prompt 注入格式与 Token 预算
- `persistence.md` — 持久化边界与 turn_meta
- `testing.md` — 测试矩阵与回归要求
- `tasks.md` — V6-001~011 任务注册表
