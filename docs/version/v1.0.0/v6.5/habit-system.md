# Habit System

## 1. 定位

Habit 模拟**长期行为倾向**——不是这一轮的策略（那是 Strategy），而是这个角色「一贯如此」的习惯。真实角色不根据每次输入重新决定自己的习惯：

```text
关心别人：更喜欢行动表达（先做事再开口）
开心：    轻微吐槽
生气：    保持克制
安慰：    先陪伴，再询问
```

与 BehaviorPolicy 的分工（behavior-policy.md §5）：Policy 是**参数**（上限/等级/偏向），Habit 是**规则**（条件 → 倾向短句）。

## 2. Habit 模型

```python
# app/models/behavior_strategy.py
HabitDomain = Literal["relate", "express", "pace"]
# relate  = 如何对待用户（关心/安慰/冲突时的习惯方式）
# express = 如何表达（情绪流露习惯、动作/语言偏好）
# pace    = 节奏习惯（先听后说、追问数量、回复长度倾向）

class HabitRule(BaseModel):
    id: str                            # habit_care_action_first 等，稳定可测
    domain: HabitDomain
    condition: str                     # 触发域描述（代码匹配或渲染为适用域提示）
    priority: int                      # 1（最高）~ 5
    instruction: str                   # ≤40 字倾向短句，禁止具体台词
```

- `condition` MVP 为**声明式**：不写代码匹配器，由 Behavior Engine 按 domain + strategy 家族判定适用性（见 §4），渲染时只注入命中的 habit。避免把 habit 写成一堆 if 分支。
- `instruction` 是方向短句，与 Strategy 指令同风格——习惯约束表达，不生成内容。

## 3. 角色资产（亚丝娜）

```python
# app/character/asuna/habits.py（新增）
HABIT_LIST: list[HabitRule] = [
    HabitRule("habit_care_action_first", "relate", 1,
              "关心人时习惯先用行动表达（做点实际的事），再开口说关心的话"),
    HabitRule("habit_comfort_companion_first", "relate", 1,
              "安慰人先陪着，等对方开口再问；不第一时间给建议"),
    HabitRule("habit_angry_restrained", "express", 2,
              "生气时保持克制，音量不升、语速放缓，说事实不说气话"),
    HabitRule("habit_happy_tease", "express", 3,
              "开心时顺口轻微吐槽或调侃一句，不喧宾夺主"),
    HabitRule("habit_listen_before_speak", "pace", 2,
              "对方话没说完时不急着接话，先回应他说的最后那个点"),
    HabitRule("habit_question_bounded", "pace", 3,
              "一次最多问一个问题，问完先等回答"),
    HabitRule("habit_memory_light_touch", "relate", 4,
              "记得对方提过的事，但只在自然相关时顺口带到，不刻意展示"),
]
```

- HABIT_LIST 与 persona 其他资产同文件风格（纯常量），随角色版本演进。
- `priority` 语义：同 domain 多条同时命中时的取舍依据 + 与 Strategy 冲突时的让位顺序参考。

## 4. Runtime 应用（适用性判定）

Behavior Engine 在解析出 Strategy 后做 habit 匹配：

```python
HABIT_APPLICABILITY: dict[BehaviorStrategyType, set[HabitDomain]] = {
    "quiet_companion":    {"relate", "pace"},
    "direct_support":     {"relate", "pace"},
    "gentle_redirect":    {"relate", "pace"},
    "warm_celebration":   {"express", "relate"},
    "playful_tease":      {"express"},
    "affectionate_expression": {"express", "relate"},
    "reserved_distance":  {"express", "pace"},
    "sincere_repair":     {"relate", "express"},
    "natural_continuation": {"pace", "relate", "express"},
    "curious_inquiry":    {"pace"},
    "self_disclosure":    {"express"},
    "focused_assistance": set(),          # 专业模式不带习惯色彩
}
```

- 按 strategy 家族取适用 domain，命中 habit 按 priority 升序取**前 2 条**（上限防 prompt 膨胀），输出 `matched_habits: list[HabitRule]`。
- domain 适用而不是全文匹配——保证同一 habit 在「陪伴」和「追问」场景下自然出现不同侧重，且匹配逻辑可穷举测试。

## 5. Habit 冲突裁决

三类冲突，裁决优先级固定：

```text
1. ActionBudget 硬约束    > 一切。habit 说「用行动表达关心」也不能突破本轮 max_action_desc=0
2. Strategy 轮次指令       > habit。本轮 quiet_companion 时，「行动表达关心」的habit 让位，
                            但「先陪后问」habit 与 strategy 同向，正常注入
3. Habit 之间             > priority 小者优先；同 priority 按 HABIT_LIST 声明顺序
```

- **同向合并**：habit 与 strategy 语义一致时不重复渲染（如 quiet_companion 与 habit_comfort_companion_first），去重由渲染层按语义键（habit id 与 strategy 的静态映射表）完成。
- **矛盾示例的正确结果**：strategy=direct_support（要说出来）+ habit_care_action_first（先做再说）→ Budget 允许动作时注入「先做再说」，Budget=0 时只注入 strategy 指令。裁决结果进 trace。

## 6. 动态养成（P2 边界）

MVP habit 全部静态（角色定义）。V4 记忆已有 user_preference 类型记录**用户**偏好；角色的自我习惯「养成」（从 relationship_events 中沉淀出角色自己的行为习惯）需要 habit 候选生成 + 人工/代码审核机制，属 V6.5-012（P2），不阻塞主线。MVP 阶段禁止运行时写 HABIT_LIST。

## 7. 失败降级

- habit 匹配异常 → `matched_habits=[]`，只渲染 Strategy + Budget，回答不受阻。
- HABIT_LIST 加载校验（id 唯一、priority 域、instruction 长度）在单元测试与启动期完成。
