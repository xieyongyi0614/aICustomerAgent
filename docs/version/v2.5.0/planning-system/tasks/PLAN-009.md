# PLAN-009 Task Detail — Memory Integration

> 上游：[../architecture.md](../architecture.md) §7.5（§7.5.1 ~ §7.5.5）、§6.2 ⑦、§6.7 ⑩、§9.6 G-MEMORY；[../tasks.md](../tasks.md) PLAN-009
> 状态：DONE（已实现，2026-09-16；commit 待提交）
> 范围红线：**计划本体与中间步骤不进 `memories`**；计划结果进记忆必须经 `memory_policy.apply_policy`（R1~R8 零豁免）；**不新建记忆系统、不覆盖工具侧 deposit 决策、不新增 `memories` 列**。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | PLAN-009 |
| **Task Name** | Memory Integration |
| **Priority** | P1 |
| **Dependencies** | PLAN-005, PLAN-006 |
| **Phase** | Phase 3 系统集成 |
| **建议提交** | `feat: V2.5.0 计划终态记忆边界表` |

## 1.1 Goal

交付计划结果的**记忆分层判据**：

1. **判据 A（计划本体是否落 `goal_plans`）**：三条条件全满足才落计划；五类场景裁决。
2. **判据 B（计划结果是否进 `memories`）**：`PlanMemoryPolicy` 纯数据资产，形态对齐 `services/tool/memory_policy.py`。
3. **判据 C（步骤级沉淀）**：中间步骤是否沉淀**不由 Planning 决定**——由该步调用的工具按 V2.4.0 边界表决定。
4. **记忆通道零新建**：复用 `memory2.ingest.ingest_from_goal_completion` + `memory_policy.apply_policy` + `effects has_memory_effect`。

## 1.2 Scope

**包含**

- 新建 `app/services/planning/memory_policy.py`：`PlanMemoryPolicy` 纯数据资产 + `PlanMemoryDecision`。
- 计划终态三类（完成 / 失败 / 放弃）的候选构造与 `importance` / `content` 模板。
- **R1 不误杀**（G-MEMORY）：失败 / 放弃类候选的 `source` 与 `importance` 能通过 `memory_policy` R1。
- 隐私步骤参数经 R3（`action="forget"` 分支）转隐私执行。
- 判据 A 的三条条件与五类场景裁决。
- 判据 C：工具侧 deposit 决策**不被覆盖**的断言。
- 幂等：`has_memory_effect` 泛化生效。
- 单元 / 集成 / 场景测试。

**不包含（Non-Scope）**

- `memory_policy` R1~R8 的**任何改动**（V2.0 冻结，零豁免）。
- `memory2.ingest` / `memory2.retriever` 的改动（既有函数复用）。
- 工具侧 `TOOL_MEMORY_TEMPLATES` / `services/tool/memory_policy.py::BOUNDARY_TABLE` 的**任何改动**。
- `memories` 表结构（零迁移）。
- 反思证据窗（PLAN-010）。
- 世界写入与广播（PLAN-008）。
- 自治 `plan_facts`（PLAN-007）。

## 1.3 本任务解决什么问题

架构 §7.5 的核心裁决是：**计划本体与中间步骤不进记忆；只有「计划终态」这一类事件性事实进候选。**

若不做本任务，实现期最可能犯两个错：

| 错误 | 后果 | 本任务的守卫 |
|---|---|---|
| 把「计划创建 / 计划修订 / 单步成功」当事件沉淀 | 记忆被内部结构噪声淹没；检索质量下降 | 判据 B 的 ❌ 行 + 零写入断言 |
| 失败 / 放弃类候选直接写 `source="ai_inferred"` | **被 R1 直接丢弃**（「AI 推测不入库」），失败类记忆永远存不进去 | **G-MEMORY**：R1 不误杀断言（§9.1 U4） |

第二条尤其隐蔽：`ai_inferred` 是直觉上"内部推断"最自然的 `source`，但 `memory_policy._evaluate` 对它的处理是 `DECISION_DISCARD / "R1"`。因此失败 / 放弃类沉淀必须**走加权重路径**——提升 `importance` 并把 `source` 定为 `user_derived`（内容锚定在用户委托的目标描述上），或**复用既有 `ingest_from_goal_completion`**（其 `source` 取自目标本身）。这是 architecture §9.6 单列的 Gate `G-MEMORY`。

---

# 2. Background

## 2.1 当前系统现状

| 系统 | 与本任务的关系 |
|---|---|
| **Memory 2.0** | **核心交互面**：`memory_policy.apply_policy`（R1~R8）/ `memory2.ingest.ingest_from_goal_completion` / `memories` 表 |
| **Tool System V2.4.0** | `services/tool/memory_policy.py::BOUNDARY_TABLE` / `TOOL_MEMORY_TEMPLATES` / `has_memory_effect`（**判据 C 的权威**） |
| **Reflection System** | 记忆证据窗（`EVIDENCE_CHANNEL_MEMORY`）既有；**本任务不涉及** |
| **Action Engine（V9）** | `integrate_result` 的 memory 通道（`_deliver_memory`）既有 |
| **Autonomy 2.0** | **不涉及**（属 PLAN-007） |
| **World Simulation** | **不涉及**（属 PLAN-008） |

**关键事实（已核对真实源码）**

- `app/services/memory_policy.py`：`apply_policy(...)` / `PolicyOutcome` / `PolicyReport` / `DECISION_SAVE="save"` / `DECISION_DISCARD="discard"` / `DECISION_PRIVACY="privacy"`；规则语义：
  - **R1**：`ai_inferred` → `DECISION_DISCARD`（「AI 推测不入库」）
  - **R2**：本轮被 suppress 指令阻断
  - **R3**：用户要求遗忘 → `DECISION_PRIVACY`（「用户要求遗忘，转隐私执行」）
  - **R4**：一次性信息（`ONE_OFF_PATTERN`）
  - **R5**：置信度过低
  - **R6**：重要性过低
  - **R7**：与既有记忆完全重复（`_is_exact_duplicate`）
  - **R8**：含未消解指代（`UNRESOLVED_REFERENCE_PATTERN`）
  - `PolicyReport.has_privacy_request` 等派生属性。
- `app/services/memory2/ingest.py`：`ingest_from_goal_completion(user_id, goal_id, description)`（既有，**本任务优先复用**）、`ingest_from_conversation` / `ingest_from_action_record` / `ingest_from_world_event` / `ingest_from_relationship_event` / `ingest_from_relationship_milestone` / `_create_candidate`。
- `app/services/tool/memory_policy.py`：`BOUNDARY_TABLE` / `BOUNDARY_PREFIX_TABLE` / `DEPOSIT_SKIP="skip"` / `REASON_READ_ONLY="read_only_tool"` / `REASON_POLICY_SKIP` / `REASON_POLICY_DECLINED` / `REASON_POLICY_DEPOSIT` / `READ_SIDE_EFFECT="read"` / `FAILED_IMPORTANCE_FLOOR=0.6` / `DEFAULT_MEMORY_TYPE="important_event"` / `DEFAULT_IMPORTANCE=0.5` / `DEFAULT_SOURCE="user_derived"` / `MEMORY_CONTENT_MAX_CHARS=120` / `MemoryDecision` / `ToolMemoryPolicy` / `get_tool_memory_policy()` / `has_memory_effect(record)` / `tool_id_of(record)` / `policy_key_for(record, defn)` / `namespaces_for` / `is_read_only(defn)` / `delivery_status(record)`；另有 `BIRTHDAY_WEIGHTED_KEYS = ("builtin.reminder.create",)` / `BIRTHDAY_PROMOTED_TYPE="user_fact"` / `BIRTHDAY_PROMOTED_IMPORTANCE=0.8`。
- `app/character/asuna/tool.py` 的 `builtin.reminder.create` 在边界表为 deposit ✅（`important_event` / 0.7）；`world.env.query` 为读类工具**强制不沉淀**；`builtin.memory.save` 为 `skip`（避免二次投递）。
- `app/models/memory.py` / `memory2.py`：记忆类型与 `source` 值域（含 `user_derived` / `ai_inferred`）。
- 迁移链头 0046。

## 2.2 为什么需要本任务

记忆是「角色记得住」的唯一凭据。计划系统如果无节制地往记忆里写，会让记忆从「用户可感知的事实」退化为「Agent 的内部日志」——而 `memory_policy` 的 R1~R8 正是为防止这类退化而存在的政策闸。

本任务的价值是把「计划该不该进记忆」写成**纯数据边界表**（形态对齐工具侧），并让**两层判据正交**：

| 层 | 判什么 |
|---|---|
| Planning（`PlanMemoryPolicy`） | 「计划这个**整体**值不值得记住」 |
| Tool（`services/tool/memory_policy.py`） | 「这次**调用**值不值得记住」 |

---

# 3. Responsibility

## 3.1 本任务负责

| # | 负责项 | 形态 |
|---|---|---|
| R1 | 判据 A：计划本体是否落 `goal_plans`（三条条件 + 五类场景裁决） | 判据表 + 用例 |
| R2 | 判据 B：`PlanMemoryPolicy` 边界表（七行事件 × deposit/type/importance/source） | 纯数据资产 |
| R3 | 计划终态三类候选构造（复用 `ingest_from_goal_completion` + 模板调整） | 构造流程 |
| R4 | **G-MEMORY**：R1 不误杀（失败 / 放弃类候选的 `source` 与 `importance` 可通过 R1） | 断言 + 用例 |
| R5 | R1~R8 零豁免断言（全部候选经 `apply_policy`，无旁路写库） | 静态 + 运行时断言 |
| R6 | 判据 C：工具侧 deposit 决策不被覆盖 | 断言 + 用例 |
| R7 | 幂等：`has_memory_effect` 泛化（重复投递不产生第二条） | 用例 |
| R8 | 隐私步骤参数经 R3 转隐私执行 | 用例 |
| R9 | `v25_plan_memory_enabled` 与 `v25_plan_memory_importance_floor` 门控 | 用例 |

## 3.2 本任务不负责

| # | 不负责 | 归属 |
|---|---|---|
| N1 | `memory_policy` R1~R8 的规则改动 | **永不**（V2.0 冻结，零豁免） |
| N2 | `memory2.ingest` / `retriever` 的改动 | **永不**（既有函数复用） |
| N3 | 工具侧 `BOUNDARY_TABLE` / `TOOL_MEMORY_TEMPLATES` 的改动 | **永不**（V2.4.0 冻结） |
| N4 | 「哪些工具会沉淀」的决策 | V2.4.0 工具侧（本任务只消费） |
| N5 | `memories` 表结构变更 | 零迁移（全版本） |
| N6 | 反思证据窗（记忆证据） | 既有（本任务不改）；计划证据窗属 PLAN-010 |
| N7 | 世界写入与广播 | PLAN-008 |
| N8 | 自治 `plan_facts` | PLAN-007 |
| N9 | 记忆检索进 `PlanContext` | PLAN-003（本任务不涉及） |

## 3.3 职责边界一句话

> **Planning 判「计划整体值不值得记住」；Tool 判「这次调用值不值得记住」。两层正交，Planning 不覆盖工具侧决策，也不绕过 R1~R8。**

---

# 4. Technical Design

## 4.1 Module Design

### 4.1.1 模块职责与依赖方向

| 文件 | 性质 | 职责 | 依赖方向 |
|---|---|---|---|
| `app/services/planning/memory_policy.py` | **新增** | `PlanMemoryPolicy` 纯数据边界表 + `PlanMemoryDecision` + 候选构造 | → `memory2.ingest.ingest_from_goal_completion` / `memory_policy.apply_policy` / `memory_repository`（既有写面）/ `services/tool/memory_policy.py`（只读 `has_memory_effect`） |
| `app/services/planning/observer.py`（PLAN-005） | 已有 | `settle` 终态后触发记忆候选 | → `PlanMemoryPolicy` |

**分层纪律（静态断言强制）**
- `services/planning/memory_policy.py` 零绕过 `memory_policy.apply_policy` 的写路径（无直接 INSERT）。
- 零修改 `memory_policy` / `memory2` / `services/tool/memory_policy.py`。
- 零新增 `memories` 列。

### 4.1.2 Component 划分

```text
app/services/planning/memory_policy.py（新增，纯数据 + 纯函数）
├── 判据 A：should_persist_plan(...) -> bool
│     三条条件（全满足才落计划）
├── 判据 B：PlanMemoryPolicy（边界表）
│     decide(event_kind) -> PlanMemoryDecision{deposit, type, importance, source}
│     · 七行事件 × deposit/type/importance/source
└── 候选构造：build_candidate(goal, plan, event_kind) -> MemoryCandidate
      · 优先复用 memory2.ingest.ingest_from_goal_completion(user_id, goal_id, description)
      · 按终态调整 importance / content 模板

记忆通道（既有，零新建）
    候选 → memory_policy.apply_policy([candidate], active_contents) → R1~R8
         → memories（既有表）
         → effects 登记 kind=memory（has_memory_effect 泛化做重复投递检测）
```

### 4.1.3 数据流：计划终态 → 记忆

```text
计划终态（PlanObserver.settle）
    │
    ├─ completed（全步 done）  ┐
    ├─ failed（达预算 / abort） ├─ 三类终态
    └─ abandoned（双信号）     ┘
    │
    ▼
① 分类（PlanMemoryPolicy，纯函数）
   deposit=True ⇒ 构造候选；deposit=False ⇒ 直接返回（零写入）
        │
        ▼
② 候选构造（复用既有）
   ├─ 优先：memory2.ingest.ingest_from_goal_completion(user_id, goal_id, description)   ← 既有函数
   └─ 补充：按计划终态调整 importance / content 模板（失败 / 放弃类带未完成语义）
        │
        ▼
③ 政策闸（零豁免）
   memory_policy.apply_policy([candidate], active_contents) → R1~R8
     · R1 拦 ai_inferred；R4 拦一次性表述；R5/R6 拦低置信/低重要度；
       R7 拦完全重复；R8 拦未消解指代；R3 转隐私执行
   未通过 → 丢弃（★ 不回滚计划执行，与 V9 同款纪律）
        │
        ▼
④ 落库与幂等
   memories（既有表，零新列）
   effects 里登记 kind=memory → 重复投递检测（既有 has_memory_effect 泛化）
```

## 4.2 Core Model

本任务**不新增持久模型**。下表为边界表与判据。

### 4.2.1 判据 A：计划本体是否落库（`goal_plans`）

**判据（三条，全满足才落计划；任一不满足走 action 直通）**

| # | 条件 | 说明 |
|---|---|---|
| A1 | 步骤数 ≥ 2 **或** 需要跨 tick 观测 | 单步且当场可判定 → 不需要计划结构 |
| A2 | 每步有独立达成判据 | 无判据 → 不可观测 → 不构成 Task |
| A3 | 需要幂等 / 重试 / 失败恢复 | 一次性、无副作用、失败即弃的操作不需要计划 |

**五类场景裁决（可判定）**

| 场景 | 落计划 | 理由 | 命中的判据 |
|---|---|---|---|
| 「把杯子放桌上」（单步、当场可验） | ❌ | 走 `post_process` 第 9 步 → `action_engine` 直通 | A1 不满足 |
| 「帮我准备后天的面试」（多步、跨天） | ✅ | 4 步 + 跨 tick 观测 | A1/A2/A3 全满足 |
| 「提醒我明早八点开会」（单步但需跨天确认送达） | ❌ | 单步，`builtin.reminder.create` 自带 `pending_confirmation` 与 `action_records` 重试 | A1 不满足（A3 可由工具自身满足） |
| 「周末陪我看部电影」（需先查日程再定时间） | ✅ | 2 步且第 2 步依赖第 1 步结果 | A1/A2/A3 全满足 |
| 纯查询（「今天天气怎么样」） | ❌ | 无副作用、无判据 | A2 不满足 |

### 4.2.2 判据 B：`PlanMemoryPolicy` 边界表

| 事件 | deposit | `type` | `importance` | `source` | 判据 |
|---|---|---|---|---|---|
| 计划完成（全部步骤 `done`） | ✅ | `important_event` | 0.7 | `user_derived` | 用户可感知的结果，值得记住 |
| 计划失败（达预算 / `on_failure=abort`） | ✅ | `important_event` | ≥ `v25_plan_memory_importance_floor`（0.6） | **`user_derived`** ※ | 内容带未完成语义；**与 V9 失败纪律一致** |
| 计划被放弃（`abandonment` 双信号） | ✅ | `important_event` | ≥ 0.6 | **`user_derived`** ※ | 同上 |
| 计划创建 | ❌ | — | — | — | 计划本体是内部结构，进记忆 = 噪声 |
| 计划修订 | ❌ | — | — | — | 内部结构变化 |
| 单个步骤成功（中间态） | ❌ | — | — | — | 除非该步**自身的工具**按 §4.2.3 沉淀 |
| 单个步骤失败（未达 Plan 层上限） | ❌ | — | — | — | 未达失败阈值 |
| 涉及用户隐私的步骤参数 | privacy | — | — | — | 经 `memory_policy` R3（`action="forget"` 分支）转隐私执行 |

> **※ 最容易写错的一行**：`ai_inferred` 会被 `memory_policy` **R1 直接丢弃**（`DECISION_DISCARD / "R1"`，理由「AI 推测不入库」）。因此失败 / 放弃类沉淀**必须**走加权重路径——提升 `importance` 并把 `source` 定为 `user_derived`（内容锚定在用户委托的目标描述上），或复用既有 `ingest_from_goal_completion`（其 `source` 取自目标本身）。**这条列入 Gate `G-MEMORY`。**

### 4.2.3 判据 C：步骤级沉淀（复用既有工具边界表）

中间步骤是否沉淀，**不由 Planning 决定**，而是由该步**调用的工具**按 V2.4.0 的 `TOOL_MEMORY_TEMPLATES` 与 `services/tool/memory_policy.py` 边界表决定：

| 工具 | deposit | 结果 |
|---|---|---|
| `builtin.reminder.create` | ✅ `important_event` / 0.7 | 步骤成功 → 沉淀一条（**无论它在不在计划里**） |
| `world.env.query` | ❌ | 读类工具（`READ_SIDE_EFFECT="read"` / `REASON_READ_ONLY`）强制不沉淀 |
| `builtin.memory.save` | `skip`（`DEPOSIT_SKIP`） | 直通（避免二次投递） |

**纪律**：Planning **不新增**工具记忆边界表，**不覆盖**工具侧的 deposit 决策。两层判据**正交**：

| 层 | 判什么 | 权威 |
|---|---|---|
| Planning | 计划这个整体值不值得记住 | `PlanMemoryPolicy` |
| Tool | 这次调用值不值得记住 | `services/tool/memory_policy.py::BOUNDARY_TABLE` |

### 4.2.4 幂等与去重（复用既有）

| 机制 | 位置 | 本任务用法 |
|---|---|---|
| `has_memory_effect(record)` | `services/tool/memory_policy.py` | 泛化为「同一次执行重复投递不产生第二条记忆」的检测依据 |
| R7（完全重复） | `memory_policy._is_exact_duplicate` | 政策闸内的第二道去重 |
| `effects` 登记 `kind=memory` | `action_records.steps[].result.effects` | 幂等标记的承载位（既有） |

### 4.2.5 门控参数（消费 PLAN-002 配置）

| Flag / 参数 | 作用 |
|---|---|
| `v25_plan_memory_enabled` | 计划终态记忆边界表总开关（依赖总闸 + `v2_memory_enabled`）；off → 走既有原路径 |
| `v25_plan_memory_importance_floor` | 失败 / 放弃类终态的记忆重要度下限（默认 0.6，对齐 `memory_importance_threshold`） |

## 4.3 State Machine

本任务**不新增状态机**。下为记忆候选的既有生命周期在计划链路中的体现。

### 4.3.1 记忆候选生命周期（既有）

```text
候选构造（本任务：ingest_from_goal_completion + 模板调整）
        │
        ▼
memory_policy.apply_policy([candidate], active_contents)
        │
        ├─ DECISION_SAVE    → 落 memories（既有表）
        ├─ DECISION_PRIVACY → 转隐私执行（R3；用户要求遗忘）
        └─ DECISION_DISCARD → 丢弃（R1 / R2 / R4 / R5 / R6 / R7 / R8）
                                ★ 不回滚计划执行
        ▼
effects 登记 kind=memory（幂等标记）
```

### 4.3.2 计划终态 × 记忆决策矩阵

| 计划终态 | deposit | 内容语义 | `source` |
|---|---|---|---|
| `completed` | ✅ | 「帮用户把后天的面试准备好了」 | `user_derived` |
| `failed`（达预算 / `abort`） | ✅ | 「想帮用户准备面试，但没做成」 | `user_derived`（**不得** `ai_inferred`） |
| `abandoned` | ✅ | 同上（未完成语义） | `user_derived`（**不得** `ai_inferred`） |
| `rejected`（计划被拒） | ❌ | — | — |
| `superseded`（被修订取代） | ❌ | — | — |
| 步骤级中间态 | ❌（由工具侧独立判定） | — | — |

---

# 5. System Interaction

## 5.1 与 Autonomy

**完全不涉及。**

| 关注点 | 本任务 | 原因 |
|---|---|---|
| `plan_facts` | 由 PLAN-007 装配 | 自治不消费记忆候选 |
| 额度与决策 | 由 PLAN-007 断言 | 记忆沉淀不参与自治裁决 |

## 5.2 与 Tool System

| 关注点 | Tool System（V2.4.0，零改动） | 本任务 |
|---|---|---|
| 工具记忆边界表 | `services/tool/memory_policy.py::BOUNDARY_TABLE` / `TOOL_MEMORY_TEMPLATES` | **只读消费，不覆盖**（判据 C） |
| `has_memory_effect` | 既有 | **复用**做幂等检测 |
| `MEMORY_CONTENT_MAX_CHARS=120` / `FAILED_IMPORTANCE_FLOOR=0.6` / `DEFAULT_MEMORY_TYPE` / `DEFAULT_SOURCE` | 既有常量 | **复用同款取值**（不新造常量） |
| 工具执行结果 | `ToolResult.effects` | 记忆幂等标记的承载位 |

**为什么不覆盖**：工具这次的调用「值不值得记住」是工具侧的领域判断（如读类工具强制不沉淀避免噪声）；Planning 没有比它更细的信息。**两层正交是本任务的架构前提。**

## 5.3 与 World Simulation

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| `ingest_from_world_event`（世界事件 → 记忆） | 既有独立通道 | **零改动**（不涉及） |
| 计划终态广播产生的世界事件 → 记忆 | 既有通道自动处理 | **不涉及**；与计划终态候选是**两条独立通道**（PLAN-008 §5.4 已声明） |

**纪律**：不因「计划完成产生了世界事件」而额外写一条记忆——世界事件通道已有 `ingest_from_world_event`；两层若都写会造成重复（并被 R7 拦截，但不应依赖 R7 兜底）。

## 5.4 与 Memory 2.0（本任务核心）

| 关注点 | 既有（零改动） | 本任务 |
|---|---|---|
| 政策闸 | `memory_policy.apply_policy` R1~R8 | **零豁免**消费 |
| 候选构造 | `memory2.ingest.ingest_from_goal_completion` | **优先复用**（不新建候选构造器） |
| 检索 | `memory2.retriever.retrieve` | 不涉及（`PlanContext.memories` 属 PLAN-003） |
| `memories` 表 | 既有 | **零新列** |
| 记忆类型 / `source` 值域 | 既有（含 `user_derived` / `ai_inferred` / `important_event`） | **不新增值** |

## 5.5 与 Reflection

| 关注点 | 关系 | 本任务动作 |
|---|---|---|
| 记忆证据窗（`EVIDENCE_CHANNEL_MEMORY`） | 既有 | **零改动** |
| 计划证据窗（`EVIDENCE_CHANNEL_PLAN`） | PLAN-010 | **不涉及** |

**边界**：本任务写出的记忆自然进入既有记忆证据窗的样本池（既有能力，无需新增接线）；计划证据窗是另一条通道。

## 5.6 不涉及的子系统（汇总）

| 子系统 | 本任务 | 原因 |
|---|---|---|
| 六源装配 / 计划生成 / 拆解 | 不涉及 | PLAN-003 / PLAN-004 |
| 调度 / 执行 / 观测 / 修订本体 | 不涉及（本任务只消费其终态） | PLAN-005 |
| 工具治理 | 不涉及 | PLAN-006 |
| 世界写入与广播 | 不涉及 | PLAN-008 |
| 反思证据窗与监听器 | 不涉及 | PLAN-010 |
| 自治 `plan_facts` | 不涉及 | PLAN-007 |
| 调试端点 | 不涉及 | PLAN-011 |

---

# 6. API / Interface Design

## 6.1 判据 A 接口

```text
interface PlanPersistPolicy:                    # 纯函数、零 IO
    should_persist_plan(
        *,
        step_count: int,
        cross_tick: bool,
        every_step_has_criteria: bool,
        needs_idempotency_or_recovery: bool,
    ) -> bool
    # A1: step_count >= 2 or cross_tick
    # A2: every_step_has_criteria
    # A3: needs_idempotency_or_recovery
    # 三条全满足 → True
```

## 6.2 判据 B 接口（`PlanMemoryPolicy`）

```text
interface PlanMemoryPolicy:                     # 纯数据资产 + 纯函数
    decide(event_kind: str, *, settings) -> PlanMemoryDecision

interface PlanMemoryDecision:
    deposit: bool
    memory_type: str | None                     # 取值即既有记忆类型（important_event 等）
    importance: float | None
    source: str | None                          # ★ 成功/失败/放弃类一律 "user_derived"（不得 ai_inferred）
    reason: str | None                          # 拒收理由（可读）
```

**`event_kind` 值集（七值，与 §4.2.2 边界表逐行对应）**

| `event_kind` | deposit |
|---|---|
| `plan_completed` | ✅ |
| `plan_failed` | ✅ |
| `plan_abandoned` | ✅ |
| `plan_created` | ❌ |
| `plan_revised` | ❌ |
| `step_succeeded` | ❌ |
| `step_failed` | ❌ |

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D1 | 纯数据 + 纯函数：零 IO、零 LLM | 静态断言 |
| D2 | 形态对齐 `services/tool/memory_policy.py`（`BOUNDARY_TABLE` + `MemoryDecision` 同构） | 结构对照 |
| D3 | `source` 对三类终态一律 `user_derived`（**G-MEMORY**） | 用例断言（U4） |
| D4 | 常量复用既有取值（`MEMORY_CONTENT_MAX_CHARS` / `DEFAULT_MEMORY_TYPE` / 重要度下限），不新造 | 常量对照 |

## 6.3 候选构造接口

```text
build_candidate(goal: GoalRecord, plan: GoalPlanRecord, event_kind: str) -> MemoryCandidate | None
    # 优先：memory2.ingest.ingest_from_goal_completion(user_id=goal.user_id,
    #                                                   goal_id=goal.id,
    #                                                   description=goal.description)
    # 补充：按 event_kind 调整 importance / content 模板
    #       · completed → 完成语义模板
    #       · failed / abandoned → 未完成语义模板
    # 返回 None → 不构造候选（deposit=False 的事件）
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D5 | 候选构造**不绕过** `apply_policy` | 静态断言：零直接 INSERT `memories` |
| D6 | 隐私步骤参数经 R3 分支（`action="forget"`）转隐私执行 | 用例 |
| D7 | 内容长度 ≤ `MEMORY_CONTENT_MAX_CHARS`（120） | 预算断言 |

## 6.4 落库与幂等接口

```text
# 政策闸（既有，零改动）
memory_policy.apply_policy(candidates, active_contents) -> PolicyReport

# 落库（既有写面）
memory_repository.<save>(...)                    # 既有函数

# 幂等标记（既有承载位）
effects 登记 kind=memory
has_memory_effect(record) -> bool                # 既有，泛化用于重复投递检测
```

**契约纪律**

| # | 纪律 | 验证方式 |
|---|---|---|
| D8 | **R1~R8 零豁免**：全部候选经 `apply_policy`，无旁路写库 | 静态 + 运行时断言 |
| D9 | 重复投递不产生第二条记忆 | 用例（U7） |
| D10 | 政策闸未通过 → 丢弃，**不回滚计划执行** | 用例（与 V9 同款纪律） |

## 6.5 异常契约

| 异常 | 来源 | 处置 |
|---|---|---|
| 候选构造异常 | `ingest_from_goal_completion` / 模板 | 捕获 → 跳过本次沉淀；log；不影响计划终态 |
| `apply_policy` 异常 | `memory_policy` | 捕获 → 丢弃候选（保守）；log；不影响计划终态 |
| 落库异常 | `memory_repository` | 捕获 → log；不影响计划终态（`effects` 不登记 → 下次可重投） |
| 隐私请求（R3） | `apply_policy` | 转隐私执行（既有分支），**不是异常** |

---

# 7. Database Design

**本任务与全版本均无任何数据库变更（零迁移强断言）。**

| 项 | 结论 | 理由 |
|---|---|---|
| 新表 | 无 | 记忆落既有 `memories` 表；证据不建表（投影） |
| 新列 | 无 | 记忆类型 / `source` / `importance` / `content` 均为既有列；`effects` 为既有 JSON 列（`action_records.steps[].result.effects`） |
| 新索引 | 无 | 重复投递检测复用既有 `has_memory_effect` 与 R7 的既有查询 |
| 改 CHECK | 无 | `memories.type` 与 `source` 值集未扩（复用 `important_event` / `user_derived`） |
| 迁移 | 无 | 迁移链保持 **0046** |

**本任务的写入面**

| 数据 | 落点 | 写入入口 | 是否新列 |
|---|---|---|---|
| 计划终态记忆 | `memories` | `memory_repository`（**必经 `memory_policy.apply_policy`**） | ❌ |
| 记忆幂等标记 | `action_records.steps[].result.effects` | 既有 `effects` 登记（`kind=memory`） | ❌ |
| 计划状态 / 步骤 | `goal_plans` | `goal_repository.update_plan_progress`（PLAN-005） | ❌ |

> **零新列、零绕过**：`memories` 表结构不变；全部写入必经政策闸。若实现期发现需要为「计划记忆」加列（如 `plan_id`），说明 architecture §7.5 的边界表设计被违背——**应改由候选内容与 `source_ref` 承载**，不得加列。

---

# 8. Implementation Plan

## Step 1 — 判据 A：计划本体落库判据

1. 实现 `should_persist_plan(...)` 纯函数（三条条件）。
2. 用五类场景（§4.2.1）做边界用例：单步当场可验 / 多步跨天 / 单步跨天确认送达 / 两步依赖 / 纯查询。
3. 与 PLAN-003（`PlanningEngine.plan` 的调用点）确认：A 不满足时走 action 直通，不落 `goal_plans`。
4. 单测：五类场景裁决逐条可判定。

## Step 2 — 判据 B：`PlanMemoryPolicy` 边界表

1. 定义 `PlanMemoryPolicy`（纯数据 + `decide`）+ `PlanMemoryDecision`，形态对齐 `services/tool/memory_policy.py`。
2. 七行 `event_kind` × `deposit` / `type` / `importance` / `source` 逐行落地。
3. **关键**：失败 / 放弃类 `source` 定为 `user_derived`，`importance ≥ v25_plan_memory_importance_floor`；**禁止 `ai_inferred`**（G-MEMORY）。
4. 常量复用既有取值（`DEFAULT_MEMORY_TYPE="important_event"` / `MEMORY_CONTENT_MAX_CHARS=120` / `FAILED_IMPORTANCE_FLOOR=0.6` 的语义）。
5. 单测：七行逐条；`ai_inferred` 负例（构造该值即用例失败）。

## Step 3 — 候选构造（复用 `ingest_from_goal_completion`）

1. 优先路径：调既有 `memory2.ingest.ingest_from_goal_completion(user_id, goal_id, description)`。
2. 补充：按 `event_kind` 调整 `importance` / `content` 模板（成功用完成语义，失败 / 放弃用未完成语义）。
3. 内容长度受 `MEMORY_CONTENT_MAX_CHARS` 约束。
4. 隐私步骤参数经 `action="forget"` 走 R3 分支。
5. 单测：三类终态候选内容语义正确；隐私分支正确；长度预算。

## Step 4 — 政策闸与幂等

1. 全部候选统一经 `memory_policy.apply_policy([candidate], active_contents)`。
2. **零旁路**：断言无直接 INSERT `memories`（静态）。
3. 未通过政策闸 → 丢弃，**不回滚计划执行**。
4. 幂等：`effects` 登记 `kind=memory`；`has_memory_effect` 泛化检测重复投递。
5. 单测：R1 不误杀（G-MEMORY）；重复投递不产生第二条；政策闸未过不回滚。

## Step 5 — 判据 C：工具侧决策不被覆盖

1. 断言 `builtin.reminder.create` 步骤成功仍按 V2.4.0 边界表沉淀一条（且**不因它在计划里而改变**）。
2. 断言 `world.env.query` 仍强制不沉淀（即使配置为沉淀）。
3. 断言 `builtin.memory.save` 仍 `skip`（避免二次投递）。
4. 断言 Planning 未新增工具边界表（静态：`planning/` 零 `dict[str, dict]` 形态的工具记忆映射）。
5. 单测：三条逐条通过。

## Step 6 — 门控与回归

1. `v25_plan_memory_enabled` off → 记忆通道走既有原路径（逐字节一致）。
2. `v25_plan_memory_importance_floor` 生效于失败 / 放弃类。
3. 回归：`memories` 表结构零变更；`memory_policy` / `memory2` / `services/tool/memory_policy.py` diff 为空。
4. Flag 全 off 时全量既有测试零修改通过；prompt 逐字节一致。

---

# 9. Testing Strategy

## 9.1 Unit Test（核心逻辑）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 判据 A 三条条件 | 各一通过 / 不通过用例；三条件全满足才 `True` |
| U2 | 判据 A 五类场景 | 与 §4.2.1 裁决表逐条一致 |
| U3 | 边界表七行 | `event_kind` × deposit 逐行一致；✅ 三行有 `type` / `importance` / `source`，❌ 四行为空 |
| U4 | **R1 不误杀（G-MEMORY）** | 失败 / 放弃类候选的 `source` 与 `importance` **能通过 `memory_policy` R1**；若被 R1 丢弃则用例失败；断言 `source != "ai_inferred"` |
| U5 | 候选内容语义 | `completed` 完成语义；`failed` / `abandoned` 带未完成语义 |
| U6 | 内容长度预算 | ≤ `MEMORY_CONTENT_MAX_CHARS`（120） |
| U7 | 幂等 | 同一次执行重复投递 **不产生第二条记忆**（`has_memory_effect` 泛化生效） |
| U8 | 隐私分支 | 隐私步骤参数经 R3（`action="forget"`）转隐私执行 |
| U9 | 政策闸未过不回滚 | R4/R5/R6/R7/R8 任一命中 → 丢弃，计划执行结果不变 |
| U10 | 常量复用 | 零新造 `MEMORY_CONTENT_MAX_CHARS` / `DEFAULT_MEMORY_TYPE` 类常量（静态） |
| U11 | `PlanMemoryPolicy` 纯函数 | 零 IO、零 LLM、零仓储导入（静态断言） |
| U12 | 形态对齐 | 与 `services/tool/memory_policy.py` 的 `BOUNDARY_TABLE` + `MemoryDecision` 同构（结构对照） |
| U13 | 失败 / 放弃 `importance` 下限 | ≥ `v25_plan_memory_importance_floor`（默认 0.6） |

## 9.2 Integration Test（与已有模块交互）

| # | 用例 | 断言 |
|---|---|---|
| I1 | **零写入断言** | 计划本体与中间步骤零写入 `memories`；`plan_created` / `plan_revised` / `step_succeeded` / `step_failed` 四类事件均不沉淀 |
| I2 | 三类终态各沉淀一条 | `completed` / `failed` / `abandoned` 各产生恰好一条 |
| I3 | **R1~R8 零豁免** | 全部候选经 `memory_policy.apply_policy`；无旁路写库（静态 + 运行时断言） |
| I4 | 工具侧 deposit 不被覆盖（判据 C） | `builtin.reminder.create` 步骤成功仍沉淀一条；`world.env.query` 仍强制不沉淀（即使配置为沉淀）；`builtin.memory.save` 仍 `skip` |
| I5 | `memory_policy` 零改动 | diff 为空；R1~R8 规则与理由码未变 |
| I6 | `memory2.ingest.ingest_from_goal_completion` 复用 | 调用点可追溯；零新建候选构造器（静态） |
| I7 | `services/tool/memory_policy.py` 零改动 | diff 为空；`BOUNDARY_TABLE` / `TOOL_MEMORY_TEMPLATES` 未变 |
| I8 | `memories` 表零变更 | 列集与 CHECK 未变；迁移链头 `0046` |
| I9 | 终态记忆与「世界事件 → 记忆」两通道独立 | 计划完成不因广播的世界事件而额外写第二条 |
| I10 | **Flag off 逐字节一致** | 记忆通道走既有原路径 |

## 9.3 Scenario Test（端到端）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| S1 | **「帮我规划一次旅行」完成沉淀** | 计划全步 `done` → 终态 `completed` | 恰好一条 `important_event` / `importance 0.7` / `source user_derived`；内容为用户可感知的完成语义 |
| S2 | 计划失败沉淀 | 达修订预算 → 目标 `failed` | 一条 `important_event` / `importance ≥ 0.6` / `source user_derived`；内容带**未完成语义**；**未被 R1 丢弃** |
| S3 | 计划放弃沉淀 | `check_abandonment` 双信号 → `abandoned` | 同上 |
| S4 | **中间步骤不沉淀** | 4 步计划逐步执行 | `memories` 零新增（除工具侧按自身边界表沉淀的，如 `builtin.reminder.create` 一条） |
| S5 | 判据 C 正交性 | 计划含 `world.env.query`（读类）与 `builtin.memory.save`（skip）步骤 | 两者均不额外沉淀；`builtin.reminder.create` 步骤沉淀一条（**与它在不在计划里无关**） |
| S6 | 重复投递幂等 | 同一次执行重复投递 | 不产生第二条记忆 |
| S7 | 隐私参数 | 步骤参数含用户要求遗忘的内容 | 经 R3 转隐私执行 |
| S8 | 判据 A 两侧 | 单步当场可验的目标 vs 多步跨天目标 | 前者走 action 直通（不落 `goal_plans`）；后者落计划 |
| S9 | Flag off | 记忆子闸 off → 计划完成 | 记忆通道走既有原路径；无计划终态候选 |

---

# 10. Acceptance Criteria

## 10.1 Functional Acceptance

- **零写入断言**：计划本体与中间步骤零写入 `memories`；计划创建 / 计划修订 / 单步成功 / 单步失败（未达上限）四类事件均不沉淀。
- 计划完成 / 失败 / 放弃三类终态各沉淀一条，且内容语义正确（失败与放弃类带未完成语义）。
- **R1 不误杀断言（G-MEMORY）**：失败 / 放弃类候选的 `source` 与 `importance` 能通过 `memory_policy` R1；若被 R1 丢弃则用例失败。
- **R1~R8 零豁免**：全部候选经 `memory_policy.apply_policy`，无旁路写库（静态与运行时断言）。
- 工具侧 deposit 决策**不被覆盖**：`builtin.reminder.create` 步骤成功仍按 V2.4.0 边界表沉淀一条；`world.env.query` 仍强制不沉淀（即使配置为沉淀）；`builtin.memory.save` 仍 `skip`（避免二次投递）。
- 幂等：同一次执行重复投递不产生第二条记忆（`has_memory_effect` 泛化生效）。
- 判据 A 的三条条件与五类场景裁决各有用例，边界场景（单步但需跨天确认送达 → 不落计划）可判定。
- `memories` 表结构零变更、零迁移；Flag off 时记忆通道走既有原路径（逐字节一致）。

## 10.2 Integration Acceptance

- `memory_policy` / `memory2` / `services/tool/memory_policy.py` 三个模块 diff 为空（零改动）。
- `memory2.ingest.ingest_from_goal_completion` 被复用（调用点可追溯）；零新建候选构造器。
- `memories` 表列集与 CHECK 未变；迁移链头 `0046`。
- 政策闸未通过 → 丢弃且**不回滚计划执行**（与 V9 同款纪律）。
- 终态记忆与「世界事件 → 记忆」（`ingest_from_world_event`）两条通道互不重复写入。
- 既有 `memory_policy` / `memory2` / `tool/memory_policy` 相关测试零失败。
- **Flag 全 off 时全量既有测试零修改通过**；prompt 与 V2.4.0 逐字节一致。

## 10.3 Quality Acceptance

- **零迁移**：无新表 / 新列 / 新索引 / 新 CHECK 值；迁移链头仍为 `0046`；`memories` 类型与 `source` 值集未扩。
- **零新建记忆系统**：不新建政策闸、不新建候选构造器、不新增工具记忆边界表；全部复用既有。
- **两层判据正交可举证**：Planning 层（`PlanMemoryPolicy`）与 Tool 层（`BOUNDARY_TABLE`）各自权威、互不覆盖；判据 C 的三条用例可判定。
- **G-MEMORY 可举证**：失败 / 放弃类的 `source` 定为 `user_derived` 这一条既有用例断言（U4），又有 R1 规则的既有语义支撑（`ai_inferred` → `DECISION_DISCARD / "R1"`）。
- **形态对齐**：`PlanMemoryPolicy` 与 `services/tool/memory_policy.py` 的 `BOUNDARY_TABLE` + `MemoryDecision` 同构（结构对照用例）。
- **文档一致**：本文件与 architecture §7.5（§7.5.1 ~ §7.5.5）、§6.2 ⑦、§6.7 ⑩、§9.6 G-MEMORY 及 tasks.md PLAN-009 Acceptance Criteria 逐条对应，无自相矛盾。
