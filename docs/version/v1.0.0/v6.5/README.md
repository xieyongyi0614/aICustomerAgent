# Roleplay V6.5：Character Behavior Refinement

> 状态：**设计完成，待实现**。任务入口 `tasks.md`。前置：V1~V6 全部完成。
> 设计原则：**Behavior 不生成内容**——行为层只产出约束、策略、预算与方向，最终文本仍由 LLM 生成。

## 1. V6.5 解决什么问题

V6 让角色知道了「为什么这么回应」，但真实测试暴露：知道了为什么，仍然不知道**怎么表现**——

```text
V6：  Goal → Intention → Response            （知道做什么，表现全凭 LLM 现场发挥）
V6.5：Goal → Intention → Behavior Strategy
      → Policy/Habit/Budget → Response       （表现方式由代码锚定，LLM 在收窄空间内表达）
```

四个真实症状对应四个缺口：动作描写过度（无预算）、风格逐轮漂移（无策略层）、习惯不稳定（无长期倾向定义）、当前活动凭空消失（活动只存储不表现）、mode 逐轮跳变（模式不持久化）。

## 2. 硬边界（V6.5 明确不做）

- 不重新设计 V5/V6 Runtime——全部走 chat_pipeline / post_process 既有缝，零新增 LLM 链。
- 不做输出侧拦截/重写——NDJSON 流式透传架构下预算只能事前注入（action-budget.md §2）。
- 不引入第二套模式枚举——基调由 Strategy 表达，Mode 只持久化 RoleMode 三值（conversation-mode.md §1.2）。
- 不做活动世界模拟——Activity 复用 V3 SceneState，只加表现层（activity-state.md §5）。
- 不做 V7 Autonomy——主动行为的时机问题独立演进；V7 主动消息可复用本层渲染。

## 3. 核心设计一览

| 概念 | 职责 | 形态 | 持久化 |
|---|---|---|---|
| BehaviorPolicy | 角色通常如何行动（stage×mood 参数表） | 角色资产常量 | 代码 |
| Habit | 长期行为倾向规则（条件→短句） | 角色资产常量 | 代码 |
| BehaviorStrategy | 这一轮用什么方式表现（12 值） | 纯函数：intention 映射+白名单修饰 | trace/turn_meta |
| ActionBudget | 本轮动作/情绪/接触上限 | 纯函数：7 步预算表 | trace/turn_meta |
| Activity 表现层 | 正在做的事影响回复 | 复用 V3 字段的纯函数分类 | scene_state（已有） |
| ConversationMode | RoleMode 会话级持久化+迟滞稳定 | 纯函数稳定器 5 规则 | conversations 表 +2 列（迁移 0010） |
| Response Style Controller | 全部产出渲染为 prompt 段 | 渲染模块，非模板系统 | — |

文档导航：

- `architecture.md` — 接入点与数据流（chat_pipeline 既有缝内三处改动）
- `behavior-model.md` — 六概念三层职责总分类学（先读这篇）
- `behavior-policy.md` — Module 1 角色行为策略（含四问四答）
- `behavior-strategy.md` — Module 3 表现策略层（12 值枚举 + 修饰白名单 + V2 收编）
- `action-budget.md` — Module 2 动作预算（流式架构约束 + 7 步预算表）
- `habit-system.md` — Module 4 习惯系统（7 条亚丝娜习惯 + 冲突裁决）
- `activity-state.md` — Module 5 活动状态（复用 V3 决策 + 表现层三件事）
- `conversation-mode.md` — Module 6 模式持久化（迟滞稳定器 R1~R5）
- `response-controller.md` — Module 7 表现渲染（prompt 接入点 + token 预算）
- `persistence.md` — 持久化边界 + 迁移 0010 提案
- `testing.md` — 14 Case 测试矩阵 + golden 策略
- `tasks.md` — V6.5-001~012 任务注册表（P0×7 / P1×2 / P2×3）

## 4. 一分钟架构图

```text
gather 4 链（不变）→ intention enforce（不变）
  → mode_service.stabilize        纯函数（迟滞：连续 2 轮 + conf≥0.7 才切换）
  → behavior_engine.resolve       纯函数（intention → strategy + budget + habits）
  → PromptBuilder【表现方式】段    约束短句，非模板
  → answer_chain（LLM，不变）
  → save_turn（mode 同事务写回）→ post_process（不变，零新增步骤）
```
