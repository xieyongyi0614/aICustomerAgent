# Goal Integration（V7 × V6）

## 1. 复用边界（V6 零改动清单）

| V6 组件 | V7 用法 | 改动 |
|---|---|---|
| `goal_service.select()` | Worker 评估时直接调用，取主导目标 | **零改动** |
| `goal_service.review()` | 照常在 post_process 运行（用户在场才产生信号，worker 不触发 review） | 零改动 |
| `GoalRecord` / PROACTIVE 白名单 | Worker 只认 user_care/relationship 两个类型（autonomy-model.md §4） | 新增白名单常量于 V7 模块 |
| Persistent 种子 | "守护用户身心状态"正是 check_in 的动机来源 | 零改动 |

结论：**V7 不修改 V6 的任何决策逻辑**，只在其上加"没有用户消息时是否仍走这套决策"的门。

## 2. 主动场景的 Goal → Intention 映射

```text
user_care 类目标（陪伴/关心/劝休） → intention = check_in
relationship 类目标（修复隔阂）   → intention = repair_rapport
```

- check_in 是新 IntentionType 值（V6-011 的预留位），语义："主动问候/关心用户近况"，表达要求含"允许用户不回复"。
- 不使用 comfort_user/suggest_rest 等反应式意图：它们预设了用户消息语境，主动场景没有。
- repair_rapport 复用 V6 枚举，tension > 0.5 且用户离开时是最高价值主动行为。

## 3. Action 文本生成仍然走 Goal+Intention 双段

Executor 生成文本时，Prompt 注入（proactive prompt，结构对齐 V6 goal-context.md）：

```text
【角色当前目标】主导：陪伴用户放松（无用户输入场景）
【本轮意图】check_in（主动关心用户近况）
【最近对话】最后 2 轮（衔接语境，避免凭空问候）
表达要求：自然开启话题，允许用户不回复，不要追问施压；一句话。
```

- 约束句：主动消息**禁止连续追问、禁止长文本、单句优先**（复用 V2 语言风格资产 + 追加主动场景约束）。
- 人格优先约束沿用（温柔的人主动关心是贴心的问候，傲娇是别扭的"没什么，就是想问问你忙完没"）。

## 4. Motivation 完整示例（验收 Scenario 1 对应）

```text
Trigger：会话闲置 35 分钟（最后一条："我去忙了"）
Motivation：persistent"守护用户身心状态" + active"陪伴用户放松"
Permission：intimacy 0.62，无生成中标记，非静音时段
Cooldown：上次主动 6 小时前
Validity：check_in 白名单合法
→ ACT(check_in) → proactive_chain 生成 → "忙完了吗？记得喝口水。"
```

## 5. 负例（必须 IGNORE 的动机缺口）

```text
Trigger：闲置 35 分钟
Goals：仅 conversation"延续当前话题"
→ Policy 第 7 条 IGNORE("对话类目标不触发主动")
```

这条负例是"没有动机就不行动"的守门测试（testing.md Case 7 对应）。
