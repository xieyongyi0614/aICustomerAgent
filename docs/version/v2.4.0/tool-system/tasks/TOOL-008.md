# TOOL-008 Task Detail — Memory Integration

> 上游：[../architecture.md](../architecture.md) §7.4（Tool 与 Memory 2.0 集成）、§8.3（短/中/长期分流）；[../tasks.md](../tasks.md) TOOL-008
> 状态：设计稿（未实现）
> 范围红线：**不新建 Memory 系统**；记忆写入必须经既有 `memory_policy` R1~R8（零豁免）；不新增记忆表、不扩记忆类型域；读类工具强制不沉淀。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-008 |
| **Task Name** | Memory Integration |
| **Priority** | P1 |
| **Dependencies** | TOOL-003, TOOL-005 |
| **建议提交** | `feat: V2.4.0 工具结果记忆分层` |

## 1.1 Goal

交付工具结果的**记忆分层**：普通结果不保存、重要结果进候选、结果本身是记忆写入则直通。把 V9 的行动记忆边界表泛化到工具维度，并落地三条硬纪律（读类工具强制不沉淀、外部 API 默认不沉淀、自定义命名空间默认不沉淀）。

核心原则继承 V2.3.0 §8.3：**记忆只沉淀"对关系与人格有意义的事实"，不搬运世界的原始账本**。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/memory_policy.py`：`ToolMemoryPolicy` 边界表（键从 `action_type` 升级为 `memory_policy_key`）。
- 扩展 `app/services/action/memory_bridge.py`：泛化边界表查询（旧键保留兜底）。
- 扩展 `app/character/asuna/tool.py`：`TOOL_MEMORY_TEMPLATES` 内容模板资产（保留 `ACTION_MEMORY_TEMPLATES`）。
- 扩展 `app/application/action_engine.py::integrate_result`：记忆投递走泛化路径。
- 单测：三条硬纪律、R1~R8 零豁免、幂等、失败结果形态。

**不包含（Non-Scope）**

- 反思与 Insight（TOOL-009）。
- 关系域信号映射（`relationship_bridge` 既有，本任务不扩展；Q8 留后续）。
- 记忆检索侧改动（`memory2/retriever.py` 零改动）。
- 短期上下文（`ToolContext` / `ToolObservation` 只进工作上下文，**不落记忆**）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/memory_policy.py` | 新增 | 工具记忆边界表 + 候选构造 |
| `app/services/action/memory_bridge.py` | 扩展 | 泛化键查询（旧键兜底） |
| `app/character/asuna/tool.py` | 扩展 | 内容模板资产 |
| `app/application/action_engine.py::integrate_result` | 扩展 | 投递走泛化路径 |
| `services/memory_policy.py` | 复用不改 | R1~R8 政策闸（零豁免） |
| `repositories/memory_repository.py` | 复用不改 | 记忆写入 |

**分层流图**

```text
Tool Execution 完成（TOOL-003 已产出 ToolResult）
        │
        ▼
① 分类（ToolMemoryPolicy.classify，纯函数）
   ├─ 读类工具（side_effects ⊆ {read}）→ deposit=False（强制，配置不可违背）
   ├─ 外部 API / 自定义命名空间      → deposit=False（默认）
   ├─ 边界表 deposit=False          → 不沉淀
   ├─ 边界表 deposit=True           → 构造候选
   └─ 边界表 deposit=skip           → 直通（结果本身即记忆写入）
        │
        ▼
② 候选构造（纯函数）
   MemoryCandidate{action:"save", type, content, importance, confidence, source}
   · content 由 TOOL_MEMORY_TEMPLATES[tool_id].format(params) 渲染
   · 失败结果 → importance ≥ 0.6、type=important_event、内容带未完成语义
        │
        ▼
③ 政策闸（既有，零豁免）
   memory_policy.apply_policy([candidate]) → R1~R8
   未通过 → 丢弃（不回滚工具执行）
        │
        ▼
④ 落库与幂等
   memory_repository.create_memory(...)
   effects 登记 kind="memory" → 重复投递检测
```

## 2.2 数据结构

### 边界表行（`ToolMemoryPolicy` 行）

| 字段 | 类型 | 说明 |
|---|---|---|
| `deposit` | bool 或 `"skip"` | `True` 沉淀 / `False` 不沉淀 / `"skip"` 直通 |
| `memory_type` | str | 既有记忆类型域内取值 |
| `importance` | float | 0~1 |
| `source` | str | 仅允许 `user_stated` / `user_derived`（与 V9 同纪律） |
| `template_key` | str? | 覆盖默认模板键 |

### 边界表内容（首版）

| tool_id / memory_policy_key | deposit | memory_type | importance | source | 说明 |
|---|---|---|---|---|---|
| `builtin.reminder.create` | ✅ | important_event | 0.7 | user_derived | 命中生日关键词 → user_fact / 0.8（V9 加权保留） |
| `builtin.reminder.cancel` | ✅ | important_event | 0.5 | user_derived | — |
| `builtin.memory.save` | skip | — | — | user_stated | 直通，避免二次投递（V9 既有豁免） |
| `world.object.create` | ✅ | user_preference | 0.5 | user_derived | — |
| `world.object.move` / `world.object.use` | ❌ | — | — | — | 世界状态变更不搬运进记忆 |
| `world.env.query` | ❌ | — | — | — | 读类，强制不沉淀 |
| `builtin.search.query` | ❌ | — | — | — | 读类，强制不沉淀 |
| `builtin.notification.send` | ✅ | important_event | 0.6 | ai_inferred | 主动关怀类 |
| `channel.feishu.send` | ✅ | important_event | 0.6 | ai_inferred | 主动关怀类 |
| `ext.api.*` | ❌ | — | — | — | 第三方内容不可信，默认不沉淀 |
| `user.*` | ❌ | — | — | — | 不受信来源，默认不沉淀 |

### 内容模板资产

| 模板键 | 内容 |
|---|---|
| `builtin.reminder.create` | `用户请我提醒他：{content}` |
| `builtin.reminder.cancel` | `用户不想再被提醒：{target}` |
| `builtin.memory.save` | `用户告诉我：{fact}` |
| `world.object.create` | `用户请我准备：{object}` |
| `builtin.notification.send` | `我主动提醒了用户：{content}` |
| `channel.feishu.send` | `我主动给用户发了消息：{content}` |

**失败结果模板覆盖**：`上次没能帮用户完成：{内容}`（importance ≥ 0.6，type=important_event）。

## 2.3 核心流程

### 分类判定（纯函数，短路）

```text
classify(record, tool_defn) -> MemoryDecision
   │
   ├─ ① side_effects ⊆ {"read"}          → deposit=False（reason="read_only_tool"）★硬纪律
   ├─ ② namespace in {"ext.api","user"}  → deposit=False（reason="untrusted_source"）★硬纪律
   ├─ ③ 边界表无该键                      → deposit=False（reason="no_policy_row"）
   ├─ ④ 边界表 deposit == "skip"          → deposit="skip"（直通）
   ├─ ⑤ 边界表 deposit == False           → deposit=False（reason="policy_declined"）
   └─ ⑥ 边界表 deposit == True            → deposit=True（构造候选）
```

**①②优先于③④⑤⑥**——硬纪律不可被边界表配置绕过（配置不可违背）。

### 幂等与投递

```text
deliver_tool_memory(record, user_id, character_id) -> dict | None
   ├─ v24_tool_memory_enabled off → 走 V9 原路径（action_type 键）
   ├─ 已有 effects.kind == "memory" → 跳过（幂等）
   ├─ record.status not in (succeeded, failed) → 跳过
   ├─ record.status == failed 且 gate_reason 非空 → 跳过（未执行不算失败）
   ├─ classify → deposit 判定
   ├─ 构造候选 → memory_policy.apply_policy（R1~R8）
   ├─ 未通过 → 返回 None（丢弃，不回滚）
   └─ 通过 → memory_repository.create_memory → 返回 {memory_id, content}
```

### 失败结果的特殊处理

| 条件 | 处理 |
|---|---|
| `status == failed` 且 `gate_reason is None`（真执行失败） | 沉淀，importance ≥ 0.6，type=important_event，内容带"上次没能帮用户完成" |
| `status == failed` 且 `gate_reason` 非空（未执行：denied / invalid / unavailable） | **不沉淀**（不是失败，是没做） |
| `status == denied` / `invalid` / `pending_confirmation` | **不沉淀**（未触达外部能力，无事实可记） |
| `status == timeout` | 沉淀（属真失败，可被反思消费） |

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/memory_policy.py::apply_policy` | 候选必须经它（R1~R8） | **零改动** |
| `repositories/memory_repository.py::create_memory` | 唯一写入调用 | 零改动 |
| `services/action/memory_bridge.py` | 泛化键查询；`ACTION_MEMORY_TEMPLATES` 保留兜底 | 增量 |
| `models/memory.py::MemoryCandidate` | 复用既有结构 | 零改动 |
| `application/action_engine.py::integrate_result` | 投递调用改为泛化路径 | 增量 |
| `character/asuna/action.py::ACTION_MEMORY_TEMPLATES` | 保留，作为工具模板缺失时的兜底 | 零改动 |
| `core/settings/action.py::action_memory_policy_json` | V9 既有边界表配置保留（off 路径使用） | 零改动 |
| V2.3.0 `services/world/memory_bridge.py` | **不同通道**（世界事件 → 记忆）；本任务不合并、不改动 | 零改动 |

**与 V2.3.0 世界记忆桥的关系**：两条通道**独立**——世界事件沉淀（V2.3.0）与工具结果沉淀（本任务）各走各的，共同汇入既有 `memory_policy` R1~R8 与 `memories` 表。本任务**不合并两者**，避免破坏 V2.3.0 的幂等标记（`memory_materialized`）语义。

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 复用 `memories` / `memory_candidates`（V4/V2.0 既有） |
| Field | 无新增列 | `memory_policy_key` 是代码资产字段，非 DB 列 |
| Index | 无新增 | — |
| Migration | **无** | — |

**明确不建**：

- 工具专用记忆表（记忆是统一资产，按来源分表会破坏检索与衰减的一致性）。
- 工具执行历史表（执行台账已在 `action_records.steps`，TOOL-003 已裁决）。

**记忆类型域零扩展**：本任务只使用既有类型（`important_event` / `user_fact` / `user_preference`），不新增类型值。

---

# 4. API / Interface Design

## 4.1 边界表接口

```text
interface ToolMemoryPolicy:
    row_for(policy_key: str) -> dict | None
    classify(record: ActionRecord, defn: ToolDefinition) -> MemoryDecision
    to_candidates(record: ActionRecord, defn: ToolDefinition) -> list[MemoryCandidate]
    has_memory_effect(record: ActionRecord) -> bool

MemoryDecision:
    deposit: bool | str        # True / False / "skip"
    reason: str
    memory_type: str | None
    importance: float | None
    source: str | None
```

| 项 | 内容 |
|---|---|
| **Input** | 行动记录 + 工具声明 |
| **Output** | 分类决策 / 候选列表 |
| **失败形态** | 无对应行 → `deposit=False`（保守不沉淀）；模板渲染失败 → 返回空候选 |
| **纪律** | 纯函数、零 IO |

## 4.2 投递接口（扩展既有）

```text
interface ToolMemoryBridge:
    deliver(record: ActionRecord,
            user_id: str,
            character_id: str = "asuna") -> dict | None
        # 返回 {memory_id, content} 或 None
        # 总闸 off → 回退既有 deliver_action_memory（action_type 键）
```

| 项 | 内容 |
|---|---|
| **Input** | 行动记录（含 `steps[].result`）+ 用户/角色 id |
| **Output** | `{memory_id, content}` 或 `None` |
| **失败形态** | 任何异常只 log，**不回滚工具执行**（V9 既有纪律） |

## 4.3 模板接口

```text
interface ToolMemoryTemplates:
    render(policy_key: str, params: dict, *, failed: bool) -> str
        # failed=True → 使用未完成语义模板
        # 无模板 → 返回空字符串（调用方据此跳过沉淀）
```

---

# 5. Implementation Plan

## Step 1 — 边界表与分类纯函数

1. 实现 `ToolMemoryPolicy` 边界表（首版覆盖 §2.2 全部条目）。
2. 实现 `classify` 六步短路（**①②硬纪律优先**）。
3. 实现 `to_candidates` 候选构造 + 失败结果特殊处理。
4. 单测：三条硬纪律各有违背配置的负例（配置 deposit=True 仍不沉淀）；失败结果四态处理；模板渲染。

## Step 2 — 投递路径泛化

1. 扩展 `memory_bridge`：新增 `deliver` 走 `memory_policy_key`；保留 `deliver_action_memory` 作为 off 路径。
2. 扩展 `integrate_result`：总闸 on 走泛化路径，off 走 V9 原路径。
3. 幂等：`effects.kind == "memory"` 检测（复用既有 `has_memory_effect`）。
4. 单测：R1~R8 零豁免（构造被政策拒的候选，验证丢弃）；幂等重复投递；off 路径逐字节一致。

## Step 3 — 模板资产与端到端验证

1. 落地 `TOOL_MEMORY_TEMPLATES` 资产（保留 `ACTION_MEMORY_TEMPLATES` 兜底）。
2. 端到端：用户设置提醒 → 工具执行 → 候选 → R1~R8 → `memories` 落库。
3. 端到端：查询天气 → 工具执行 → **零记忆写入**（断言 `memories` 表无新增）。
4. 回归：Flag 全 off 时记忆投递与 V2.3.0 逐字节一致；V2.3.0 世界记忆桥测试零失败。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 边界表覆盖 §2.2 全部条目；`row_for` 对未知键返回 `None`。
- **三条硬纪律**各自有"配置违背"负例测试：读类工具即使配置 `deposit=True` 也不沉淀；`ext.api.*` / `user.*` 同理。
- 普通结果（如 `world.env.query`）**零记忆写入**（`memories` 表零新增断言）。
- 重要结果（如 `builtin.reminder.create`）进候选并经 R1~R8 后落库，内容与模板一致。
- 生日关键词加权保留：`create_reminder` 内容含"生日" → `user_fact` / importance 0.8。
- 失败结果形态正确：`importance ≥ 0.6`、`type=important_event`、内容带未完成语义。
- 未执行态（denied / invalid / unavailable / pending_confirmation）**零沉淀**。

## 6.2 Integration Acceptance

- 记忆写入**必经** `memory_policy.apply_policy`：人为构造必被政策拒的候选，验证丢弃且无落库（零豁免断言）。
- 幂等：同一次执行重复投递不产生第二条记忆；`effects.kind == "memory"` 检测生效。
- `memory_bridge` 与 `world/memory_bridge` 两条通道独立工作，互不干扰（同轮内两者均触发时各自正确）。
- `memories` / `memory_candidates` 表结构零改动（模型 diff 断言）；零迁移。
- 投递失败**不回滚工具执行**（构造投递异常，验证 `ActionRecord.status` 仍为 `succeeded`）。
- **Flag 全 off 时**：走 V9 `action_type` 键路径，行为与 V2.3.0 逐字节一致；既有记忆测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 边界表无该 tool_id 行 | `deposit=False`（reason=`no_policy_row`），不沉淀、不报错 |
| E2 | 模板渲染缺参（params 无 `content`） | 返回空字符串 → 跳过沉淀（不写半成品内容） |
| E3 | `record.status == "failed"` 且 `gate_reason="permission_denied"` | 不沉淀（未执行，非失败） |
| E4 | `record.status == "timeout"` | 沉淀（真失败），可被反思消费 |
| E5 | `builtin.memory.save` 成功 | `deposit="skip"` 直通；`deliver` 返回 `None` 避免二次投递 |
| E6 | 同一 action 重试后成功（先 failed 后 succeeded） | 仅在终态投递一次；重试期间不投递中间态 |
| E7 | R1~R8 拒绝候选（如内容过短） | 丢弃并记日志；工具执行状态不变 |
| E8 | 内容超 120 字 | 截断至 120 字（V9 既有纪律）后投递 |
| E9 | `v24_tool_memory_enabled` on 但 `action_memory_policy_enabled` off | 泛化路径仍受政策总开关约束 → 不投递 |
| E10 | `ext.api.*` 工具声明 `deposit=True` | 硬纪律优先 → 仍不沉淀 |
| E11 | 工具 `side_effects` 含 `read` 与 `write_memory` 混合 | 非纯读类 → 按边界表判定（不被①误判为读类） |
| E12 | `channel.feishu.send` 确认未完成（pending_confirmation） | 不沉淀（未送达）；确认后成功轮次才沉淀 |
| E13 | 同一轮对话中工具沉淀与对话抽取同时产生候选 | 各自独立经 R1~R8；可能触发既有冲突消解（`memory_conflict`），行为不变 |
