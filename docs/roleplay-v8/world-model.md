# M1 World State Core

> 目标：定义世界的聚合根与生命周期。世界是**用户域的持久状态机**——不是 prompt 片段，不是会话属性。

## 1. 一个 World 包含什么

```json
{
  "world_id": "home",
  "user_id": "default-user",
  "name": "家",
  "time_mode": "real_sync",
  "sim_time": null,
  "environment": { "weather": "rain", "temperature_c": 18, "lighting": "dark" },
  "locations": ["home", "home.kitchen", "home.living_room", "home.bedroom"],
  "objects": [ { "id": "watermelon_001", "location": "home.kitchen.fridge", "state": "whole", "quantity": 1 } ],
  "events": [ { "type": "interview", "due_at": "...", "status": "scheduled", "importance": "high" } ]
}
```

作用域决策：**每用户一个默认世界**（world_id="home"，user_id 隔离），跨会话持久；多世界（world_id 扩展）仅预留模型字段，本阶段不开放。角色单角色（asuna），世界不含其他角色实体。

## 2. 核心模型（`app/models/world.py`，Domain 层）

### World（聚合根视图，读模型）

| 字段 | 类型 | 说明 |
|---|---|---|
| world_id / user_id / name | str | 标识；name 供 prompt 引用（"家"） |
| time_mode | WorldTimeMode | real_sync / simulated / story |
| sim_time | datetime \| None | simulated/story 模式的世界时钟；real_sync 恒 None |
| created_at / updated_at | datetime | |
| environment / locations / objects / events | 派生 | 由仓储按需装载，World 模型本身不持久化整包（除快照） |

### WorldObject（M4 详见 object-system.md）

id、name、category（food/tool/furniture/…）、location_id、state、quantity（float，支持 0.8）、properties（JSON：expiry、size…）、status（active/destroyed）、时间戳。

### WorldLocation / WorldEnvironment

Location 是**静态设定**（层级 + 可用动作，角色资产定义，不入库）；Environment 是**动态状态**（每世界一行）。区分动机：地点布局是世界观设定，改动频率≈0；环境随时间/剧情变化。

### WorldContext（进 Character 的切片，只读）

| 字段 | 类型 | 说明 |
|---|---|---|
| time | TimeContext | now / part_of_day / weekday / time_mode |
| location | LocationContext | 当前位置 + 层级路径 + available_actions |
| environment | EnvironmentContext \| None | 选择性携带 |
| nearby_objects | list[ObjectBrief] | 同位置物品摘要（≤3，字段有界） |
| salient_events | list[EventBrief] | due 今日 / 高重要度 / 刚完结（≤3） |
| notes | list[str] | 解释器产出的世界备注（有界，可空） |

### StateSnapshot（快照）

id、world_id、label（如 `before_dinner` / `2026-08-31T22:00`）、state（整包 JSON：environment + entities + events + sim_time）、created_at。

## 3. 生命周期

```text
创建 create      首次需要时惰性创建（ensure_world）：默认 home 布局 + 空实体 + 空事件
                  + real_sync 时钟；创建动作幂等。
更新 update      唯一变更入口 = World Update Interpreter（用户消息 → 迁移）+ 手动 debug 端点
                  + 事件调度系统；任何其他模块不得写世界。
查询 query       build_context（每 turn 一次，选择切片）/ get_world（调试全量）。
快照 snapshot    手动端点 + 显著迁移时自动（采样）；整包 JSON 存 world_snapshots。
恢复 restore     从快照整包回写（覆盖 entities/environment/events 当前态），P2 开放 API。
销毁 destroy     不提供；世界随用户存在（TTL 只清历史快照与完结事件）。
```

## 4. 世界的合法变更源（白名单，硬约束）

| 来源 | 例子 | 载体 |
|---|---|---|
| 用户消息解释 | "给我拿个西瓜" → 西瓜从 fridge → kitchen、state=cut? 否——只迁移**确定性**部分 | interpreter（确定性规则 P0，LLM 辅助 P1 采样） |
| 时间演化 | 食物过期、事件到期触发 | due 检查（turn 内 + lifespan 循环） |
| 事件调度 | "明天面试" → scheduled → due 触发 → completed | event system |
| 手动运维 | 调试台设置天气/播种物品 | /debug/world 手动端点（显式标注） |
| 快照恢复 | 回滚到昨晚 | restore（P2） |

**解释器的确定性原则**：只迁移用户消息中明确陈述的世界变化；LLM 输出与规则输出冲突时以规则为准；完全无匹配 → 无迁移（宁缺毋滥，不造事实）。

## 5. WorldContext 的一次装配（伪流程）

```text
ensure_world(user_id)                          幂等
time = TimeProvider.now(world)                 real_sync → 真实时钟；simulated → sim_time 步进
location = 当前位置（world 级，默认 home.living_room；随解释器迁移）
environment = 仓储读（缺省用默认值）
objects/events = 仓储按选择器条件查（同位置 / due 邻域）
WorldContextSelector.select(...) → 有界切片（预算 600 字符）
```

## 6. 边界

- World 模型不含任何 Character 概念（情绪/关系/记忆字段零出现）。
- StateSnapshot 只存世界自身；恢复后 Character 状态不回滚（时间不可倒流的叙事约束，文档化为设计决策）。
- 数量单位约定：quantity 无单位浮点（0~n），语义由 category 决定（食物=个/块，燃料=度）；模型不引入单位系统（YAGNI）。
