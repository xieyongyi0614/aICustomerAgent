# M4 Object State System（V8 核心模块）

> 目标：世界中的实体——可被创建、移动、使用、变化、销毁，状态跨会话持久。这是"冰箱里有没有西瓜"的直接答案来源。

## 1. WorldObject 模型

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | `watermelon_001`（category 前缀 + 序号，仓储生成） |
| world_id | str | 归属世界 |
| name | str | "西瓜"（prompt/匹配用） |
| aliases | list[str] | 匹配别名（"瓜"），资产/解释器补充 |
| category | str | food / drink / tool / furniture / clothing / device / misc |
| location_id | str | 当前位置（`home.kitchen.fridge`，容器即地点层级叶节点或独立容器词表） |
| state | str | 类目状态机当前态（whole / cut / eaten / …） |
| quantity | float | 数量（1 → 0.8 → 0；无单位，语义随 category） |
| properties | dict | 类目扩展（expiry_at、size、color…，有界） |
| status | str | active / destroyed |
| last_action_at / created_at / updated_at | datetime | 演化审计 |

容器处理：fridge 不建模为"容器内物品列表"，而是**地点层级的一个节点**（`home.kitchen.fridge`）——物品的 location_id 指向它即"在冰箱里"；容器自身的开关状态是普通 Object（state=open/closed，P1）。

## 2. Object 生命周期（五事件）

```text
Created   解释器发现新实体（"买了个西瓜"）或手动播种 → status=active, 初始 state/quantity
Moved     位置迁移（"把西瓜放回冰箱"）→ location_id 变更
Used      使用/消耗（"切西瓜""吃一块"）→ state 迁移 + quantity 扣减
Changed   属性变化（过期/变坏/充电完成）→ properties/state（多由时间演化触发）
Destroyed 用尽/丢弃（"扔了"）→ quantity=0 或 status=destroyed（保留行做历史，不物理删除）
```

## 3. Object 状态机（声明式，按类目）

状态机定义在**角色资产**（`app/character/asuna/world.py`），不是硬编码 if：

```python
OBJECT_STATE_MACHINES = {
    "food": {
        "initial": "whole",
        "transitions": {
            ("whole", "cut",       "cut"),
            ("cut",   "eat",       "eaten"),      # quantity 扣减由动作参数决定
            ("*",    "expire",     "expired"),    # 时间演化（expiry_at）
            ("*",    "discard",    "empty"),
        },
    },
    "generic": {"initial": "intact", "transitions": {("*", "damage", "damaged"), ("*", "discard", "destroyed")}},
}
```

- `transitions.py`（services/world）提供纯函数 `apply_action(machine, state, action) -> state | None`：非法迁移返回 None（解释器放弃，不造事实）。
- 迁移不产生连锁（cut 不自动触发 expire）；时间演化统一由 due 检查驱动（每 turn + lifespan 循环），幂等。

## 4. 数量演化（西瓜示例全链）

```text
初始：  watermelon_001  fridge  whole    quantity=1
用户："给我拿个西瓜"      → Moved: fridge → kitchen（note: 已取出）
用户："切一下"           → Used:  whole → cut
用户："吃一块"           → Used:  cut → eaten, quantity 1 → 0.8（块数由资产定义"西瓜按 5 块切"或解释器参数；无参数时默认扣 1/切份数）
次日：  expiry_at ≤ now  → Changed: expired（时间演化）
用户："西瓜还能吃吗"      → Context: state=expired → 角色据实回答
用尽：  quantity ≤ 0     → Destroyed: empty（可再"买个新的"→ Created）
```

- 未指定份数的消耗动作：扣减规则在资产类目里声明（`default_portions`），解释器不猜数值。
- quantity 精度：保留 2 位小数；下限 0。

## 5. Object Action（声明式动作，非工具）

| 动作 | 参数 | 效果 |
|---|---|---|
| take / put_back | location | Moved |
| cut / open / close | - | state 迁移 |
| eat / use / drink | portions? | state 迁移 + quantity 扣减 |
| discard / buy | count? | Destroyed / Created |
| move_to | location | Moved（大件） |

动作表 = 资产词表；解释器把"用户消息 + 当前世界"映射到 `(object, action, params)`；映射失败 → 无迁移。**动作永远不调用任何函数**，只驱动声明式状态迁移——这是与 Tool Calling 的分界线（V8 明令禁止 Tool Calling）。

## 6. 实体如何进入世界（入库渠道，白名单）

1. **用户消息解释**（主渠道，interpreter）：明确陈述才入库（"我买了个西瓜"）。
2. **手动播种**：/debug/world 端点（调试与回归测试用）。
3. **资产初始实体**：home 布局自带的固定物件（家具类，furniture，极少演化）。
- LLM 辅助链（P1，采样）只做"候选提议"，入库仍需通过确定性校验（名称可匹配、类目合法、状态机存在）。

## 7. 边界

- 不建模物理仿真（重量/体积/碰撞）；不建模物品间依赖（"没有刀不能切"——由 available_actions + note 表达，不硬约束）。
- 人物不入世界实体（Multi Character 禁令；用户作为对话方存在于 Character Runtime 视角）。
- properties 字符上限（复用有界工具），expiry_at 是唯一标准化时间属性（时间演化依赖）。
