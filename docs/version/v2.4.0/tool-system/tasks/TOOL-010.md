# TOOL-010 Task Detail — Built-in Tools

> 上游：[../architecture.md](../architecture.md) §4.2.4（内置 Tool 清单）、§7.6（Channel 集成）、§10.1（新增工具四步）、§9.4（敏感操作确认）；[../tasks.md](../tasks.md) TOOL-010
> 状态：设计稿（未实现）
> 范围红线：**不新建通道**（复用既有 `OutboundMessage` 契约与切分逻辑）；不修改 V9 六个 Capability 的执行语义（只补声明与可用性）；不新建表。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-010 |
| **Task Name** | Built-in Tools |
| **Priority** | P1 |
| **Dependencies** | TOOL-002, TOOL-003, TOOL-005, TOOL-007 |
| **建议提交** | `feat: V2.4.0 内置工具集与通道工具` |

## 1.1 Goal

交付**工具供给与首批落地能力**。把 V9 六个既有能力的声明补全为可治理工具，把两个既有空壳能力（`search` / `notification`）从"接口预留"推进到可用或明确降级语义，并交付 `channel.feishu.*` 通道工具包装（复用既有出站契约与文本切分）作为高风险确认流的端到端样板。

同时交付角色资产：工具语义描述文案、确认话术模板、工具面投影的场景与关系规则、记忆边界表键。

## 1.2 Scope

**包含**

- 补全 V9 六能力的工具声明（`reminder` / `memory` / `world_action` / `environment_query` / `search` / `notification`）——声明已在 TOOL-002 落地，本任务补全 **schema 细节、observations 映射、记忆边界键、语义校验器绑定**。
- 推进 `search` / `notification` 两能力可用性（接可用来源或明确降级语义与失败分类）。
- 新增 `channel.feishu.send` 工具包装（复用 `channels/base.py` 契约 + `feishu/outbound.split_text` + `OutboundMessage.idempotency_key`）。
- 新增 `app/character/asuna/tool.py`：工具语义文案 / 确认话术 / 投影规则（TOOL-004 已建骨架，本任务补全内容）/ 记忆边界键。
- 端到端验证：≥ 9 工具 × 成功 / 校验失败 / 权限拒绝三类路径。
- 新增工具的四步流程实操验证（作为可扩展性的验收证据）。

**不包含（Non-Scope）**

- 外部 API 工具与自定义工具（TOOL-011）。
- 工具注册表、执行器、权限闸、工具面投影本体（TOOL-002 ~ TOOL-005）。
- 多步工具编排（`action_plan_max_steps` 保持 1）。
- 工具清单进 prompt 渲染（若需，属 prompt 预算决策，见 Q5）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/builtin.py` | 新增 | 内置工具的完整声明（schema / observations / 校验器绑定） |
| `app/services/action/capabilities/search.py` | 扩展 | 从空壳推进到可用或明确降级 |
| `app/services/action/capabilities/notification.py` | 扩展 | 从空壳推进到可用（行动 note + 到期汇报） |
| `app/services/tool/channel_tools.py` | 新增 | 通道工具包装（复用出站契约） |
| `app/character/asuna/tool.py` | 扩展 | 文案 / 话术 / 投影规则 / 记忆键资产 |
| `app/channels/feishu/*` | 复用不改 | 出站契约、切分、身份、投递 |

**工具分层图**

```text
ToolDefinition（声明，TOOL-002 注册）
        │  绑定
        ▼
Capability（V9 既有实现体，本任务不改执行语义）
   ├─ ReminderCapability         → builtin.reminder.create / cancel
   ├─ MemoryCapability           → builtin.memory.save
   ├─ WorldActionCapability      → world.object.create / move / use
   ├─ EnvironmentQueryCapability → world.env.query
   ├─ SearchCapability           → builtin.search.query      ← 本任务推进
   └─ NotificationCapability     → builtin.notification.send ← 本任务推进
        │
        ▼
ChannelCapability（本任务新增，包装既有 Feishu 出站）
   └─ channel.feishu.send
```

## 2.2 数据结构

### 内置工具完整声明（本任务补全的字段）

| tool_id | input_schema 要点 | observations 映射 | 语义校验器 | memory_policy_key |
|---|---|---|---|---|
| `builtin.reminder.create` | `content`(str, req, ≤40) / `due_at`(datetime, req) / `importance`(enum) | `world.event_id` / `time.due_at` | `future_datetime`, `content_within_budget` | 同名 |
| `builtin.reminder.cancel` | `target`(str, req) | `world.cancelled_count` | — | 同名 |
| `builtin.memory.save` | `fact`(str, req) / `memory_type`(enum) / `importance`(number) | `memory.id` | `content_within_budget` | 同名（skip 直通） |
| `world.object.create` | `object`(str, req) / `category`(enum?) | `world.object_id` | — | 同名 |
| `world.object.move` | `object`(str, req) / `location`(str, req) | `world.object_id` / `world.location_id` | `object_in_inventory`, `location_exists` | 无（不沉淀） |
| `world.object.use` | `object`(str, req) | `world.object_id` | `object_in_inventory` | 无 |
| `world.env.query` | 无必填 | `env.weather` / `env.part_of_day` / `env.location` | — | 无（读类强制不沉淀） |
| `builtin.search.query` | `query`(str, req, ≤60) | `search.result_count`（内容打 `untrusted`） | `content_within_budget` | 无（读类强制不沉淀） |
| `builtin.notification.send` | `content`(str, req, ≤200) | `note.created` | `content_within_budget` | 同名 |
| `channel.feishu.send` | `content`(str, req, ≤200) / `recipient`(str, req) | `external.message_id` | `recipient_authorized`, `content_within_budget` | 同名 |

### 通道工具声明要点

| 字段 | 值 | 理由 |
|---|---|---|
| `namespace` | `channel` | 命名空间默认等级 `sensitive` |
| `permission.level` | `sensitive` | 有外部可见性 |
| `permission.scope` | `("channel:feishu",)` | 范围限定 |
| `permission.confirm` | `first_time` | 首次确认 + TTL 内复用 |
| `permission.requires_online` | `True` | 不在离线时刻主动外发 |
| `permission.audit` | `True` | 外部可见操作强制审计 |
| `side_effects` | `("send_external",)` | 触发高风险判定 |
| `idempotency` | `keyed` | 幂等键填 `OutboundMessage.idempotency_key` |

### 角色资产（`app/character/asuna/tool.py`）

| 资产 | 内容 |
|---|---|
| `TOOL_SEMANTIC_TEXT` | tool_id → 中文语义描述（≤ 120 字） |
| `TOOL_CONFIRM_PROMPTS` | tool_id → 确认话术模板（角色语气，≤ 60 字） |
| `TOOL_SURFACE_RULES` | Run Profile / 日时段 / 场景 / 关系阶段投影规则（TOOL-004 消费） |
| `TOOL_MEMORY_TEMPLATES` | 工具内容模板（TOOL-008 消费） |
| `TOOL_OBSERVATION_KEYS` | tool_id → observations 键映射表 |
| `CONFIRM_APPROVE_LEXICON` / `CONFIRM_DENY_LEXICON` | 确认意图词表（TOOL-005 消费） |

## 2.3 核心流程

### `search` 能力推进（从空壳到可用）

```text
现状：execute() 直接返回 status="unavailable"
本任务两条路线（择一，需在任务内裁决并留痕）：
   路线 A（推荐）：接入一个可用的检索来源（既有依赖内可满足者），
                  返回 status="succeeded" + observations{result_count}
                  外部内容一律打 untrusted=True 标记
   路线 B：明确降级语义——保持 unavailable，但补齐 failure_kind 与用户可见话术，
          并在工具面规则中默认裁剪（避免用户反复触发必然失败的工具）
判定标准：无论选哪条，工具必须"有可判定行为"——不允许继续停留在无信息的空壳态
```

### `notification` 能力推进

```text
现状：execute() 直接返回 status="unavailable"
本任务：落为"行动 note + 既有 V7 到期汇报"
   · send → 产出 note 类效果（ToolEffect.kind="note"）
   · 进回复素材（角色自然语言提及）
   · 到期汇报复用既有 trigger_registry（action_due）通道，不新建机制
```

### 通道工具执行链

```text
channel.feishu.send 调用
        │
        ▼
① 权限闸（TOOL-005）
   level=sensitive + confirm=first_time
   ├─ 无 grant → confirm_required（话术进回复）
   └─ 有 grant → allow
        │
        ▼
② 参数校验（TOOL-003）
   recipient_authorized（需 TOOL-005 填充 authorized_recipients）
   content_within_budget（≤ 200）
        │
        ▼
③ 执行（复用既有出站设施）
   构造 OutboundMessage{
     channel="feishu",
     recipient=RecipientRef(channel, external_id),
     text=content,
     idempotency_key=<dedupe_key>
   }
   → 既有 ChannelAdapter.send()
   → SendResult{ok, external_message_id, error}
        │
        ▼
④ 归一
   ok     → status="succeeded", effects=[{kind:"external", ref:message_id, reversible:False}]
   !ok    → status="failed", failure_kind 由 ChannelErrorKind 映射
        │
        ▼
⑤ 文本切分
   复用 feishu/outbound.split_text（不变式："".join(parts) == text）
```

**ChannelErrorKind → failure_kind 映射**

| ChannelErrorKind | failure_kind | 是否重试 |
|---|---|---|
| `RATE_LIMITED` | transient | 是 |
| `TIMEOUT` | timeout | 是 |
| `SERVER_ERROR` | transient | 是 |
| `AUTH` / `DISABLED` | permanent | 否 |
| `NOT_FOUND` / `INVALID_REQUEST` | permanent | 否 |
| `CLIENT_ERROR` / `UNKNOWN` | transient | 是 |

### 新增工具的四步流程（可扩展性验证）

```text
① 声明  → builtin.py 加一条 ToolDefinition（含 schema / permission / side_effects / 记忆键）
② 实现  → 复用既有 Capability（或新增实现体）
③ 注册  → register_builtin_tools 加一行
④ 资产  → asuna/tool.py 加语义文案 / observations 键 / 记忆模板
不需要改：planner / decision_pipeline / chat_pipeline / post_process / action_engine / autonomy_engine / prompt builder
```

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/action/capabilities/*`（6 个） | 保留执行语义；仅补 schema / observations / 校验器绑定 | 增量 |
| `services/action/capabilities/search.py` | 从空壳推进（本任务核心改动之一） | 实现 |
| `services/action/capabilities/notification.py` | 从空壳推进 | 实现 |
| `channels/base.py`（`OutboundMessage` / `SendResult` / `RecipientRef`） | 通道工具包装复用，**零改动** | 零改动 |
| `channels/feishu/outbound.py::split_text` | 复用，**零改动**；不变式沿用既有测试 | 零改动 |
| `channels/feishu/client.py` / `delivery.py` | 经既有 Adapter 发送 | 零改动 |
| `services/channel_identity_service.py` | 身份解析（收件人 external_id） | 只读 |
| `services/action/registry.py::CapabilityRegistry` | 新增 `ChannelCapability` 注册 | 增量（注册一行） |
| `character/asuna/action.py` | 保留 `ACTION_CAPABILITY_MAP` / `ACTION_MEMORY_TEMPLATES` | 零改动 |
| `services/action/memory_bridge.py` | 消费 `TOOL_MEMORY_TEMPLATES` | 零改动（TOOL-008 已泛化） |
| `application/world_engine.py` | 世界类工具经既有延迟投递（TOOL-007 已保障） | 零改动 |

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 通道工具不建发送记录表（幂等由 `OutboundMessage.idempotency_key` + `action_records.dedupe_key` 双保险）；行动 note 走既有 `ActionRecord.result.effects` |
| Field | 无新增列 | `external.message_id` 落 `steps[].result.effects`（JSON 内嵌，TOOL-003 已定义） |
| Index | 无新增 | — |
| Migration | **无** | — |

**明确不建**：

- 通道发送记录表（发送事实已在 `action_records` 台账 + 通道侧既有记录）。
- 通知队列表（`trigger_registry` 已承担到期触发）。

---

# 4. API / Interface Design

## 4.1 内置工具声明接口

```text
interface BuiltinToolRegistry:
    register_all(registry: ToolRegistry) -> None
        # 按 §2.2 表逐条声明；含 schema 细节、observations 键、校验器绑定
    definitions() -> list[ToolDefinition]      # 供快照测试
```

## 4.2 通道工具接口

```text
interface ChannelToolCapability:
    name: str = "channel_feishu"
    actions: {"send": ActionSchema}

    validate(action: str, params: dict) -> list[str]

    async execute(action: str,
                  params: dict,
                  ctx: ExecutionContext) -> CapabilityResult
        # 内部：构造 OutboundMessage → Adapter.send → 映射 SendResult
```

| 项 | 内容 |
|---|---|
| **Input** | `content`（≤ 200）+ `recipient`（external_id） |
| **Output** | `CapabilityResult`（`payload.external_message_id` 或 `failure_kind`） |
| **失败形态** | 通道错误按 §2.3 映射表归一；**不抛异常** |
| **纪律** | 不重写文本切分；幂等键直填 `OutboundMessage.idempotency_key` |

## 4.3 观察键映射接口

```text
interface ToolObservationKeys:
    keys_for(tool_id: str) -> dict[str, str]
        # 返回 {payload_key: observation_key}，如
        #   {"world_event_id": "world.event_id", "due_at": "time.due_at"}
        # 归一器（TOOL-003）据此填充 observations，同时保留旧键
```

## 4.4 角色资产接口

```text
interface ToolAssets:
    semantic_text(tool_id: str) -> str              # ≤ 120 字
    confirm_prompt(tool_id: str, params: dict) -> str   # ≤ 60 字，角色语气
    surface_rules(run_kind: str) -> SurfaceRule
    memory_template(tool_id: str) -> str
    observation_keys(tool_id: str) -> dict[str, str]
    approve_lexicon() -> tuple[str, ...]
    deny_lexicon() -> tuple[str, ...]
```

---

# 5. Implementation Plan

## Step 1 — 内置工具声明补全与资产落地

1. 实现 `builtin.py`：按 §2.2 补全 ≥ 9 个工具的完整声明（schema / observations / 校验器 / 记忆键）。
2. 落地 `asuna/tool.py` 全部资产（语义文案 / 确认话术 / 投影规则 / 记忆模板 / 观察键 / 确认词表）。
3. 单测：声明快照稳定；文案与话术长度预算；观察键映射完整。

## Step 2 — 两能力推进与通道工具

1. **先裁决 `search` 路线 A 或 B** 并留痕，然后实现。
2. 实现 `notification` 的行动 note 路径（复用既有到期汇报通道）。
3. 实现 `ChannelCapability` + `channel.feishu.send` 声明（复用出站契约与切分）。
4. 单测：两能力有可判定行为；通道工具错误映射表逐行；切分不变式沿用既有测试；幂等键对齐。

## Step 3 — 端到端验证与四步流程实操

1. 端到端：≥ 9 工具 × 成功 / 校验失败 / 权限拒绝三类路径（≥ 27 个用例）。
2. 确认流端到端：`channel.feishu.send` 首发确认 → 批准 → TTL 内复用 → 过期后再次确认。
3. 四步流程实操：新增一个示例工具，记录实际改动文件数与步骤数（验收证据）。
4. 回归：Flag 全 off 时既有能力行为逐字节一致；V9 能力测试零失败。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- ≥ 9 个内置工具可被 `describe` / `resolve` / 执行，各自端到端通过。
- 每个工具有三类路径用例：成功 / 校验失败（`invalid`）/ 权限拒绝（`denied`）。
- `search` 与 `notification` **不再是"尚未接入"空壳**：有可判定行为，或明确的降级语义 + 失败分类 + 工具面默认裁剪。
- 通道工具：首发需确认；批准后 TTL 内复用；切分不变式 `"".join(parts) == text` 沿用既有测试通过；幂等键与 `OutboundMessage.idempotency_key` 一致。
- 通道错误映射表逐行正确；`AUTH` / `DISABLED` 不重试，`RATE_LIMITED` / `TIMEOUT` 重试。
- 语义文案 ≤ 120 字、确认话术 ≤ 60 字且经人工审核可读（非系统公告口吻）。
- observations 键映射与 §2.2 表一致，且 V9 旧键保留。

## 6.2 Integration Acceptance

- 新增一个内置工具的完整步骤 **≤ 4 步**，且**不改动** planner / decision_pipeline / chat_pipeline / post_process / action_engine / autonomy_engine / prompt builder（diff 断言）。
- `channels/base.py` / `feishu/outbound.py` / `feishu/client.py` / `feishu/delivery.py` **零 diff**。
- `services/action/capabilities/` 中除 `search.py` / `notification.py` 外其余**零 diff**（执行语义未变）。
- 通道工具经既有延迟投递与既有 outbox 路径（TOOL-007 契约）；无直写世界/角色域。
- 确认流端到端与 TOOL-005 契约一致；确认请求复用既有待办触发台账。
- **Flag 全 off 时**：既有六能力行为逐字节一致；V9 能力测试零失败。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `search` 选择路线 B（保持 unavailable） | 工具面默认裁剪该工具（避免反复触发必然失败）；调用时返回 `unavailable` + 明确话术 |
| E2 | 通道发送内容超 200 字 | `content_within_budget` 拦截 → `invalid`，不触达通道 |
| E3 | 收件人不在已授权名单 | `recipient_authorized` 拦截 → `invalid`（不进入确认流） |
| E4 | 通道未绑定（`feishu_enabled=False`） | 工具 `effective_status=disabled` → 不进工具面 |
| E5 | 通道返回 `AUTH` 错误 | `failure_kind=permanent`，不重试；健康度计失败 |
| E6 | 通道返回 `RATE_LIMITED` | `failure_kind=transient`，既有退避重试；同 `dedupe_key` 不重复发送 |
| E7 | 发送成功但响应无 `external_message_id` | `status=succeeded` 但 effects 的 `ref` 为空字符串；记日志（不视为失败） |
| E8 | 确认后用户改口（先批准后又否定） | 批准已消费则否定不生效；未消费（pending）则否定置 denied |
| E9 | 同一内容对同一收件人重复请求 | `dedupe_key` 相同 → V9 G4 去重窗口拦截 |
| E10 | `world.object.use` 物品不在库存 | `object_in_inventory` 拦截 → `invalid`（TOOL-007 供给事实） |
| E11 | `builtin.reminder.create` 的 `due_at` 为过去 | `future_datetime` 拦截 → `invalid` |
| E12 | 工具文案超长 | 声明期校验拒绝（TOOL-002 校验 7） |
| E13 | 确认话术模板缺参 | 回退通用话术（TOOL-005 兜底） |
| E14 | `notification` 产出 note 但用户离线 | note 进回复素材待下次上线呈现；不因离线而外发 |
| E15 | 新增示例工具忘记加资产条目 | 声明快照测试失败（观察键或文案缺失） |
