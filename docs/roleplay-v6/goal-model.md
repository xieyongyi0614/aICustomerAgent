# Goal Model

## 1. 两级 Goal（第一版不做三层）

```text
PersistentGoal（角色定义级，长期不变）
  ↓ 派生
CurrentGoal（情境级，小时~天级）
```

"Immediate Goal" 不单独建模——它就是当轮的 Intention（见 intention-model.md），避免 Goal/Intention 职责重叠。

## 2. 类型（4 类，V6 封顶）

```python
GoalType = Literal[
    "user_care",       # 用户福祉：关心/劝休/减压（asuna 的体贴底色）
    "relationship",    # 关系经营：拉近距离/修复隔阂/维持信任
    "conversation",    # 对话经营：延续话题/活跃气氛/了解用户
    "scene",           # 场景事务：完成当前场景动作/推进场景
]
```

不采纳 task/self 类型：scene 已覆盖事务性目标，"自我目标"在固定人设下由 Persistent Goal 承载，无运行时变化需求。

## 3. 字段

```python
class GoalRecord(BaseModel):
    id: str                      # uuid
    user_id: str
    character_id: str = "asuna"
    type: GoalType
    description: str             # ≤40 字，动宾短语（"陪伴用户放松"）
    priority: int = Field(ge=1, le=5)   # 同类型内的细分权重，5 最高
    status: GoalStatus = "active"
    horizon: Literal["persistent", "current"] = "current"
    source: GoalSource           # definition / policy / scene
    created_turn: int = 0
    created_at: datetime
    updated_at: datetime
    expires_at_turn: int | None = None   # current 类的轮次 TTL
```

GoalSource：

```python
GoalSource = Literal[
    "definition",   # 角色定义种子（唯一允许创建 persistent 的来源）
    "policy",       # 代码策略触发（冲突/修复/场景规则，见 goal-policy.md）
    "scene",        # V3 场景 pending action 派生
]
```

## 4. 状态

```python
GoalStatus = Literal["active", "completed", "expired", "cancelled"]
```

不引入 paused：current 类目标生命周期短，挂起语义由 priority=1 表达。persistent 类状态恒为 active，只能被 definition 变更（属于改角色资产，非运行时行为）。

## 5. 种子（Character Definition）

`app/character/asuna/goals.py` 新增角色资产：

```python
PERSISTENT_GOALS = [
    GoalSeed(type="user_care", description="守护用户的身心状态", priority=4),
    GoalSeed(type="relationship", description="与用户建立彼此信赖的陪伴关系", priority=3),
    GoalSeed(type="conversation", description="成为用户愿意倾诉的对话伙伴", priority=2),
]
```

种子在首次访问该用户时幂等播种（goal_service.seed_if_absent），source=definition、horizon=persistent。**用户语言永远不直接产生 persistent goal**（见 goal-policy.md §5）。

## 6. 当前目标的示例全集

```text
user_care:     陪伴用户放松 / 劝用户早点休息
relationship:  修复争吵后的隔阂 / 维持日常亲近感
conversation:  延续当前话题 / 了解用户近况
scene:         完成切西瓜的承诺
```
