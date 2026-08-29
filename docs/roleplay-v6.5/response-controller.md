# Response Style Controller

## 1. 定位

把 Behavior 层的全部产出（Strategy + Budget + Habit + Activity 延续）转换为 LLM Context 的**唯一出口**。实现为 prompt 渲染模块 + builder 接入，不是新服务类。

明确边界：**不是模板系统**。渲染的是「方向短句 + 硬上限」，没有 if-comfort-输出固定文本 的路径；每条注入都约束形态，不指定内容。

## 2. 输入与输出

```python
# 输入：BehaviorDirective（Behavior Engine 的聚合输出，app/models/behavior_strategy.py）
class BehaviorDirective(BaseModel):
    strategy: BehaviorStrategy
    budget: ActionBudget
    habits: list[HabitRule]          # 已裁决、已去重，≤2 条
    activity: ActivityPresence       # idle / ambient / engaged / pending
    activity_text: str | None        # 当前活动描述（V3 scene_state）
    fallback_v2: str | None          # 非 None 时渲染 V2 行为段（degraded 路径）

# 输出：prompt 段列表，交 PromptBuilder 插入
build_behavior_sections(directive) -> list[str]
```

## 3. 渲染规则

### 3.1 正常路径【表现方式】段

```text
【表现方式】
这一轮：先安静陪着，接住情绪；不急着给建议。（strategy.instruction）
表达习惯：安慰人先陪着，等对方开口再问。（habit 1）
         一次最多问一个问题。（habit 2，仅在与 strategy 不同向时注入）
本轮动作描写：0 个；情绪通过语气流露，不做显式动作。（budget 行，仅在非默认时渲染）
```

- strategy 行必渲染（degraded=False 时）；habit 行 ≤2 条且与 strategy 同向的跳过（habit-system.md §5 去重）；budget 行按 action-budget.md §5 的「偏离默认才渲染」规则。
- 段尾统一追加一行收束：「以上是表达方式约束，内容仍由你根据对话自然决定。」——保持「约束不是模板」的语义锚。

### 3.2 Activity 延续段（独立段，非 idle 时）

见 activity-state.md §3.1，渲染为【活动延续】段，随 scene_ctx 出现在 tail 场景段之后。

### 3.3 降级路径

`fallback_v2` 非 None 时，【表现方式】段整体替换为 V2 的【本轮行为指令】段（BEHAVIOR_INSTRUCTIONS[behavior]），Budget 行仍渲染（预算不因 strategy 降级而失效）。保证行为层永不为空。

## 4. PromptBuilder 接入点

```text
现有顺序（builder.build）：
  identity 4 段 → 情绪/状态/关系段 → goal 段 → intention 段
  → 记忆段 → 摘要段 → history
  → tail：MODE 段 → 【本轮行为指令】段 → scene 段 + RHYTHM → current_input

V6.5 后：
  identity 4 段 → 情绪/状态/关系段 → goal 段 → intention 段
  → ★【表现方式】段（紧随 intention：先说做什么，再说怎么做）   ← 新增
  → 记忆段 → 摘要段 → history
  → tail：MODE 段（持久化生效值） → scene 段 + RHYTHM（动作行由 Budget 值替换） 
         → ★【活动延续】段 → current_input
  （V2【本轮行为指令】段：仅 degraded fallback 时在原位渲染）
```

- 插入 identity 之后可裁剪区（`_fit_variable_parts` 滑窗只裁 history/memories/summary），**表现方式段不受裁剪**——行为约束被裁掉等于白做；长度预算计入 fixed_chars。
- RHYTHM_BLOCK 收口：动作密度行替换为 Budget 值（同一约束一个数字），其余 V3 硬约束原样保留。
- 全部动态文本过 `_literal()` 转义，遵守 golden prompt 快照机制（新增 prompt_v65_full 快照）。

## 5. Token 预算

| 段 | 典型长度 | 上限 |
|---|---|---|
| 【表现方式】 | 80~140 字 | 200 字（strategy ≤40 + habits ≤80 + budget ≤40 + 收束 ≤40） |
| 【活动延续】 | ~60 字 | 100 字 |
| RHYTHM 替换节省 | −20 字 | — |

净增量约 +150 字，占 context_total_char_budget=12000 的 1.2%，history 滑窗可吸收，无需调全局预算。

## 6. 不做什么

- 不做输出后处理改写（流式不可拦截，见 action-budget.md §2）。
- 不渲染任何内部字段名（intensity/budget 数值/factor），只渲染自然语言约束——沿用 V6「内部字段不进 Prompt」原则。
- 不引入按策略的示例台词库——示例即模板，会制造新的趋同漂移；方向指令 + 既有 modes.py 中的示例已足够。
