# V9 World Integration（行动 ↔ V8 双向集成）

> 行动改变世界，世界约束行动。V9 是世界的第一个**主动执行者**（V8 interpreter 是被动解释者）；本篇定义行动→世界的写通道映射、世界→行动的读约束、执行顺序契约与快照回滚语义。**world_engine 全部既有方法零修改**——V9 只做消费方。

## 1. 写通道映射（行动效果 → 世界）

| ActionType（capability.action） | world_engine 调用 | 世界产物 |
|---|---|---|
| create_reminder（reminder.create） | `create_event(user_id, event_type="reminder", title=content, importance="high", due_at=解析结果, source="autonomy")` | WorldEvent(scheduled, due_at)——到期触发/宽限过期/完结/记忆沉淀全部继承 V8 事件语义 |
| cancel_reminder（reminder.cancel） | `cancel_events_by_type(user_id, "reminder")`（带 title 关键词过滤，未来预留按 event_id 精确取消） | WorldEvent(cancelled, completed_at 回填) |
| remember_fact（memory.save） | 无世界效果 | memories 表（memory-policy.md） |
| create_object（world_action.create） | `create_object(user_id, name, category=资产词表推断, location_id=推断/默认, quantity)` | WorldObject(active)——受 `world_active_entities_limit` 约束 |
| move_object（world_action.move） | `move_object(user_id, object_id, location_id)`（location 必须在 HOME_LOCATIONS） | WorldObject(location_id 变更) |
| use_object（world_action.use） | `apply_object_action(user_id, object_id, action)` | 状态机迁移（eat/…），quantity 扣减，≤0 → DESTROYED |
| query_environment（environment_query.query） | `build_time_context` + WorldEnvironment 只读 | 无写 |
| query_search / send_notification | 无世界效果 | effect[note] |

映射纪律：

1. **source 一律传 `"autonomy"`**——V8 EventSource 白名单（user_mention/manual/autonomy）中 autonomy 语义即"系统主动创建"，行动创建的事件与用户口头提及（interpreter 命中 user_mention）可区分；记忆沉淀时 source 映射 ai_inferred → 由 action memory bridge 改映射 user_derived（memory-policy.md §3）。
2. **世界写失败 = 行动失败**：create_event 返回 None（如 `world_active_events_limit` 满）→ CapabilityResult.failed(permanent)，ActionRecord 留痕，**不静默假成功**——这是行动与 interpreter 的本质差异（interpreter 宁可不迁移，行动必须如实报告成败）。
3. 世界数据缺失（world_enabled=false / 世界未初始化）→ 依赖世界的行动（reminder/world_action/environment_query）在 G3 附加检查后置 unavailable 拒绝执行；不依赖世界的行动（memory）正常执行。

## 2. 读约束（世界 → 行动）

- **G6 闸门的现状输入**：装配闸门快照时读世界（`get_world` / `list_objects` / `list_events`）——create_object 前查同名活跃物品（防重复创建）、cancel_reminder 前查目标事件存在（target_not_found 否决）。
- **参数校验的实体匹配**：use_object / move_object 的 object 参数经 `find_object_by_name` 语义匹配；无匹配 → G6 target_not_found（"没有这个东西"是可回答的事实，不是行动失败）。
- **available_actions 语义延伸**：V8 LocationContext.available_actions（资产词表）同时约束 world_action 的 use 动作合法性（地点不符不造事实——V8 地点纪律的行动侧复用）。

## 3. 行动事实回流上下文

行动产生的事实经两条既有只读出口回到角色视野：

1. **行动上下文段**（tool-integration.md §4）：ActionRecord 视角（"我设过什么提醒、成败如何"）。
2. **世界切片**（V8 WorldContext，零修改）：WorldEvent 视角（"世界将发生什么"）——行动创建的 reminder 在下一轮的【当前世界】段 salient_events 中天然可见。

两条通道互补不重复：行动段回答"我做过什么"，世界段回答"世界上有什么"。渲染预算独立（action_context_char_budget / world_context_char_budget）。

## 4. 生命周期分工（ActionRecord vs WorldEvent）

```text
"明天提醒我开会"
  T0 第 9 步   ActionRecord(created→planned→executing→succeeded)
              WorldEvent(reminder, scheduled, due=明天 8:00)     ← 一次行动，两个宿主
  ……          WorldEvent 到期 → active（trigger_due_events）
              ActionRecord 保持 succeeded（执行审计已闭环，不再变化）
  到期时       自治 due_action 触发器 → 主动汇报（言语，不新建 ActionRecord）
  "面完了"     interpreter/行动 → WorldEvent(completed) → 记忆沉淀（V8 memory_bridge）
              ActionRecord 依旧不变
```

- **ActionRecord 记执行，WorldEvent 记事实**：行动成功即终态（审计不可变）；事件存续到完结（事实生命周期）。提醒是否送达、用户是否响应，属于事件域与对话域，不回写执行域。
- 联动查询：ActionRecord.scheduled_at 冗余存储 due（List 页面免联查）；权威状态以 WorldEvent 为准。

## 5. 与 V8 interpreter 的执行顺序契约（防双重执行）

第 8 步（interpreter）→ 第 9 步（action）顺序固定，矩阵如下：

| 消息形态 | interpreter（第 8 步） | action（第 9 步） | 结果 |
|---|---|---|---|
| 叙事性："切西瓜" | 命中 TAKE/CUT/EAT 词表 → 迁移 | 未检出（祈使主语非"帮我"） | 单一执行（V8 语义） |
| 委托性："帮我买牛奶" | 未命中（BUY 词表范围外/无实体上下文） | 检出 create_object → 执行 | 单一执行（V9 语义） |
| 双命中："把牛奶放冰箱" | 已迁移 move | G6 effect_already_satisfied 否决 | 单一执行（interpreter 赢——话语解释优先于委托执行，消息更贴近叙事） |
| 行动型取消："不用提醒了" | 未命中 | cancel_reminder → cancel_events_by_type | 单一执行（interpreter 无取消词表） |
| 明日事件陈述："明天面试" | create_event(user_mention) | 未检出（陈述非委托） | 单一执行（V8 语义） |

- 原则：**叙事解释优先，委托执行补位，G6 兜底**。interpreter 是低成本高召回的话语解释器；行动是带闸门与留痕的委托执行器。
- interpreter 词表与行动词表的边界维护在角色资产中同表评审（`app/character/asuna/action.py` 注释级对照），避免漂移。

## 6. 快照回滚语义

- `restore_snapshot`（V8-013）只回滚世界四表；**ActionRecord 不回滚**——执行历史是审计事实，与 V8"Character 状态不回滚"同款语义扩展到行动记录。
- 回滚后行动效果可能失配（如行动创建的 WorldEvent 被回滚掉）：ActionRecord.status 保持 succeeded，effect.ref 指向的宿主可能已不存在——行动上下文段渲染时对 effect 做存在性校验（宿主缺失 → 降级显示"已失效"），不做自动重放（effects 重放留待未来，参考 V8.5 replay 思路）。
- /debug/actions 提供按时间窗查询，可与 /debug/world/snapshots 对照审计。
