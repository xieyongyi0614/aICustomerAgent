# Character Action Sync — 架构设计

> 阶段：**v2.0.0 Acceptance**
> 模块：Character Action Sync（角色行为同步）
> 状态：**设计完成，未实现（Architecture & Documentation only）**
> 上游证据：[`docs/household-inventory-review.md`](../../../../household-inventory-review.md)（Household Inventory 对话审查报告）
> 铁律：**不新建第二套 World 系统；AI 回复文本不得直接写库；所有世界修改必经 `WorldAction → Validator → World Engine`。**
> 只读归档：`docs/version/v1.0.0/` 不得修改。

---

## 0. TL;DR

角色说「我给你做鸡蛋卷，我用了两个鸡蛋」，这句话目前**只是文本**。世界库存不会变化，于是下一轮角色又看到 6 个鸡蛋，继续编造。根因不是提示词不够狠，而是**「角色自主动作」这条写入通道根本不存在**：世界解释器只吃用户消息（`interpreter.interpret(user_message)`），从不读角色回复。

本模块新增一条**角色叙事行为 → 结构化世界动作 → 校验 → 世界引擎 → 状态变更**的同步层，第一阶段只支持 `CREATE / MOVE / CONSUME` 三种动作。它不引入新世界、不引入新事实源，只是把「角色嘴上做的事」翻译成「世界引擎已经会做的事」，并在校验不通过时**拒绝执行而非造事实**。

一句话边界：

```text
本模块只解决「角色行为如何进入 World」。
本模块不解决 Cooking / Recipe / Shopping / Autonomy / Goal Planning / Desire。
```

---

## 1. 为什么需要 Character Action Sync

### 1.1 Narrative 不等于 Fact

角色回复是**叙事**（narrative）：为对话服务的自然语言表达，可以省略、可以含蓄、可以带修辞。世界状态是**事实**（fact）：可查询、可结算、可被后续检索与统计的账目。

两者天然不是一回事：

| | Narrative（角色回复） | Fact（World State） |
|---|---|---|
| 载体 | 一段自然语言 | `world_entities` / `worlds` 行 |
| 精度 | 模糊（"剩点面""半盒牛奶"） | 精确（`quantity=2`、`state=available`） |
| 生命周期 | 随对话上下文消亡 | 跨轮、跨会话持久 |
| 修改者 | LLM 生成 | 只能由代码写入 |
| 能否被信任 | 不能（LLM 会编） | 是唯一真相来源 |

把 narrative 直接当 fact 使用，等于把 LLM 的自由发挥当成数据库。`household-inventory-review.md` 已给出真实反例：用户问「鸡蛋没了吗」，角色答「没了」，而库存 6 个、全程零迁移。

### 1.2 LLM 输出不能直接修改 World

LLM 是本系统的三类引擎（Reasoning / Generation / Evaluation）之一，**不是**状态所有者。它输出的文本可以被人类理解，但字段级不确定性极高：数量可能用中文数字、可能省略、可能是假设句、可能是复述用户的话。

因此必须引入**结构化中间层**：先由提取器把文本变成候选结构化动作，再由确定性校验器逐条裁决，最后由世界引擎执行。LLM 的输出在这条链上**只是输入，不是命令**。

### 1.3 World 必须有唯一事实来源（Single Source of Truth）

v1.0.0 已明确 World Domain 的 SoT 是 `worlds` + `world_entities` + `world_events` 三张业务表（见 [`version-boundary.md`](../../version-boundary.md)）。若允许「角色回复 → 直接改库存」，就会出现第二条写入路径，账目必然分叉。

本模块**不新增事实源**：它只是给既有 World Engine 增加一个**调用者**（caller）。

### 1.4 直接证据（来自审查报告）

审查报告已定位到根因（第 4 条「自主动作不记账」）：

- 世界的消耗**只能由用户消息经解释器触发**（`interpreter.py` 的吃/喝/拿/扔动词 + `world_engine.run_turn_update`）。
- 角色自己「用鸡蛋做煎蛋卷」这类**自主行为没有任何机制把库存扣减**。
- 于是「角色叙事里的消耗」与「世界库存」成为两条互不同步的线。

审查报告第 4 节给出的三个改进方向中，**方向 2（角色自主消耗记账）与方向 3（叙事回写钩子）正是本模块的职责**；方向 1（库存数量强制校验 / grounding）属提示与 grounding 平面，**不在本模块范围内**（见 §12 残留问题）。

---

## 2. 当前架构问题

### 2.1 现状：AI Reply 是链路的终点

`application/post_process.py` 的 `STEP_HANDLERS` 目前 9 步，其中与世界相关的是：

- 第 8 步 `run_world_update` → `world_engine.run_turn_update(ctx.user_id, ctx.user_input)`：**只吃 `ctx.user_input`**。
- 第 9 步 `run_action_planning` → 消费**用户消息**检出的 `ActionIntent`（`detector.detect_action_intent(content=用户消息)`），且 `action_enabled` 出厂默认 **False**。

角色回复 `ctx.ai_reply` 虽然被 `run_scene_update`（叙事场景）与 `run_memory_extract`（记忆）读取，但**没有任何步骤把它翻译成世界变更**。

```text
当前（断裂）
─────────────────────────────────────────────
User Message ──► Chat Pipeline ──► AI Reply ──► 落库 ──► 结束
     │                                                        ▲
     └──► interpreter ──► world_engine ──► World State         │
                                    （角色行为在此缺席）─────────┘

结果：
     角色行为 ≠ 世界变化
```

### 2.2 目标：把 AI Reply 纳入写入链，但只作为「提案」

```text
目标（同步）
─────────────────────────────────────────────
User Message ──► Chat Pipeline ──► AI Reply
     │                                 │
     │                                 ▼
     │                        Action Extraction      （只产出候选，不写库）
     │                                 │
     │                                 ▼
     │                            WorldAction        （结构化值对象）
     │                                 │
     │                                 ▼
     │                        World Validation       （确定性裁决，失败即拒绝）
     │                                 │
     ▼                                 ▼
interpreter ──►              World Engine            （既有 create/move/consume）
                                   │
                                   ▼
                              Persistence            （世界唯一事实源）
                                   │
                                   ▼
                             Context Update          （下一轮可见）
                                   │
                                   └──► Next Turn
```

### 2.3 问题清单（本模块要解决 / 不解决的）

| # | 问题 | 本模块是否解决 | 说明 |
|---|---|---|---|
| P1 | 角色自主消耗不记账（用了 N 个鸡蛋，库存不变） | **解决** | CONSUME 动作 + 既有 `consume_object` |
| P2 | 角色创造不存在的物品（"我做好了一碗面"） | **部分解决** | 只处理"角色做/产生了某物"的 CREATE 动作 |
| P3 | 角色移动物品位置（"把牛奶拿到桌上"） | **解决** | MOVE 动作 + 既有 `move_object` |
| P4 | 角色声称"有某物"但该物不存在（"有番茄汤"） | **不解决** | 存在性声称不是动作，属 grounding 平面（§12） |
| P5 | 数量/状态张口就来（"半盒牛奶"） | **不解决** | 数量分割不属三种动作，属 grounding 平面（§12） |
| P6 | 下一轮角色不知道上一轮世界发生过什么 | **解决** | ACTION-005 Context 与历史同步 |
| P7 | 角色创造的物品在 World 不可见（无法被后续 MOVE/CONSUME） | **解决** | CREATE 落 `world_entities`，复用既有实体通道 |

---

## 3. 设计目标与不变量

### 3.1 目标

1. **闭合写入通道**：角色叙事中的行为可在同轮进入 World。
2. **可验证**：每条世界变更都能回答「因为哪句话、通过了哪条校验、执行了哪个引擎函数」。
3. **可拒绝**：校验不通过一律不修改 World（宁缺毋滥，不造事实）。
4. **可复用**：零新世界系统；复用 `world_entities` / `world_engine` / `scene_state` / `world_events` / `persistence` 与既有 observability。
5. **可回滚**：单一 Feature Flag 关闭即回到现状（prompt 与行为字节级不变）。
6. **可延展**：为 Cooking / Recipe / Relationship / Life Loop / Autonomy 留出接入点而不预先实现。

### 3.2 不变量（Invariants，实现期必须永真）

| ID | 不变量 |
|---|---|
| INV-1 | 角色回复文本**永远不能**直接写 `world_entities` / `worlds` / `world_events`。 |
| INV-2 | 任何世界状态变更只能由 `WorldAction → Validator → World Engine` 路径产生。 |
| INV-3 | Validator 判定失败时，World 零变更（无部分扣除、无补偿写入）。 |
| INV-4 | 提取阶段（Action Extraction）是**纯读取**：读 `ai_reply` / `scene_state` / 世界切片，零写库。 |
| INV-5 | 世界事实唯一真相源仍是 `worlds` / `world_entities` / `world_events`；本模块不引入第二事实源。 |
| INV-6 | 总闸关闭时，链路零执行、prompt 零字节变化、世界零变更。 |
| INV-7 | 前台链路（chat pipeline）不新增 LLM 调用；提取的 LLM 通道仅后台、且默认关闭。 |
| INV-8 | 所有世界读写仍受 `post_process` 的 per-user 写锁保护（`get_user_write_lock`）。 |

---

## 4. 模块边界

### 4.1 三层职责

严格三层，不交叉：

```text
┌───────────────────────────────────────────────────────────────┐
│ Character Layer（角色层）                                      │
│ 负责：性格 · 决策 · 行为意图                                    │
│ 既有：character/asuna/*（identity/personality/modes/…）        │
│ 本模块：新增「叙事行为词表与句型资产」——只是"设定"，无逻辑。      │
│ 不做：不校验、不写世界、不知道世界引擎长什么样。                  │
└───────────────────────────────┬───────────────────────────────┘
                                │ 角色回复文本（narrative）
┌───────────────────────────────▼───────────────────────────────┐
│ Action Layer（动作层）—— 本模块新增                              │
│ 负责：行为结构化 · 参数解析 · 校验                               │
│ 组成：Action Extractor（提取候选）→ WorldAction（值对象）        │
│       → Action Validator（确定性裁决）                          │
│ 不做：不生成叙事、不解释世界语义、不直接落库（除经 World Engine）。│
└───────────────────────────────┬───────────────────────────────┘
                                │ 已校验的 WorldAction
┌───────────────────────────────▼───────────────────────────────┐
│ World Layer（世界层）—— 既有，只增不改                          │
│ 负责：状态变化 · 数量变化 · 持久化                               │
│ 既有：world_engine / world_entities / world_events /           │
│       world_repository / scene_state（只读咨询）                │
│ 不做：不解析叙事、不理解 LLM、不做自然语言推理。                   │
└───────────────────────────────────────────────────────────────┘
```

**裁决规则**：三层之间只传「值对象」。Character 层传文本；Action 层传 `WorldAction`；World 层只接受结构化参数返回结构化结果（如 `ConsumeResult`）。任一层的失败都不向上一层抛出异常——**降级为「本轮不做该动作」**（沿 v1「聊天永不因世界而失败」纪律）。

### 4.2 与既有域的边界

| 既有域 | 与本模块的关系 | 触碰方式 |
|---|---|---|
| **World（V8）** | 被复用 | 仅调用 `world_engine` 公开函数；不改 V8 模型、不改解释器语义 |
| **Scene（V3）** | **只读咨询** | 读 `SceneState`（`current_action` / `pending_action` / `location`）辅助指代消解与位置合理性；**不写 scene_state** |
| **Action（V9）** | **平行、不合并** | V9 处理「用户祈使行动」，本模块处理「角色叙事行为」；两者都写 World，但通道独立（见 §4.4） |
| **Memory 2.0（P1）** | **下游受益** | 落库的 WorldEvent 会被 `memory_sources.fetch_completed_world_events` 摄取 → 角色"记得自己做过饭"（无需本模块直接调用 Memory） |
| **Relationship（V8.5）** | 未来扩展 | 本阶段不投递关系信号（见 §11） |
| **Reflection / Development** | 未来扩展 | 本阶段不产出 Insight（见 §11） |
| **Observability** | 被复用 | 复用 `runtime_traces` 与 `trace.record(...)`，不新建存储 |

> **关于 Scene 的边界争议（需在设计评审明确）**：`services/world/locations.py` 的文档纪律写明「不读写 `scene_state`——叙事位置与世界事实独立并存」。本模块读 `scene_state` 会触碰这条纪律。裁决建议：CAS 属于**同步边界层**，不是 World Domain 核心；World Engine 本身仍不读 `scene_state`，只有 CAS 作为"翻译层"读取它以改善指代消解与位置合理性判断，且该读取**仅为 advisory，永不作权威依据**。若评审不接受，则降级方案为 CAS 完全不读 scene_state（功能损失仅限指代替换率）。

### 4.3 Non-Goals（本阶段明确不做）

> 按任务要求，以下内容**只留扩展点，不实现**：

- ❌ Recipe / 食谱系统 / 自动做饭 / 烹饪状态机
- ❌ Shopping / 购买流程
- ❌ Autonomy / Life Loop 驱动的角色自主动作
- ❌ Goal Planning / Sub-Goal / Desire System
- ❌ 多角色 / 多人世界
- ❌ 关系信号、记忆写入、反思产出（由其他 Phase 负责，本模块只产出可被它们消费的 WorldEvent）
- ❌ 存在性声称（"有 X"）与数量分割（"半盒"）的 grounding 校验（属提示/grounding 平面，见 §12）
- ❌ 第二条世界账本 / 状态缓存 / 影子世界

### 4.4 三条写入链的关系（避免概念债）

v2.0.0 总览已指出 v1 存在「五种意图/动作模型并行」的概念债（`README.md` §3.3）。本模块**不新增第六种世界写入路径**，而是明确三条链的分工：

```text
① 用户消息 → interpreter（规则解释器，V8）      → world_engine   [既有]
② 用户祈使 → ActionDetector/Planner（V9）      → world_action 能力 [既有，默认关]
③ 角色叙事 → Character Action Sync（本模块）    → world_engine   [新增，默认关]

三条链共用同一个出口：world_engine 的世界写入函数。
三条链互不调用、互不改写对方的记录。
并发安全由 post_process 的 per-user 写锁统一保证。
```

> **为什么不复用 V9 ActionRecord 承载本模块？** 因为 V9 的 `ActionType` / `ActionSource` 是闭合字面量（不含 consume，也不含 `character_reply`），其六态状态机语义面向"用户请求的执行"，与本模块"叙事行为提案"的语义（candidate/validated/rejected/applied）不同。强行合并需要改 V9 枚举与状态机，属于对既有域的非必要改造，违背 version-boundary 的 Preserve 约束。**结论：平行、不合并**；若未来二者收敛，另立 Phase 处理。

### 4.5 单一真相源裁决（三层账本，职责不重叠）

| 账本 | 定位 | 是否权威 | 存储 |
|---|---|---|---|
| `worlds` / `world_entities` | **世界当前状态（SoT）** | ✅ 唯一权威 | 既有表，不改 |
| `world_events`（本模块写入的 `character_action` 事件） | **世界变更历史 / 审计** | ❌ 历史投影，不可作为当前状态读 | 复用既有表，不新增列 |
| `runtime_traces` | **决策归因**（为什么拒绝） | ❌ 观测旁路 | 复用既有表 |

**硬规则**：任何代码不得以「历史上发生过 X」推断「现在 X 还在」。当前状态只能读 `world_entities`。

---

## 5. 数据流

### 5.1 一次聊天的完整数据流（本模块切入后）

```text
Next Turn ─────────────────────────────────────────────────────────────┐
                                                                       │
  ┌── 读取进链（前台，无写入）────────────────────────────────────┐     │
  │  User Message                                                │     │
  │      ↓                                                       │     │
  │  world_engine.build_context()  ← 注入 最近世界变化（ACTION-005）│     │
  │      ↓                                                       │     │
  │  context_builder（库存清单 + 引导语"以本清单为准，不得凭空捏造"）│     │
  │      ↓                                                       │     │
  │  4 链并行 + answer_chain                                     │     │
  │      ↓                                                       │     │
  │  Character Response ────────────────────────────────────────►│ 落库 │
  └──────────────────────────────────────────────────────────────┘     │
                                   │（同一轮后台，per-user 写锁内）      │
  ┌── 写出链（后台 post_process，本模块插入点）────────────────────┐    │
  │  … 既有 1~7 步（state / goal / summary / memory / eval）…      │    │
  │  第 8 步  run_world_update（既有）：interpreter 读 user_input  │    │
  │  第 9 步  run_character_action_sync（新增，本模块）◄──────────┐ │    │
  │      Character Response                                      │ │    │
  │          ↓                                                   │ │    │
  │      Action Extraction（规则词表，纯读取）                     │ │    │
  │          ↓                                                   │ │    │
  │      WorldAction 候选（status=candidate）                     │ │    │
  │          ↓                                                   │ │    │
  │      Validation（对象存在/数量足够/可消耗/位置合理/容量/去重）  │ │    │
  │          ├─ 失败 → status=rejected，World 零变更，写 trace     │ │    │
  │          └─ 通过 → status=validated                           │ │    │
  │                     ↓                                        │ │    │
  │      World Engine（既有 create_object / move_object /         │ │    │
  │                     consume_object）                          │ │    │
  │                     ↓                                        │ │    │
  │      World State Mutation（world_entities / worlds）          │ │    │
  │                     ↓                                        │ │    │
  │      记录 WorldEvent(type=character_action) + 追加 notes      │ │    │
  │  第 10 步 run_action_planning（既有，V9）                      │ │    │
  └──────────────────────────────────────────────────────────────┘     │
                                                                       │
  Context Update（下一轮 render【当前世界】时可见「最近世界变化」）──────┘
```

### 5.2 分层数据流表

| 阶段 | 输入 | 输出 | 写库 | LLM | 失败语义 |
|---|---|---|---|---|---|
| Extraction | `ctx.ai_reply`、`scene_state`（只读）、世界切片（库存名/当前位置）、turn 引用 | `list[WorldAction(status=candidate)]` | ❌ 零写 | 默认 ❌；可选通道 ✅（默认关） | 返回空列表 |
| Validation | 候选 `WorldAction` + 世界快照 | 每条 → `validated` / `rejected(reason)` | ❌ 零写 | ❌ | 单条拒绝，不影响其他条 |
| Mutation | `validated` 的 `WorldAction` | 变更后的实体 / `ConsumeResult` / CREATE 后的新对象 | ✅ **仅经 world_engine** | ❌ | 该条 failed，不部分扣除 |
| Context Sync | 已 applied 的动作 + 结果 | `WorldEvent(character_action)`、`world.notes` 摘要、trace | ✅ 经 world_engine / world_repository | ❌ | 记录失败仅 log，不回滚状态变更 |

### 5.3 读写纪律与并发

- **读取进链、写入出链**（v1 既有约定）：本模块全部在 `post_process` 内执行，前台链路零改动。
- **per-user 写锁**：`run_post_process` 已包在 `get_user_write_lock(user_id)` 内；本模块作为 STEP_HANDLERS 成员天然持有该锁，**不得自行开线程/任务绕开锁**。
- **顺序**：`run_world_update`（第 8 步）先执行，`run_character_action_sync`（第 9 步）后执行。理由：用户消息的世界迁移先落地，角色动作基于**已更新的**世界状态校验，避免两个通道在同一轮内互相看不见对方的结果。
- **轮内先后**：一条回复可能同时含 CREATE + CONSUME（"我做好鸡蛋卷，用了两个鸡蛋"）→ 必须**按文本顺序**执行，使 CREATE 产出的实体可被同轮后续动作引用。

---

## 6. WorldAction 契约（总览）

完整字段与状态机见 [ACTION-001](task-details/ACTION-001.md)。总览：

```text
WorldAction
├── action_type : CREATE | MOVE | CONSUME          （第一阶段仅三值）
├── actor       : character                        （预留 user / autonomy）
├── target      : { name, object_id?, category?, location_id? }
├── quantity    : float | null                     （CREATE 默认 1；CONSUME 显式或默认 1 份）
├── source      : character_reply | user_message | autonomy | …
├── metadata    : { evidence, span, location_id, unit, before, after, channel, confidence }
├── status      : candidate | validated | rejected | applied | failed | skipped
├── dedupe_key  : str                              （幂等键）
└── turn_ref    : { session_id, turn_id, ordinal }
```

语义映射（一次角色行为 → 一个 WorldAction）：

| 角色叙事例 | action_type | target | quantity | 落到 World Engine |
|---|---|---|---|---|
| 我做好了一碗面 | CREATE | `{name: "面"}` | 1 | `create_object(...)` |
| 我把牛奶拿到桌上 | MOVE | `{name: "牛奶"}` + `location_id` | null | `move_object(...)` |
| 我用了两个鸡蛋 | CONSUME | `{name: "鸡蛋"}` | 2 | `consume_object(...)` |

---

## 7. 三道闸（提取 → 校验 → 执行）

```text
                  ┌── 闸 1：提取（Action Extraction）
「我用了两个鸡蛋」 │   问题：这句话在不在说一件已发生的行为？
                  │   纪律：宁缺毋滥——疑问句/假设句/未来计划/复述 一律不提取
                  └── 产出：candidate（可带低置信度）

                  ┌── 闸 2：校验（Action Validation）—— 唯一权威裁决
candidate          │   问题：世界允不允许这件事？
                  │   对象存在？数量足够？可消耗？位置合理？容量未满？重复？
                  └── 失败：status=rejected，World 零变更（INV-3）

                  ┌── 闸 3：执行（World Engine Mutation）
validated          │   只调用既有引擎函数；引擎自身再校验一次（双保险）
                  │   consume_object 会二次核对 consumable 与库存量
                  └── 失败：status=failed，不部分扣除

applied ──► 记录 WorldEvent + 追加 notes ──► 下一轮可见
```

**为什么校验要独立成闸而引擎已经会校验？** 引擎的校验是**最终安全网**（防脏写），校验闸是**可归因决策点**（能回答"为什么这条没生效"）。二者职责不同，必须都在。

---

## 8. 失败与降级策略

| 失败点 | 表现 | 处理 | 对用户的影响 |
|---|---|---|---|
| 总闸关闭 | `v2_character_action_sync_enabled=False` | 步骤直接 return | 无（现状行为） |
| 提取异常 | 词表解析抛错 | 捕获 → 空候选 → trace error | 无（本轮不同步） |
| 源开关缺失 | `/chat` 无 user_id / world | 空候选 | 无 |
| 校验失败 | 逐条原因 | `rejected` + trace | 无；世界不变，下一轮角色看到真实状态可自纠 |
| 引擎失败 | `None` / `ConsumeResult(ok=False)` | `failed` + trace | 无 |
| 记录事件失败 | DB 异常 | log + trace，**不回滚已生效的状态变更** | 无（状态已正确） |
| 世界不可用 | `world_enabled=False` | 空候选 | 无 |

**总原则**：本模块的任何失败都不得影响本轮回答、不得让聊天链失败、不得留下半截状态。

---

## 9. 幂等与事务边界（总览）

### 9.1 幂等

- **键**：`dedupe_key = hash(action_type, actor, target.canonical_name, quantity, source, session_id, turn_id, ordinal)`，风格对齐既有 `models/action.py:make_dedupe_key`。
- **域内去重**：同一轮内，已 accepted 的动作集合参与后续候选去重。
- **跨轮去重（有界窗口）**：查询最近 `world_events`（`type=character_action`）的 `payload.dedupe_key` 集合，命中即 `rejected(reason=DUPLICATE)`。窗口大小进 settings。
- **保证范围（诚实声明）**：本阶段保证「同轮内 + 有界近期窗口」幂等；**跨进程崩溃后的强幂等不保证**。强幂等依赖 P5/LIFE-004 已铺设的 `background_jobs` / `outbox_events`（迁移 0029/0030）——本模块为该演进预留 `source` 与 `dedupe_key` 字段（见 [ACTION-004](task-details/ACTION-004.md) §幂等）。

### 9.2 事务边界

- 每个世界写入由**既有引擎函数内部独立提交**（各 repository 各自 `SessionLocal()`），因此**单动作原子**成立。
- **整轮不原子**：第 3 条动作失败不会回滚第 1 条。这是**有意设计**——世界状态是"发生过即成立"，补偿回滚反而制造新的不一致。
- 因此顺序至关重要：候选按**文本顺序**执行；后续动作基于前序动作产生的中间状态校验（working view）。
- 校验闸在真正写入前完成全部前置检查，使"引擎失败"成为罕见路径；一旦发生，`failed` 记录 + trace 供人工定位。

---

## 10. 可观测性（总览）

复用既有 `runtime_traces` 与 `trace.record(...)`（`observability.py` / `bound_extra`）：

```text
trace 步骤：character_action_sync
  ├─ 汇总：candidates / validated / applied / rejected / skipped / duration_ms
  └─ 逐条（bounded）：{action_type, target, quantity, status, reason, engine_fn}
```

必须能回答的六问（对齐 P1 的 trace 纪律）：

1. 本轮角色说了哪些可能的世界行为？→ candidates + evidence span
2. 哪条被拒绝了？为什么？→ reason（枚举）
3. 哪条被执行了？调了哪个引擎函数？→ engine_fn + before/after
4. 为什么没同步？（总闸关 / 无候选 / 全被拒 / 异常）→ 汇总状态
5. 世界现在是什么？→ 只能读 `world_entities`（debug API 既有）
6. 下一轮角色看到了什么？→ `world.notes` + `WorldContext.recent_world_changes`

---

## 11. 未来兼容扩展点（本阶段只留接口，不实现）

| 未来能力 | 本模块预留的接入点 | 本阶段不做 |
|---|---|---|
| **Cooking** | `action_type` 枚举可扩（如 `COOK`）；规则提取词表可扩；引擎可扩 `apply_object_action` 状态 | 不实现 Recipe / 烹饪状态机 |
| **Recipe** | `WorldAction.metadata.recipe_ref` 预留；多动作可由更上层编排为动作序列 | 不实现配方匹配与配料表 |
| **Relationship** | `source` 字段可标记行为来源，供未来关系信号映射（可参考 V9 `ACTION_RELATIONSHIP_MAP` 模式） | 不投递关系信号 |
| **Life Loop** | `actor=autonomy` + `source=autonomy` 已预留；`dedupe_key` 支持后台重放 | 不接 Life Loop |
| **Autonomy / Goal** | 同上；动作序列化能力（多个 WorldAction）天然支持 Plan → Act | 不实现规划 |
| **Memory / Reflection** | 已 applied 的动作落成 `WorldEvent`，被既有 Memory 2.0 摄取通道自然消费（`fetch_completed_world_events`） | 不直接调 Memory/Reflection |
| **强幂等 / 分布式** | 走 P5 的 `background_jobs` / `outbox_events` | 不引入队列 |

---

## 12. 风险、已知限制与残留问题

### 12.1 已知限制

| 限制 | 说明 | 影响 |
|---|---|---|
| **回复先于状态变更** | 回复生成时读到的是**上一轮**世界；同步在本轮后台才发生 | 角色本轮叙事与最终世界可能有细微时序差；下一轮可自纠（Context 已同步） |
| **整轮非原子** | 见 §9.2 | 极端情况下部分动作生效 |
| **提取召回率有限** | 规则词表覆盖有限；复杂表达可能漏提 | 漏提 = 不同步（安全侧），不会造事实 |
| **可选 LLM 通道有成本** | 默认关闭；开启后每轮 +1 次后台 LLM | 计入日预算 |
| **`HOME_LOCATIONS` 缺桌面节点** | 现状**没有**餐桌/桌面地点（仅 home / living_room / kitchen / bedroom / balcony / fridge / cabinet / bathroom） | 审查报告里的「牛奶拿到桌上」MOVE **会因目标地点无法解析而被拒绝**——这是正确行为（不造地点），但功能上缺失。需决策：本阶段是否新增 `home.dining_area` 静态节点（唯一资产变更，见 [ACTION-003](task-details/ACTION-003.md)/[ACTION-004](task-details/ACTION-004.md)） |

### 12.2 残留问题（本模块明确不解决，需另行立项）

审查报告的三个根因中，本模块覆盖「自主动作不记账」，但**不覆盖**：

| 残留 | 报告条目 | 归属 |
|---|---|---|
| LLM 凭空声称库存（"没了"，实际 6 个） | 问题 ① | grounding / 提示约束平面（报告方向 1） |
| 凭空存在物（"有番茄汤"） | 问题 ② | grounding（存在性声称不是动作） |
| 数量/状态张口就来（"半盒牛奶""昨晚的面"） | 问题 ③ | grounding（数量分割不是动作） |

**但是**：本模块上线后，这三类的**触发面会显著缩小**——因为 P1/P3 记账后，"角色真的消耗/创建/移动过什么"变成可查询事实，下一轮 Context 会给出真实数量，LLM 编造的空间被压缩。

建议配套（不属本模块、另行立项）：**回复-世界一致性守卫**（reply grounding check），对回复中涉及库存的陈述做校验，属提示与评估平面。

---

## 13. 验收与回归

- Task 拆分、依赖、Acceptance 见 [tasks.md](tasks.md)。
- Task 详细工程设计见 [task-details/](task-details/)。
- **端到端验收场景**：直接复现 [`household-inventory-review.md`](../../../../household-inventory-review.md) 的对话（鸡蛋 6 → 角色声称用了 1 个 → 库存 6→5 → 下一轮角色知晓"消耗鸡蛋 1 个"）。
- **回归基线**：总闸关闭时，世界零变更、prompt 字节级不变、v1 全量 pytest 不变。

---

## 14. 文档地图

```text
docs/version/v2.0.0/acceptance/character-action-sync/
├── architecture.md              ← 本文件（为什么 / 边界 / 数据流）
├── tasks.md                     ← ACTION-001~005 任务拆分 + Milestone
└── task-details/
    ├── ACTION-001.md            ← WorldAction 基础模型与状态机
    ├── ACTION-002.md            ← AI Reply Action Extraction
    ├── ACTION-003.md            ← Action Validation
    ├── ACTION-004.md            ← World Engine Mutation
    └── ACTION-005.md            ← Context 与历史同步
```

---

## 附录 A：真实代码坐标（审计锚点）

> 本设计基于对 `apps/backend/app/` 的真实代码审计，以下为关键锚点。

| 关注点 | 真实位置 | 现状 |
|---|---|---|
| 后台步骤注册表 | `application/post_process.py` `STEP_HANDLERS` | 9 步；第 8 步 world、第 9 步 action |
| 世界更新入口（只吃用户消息） | `application/world_engine.py` `run_turn_update(user_id, message)` | 调用 `interpret(message, …)` |
| 规则解释器 | `services/world/interpreter.py` `interpret(...)` | 动词表：拿/放/切/吃/扔/买；`WorldUpdateResult` |
| **统一 Consume API（复用点）** | `application/world_engine.py` `consume_object(user_id, object_ref, quantity)` → `ConsumeResult` | 已具备 `consumable` / 数量 / `INSUFFICIENT_QUANTITY` 校验 |
| 创建 / 移动 | `world_engine.create_object(...)`、`move_object(...)` | 含 `world_active_entities_limit` 上限、`HOME_LOCATIONS` 白名单 |
| 实体模型 | `models/world.py` `WorldObject` | id/name/aliases/category/location_id/state/quantity/unit/consumable/properties/status |
| 事件模型 | `models/world.py` `WorldEvent`（`type: str` 自由串、`source: EventSource`） | 可承载 `character_action` 类型 |
| 世界上下文 | `services/world/context_selector.py` `build_world_context` / `render_world_section` | 已含 `inventory` + `notes` + 引导语（L119） |
| 地点设定 | `character/asuna/world.py` `HOME_LOCATIONS` / `LOCATION_ALIASES` | **无桌面/餐桌节点** |
| 类目推断 | `character/asuna/action.py` `infer_object_category` / `OBJECT_CATEGORY_KEYWORDS` | 可复用 |
| 场景状态（只读咨询） | `models/scene.py` `SceneState`（location/current_activity/current_action/pending_action/completed_actions） | V3 叙事场景，⚠️ 单独成域 |
| per-user 写锁 | `post_process.get_user_write_lock` | CAS 天然持有 |
| 幂等键惯例 | `models/action.py` `make_dedupe_key` / `normalize_core_params` | 风格对齐 |
| 观测 | `application/observability.py` `trace.record` / `models/observability.bound_extra` | 复用 |
| Memory 摄取闭环 | `post_process._run_memory_ingest_v2` → `memory_sources.fetch_completed_world_events` | 落库的 WorldEvent 自动被摄取 |
| 最新迁移 | `migrations/versions/0034_world_entities_consumable_unit.py` | 本模块**不新增迁移**（零新表） |
| 存量 outbox | `repositories/outbox_repository.py` / `application/outbox_consumer.py`（迁移 0030） | 未来强幂等接入点 |
