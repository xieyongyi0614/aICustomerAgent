# Goal Context（Prompt 注入）

## 1. 注入位置与顺序

现有 system 段顺序（prompts/builder.py）：人格块 → 情绪 → 角色状态 → 关系 → 记忆 → 摘要 → 历史 → mode → 行为指令 → 场景 → input。

V6 在**关系段之后、记忆段之前**插入两段（动机先于素材）：

```text
【角色当前目标】
主导：陪伴用户放松
因为：用户表达疲惫，user_care 目标提升
内心倾向：暂时放下其他话题，先照顾用户的状态

【本轮意图】
comfort_user（安抚用户的情绪）
表达要求：意图通过关心和陪伴的举动自然体现，不要直接说出意图名称或策略。
```

## 2. 格式规则

- **主导目标**：SelectedGoal.goal.description；reason 一行；`suppressed` 目标最多 1 条以"内心倾向"句带出（背景化，不罗列）。
- **意图**：`类型中文名（描述）`+ 表达要求固定句。类型→中文映射表代码持有（对齐 builder.MEMORY_TYPE_LABELS 模式）。
- **不暴露**：goal_id、priority 数字、status、horizon、confidence——内部字段一律不进 Prompt（对齐 V4 privacy 原则）。
- reason 注入与否：goal 的 reason 注入（帮 LLM 理解动机）；intention 的 reason 不注入（内部解释，防照读）。

## 3. 预算

| 段 | 上限 |
|---|---|
| 目标段 | 120 字（动态部分：主导+因为+内心倾向） |
| 意图段 | 80 字 |
| 总预算 | 计入 REF-007 的 `context_total_char_budget`（两段约 200 字，由 fixed 段扣减自动生效） |

超预算处理：截断 reason，**表达要求句永不截断**（对齐 V5 情绪段预算策略）。

## 4. 空值兼容

- 无 selected goal（播种失败降级）→ 目标段整体省略；
- intention 降级 continue_topic → 意图段照常注入（"延续当前话题"），不省略——保持段落结构稳定，避免 LLM 因段落消失而行为漂移；
- 无 analysis（V1 路径）→ 两段均省略（与 V5 情绪段同规则），golden 快照锁定。

## 5. 人格优先（对齐 V5 约束）

意图段尾部固定追加：

> 意图叠加在你的人格之上：温柔的人安慰是贴近的陪伴，傲娇的人安慰是别扭的关心。用你自己的方式去达成意图，而不是套用模板。

（与 V5 PERSONALITY_FIRST_CONSTRAINT 同族，独立常量 PERSONALITY_INTENT_CONSTRAINT。）

## 6. Golden

tests/golden/ 新增 `prompt_v6_full.txt`（含目标/意图段）与 `prompt_v1_default.txt`（确认 V1 无新增段），变更需 UPDATE_GOLDEN=1 显式再生。
