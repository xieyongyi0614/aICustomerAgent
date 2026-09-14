# TOOL-005 Task Detail — Tool Permission System

> 上游：[../architecture.md](../architecture.md) §9（权限与安全设计）、§7.3（确认流）、§8.5（确认流接口）；[../tasks.md](../tasks.md) TOOL-005
> 状态：设计稿（未实现）
> 范围红线：**不新建表**（确认请求复用 `trigger_registry`）；权限闸与 V9 六闸门正交串联、不得绕过；默认拒绝（fail-closed）；不新增 ActionStatus 值。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-005 |
| **Task Name** | Tool Permission System |
| **Priority** | P0 |
| **Dependencies** | TOOL-003, TOOL-004 |
| **建议提交** | `feat: V2.4.0 工具权限闸与确认流` |

## 1.1 Goal

交付**执行前的授权闸**与高风险操作的确认流。实现四档权限等级判定、命名空间默认等级下限、四类授权粒度、默认拒绝的七步短路判定，以及确认请求登记 / 用户批准 / 授权复用 / TTL 过期全流程。

本任务结束后，任一工具调用在触达外部能力之前都必须回答："这次调用被授权了吗？如果需要用户点头，请求登记了吗？"

## 1.2 Scope

**包含**

- 新增 `app/services/tool/permission.py`：`ToolPermissionGate`（纯函数七步判定）。
- 新增 `app/services/tool/confirmation.py`：`ConfirmationService`（请求 / 批准 / 撤销 / TTL）。
- 授权存储：复用 `trigger_registry`（确认请求）+ 内存态（会话级授权）。
- 替换 TOOL-003 的占位权限段为真实判定（接口形状不变）。
- 敏感参数脱敏与高风险审计开关的实际生效（框架在 TOOL-003，本任务接线到权限画像）。
- 单测：四档判定表、默认拒绝全路径、确认流端到端、授权复用与过期。

**不包含（Non-Scope）**

- 工具面投影（TOOL-004）——本任务不参与"哪些工具可用"的判定，只判"选中的这个能不能执行"。
- 工具实现体（TOOL-010）——`channel.feishu.send` 的确认流样板在 TOOL-010 端到端验证。
- 用户自定义工具的注册与校验（TOOL-011）。
- 权限管理 UI（本任务只提供调试端点可见性）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/permission.py` | 新增 | `ToolPermissionGate`（纯函数）+ `PermissionSnapshot` 装配 |
| `app/services/tool/confirmation.py` | 新增 | `ConfirmationService`（请求 / 批准 / 撤销 / 过期 / 授权复用） |
| `app/repositories/trigger_registry_repository.py` | 复用不改 | 确认请求与授权的持久化通道（若需新方法，须在任务内裁决，见 §3） |
| `app/services/tool/executor.py` | 扩展 | 占位权限段替换为真实调用 |
| `app/application/action_engine.py` | 扩展 | `_build_snapshot` 装配 `PermissionSnapshot` |
| `app/application/post_process.py` | 扩展 | 确认话术进入回复素材（不改步骤） |
| `app/api/v1/debug.py` | 扩展 | 确认请求与授权的只读可见性 |

**判定位置图**

```text
ToolExecutor.run（TOOL-003 五段短路）
   │
   ├─ ① resolve
   ├─ ② permission  ◄── 本任务替换为真实判定
   │      ToolPermissionGate.evaluate(defn, inv, snapshot) → PermissionDecision
   │        allow            → 继续 ③
   │        confirm_required → ConfirmationService.request() → 终止（零外部调用）
   │        deny             → 终止（零外部调用）
   ├─ ③ validate
   ├─ ④ invoke
   └─ ⑤ normalize + record
```

## 2.2 数据结构

### PermissionSnapshot（调用方预读，闸门内零 IO）

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | str | 授权主体 |
| `now` | datetime | 判定时刻 |
| `grants` | list[dict] | 有效授权 `{tool_id, scope, granted_at, expires_at, source}` |
| `pending` | list[dict] | 未决确认请求 `{request_id, tool_id, created_at, expires_at}` |
| `channel_bound` | bool | 通道是否已绑定（`channel_identities` 既有） |
| `settings` | Any | 全局 settings |
| `namespace_floors` | dict[str, str] | 命名空间默认等级（来自 TOOL-001 纯函数） |

### PermissionDecision

| 字段 | 类型 | 说明 |
|---|---|---|
| `decision` | str | `allow` / `confirm_required` / `deny` |
| `level` | str | 生效等级（四档） |
| `reason` | str | 判定原因（可读，进 `steps[].permission.reason`） |
| `confirm_prompt` | str? | 确认话术（角色语气） |
| `scope_required` | tuple[str, ...] | 本次调用所需的授权范围 |
| `confirm_kind` | str? | `first_time` / `always` |

### ConfirmationRequest

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | str | 复用 `trigger_registry` 行 id |
| `user_id` | str | — |
| `tool_id` | str | 目标工具 |
| `invocation_snapshot` | dict | 原调用参数快照（批准后复用，防参数漂移） |
| `dedupe_key` | str | 原调用幂等键（批准后复用，防重复发送） |
| `scope_required` | tuple[str, ...] | 需授权范围 |
| `status` | str | `pending` / `approved` / `denied` / `expired` |
| `created_at` / `expires_at` | datetime | TTL = `v24_tool_confirm_timeout_hours` |

### GrantRecord

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` / `tool_id` | str | 授权主体与对象 |
| `scope` | tuple[str, ...] | 授权范围 |
| `granted_at` / `expires_at` | datetime | 有效期 |
| `source` | str | `user_confirm` / `channel_bind` / `session` |

## 2.3 核心流程

### 七步判定（纯函数，短路）

```text
evaluate(defn, inv, snapshot) -> PermissionDecision
   │
   ├─ ① 等级为 safe 或 normal          → allow（reason="level_no_grant_required"）
   ├─ ② 存在有效 grant（scope 覆盖）    → allow（reason="grant_matched"）
   ├─ ③ confirm == first_time 且无 grant → confirm_required（kind=first_time）
   ├─ ④ confirm == always               → confirm_required（kind=always，不落长期 grant）
   ├─ ⑤ scope 越界（请求范围未被授权集覆盖）→ deny（reason="out_of_scope"）
   ├─ ⑥ 不受信命名空间（user.* / ext.api.*）无任何 grant → deny（reason="untrusted_namespace"）
   └─ ⑦ 以上皆非 → deny（reason="default_deny"）
```

**默认拒绝（fail-closed）** 是硬纪律：任何未明确 allow 的情况一律 deny——与 V9 detector "宁缺毋滥"（异常返回 `None`）同一价值观。

### 确认流全链

```text
① evaluate 命中 confirm_required
        │
        ▼
② ConfirmationService.request(inv, decision, ctx)
   · 登记 trigger_registry（type=confirmation_pending，due_at=now+TTL）
   · 生成确认话术（角色语气，≤ 预算）
   · ⚠ 本轮零外部调用
        │
        ▼
③ 回复生成（既有 answer_chain）
   "要我现在就把这条消息发给小林吗？"
        │
        ▼
④ 用户回应（下一条消息）
   ├─ 肯定 → 检出确认意图 → 作为新一轮 run_action_planning 触发
   │         · 参数复用 invocation_snapshot（不重新抽取）
   │         · 幂等复用原 dedupe_key（防重复发送）
   │         · confirm=first_time → 落 grant
   ├─ 否定 → 请求置 denied，工具不执行
   └─ 无回应 → TTL 到期置 expired（维护步清理，复用 trigger_registry 过期机制）
```

### 授权复用与撤销

```text
has_grant(user_id, tool_id, scope) -> bool
    遍历有效 grant（未过期且 scope 覆盖请求范围）

grant_scope(user_id, tool_id, scope) -> str
    写入 grant（source=user_confirm，expires_at 按策略）
    v24_tool_confirm_ttl_reuse=False 时不落长期 grant（等价 confirm=always）

revoke(user_id, tool_id) -> int
    撤销该工具全部 grant；通道解绑时撤销 channel.* 授权
```

### 授权粒度

| 粒度 | 生效范围 | 存储 | 撤销 |
|---|---|---|---|
| 会话级 | 当前 session | 内存态 | 会话结束 |
| 工具级 | `(user_id, tool_id)` | `trigger_registry` 授权行 | 显式撤销 / TTL |
| 范围级 | `(user_id, tool_id, scope)` | 同上 | 同上 |
| 通道级 | 绑定通道即隐含 `channel.<name>.*` 基础授权 | `channel_identities`（既有） | 解绑 |

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `repositories/trigger_registry_repository.py` | 确认请求与授权行的读写通道 | 复用；**若需扩列见 §3 裁决** |
| `repositories/channel_identity_repository.py` | 通道绑定状态读取（通道级授权） | 只读 |
| `application/action_engine.py::_build_snapshot` | 装配 `PermissionSnapshot`（预读 grants / pending） | 增量 |
| `application/action_engine.py::run_action_planning` | 确认态映射为 `planned` + `gate_reason=pending_confirmation` | 增量 |
| `application/post_process.py` | 确认话术进回复素材（不改步骤） | 增量 |
| `application/life_loop.py` | 复用既有维护步清理过期确认请求（**不新增维护步**） | 零改动（复用既有过期机制） |
| `services/tool/executor.py` | 权限段替换（接口形状不变） | 增量 |
| `models/action.py::GATE_REASONS` | 消费 `permission_denied` / `pending_confirmation`（TOOL-001 已加） | 零改动 |
| V9 六闸门（`services/action/planner.py`） | **正交串联**：六闸门先过（不通过则不装配计划），权限闸在执行器内 | 零改动 |

**确认意图检出（关键设计裁决）**：用户"肯定/否定"的识别**复用 V9 `services/action/detector.py` 的确定性词表机制**（新增确认词表资产），不新增 LLM 调用、不新增管线。确认轮次进入 `run_action_planning` 时，若存在 pending 请求且本轮为确认回应，则**以原 `invocation_snapshot` 与 `dedupe_key` 发起新一轮行动**。

---

# 3. Database Changes

**本任务原则上无 DDL 变更；但存在一处需在任务内裁决的例外。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 确认请求复用 `trigger_registry`（语义吻合：等待用户回应的待办触发） |
| Field | **待裁决**（见下） | 确认请求需承载 `invocation_snapshot` / `dedupe_key` / `scope_required` / 话术 |
| Index | 无新增 | 沿用 `trigger_registry` 既有索引 |
| Migration | **条件性** | 若裁决为"需扩列"则产生迁移；否则无 |

## 3.1 字段承载方案裁决（Q2）

`trigger_registry` 既有结构是否已有承载位需在实现前确认，两条路线：

| 方案 | 做法 | 代价 | 推荐 |
|---|---|---|---|
| **A（推荐）** | 复用 `trigger_registry` 既有 JSON 载荷列承载 `invocation_snapshot` / `scope_required` / 话术；`dedupe_key` 复用既有幂等键位 | 零 DDL、零迁移 | ✅ 与 architecture §5.1"零新建表"强断言一致 |
| **B** | 为 `trigger_registry` 扩 2~4 列 | 产生迁移，破坏"零迁移"断言 | 仅当 A 无法容纳时采用 |

**裁决要求**：实现前必须核对 `trigger_registry` 实际列结构并记录结论。若走方案 B，**必须回写 architecture §5.1 与 tasks.md TOOL-012 的"零迁移"断言**，否则 TOOL-012 验收条目自相矛盾。

## 3.2 授权存储

| 项 | 结论 |
|---|---|
| Table | 无新增；授权行复用 `trigger_registry`（type=`tool_grant`） |
| 会话级授权 | 内存态（进程内，会话结束即失效） |
| 通道级授权 | 不新增存储，由 `channel_identities` 绑定状态隐含 |

---

# 4. API / Interface Design

## 4.1 权限闸接口

```text
interface ToolPermissionGate:
    evaluate(defn: ToolDefinition,
             inv: ToolInvocation,
             snapshot: PermissionSnapshot) -> PermissionDecision

    build_snapshot(user_id: str, now: datetime, settings: Any) -> PermissionSnapshot
```

| 项 | 内容 |
|---|---|
| **Input** | 工具声明 + 调用意图 + 预读快照 |
| **Output** | `PermissionDecision`（decision / level / reason / confirm_prompt / scope_required） |
| **失败形态** | **不抛异常**——一切判定归一为 decision 三值之一。快照装配失败 → `deny`（reason=`snapshot_unavailable`，保守拒绝） |
| **纪律** | `evaluate` 纯函数、零 IO；`build_snapshot` 是唯一的读 IO 入口 |

## 4.2 确认服务接口

```text
interface ConfirmationService:
    request(inv: ToolInvocation,
            decision: PermissionDecision,
            ctx: ToolContext) -> ConfirmationRequest
    resolve(request_id: str, *, approved: bool, source: str) -> ConfirmationOutcome
    pending(user_id: str) -> list[ConfirmationRequest]
    expire_due(now: datetime) -> int

    grant_scope(user_id: str, tool_id: str, scope: tuple[str, ...]) -> str
    has_grant(user_id: str, tool_id: str, scope: tuple[str, ...]) -> bool
    revoke(user_id: str, tool_id: str) -> int
```

| 方法 | Input | Output | 失败形态 |
|---|---|---|---|
| `request` | 调用意图 + 判定 + 上下文 | `ConfirmationRequest` | 登记失败 → 返回 `None` 且调用方按 `deny` 处理（保守） |
| `resolve` | 请求 id + 批准与否 | `ConfirmationOutcome`（`approved` / `denied` / `not_found` / `expired`） | 已过期 → `expired`，不执行 |
| `pending` | user_id | 未决请求列表 | 无 → 空列表 |
| `expire_due` | now | 过期条数 | — |
| `grant_scope` / `has_grant` / `revoke` | 授权三元组 | grant id / bool / 撤销条数 | — |

## 4.3 确认意图检出接口

```text
interface ConfirmationIntentDetector:
    detect(content: str, pending: list[ConfirmationRequest]) -> tuple[str, str] | None
    # 返回 (request_id, "approve" | "deny")；无 pending 或无匹配 → None
```

**词表资产**（`app/character/asuna/tool.py`）：

| 意图 | 词表（示例） |
|---|---|
| approve | 好、行、可以、发吧、嗯、对、确认、就这样、帮我发 |
| deny | 不用了、算了、别发、取消、不要、先不发 |

**纪律**：与 V9 detector 同款——**问句守卫**（"能发吗？"不触发执行）+ **祈使优先**；检出异常返回 `None`（宁缺毋滥）。

## 4.4 调试端点（增量）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/debug/tools/permissions?user_id=` | 有效授权清单 |
| GET | `/api/v1/debug/tools/confirmations?user_id=` | 未决确认请求 |
| POST | `/api/v1/debug/tools/confirmations/{request_id}/revoke` | 撤销未决请求（运维） |
| POST | `/api/v1/debug/tools/permissions/revoke` | 撤销授权（运维） |

---

# 5. Implementation Plan

## Step 1 — 权限闸纯函数与快照装配

1. 实现 `ToolPermissionGate.evaluate` 七步短路（每步独立私有函数，可单测）。
2. 实现 `build_snapshot`：预读 grants / pending / 通道绑定 / 命名空间下限。
3. 实现确认话术生成（角色语气，长度预算内）。
4. 单测：四档 × 六场景判定表全覆盖；默认拒绝全路径（含快照不可用）；越界与不受信命名空间。

## Step 2 — 确认服务与授权存储

1. **先做 §3.1 裁决**：核对 `trigger_registry` 列结构，确定方案 A 或 B 并留痕。
2. 实现 `ConfirmationService`：request / resolve / pending / expire_due。
3. 实现授权：grant_scope / has_grant / revoke（工具级 + 范围级 + 会话级）。
4. 复用既有维护步清理过期请求（不新增维护步）。
5. 单测：确认流状态机、TTL 过期、授权复用（`v24_tool_confirm_ttl_reuse` 两态）、撤销、通道解绑撤销。

## Step 3 — 执行器接线与确认轮次闭环

1. 替换 `ToolExecutor` 权限段占位为真实判定。
2. 扩展 `action_engine._build_snapshot` 装配 `PermissionSnapshot`；确认态映射为 `planned` + `pending_confirmation`。
3. 实现 `ConfirmationIntentDetector` + 词表资产；确认轮次以原 `invocation_snapshot` 与 `dedupe_key` 发起新一轮行动。
4. 确认话术进回复素材（不改 `post_process` 步骤）。
5. 单测：`confirm_required` 零外部调用（打桩断言）、批准后参数与幂等键复用、确认轮次端到端、调试端点。
6. 回归：Flag 全 off 时权限段不参与（`v24_tool_permission_enabled` off 保持 allow-all 占位语义，行为与 TOOL-003 交付态一致）。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 四档等级判定表逐条通过；`safe` / `normal` 无需授权即放行。
- 七步短路顺序固定，每步有正例与负例测试。
- **默认拒绝**：未明确 allow 的情况一律 deny，含 `out_of_scope` / `untrusted_namespace` / `default_deny` 三类原因。
- `confirm_required` 生成角色语气话术（非系统公告口吻），长度在预算内。
- 确认请求状态机：`pending` → `approved` / `denied` / `expired`，非法迁移拒绝。
- 授权复用：`v24_tool_confirm_ttl_reuse=True` 时首次批准后 TTL 内直接放行；False 时每次均需确认。
- 授权撤销即时生效（同一进程内下一次判定即 deny）。
- 确认意图检出：肯定 / 否定各 ≥ 5 个词表命中；问句守卫生效（"能发吗"不触发）。

## 6.2 Integration Acceptance

- `confirm_required` 与 `deny` 路径**零外部调用**（DB 写与网络均打桩断言为 0）。
- 确认态映射为 `ActionRecord.status="planned"` + `gate_reason="pending_confirmation"`，**未新增 ActionStatus 值**（枚举 diff 断言）。
- 批准后的新一轮行动**复用原 `invocation_snapshot` 与 `dedupe_key`**：不重新抽取参数、不产生第二条 `ActionRecord`（幂等验证）。
- 确认请求的过期清理由**既有维护步**完成，`life_loop` 维护步序列零改动（diff 断言）。
- V9 六闸门零改动；权限闸与之正交串联（先六闸门后权限闸，顺序断言）。
- 确认话术进入回复素材但不改变 `post_process` 步骤数与序列（形状快照）。
- **Flag 全 off 时**：权限段不参与，行为与 TOOL-003 交付态一致；既有测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `PermissionSnapshot` 装配失败（如仓储异常） | `deny`（reason=`snapshot_unavailable`），保守拒绝，不抛错 |
| E2 | 授权已过期但仍在快照中（边界时刻） | 按 `now` 严格判定，过期即不匹配 |
| E3 | 授权 scope 为 `("external:a.com",)`，请求 `("external:b.com",)` | 范围不覆盖 → `out_of_scope` deny |
| E4 | 同一工具同时存在 `first_time` grant 与 `always` 配置 | `always` 优先（每次确认），grant 不生效 |
| E5 | 用户批准后请求又过期（批准晚于 TTL） | `resolve` 返回 `expired`，不执行；提示用户重新发起 |
| E6 | 用户否定后再次提出同一请求 | 允许（新请求），但 `dedupe_key` 与原调用相同 → 由 V9 G4 去重窗口拦截重复执行 |
| E7 | 存在 2 条 pending 请求，用户回复"好" | 命中最近一条（`created_at` 最新），另一条保持 pending |
| E8 | 存在 pending 但用户回复与确认无关的内容 | 检出 `None`，按普通对话处理，pending 不消费 |
| E9 | `channel.*` 工具且通道已绑定 | 通道级授权满足基础 scope，但 `confirm=first_time` 仍要求首次确认 |
| E10 | 通道解绑后调用 `channel.*` 工具 | 通道级授权失效 → 无 grant → `confirm_required` 或 deny |
| E11 | `user.*` 工具无任何 grant | `untrusted_namespace` deny（不进入确认流） |
| E12 | 确认话术生成失败 | 回退通用话术（"这件事需要你点头我才敢做，可以吗？"），不阻断流程 |
| E13 | 同一用户并发两条确认请求 | 按 `created_at` 排序，回复消费最近一条；不引入并发控制 |
| E14 | `v24_tool_permission_enabled` on 但总闸 off | 权限段不参与（总闸为上层门控），保持 allow-all |
