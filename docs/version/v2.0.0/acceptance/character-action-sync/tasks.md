# Character Action Sync — Tasks

> 阶段：v2.0.0 Acceptance ｜ 架构：[architecture.md](architecture.md)
> Schema：每个 Task 含 **ID / Priority / Goal / Scope / Non-Scope / Dependency / Reuse / Acceptance**（详见 [task-details/](task-details/)）。
> 能力分层：Foundation → Core → Integration。**本模块零新表、零迁移。**
> 总闸：`v2_character_action_sync_enabled`（default **False**，关闭时全链路零执行、prompt 字节级不变）。

## Capability Map

```text
Foundation:   ACTION-001  WorldAction 模型与状态机（唯一契约）
Core:         ACTION-002  Action Extraction   （回复 → 候选）
              ACTION-003  Action Validation   （候选 → 裁决）
              ACTION-004  World Engine Mutation（裁决 → 世界变更）
Integration:  ACTION-005  Context 与历史同步  （变更 → 下一轮可见）
```

依赖主链：`001 → 002 → 003 → 004 → 005`（002/003/004 可并行开发，004 依赖 001 与 003 的契约）。

---

## ACTION-001 — WorldAction 基础模型（Foundation）

- **ID**: ACTION-001
- **Priority**: **P0**
- **Goal**: 建立统一的 Action 数据结构与生命周期状态机，作为 Character Layer / Action Layer / World Layer 三层之间的唯一契约。
- **Scope**: `action_type`（CREATE/MOVE/CONSUME）、`actor`、`target`、`quantity`、`source`、`metadata`、`status` 字段定义；`candidate → validated → applied` 与 `rejected / failed / skipped` 状态机纯函数；`dedupe_key` 规范化与生成规则；Character 层叙事行为词表资产骨架。
- **Non-Scope**: 不实现提取、校验、执行；不落库；不建表；不新增迁移；不改 V9 `ActionType` / `ActionRecord`。
- **Dependency**: 无（**全部后续 Task 的契约前置**）。
- **Reuse**: 对齐 `models/action.py` 的 `make_dedupe_key` / `normalize_core_params` 与 V8/V9 的"非法迁移返回 None"状态机纪律；`models/world.py` 的 `ConsumeError` 错误码风格。
- **Acceptance**:
  - 给定任一合法动作序列，状态机的每次迁移结果与设计迁移表逐条一致。
  - 给定非法迁移（如 `applied → validated`），状态机返回 None 且不产生副作用。
  - 给定两组语义相同/不同参数的候选，`dedupe_key` 的相等性判定符合"语序无关、内容敏感"。
  - 给定同一候选重复构造，`WorldAction` 值相等且哈希稳定。

---

## ACTION-002 — AI Reply Action Extraction（Core）

- **ID**: ACTION-002
- **Priority**: **P0**
- **Goal**: 从角色回复 `ctx.ai_reply` 中提取候选世界动作，只产出候选，绝不修改 World。
- **Scope**: 确定性提取通道（叙事动词 + 中文数字 + 物品名词 + 地点别名）；疑问句/假设句/未来计划/复述/角色扮演 守卫；输出保留证据片段与文本顺序；可选 LLM 提取通道（默认关闭）。
- **Non-Scope**: 不校验世界一致性（ACTION-003）；不执行（ACTION-004）；不新增前台 LLM 调用；不生成叙事。
- **Dependency**: ACTION-001。
- **Reuse**: `services/world/interpreter.py` 的动词匹配与 `_negated` 守卫思路；`character/asuna/action.py` 的 `OBJECT_CATEGORY_KEYWORDS` / `infer_object_category` 与词表资产模式；`services/world/locations.py` 的 `resolve_location_alias`。
- **Acceptance**:
  - 给定「我用了两个鸡蛋」，提取出 `CONSUME egg quantity=2`。
  - 给定「我给你做鸡蛋卷」，提取出 `CREATE 鸡蛋卷`（**未来意向句**是否提取见 §边界，默认按"已发生"处理并以校验兜底）。
  - 给定「你把鸡蛋放哪了？」（疑问句），提取结果为空。
  - 给定「如果饿了我可以做面」（假设/未发生），提取结果为空或不产生可执行候选。
  - 提取阶段对 World 的写入次数为 0。

---

## ACTION-003 — Action Validation（Core）

- **ID**: ACTION-003
- **Priority**: **P0**
- **Goal**: 在动作执行前完成确定性校验，失败一律不修改 World。
- **Scope**: 总闸/置信度门；对象存在性；数量充足性；`consumable` 可消耗性；地点可解析与位置合理性；实体容量上限；同名实体重复；幂等去重；轮内 sequential 校验（working view）。
- **Non-Scope**: 不做状态迁移（ACTION-004）；不做自然语言推理；不改引擎函数签名；不引入 grounding 校验（属另行立项）。
- **Dependency**: ACTION-001, ACTION-002。
- **Reuse**: `world_engine.find_object_by_name` / `_find_inventory_object` 语义；`ConsumeError` 错误码；`HOME_LOCATIONS` 白名单与 `resolve_location_alias`；`world_active_entities_limit` 上限。
- **Acceptance**:
  - 给定库存 6 个鸡蛋与 `CONSUME egg 2`，校验通过。
  - 给定库存 1 个鸡蛋与 `CONSUME egg 5`，判 `INSUFFICIENT_QUANTITY` 且 World 零变更。
  - 给定不存在的物品（番茄汤）与 `CONSUME`，判 `OBJECT_NOT_FOUND`。
  - 给定 `MOVE 牛奶 → 桌上`（`HOME_LOCATIONS` 无桌面节点），判 `LOCATION_UNRESOLVED` 且 World 零变更。
  - 给定同轮两条 `CONSUME 鸡蛋 1` 而库存仅 1，仅第一条通过。
  - 校验阶段对 World 的写入次数为 0。

---

## ACTION-004 — World Engine Mutation（Core）

- **ID**: ACTION-004
- **Priority**: **P0**
- **Goal**: 将校验通过的 `WorldAction` 经**既有 World Engine** 写入世界，支持 CREATE / MOVE / CONSUME 三类。
- **Scope**: 动作 → 引擎函数映射（`create_object` / `move_object` / `consume_object`）；文本顺序执行；结果回读校验；失败不部分扣除；写入后记录 `WorldEvent(type=character_action)`。
- **Non-Scope**: 不直接调用 `world_repository` 改实体状态；不实现新状态机（复用 V8 物品状态机）；不引入新的 World 表；不实现 Cooking。
- **Dependency**: ACTION-001, ACTION-003。
- **Reuse**: `world_engine.create_object` / `move_object` / `consume_object`（**已存在的 Consume API**）/ `world_engine.consume_object` 的 `ConsumeResult`；`world_repository.save_event` + `WorldEvent`；`infer_object_category`。
- **Acceptance**:
  - 给定 `CONSUME egg 2` 于库存 6，执行后库存为 4 且 `ConsumeResult.ok=True`。
  - 给定 `CREATE 面`，执行后 `world_entities` 出现该活跃实体且可被后续 MOVE/CONSUME 引用。
  - 给定 `MOVE 牛奶 → home.kitchen`，执行后 `location_id` 变更。
  - 给定引擎返回 `None`/`ok=False`，该动作判 failed，库存与状态零变化（无部分扣除）。
  - 一条回复含 CREATE + CONSUME 时，按文本顺序执行且 CREATE 产物可被同轮引用。
  - 世界中不存在由"角色回复文本"直接产生的实体（全部可归因到引擎调用）。

---

## ACTION-005 — Context 与历史同步（Integration）

- **ID**: ACTION-005
- **Priority**: **P1**
- **Goal**: 让下一轮角色知道最近发生的世界变化，闭合"行为 → 世界 → 上下文"回路。
- **Scope**: 已 applied 动作落成可查询历史（`WorldEvent(type=character_action)`）；追加 `world.notes` 本轮摘要（与既有 interpreter notes 合并而非覆盖）；`WorldContext` 新增「最近世界变化」条目并在 `render_world_section` 内受预算渲染；trace 汇总。
- **Non-Scope**: 不直接写 Memory / Reflection / Relationship；不改 12000 / 600 总预算；不新增 prompt 段标题（复用【当前世界】）。
- **Dependency**: ACTION-004。
- **Reuse**: `World.notes` + `bounded_notes`；`world_repository.list_events` / `save_event`；`services/world/context_selector.build_world_context` / `render_world_section` 与 `world_context_char_budget`；`models/observability.bound_extra`；Memory 2.0 的 `fetch_completed_world_events` 摄取通道（自然受益）。
- **Acceptance**:
  - 给定本轮消耗鸡蛋 2 个，下一轮 `WorldContext` 含「消耗鸡蛋 2 个」且渲染在【当前世界】段内。
  - 给定本轮 CREATE 一个实体，下一轮上下文含该实体且库存列表出现真实数量。
  - 给定既有的用户消息世界迁移（interpreter notes）与本轮角色动作，两类摘要**同时存在**（不互相覆盖）。
  - 总闸关闭时，【当前世界】渲染逐字节等同现状（golden 不变）。
  - 给定同一 turn 重放，`character_action` 事件不重复累积。

---

## Milestone（交付序）

```text
M1 Contract:   ACTION-001 → unlock 全部并行开发
M2 Pipeline:   ACTION-002 ∥ ACTION-003 ∥ ACTION-004（003/004 依赖 001 契约）
M3 Close Loop: ACTION-005 → 端到端验收
M4 Acceptance: 复现 household-inventory-review 对话 + 回归清单全过
               → 申请开启 v2_character_action_sync_enabled
```

## 端到端验收场景（Acceptance 阶段）

直接复现 [`docs/household-inventory-review.md`](../../../../household-inventory-review.md) 的对话，作为本模块的 Acceptance 用例：

| 轮次 | 角色回复 | 期望同步结果 | 期望下一轮上下文 |
|---|---|---|---|
| N | 「将切好的菜倒入锅中。有煎蛋卷和番茄汤。」 | 无（叙述性 / 存在性声称，非三动作） | 库存不变 |
| N+1 | 「将盛好的煎蛋卷放在桌中央。」 | CREATE 煎蛋卷（若地点可解析）；否则拒绝并有 trace | 世界出现煎蛋卷（或如实拒绝） |
| N+2 | 「没了。刚才那枚刚好用完。」 | 需先有 CONSUME 记账（角色"用"的那轮） | 鸡蛋数量 = 6 − 已记账消耗 |
| N+2 | 「只用了一个。」 | 与前序 CONSUME 一致 | 下一轮答出真实数量 |

> 说明：本轮验收只保证 **P1（消耗记账）/P3（移动记账）/P7（创建可见）** 三项；P4/P5（存在性声称、数量分割）见 [architecture.md](architecture.md) §12.2，另行立项。

## 全局实现约束（每个 Task 均适用）

1. **零新表 / 零迁移**：不新增数据库表；所有持久化复用既有 `world_*` 与 `runtime_traces`。
2. **唯一写入出口**：任何世界变更只能经 `world_engine` 公开函数（`create_object` / `move_object` / `consume_object`）。
3. **禁止回复直写**：不得在 `answer_chain` / prompt / chain 内直接写库。
4. **后台专属**：本模块只在 `post_process` 内运行；前台链路与 prompt 字节级不变（总闸关闭时）。
5. **不新增前台 LLM**：可选 LLM 提取通道仅后台、默认关闭、计入日预算。
6. **降级优先**：任何异常 → 空候选 + log + trace，聊天永不因本模块失败。
7. **命名表达意图**：遵守项目约定"不添加代码注释"（`AGENTS.md`）。
8. **Flag 纪律**：一个总闸 + 少量参数，禁止碎闸泛滥（对齐 v2.0.0 `README.md` §10.2）。
