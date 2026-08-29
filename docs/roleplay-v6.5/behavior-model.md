# Behavior Model

## 1. V6.5 在回答什么问题

V1~V6 让角色知道了「自己是谁、现在发生什么、过去发生什么、感觉怎样、和用户什么关系、想要什么、这轮打算做什么」。
但真实测试暴露出：**知道了为什么，仍然不知道怎么表现**。

| 症状 | 缺失的概念 |
|---|---|
| 每轮 4~6 个 `*动作描写*`，像小说旁白 | 表达预算（Action Budget） |
| 上一轮温柔照顾、下一轮主动撒娇、再下一轮过度亲密 | 表现策略（Behavior Strategy） |
| 关心别人时一会儿行动一会儿说教，全凭 LLM 现场发挥 | 长期倾向（Behavior Policy / Habit） |
| 切完西瓜被问天气，当前活动凭空消失 | 活动延续（Activity 表现层） |
| default / immersive 每轮跳变 | 会话模式持久化（Conversation Mode） |

## 2. 六个概念，三层职责

V6.5 引入的行为概念共六个，按「定义期资产 → 单轮决策 → 轮内约束」三层组织：

```text
┌─ 定义期（随角色版本，代码资产，不在运行时被修改）──────────────┐
│  BehaviorPolicy   这个角色通常如何行动（分场景的策略参数表）    │
│  HabitList        这个角色的长期习惯（条件 → 行为倾向规则）      │
└──────────────────────────────────────────────────────────┘
┌─ 单轮决策（每轮由代码解析，零 LLM）────────────────────────┐
│  BehaviorStrategy  这一轮用什么方式表现（intention 的下游）    │
│  ConversationMode  会话基调持久化（RoleMode 的稳定器）         │
│  Activity          正在做什么（复用 V3 SceneState，表现层增强） │
└──────────────────────────────────────────────────────────┘
┌─ 轮内约束（渲染进 Prompt 的硬边界）────────────────────────┐
│  ActionBudget      本轮动作/情绪/身体接触的表达预算             │
└──────────────────────────────────────────────────────────┘
```

职责一句话版：

| 概念 | 回答的问题 | 生命周期 | 持久化 | 决策者 |
|---|---|---|---|---|
| BehaviorPolicy | 这个角色通常怎么行动 | 随角色版本 | 代码资产（`app/character/asuna/behavior_policy.py`） | 角色定义 |
| HabitList | 这个角色习惯做什么 | 随角色版本（动态养成为 P2） | 代码资产（`app/character/asuna/habits.py`） | 角色定义 |
| BehaviorStrategy | 这一轮用什么方式表现 | 单轮 | trace + turn_meta，不建表 | 纯代码（intention 确定性映射 + 上下文修饰） |
| ConversationMode | 这段对话处于什么基调 | 会话级，迟滞切换 | conversations 表列 | 代码稳定器（router 候选 + 迟滞规则） |
| Activity | 角色此刻正在做什么 | 随场景 | scene_state 表（V3 已有，复用） | V3 scene_update（已有） |
| ActionBudget | 本轮最多表达多少 | 单轮 | trace，不建表 | 纯代码预算表 |

## 3. 与既有层级的关系（正交性）

```text
V5 Emotion        现在感觉怎么样      → Strategy/Budget 的修饰信号
V6 Goal           想达成什么          → Intention 的上游，V6.5 只读
V6 Intention      这轮准备做什么      → Strategy 的直接上游（映射源）
V6.5 Behavior     这轮应该如何表现    → 本版本新增
V7 Autonomy       什么时候主动行动    → 独立于 V6.5；V7 主动消息同样经 Behavior 层渲染（V7 接入，非 V6.5 范围）
```

关键边界：

- **Goal/Intention 决定「做什么」，Behavior 决定「怎么做」**。Behavior 不改变 Intention 的语义，只约束它的表达形态。
- **Behavior 不生成文本**。Strategy/Budget/Habit 全部以约束短句与方向性指令进入 Prompt，最终文本仍由 answer_chain 的 LLM 产出。
- **Emotion/Relationship 不直接改 Prompt 行**。它们是 Strategy 解析与 Budget 查表的输入，输出才进 Prompt——保持「LLM 只出信号、数值与规则全在代码」的既有哲学。

## 4. 与 V2 遗留 behavior 层的收编关系

现有 `app/models/behavior.py`（`BehaviorDecision`，7 值，由 turn_analysis 产出）与 `BEHAVIOR_INSTRUCTIONS`（【本轮行为指令】段）是 V2 时代的单轮行为层，与 V6.5 Strategy 语义重叠：

- Strategy 可用（V6 intention 链成功）时：【表现方式】段（V6.5）取代【本轮行为指令】段（V2）。
- Strategy 不可用（intention 降级/链失败）时：回落 V2 behavior 段，保证行为层永不为空。
- V2 `INTENTION_BEHAVIOR_MAP` 保留，作为 Strategy 解析的输入之一。

这是收编而非重建：V2 behavior 退化为 fallback 路径，删除动作留给后续版本。

## 5. 核心不变式

1. **零新增 LLM 调用**：Strategy / Budget / Mode 稳定 / Activity 表现层全部是纯函数，前台关键路径零时延增量（SSE 零退化）。
2. **约束不是模板**：所有注入都是「方向 + 上限」短句，不是 if-else 输出固定文案；LLM 保留表达自由。
3. **人格优先**：Behavior 层叠加在人格之上（沿用 `PERSONALITY_FIRST_CONSTRAINT` 原则），任何策略都不允许把亚丝娜变成另一个人。
4. **永不为空**：Strategy 解析失败 → 回落 V2 behavior 段；Mode 读取失败 → default；Budget 计算失败 → 默认预算。行为层降级不阻塞回答。
