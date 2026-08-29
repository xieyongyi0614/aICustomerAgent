# Goal Selection

> 每轮回答前，从 active goals 中选出"本轮主导目标"（selected goal），作为 Intention Selector 的输入。

## 1. 两步选择：tier 排序 → 上下文修正

### 第一步：类型固定序（policy，不依赖 LLM）

```text
scene  >  user_care  >  relationship  >  conversation
```

理由：
- **scene 最高**：V3 的 pending action 是对用户的显式承诺，压倒表达类目标（承诺"切西瓜"就先切西瓜）。
- **user_care 次之**：asuna 人格底色是体贴；福祉类目标高于关系经营（先关心人，再经营关系）。
- **conversation 兜底**：永远有 persistent 种子垫底，选择永不落空。

同类型并列时取 priority 高者，再平则取 created_at 最新（情境目标比陈旧目标相关）。

### 第二步：上下文修正（still 纯代码，信号来自 V5）

在 tier 序基础上做**压制/提升**，不改变序本身：

| 信号 | 修正 |
|---|---|
| tension > 0.5 | relationship(修复) 目标提升到 user_care 之前（有隔阂时先修复再谈其他） |
| emotion.intensity ≥ 0.6 且为负面 | user_care 内"陪伴/劝休"类提到最前；conversation 类压制 |
| scene pending action 存在 | scene 类恒为第一（已由 tier 保证，此处显式断言） |
| 深夜（本地 23:00~6:00）且 user_emotion ∈ {tired} | user_care(劝休) 提升（见 goal-conflict.md 的裁决案例） |

修正只重排**当前轮的选择结果**，不改 goal 行的 priority 字段（priority 是持久属性，修正值是情境属性）。

## 2. 输出

```python
@dataclass
class SelectedGoal:
    goal: GoalRecord | None        # None = 仅 persistent 缺失的空窗期（理论不可达）
    reason: str                    # 结构化选择理由（"用户表达疲惫，user_care 目标提升"）
    suppressed: list[str]          # 被压制目标的 id（可解释性）
```

reason 遵循 intention-model.md §6 的结构化约束，禁止思维链。

## 3. 与 V3 Pending Action 的关系（重申）

scene pending action 不是 GoalRecord 行，而是选择时的**硬约束信号**：存在 pending 时，即使无 scene 类型 goal，SelectedGoal.reason 也要标注"存在未完成场景承诺"，由 IntentionPolicy 把表达类 intention（express_affection/tease_user 等）压到 continue_scene 语义之后（intention-selection.md §4）。

## 4. 失败语义

- goals 查询失败 → 返回 persistent 种子中的第一条 + reason 标注降级；
- 种子也缺失（播种失败）→ SelectedGoal(goal=None)，IntentionPolicy 走 V2 behavior 兜底，trace 标 degraded。
