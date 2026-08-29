# Persistence（V6 持久化边界）

## 1. 存什么、存哪

| 数据 | 存储 | 生命周期 |
|---|---|---|
| Persistent Goal | `character_goals` 表，horizon=persistent, source=definition | 随角色资产；幂等播种 |
| Current Goal | `character_goals` 表，horizon=current | created→completed/expired/cancelled（软状态） |
| Intention（当轮） | trace（内存，随 request_id 可查）+ turn_meta | 单轮 |
| Goal 生命周期变更 | trace `goal_review` step + goals 行状态 | 审计 |
| Goal→Intention 的历史统计 | **V6 不存**（P2：如需"目标达成率"再建聚合） | — |

## 2. character_goals 表

```text
id            String PK
user_id       String     索引 (user_id, status)
character_id  String     默认 "asuna"
type          String     ck: user_care/relationship/conversation/scene
description   String     ≤40 字
priority      Integer    1~5
status        String     ck: active/completed/expired/cancelled
horizon       String     ck: persistent/current
source        String     ck: definition/policy/scene
created_turn  Integer
expires_at_turn Integer nullable
created_at    DateTime
updated_at    DateTime
```

- 不绑 session/conversation（目标跨会话，对齐 V4 记忆的 user+character 绑定层级）。
- 单用户 active 行数上界：3 persistent + 策略上限 ≤5 current（goal-policy 幂等保证）——无膨胀风险，不需要 TTL 清理任务。

## 3. turn_meta 扩展

```json
{
  "type": "turn_meta",
  "role_mode": {...},
  "analysis": {...},
  "scene_intent": {...},
  "scene_state": {...},
  "intention": {
    "type": "comfort_user",
    "reason": "用户表达疲惫，当前目标为陪伴放松",
    "goal_id": "g-1",
    "degraded": false
  },
  "current_goal": {"id": "g-1", "type": "user_care", "description": "陪伴用户放松"}
}
```

前端 Debug 面板可展示"角色这轮想做什么、为什么"（V6-009）。

## 4. Repository 边界

新增 `app/repositories/goal_repository.py`，仅 CRUD/Query：
- `seed_goals(user_id, seeds)` 幂等播种
- `list_active(user_id, character_id)`
- `create_goal(record)` / `complete_goal(id)` / `expire_goal(id)` / `cancel_goal(id)`
- 全部独立事务（现状模式），goal 写入不与 V5 状态同事务（目标变更失败仅影响动机层，不影响状态层，独立容错与 trace 记录）

## 5. 与 V4 Memory 的边界（重申）

Goal 不进 V4 记忆管线（不是"关于用户的信息"）；Goal 完成时若产生叙事价值（如"陪用户度过了疲惫的一晚"），由 P2 可选任务评估是否经 V4 提取管线写入 relationship_event 记忆——V6 不实现。

## 6. 迁移

`migrations/versions/0008_character_goals_table.py`，标准 create_table/downgrade drop_table；无存量数据转换。
