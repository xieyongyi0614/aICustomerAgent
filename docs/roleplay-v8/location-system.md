# M3 Location System

> 目标：让角色知道"我在哪、这里属于哪、这里能做什么"。地点是**静态层级设定 + 动态所在位置**的组合。

## 1. 层级模型

```text
home
 ├── living_room   客厅
 ├── kitchen       厨房
 ├── bedroom       卧室
 └── balcony       阳台（环境外露：天气感知点）
```

- 默认布局以**角色资产**定义（`app/character/asuna/world.py`）：与世界"状态"分离——布局是设定，人在哪、物品在哪是状态。
- Location 模型：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | 点分路径 `home.kitchen` |
| name | str | 中文名（prompt 用："厨房"） |
| parent_id | str \| None | 层级父节点（root 为 world 本身） |
| traits | list[str] | 场景特质标签（`indoor` / `outdoor_exposed` / `quiet` / `food_related`） |
| available_actions | list[str] | 该地点的合理动作（见 §3） |
| description | str \| None | 一句话氛围（可空，进 prompt 需预算） |

LocationRelation 用"parent_id + traits"隐式表达，不建独立关系表（层级 ≤ 2 层，YAGNI）。

## 2. LocationContext（进 WorldContext）

| 字段 | 类型 | 说明 |
|---|---|---|
| current | str | 当前 location_id |
| current_name | str | "厨房" |
| path | list[str] | ["家", "厨房"]（渲染用） |
| available_actions | list[str] | 厨房 → ["拿食物", "做饭", "收拾"] |
| traits | list[str] | 选择器据此决定是否带天气（outdoor_exposed） |

### 所在位置（世界状态）

- `worlds.current_location`（单角色世界 = 角色所在位置）是**动态状态**，随解释器迁移（"我们去客厅吧" → living_room）。
- 初始值：home.living_room。
- 迁移约束：只接受目标为已定义 location 的确定性解释；不存在瞬移（跨层级跳转记录为 note）。

## 3. 可用动作（Available Actions）

- available_actions 是**声明式词表**，来源 = 角色资产；它只做两件事：
  1. 进 WorldContext → prompt 里角色"知道厨房能做饭"；
  2. 解释器校验：用户动作若与地点不符（在卧室"拿西瓜"而西瓜在厨房）→ 解释为 note（"西瓜在厨房"）而非直接成功——**世界约束动作**，这正是 V8 的价值。
- 不是 Tool Calling：动作不执行任何函数，只表达"什么合理"；真正行为仍由 Character Runtime（goal/behavior/LLM）产出。

## 4. 地点对 Behavior / Emotion 的影响通道

| 影响 | 通道 | 是否写 Character 状态 |
|---|---|---|
| Behavior：卧室 → 休息类动作合理 | prompt 世界段（available_actions） | 否 |
| Emotion：深夜+卧室 → 安静氛围 | prompt 世界段（traits + time 组合渲染） | 否 |
| Autonomy：阳台+下雨 → 提醒收衣 | world_facts（P1） | 否 |

统一原则：**影响只经过上下文与事实，不经过状态写回。**

## 5. 扩展世界（新地点）

- P0：布局写死在角色资产（home 四室）；新增地点 = 改资产文件（发布行为）。
- P2 预留：user-defined location（用户口述"我有个书房"→ 解释器创建 location）——先记录为 note，不自动建点。

## 6. 与 scene_state.location 的关系（重要）

| | scene_state.location（V3） | world current_location（V8） |
|---|---|---|
| 域 | 会话 | 用户（跨会话） |
| 语义 | 叙事场景位置（由 scene_update LLM 链维护） | 世界事实位置（由解释器确定性迁移） |
| 写入方 | scene_update（既有，不动） | interpreter（V8） |
| 取值 | 自由文本 | 受限于已定义 location 集 |

- V8 **不读写** scene_state.location；两处暂不一致属可接受（V3 是叙事近似，V8 是事实）。
- P2 预配对齐：装配时若两者冲突，以 world 为准并在 note 里说明（先观测差异频率再实现）。

## 7. 边界

- 不实现地图/距离/寻路（单宅世界，层级即全部空间关系）；"10 公里外"概念不存在。
- 不实现多建筑/多世界切换（world_id 预留但不开放）。
- available_actions 不校验 Character 能力（行为合理性由 V6.5/V7 既有策略负责，V8 不越界）。
