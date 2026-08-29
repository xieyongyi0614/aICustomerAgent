# Goal Conflict Resolution

## 1. 典型冲突（验收基准案例）

```text
Goal A（conversation/user_care-陪伴）：陪用户聊天
Goal B（user_care-劝休）：让用户早点休息

情境：凌晨 1 点，用户明显疲惫（tired, intensity 0.6），聊天正热络
```

**裁决：Goal B 胜出，但方式让步于关系。**

- tier 规则：同为 user_care 时，深夜+疲惫的上下文修正使"劝休"排在"陪伴"前。
- 表达约束：胜出目标决定 Intention 方向（suggest_rest），但**不终止陪伴**——Intention 语义是"建议收尾而非赶人"（intention-model.md 的 suggest_rest 描述），且 Prompt 注入时保留被压制目标作为背景（"仍愿意继续，但建议休息"），由人格层自然表达。

## 2. 裁决原则（优先级字典序）

1. **安全/福祉 > 愉悦**：涉用户身心状态的目标 > 关系/对话经营。
2. **承诺 > 偏好**：对用户的显式承诺（scene pending）> 一切表达类目标。
3. **关系不可逆损伤 > 短期亲近**：tension 高时修复优先，宁可这轮"疏远但正确"。
4. **平级冲突 → 更新时间新者胜**：情境目标反映最新状态。

## 3. 冲突矩阵（代码实现为 tier 表 + 修正表，不写 if-else 链）

| A \ B | scene | user_care | relationship | conversation |
|---|---|---|---|---|
| scene | pending 先完成 | pending 先完成 | pending 先完成 | pending 先完成 |
| user_care | 让位 | 深夜/疲惫修正裁决 | user_care 胜（福祉>关系经营） | user_care 胜 |
| relationship | 让位 | 让位 | tension 修正裁决 | relationship 胜 |
| conversation | 让位 | 让位 | 让位 | 并存（取最新） |

注：这是**选择排序**矩阵而非互斥矩阵——落选目标仍作为 Prompt 背景注入（goal-context.md §4），角色表达以胜者为主、不否定败者。

## 4. 不可裁决情形

两个 user_care 目标（陪伴 vs 劝休）在非深夜情境冲突 → 取 priority 字段高者；仍平 → 取 description 在 GOAL_TIER 表中排序靠前的固定条目。**永远有确定性输出**，不允许选择器返回空。

## 5. 记录

每次裁决写入 SelectedGoal.reason 与 suppressed 列表，trace 可查——"为什么这轮劝我休息而不是陪我聊"必须可回答。
