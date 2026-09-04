# M10 World + Autonomy Integration

> 目标：让 V7 自治"看得见世界"。职责一句话：**World 负责"发生了什么"，Autonomy 负责"是否行动"**——不混合。

## 1. 集成形态：world_facts（只读事实包）

```text
autonomy_engine._snapshot_for（H5，+3 行）：
    world_facts = world_engine.collect_facts(user_id)   失败 → {}（零降级成本）
    PolicySnapshot(..., world_facts=world_facts)
```

collect_facts 产出（有界 JSON，≤ 有界字符）：

```json
{
  "weather": "rain",
  "part_of_day": "late_night",
  "salient_events": [ {"type": "interview", "title": "用户的面试", "due_in_hours": 10, "importance": "high"} ],
  "location": "home.bedroom"
}
```

## 2. 职责分离矩阵

| 问题 | 归属 | 实现 |
|---|---|---|
| 现在世界什么样 | World | collect_facts（纯读） |
| 雨天该不该提醒带伞 | **Autonomy（V7 policy）** | policy 新增 world 规则（见 §3） |
| 提醒说什么 | 既有 proactive_chain | V8 不改（世界事实进文本是 P2 预留） |
| 深夜+面试明天 → 现在打扰吗 | Autonomy | 既有静音/冷却 + world 规则叠加 |

## 3. policy 消费 world_facts 的规则设计

- `autonomy_policy.evaluate` 增**可选参数** `world_facts: dict | None = None`——既有调用不传 → 行为与 V7 完全一致（八步裁决不变）；传了 → 在既有步骤后追加 world 修饰规则：
  - `W1 提议增强`：high 事件 due < 24h 且白名单类型（interview/exam）→ reason 附加"明天有{title}"，intention 建议映射到鼓励类（PROACTIVE_INTENTION_MAP 不变，仅 reason/建议字段）；
  - `W2 克制规则`：weather=rain + 对象在户外相关位 → 不生成"出门"类提议（note）；
  - `W3 静音不解除`：world 事实**永远不能**解除既有静音/冷却/关系门槛——world 只能加理由，不能拆闸门。
- 规则实现为纯函数（`world_adjustments(verdict, facts) -> verdict'`），表驱动可测；裁决链仍是纯函数。
- **P0/P1 不新增主动消息触发源**：世界事件 due 不会自动发起主动行为（那是 V7 trigger 的领地）；world_facts 只影响"已经候选时的裁决质量"。

## 4. 主动消息文本要不要提世界？（P2 预留）

- P2 前主动文本不知道天气——"提醒带伞"实际由 W1 的 reason 引导既有 proactive_chain 生成（其 prompt 无世界段，效果受限）。
- P2 预留：proactive_chain prompt 增可选世界摘要段（同 answer 的渲染函数复用，默认关闭，开启需重跑 V7 回归）。本阶段文档化为明确非目标，避免隐性行为变更。

## 5. 与 V7 既有约束的兼容清单

| V7 机制 | V8 是否触碰 |
|---|---|
| trigger_evaluator（inactivity / followup） | 否（不新增触发类型） |
| autonomy_policy 八步短路 | 否（八步顺序与闸门不变，仅追加修饰） |
| proactive_actions 状态机 / executor / 冷却 | 否 |
| schedule_proactive_evaluation / V7.5 审计 | 否（world 相关主动行为照常被 autonomy 维评估） |

## 6. 边界

- world_facts 装配失败/超时 → 空包，policy 走原路径（自治永不因世界而中断）。
- world_facts 不参与 Episode/attempt 计数等数值逻辑（只进 reason/建议）。
- 不实现"世界事件 → 自动主动消息"的直通路径（那是触发器，属 V7 领地，V8 不越界）。
