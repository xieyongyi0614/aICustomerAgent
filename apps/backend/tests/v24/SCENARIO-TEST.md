# V2.4.0 Tool System Scenario Test

> **上游依据**：[architecture.md](../../../../docs/version/v2.4.0/tool-system/architecture.md) §4（核心模块）、§5（数据模型）、§6（调用流程）、§7（集成）、§9（权限与安全）、§11.4（版本验收 Gate）；[tasks/TOOL-012](../../../../docs/version/v2.4.0/tool-system/tasks/TOOL-012.md) §2.3 场景表。
> **定位**：以「用户视角可观察的行为」为单位的场景级验收文档，覆盖 S1~S10 十组共 46 例，全部离线可跑。
> **与既有验收资产的关系**：
> - `apps/backend/tests/v24/test_tool012_scenarios.py` — 本文件全部用例的可执行实现（1:1 对应）。
> - `apps/backend/tests/v24/test_tool_acceptance.py` — Gate 层判定（Flag 矩阵 / 逐字节一致 / 零迁移）。**本文件不重复其断言**：Gate 判"能不能上线"，场景判"用起来是什么样"。
> - `apps/backend/tests/v24/ACCEPTANCE-CHECKLIST.md` — 真实模型 / 真实通道人工回归条目。
> **状态**：待执行（执行结论回写文末「执行记录」区）。
> **三条硬约束**：① 不新增功能（全部期望值取自已实现代码）；② 组件 / 表 / Flag / 事件类型一律引用 architecture 既有定义；③ 每条用例可执行、可观测、可判定。
> **落位说明（偏移登记）**：TOOL-012 原计划产出 `docs/version/v2.4.0/tool-system/scenario-test.md`；本次按用户级约束「不改文档」改落至本路径，`docs/` 零改动。

---

## 0. 场景测试总则

### 0.1 被测对象与验收目标

| 维度 | 内容 |
|---|---|
| 被测系统 | V2.4.0 Tool System（Tool Decision Layer + Registry + Executor + Permission + World/Memory/Reflection/Channel/Ext 集成） |
| 验收目标 | 工具能被**治理**（可发现、可裁剪、可拦下、可追溯）、**可执行**（四纪律生效）、**不越界**（不新建 Agent / Memory / Event，不改 Session 存储） |
| 判定基准 | 每条用例的 Expected Result 全部为布尔可判定项；任一 FAIL 即场景不通过 |
| 失败分级 | P0（越权 / 越界 / 数据损失 / 逐字节不一致）= 阻断发布；P1（行为偏差）= 修复后重测；P2（呈现瑕疵）= 登记 |

### 0.2 环境与观测面

| 项 | 说明 |
|---|---|
| Flag 基线 | 全部 `v24_*` 默认 off；每条用例 Preconditions 显式声明所需 Flag |
| 离线纪律 | 零真实 LLM（`FakeLLM` / 脚本化 stub）、零真实网络（`StubTransport`）、零真实通道（`RecordingAdapter`）、内存 SQLite |
| 观测面 ① | 调试端点 `/api/v1/debug/tools*` |
| 观测面 ② | `action_records.steps[]`（工具执行台账唯一落点） |
| 观测面 ③ | `trigger_registry`（确认 / 授权，复用既有表）+ `outbox_events` / `world_events` |

### 0.3 场景编号规则

| 段 | 主题 | 对应 architecture 章节 | 用例数 |
|---|---|---|---|
| S1 | 前台工具调用 | §6.1 完整调用链 | 11 |
| S2 | 参数校验 | §4.4 ParamValidator | 13 |
| S3 | 权限与确认 | §9.3 / §9.4 | 5 |
| S4 | 自治调用 | §7.2 Autonomy 集成 | 1 |
| S5 | 世界契约 | §7.3 World 集成 | 2 |
| S6 | 记忆分层 | §7.4 Memory 集成 | 4 |
| S7 | 反思效能 | §7.5 Reflection 集成 | 2 |
| S8 | 通道工具 | §7.6 Channel 集成 | 3 |
| S9 | 扩展性 | §10 扩展方案 | 3 |
| S10 | 多 tick 韧性 | §4.3 / §9.5 | 3 |

### 0.4 期望值溯源原则

每条用例的 Expected Result 后附 **Code Basis**（实现落点）：该期望值必须在代码中可定位，不得臆造。若实现与文档冲突，**以实现为准**并登记偏差（见 §11）。

---

## 1. S1 前台工具调用

> 覆盖：用户消息 → 工具选择 → 执行 → 结果归一 → 结果进回复素材。

### S1.1 ~ S1.10 十个声明工具各一例

- **Scenario Name**：`S1.<n> <tool_id> 前台调用可达能力实现`
- **Preconditions**：`V24_TOOL_SYSTEM_ENABLED=true`；`channel.feishu.send` 另需 `V24_TOOL_CHANNEL_ENABLED=true` + `FEISHU_ENABLED=true` + 三项飞书凭据；能力侧为打桩实现。
- **Input**：`ToolInvocation(tool_id=<声明 id>, params={"content": "在吗", ...})`，`source=conversation`。
- **Execution Flow**：`ToolExecutor.run` ①resolve（注册表命中且 `effective_status=enabled`）→ ②permission（闸 off → 占位 allow）→ ③validate（闸 off → 跳过）→ ④invoke（`CapabilityExecutor.run` → 打桩能力）→ ⑤normalize。
- **Expected Result**：`ToolExecution.tool_id == 声明 id`；`capability/action` 与声明一致；`status="succeeded"`；能力收到 `params`；`result["status"]="succeeded"`；`duration_ms` 非空。声明全集恰为 10 条（`builtin.*` 5 + `world.*` 4 + `channel.*` 1）。
- **Related Modules**：`app/services/tool/executor.py`、`app/services/tool/builtin.py`、`app/services/tool/registry.py`
- **Code Basis**：`ToolExecutor.run` 五段短路（executor.py §run）；`builtin.definitions()` 十条声明；`ToolRegistry.register` 七项校验。
- **自动化**：`test_s1_foreground_tool_call_reaches_capability[<tool_id>]`

### S1.11 工具结果的观察键进入结果契约

- **Scenario Name**：`S1.11 前台调用结果携带结构化观察`
- **Preconditions**：`V24_TOOL_SYSTEM_ENABLED=true` + `V24_TOOL_OBSERVATION_ENABLED=true`。
- **Input**：`builtin.reminder.create`，能力返回 `payload={"world_event_id": "ev-tool012"}`。
- **Execution Flow**：`ObservationNormalizer.normalize` 按 `TOOL_OBSERVATION_KEYS` 把 payload 键映射为观察键，并据 `world_event_id` 产出 `ToolEffect(kind="world")`。
- **Expected Result**：`result["observations"]["world.event_id"] == "ev-tool012"`；`result["effects"][0]["kind"] == "world"`。
- **Related Modules**：`app/services/tool/normalizer.py`、`app/character/asuna/tool.py`（`TOOL_OBSERVATION_KEYS`）
- **自动化**：`test_s1_foreground_tool_call_result_carries_observation`

---

## 2. S2 参数校验

> 覆盖：结构层 8 类 + 语义层 5 类，全部通过执行器端到端验证（非直接调校验器）。

### S2.1 ~ S2.8 结构失败八类

- **Scenario Name**：`S2.<n> <code> 在执行前拦下`
- **Preconditions**：`V24_TOOL_SYSTEM_ENABLED=true` + `V24_TOOL_SCHEMA_VALIDATION_ENABLED=true`。
- **Input**：各自构造的参数（见下表）。
- **Execution Flow**：①resolve → ②permission（allow）→ ③validate 失败 → 短路为 `invalid`（不进入 ④invoke）。
- **Expected Result**：`status="invalid"`；能力实现**零调用**；`validation.structural` 含该 code；该 issue 带非空 `param` 与 `message`。
- **Related Modules**：`app/services/tool/validator.py`
- **自动化**：`test_s2_structural_failure_blocks_execution[<code>]`

| n | code | 输入 |
|---|---|---|
| 1 | `missing_required` | `{}`（缺 `content`） |
| 2 | `type_mismatch` | `repeat="abc"`（声明 integer） |
| 3 | `enum_invalid` | `importance="urgent"` |
| 4 | `range_violated` | `repeat=99`（max 7） |
| 5 | `length_violated` | `note="超出上限的内容"`（max_length 5） |
| 6 | `pattern_mismatch` | `code="abc"`（`^[A-Z]{3}$`） |
| 7 | `format_invalid` | `email="not-an-email"` |
| 8 | `unknown_param` | `undeclared="x"`（strict 模式） |

### S2.9 ~ S2.13 语义失败五类

- **Scenario Name**：`S2.<n> <code> 在执行前拦下（语义层）`
- **Preconditions**：同 S2.1~S2.8；世界事实**已装配**（`ToolContext.world["world_enabled"]=True`）。
- **Input**：见下表；`ToolContext` 提供 `now` / `world["locations"]` / `inventory` / `authorized_recipients`。
- **Execution Flow**：结构层全过 → 语义层按 `input_schema.semantic_validators` 派发 → 失败 → `invalid`。
- **Expected Result**：`status="invalid"`；`validation.structural == []`；`validation.semantic` 含该 code；能力零调用。
- **Related Modules**：`app/services/tool/validator.py`（`BUILTIN_SEMANTIC_VALIDATORS`）
- **自动化**：`test_s2_semantic_failure_blocks_execution[<code>]`

| n | code | 输入 / 上下文 |
|---|---|---|
| 9 | `not_future` | `due_at=2020-01-01T00:00:00`（早于 `ctx.now`） |
| 10 | `location_not_found` | `location="火星基地"`，`world["locations"]=["home.living_room"]` |
| 11 | `object_not_in_inventory` | `object="水杯"`，`world_enabled=True` 且 `inventory=[]`（装配态空集是**事实**） |
| 12 | `recipient_not_authorized` | `recipient="陌生人"`，`authorized_recipients=["小林"]` |
| 13 | `content_over_budget` | `content` 长 4001 字（全局预算 4000） |
| — | `validator_unknown` | 声明未注册校验器名 → `semantic` 记 `validator_unknown`（fail-closed） |

---

## 3. S3 权限与确认

### S3.1 默认拒绝

- **Scenario Name**：`S3.1 无授权的外发工具停在确认流`
- **Preconditions**：总闸 + 权限闸 on；快照 `grants=[]`。
- **Input**：`builtin.notification.send`，`params={"content": "在吗"}`。
- **Execution Flow**：①resolve → ②permission 七步：⓪闸 on 且有快照 → ①等级 sensitive 不免授权 → ②无 grant → ③`confirm=first_time` 且无授权集 → `confirm_required`。
- **Expected Result**：`status="pending_confirmation"`；`permission.reason="first_time_confirmation"`；能力零调用。
- **Related Modules**：`app/services/tool/permission.py`
- **自动化**：`test_s3_default_deny_without_grant`

### S3.2 首次确认登记

- **Scenario Name**：`S3.2 首次确认登记待确认行`
- **Preconditions**：同 S3.1；`trigger_registry` 可写。
- **Input**：`ConfirmationService.request(invocation, decision, ctx)`。
- **Execution Flow**：`trigger_registry_repository.register(...)` 落 `trigger_type=action_due` 的待确认行，同时生成角色语气话术。
- **Expected Result**：返回值 `is_pending()` 为真；`prompt` 非空；`service.get(request_id)` 可取回；`service.pending(user)` 含该请求；**本轮零外发**。
- **Related Modules**：`app/services/tool/confirmation.py`、`app/repositories/trigger_registry_repository.py`
- **自动化**：`test_s3_first_time_confirmation_registers_pending_row`

### S3.3 TTL 内复用

- **Scenario Name**：`S3.3 授权在 TTL 内复用`
- **Preconditions**：同 S3.1；快照含 `scope=["self"]` 的有效 grant。
- **Input**：同一工具连续调用两次。
- **Execution Flow**：②`matching_grant` 命中且 `scope_covers` 成立 → `allow(grant_matched)`。
- **Expected Result**：两次均 `succeeded`；`permission.reason="grant_matched"`；能力被调用 2 次。
- **Related Modules**：`app/services/tool/permission.py`（`matching_grant` / `scope_covers`）
- **自动化**：`test_s3_grant_reuse_within_ttl`

### S3.4 过期不静默放行

- **Scenario Name**：`S3.4 过期授权回到确认流`
- **Preconditions**：同 S3.1；grant `expires_at` 早于快照 `now`。
- **Input**：`builtin.notification.send`。
- **Execution Flow**：`active_grants` 按 `now` 严格判定 → 过期即不匹配 → 回到 ③首次确认。
- **Expected Result**：`status="pending_confirmation"`；能力零调用（**不得**因"曾经授权过"而放行）。
- **Related Modules**：`app/services/tool/permission.py`（`active_grants`）
- **自动化**：`test_s3_expired_grant_returns_to_confirmation`

### S3.5 否定请求

- **Scenario Name**：`S3.5 用户否定后请求终态且不留授权`
- **Preconditions**：同 S3.2。
- **Input**：`service.resolve(request_id, approved=False)`。
- **Execution Flow**：请求行置终态（`cancelled`），不落 grant。
- **Expected Result**：`outcome.status == "denied"`；`service.get(request_id).is_pending()` 为假；`service.grant_records(user)` 为空。
- **Related Modules**：`app/services/tool/confirmation.py`
- **自动化**：`test_s3_denied_request_marks_cancelled_and_never_grants`

---

## 4. S4 自治调用

### S4.1 自治 tick 三账对齐

- **Scenario Name**：`S4.1 自治决策 → 工具执行 → 世界写入，三账对齐`
- **Preconditions**：`V2_LIFE_LOOP_ENABLED` + `V2_ACTION_OUTBOX_ENABLED` + `V21_AGENT_RUNTIME_ENABLED` + `ACTION_ENABLED` + `WORLD_ENABLED` + `AUTONOMY_ACTION_ENABLED` + `OBSERVABILITY_PERSIST_ENABLED`；`autonomy_action_enabled=true`；存在持久目标与已闲置会话；已登记到期 followup。
- **Input**：`life_loop.run_life_loop_tick(now=NOW)`。
- **Execution Flow**：维护步 → 触发评估 → 决策管线（工具面作为 `capabilities` 输入）→ `run_action_planning`（工具路径）→ `integrate_result` → outbox → `outbox_consumer.consume_pending` → `world_engine.create_event`。
- **Expected Result**：自治行动台账恰 1 条且 `status="succeeded"`，`steps[0].tool_id="builtin.reminder.create"`；`outbox_events` 出现同 `idempotency_key`；消费后 `world_events` 出现 `type=reminder` 且 `payload.outbox_action_id == record.id`；`loop_runs` 一行 `kind=autonomy/status=done`；`decision_records` 一行 `decision=act` 且其 `input_snapshot.tool_facts.available` 含所用工具；三账 `user_id` 一致。
- **Related Modules**：`app/application/life_loop.py`、`app/application/autonomy_engine.py`、`app/application/action_engine.py`、`app/application/outbox_consumer.py`
- **Code Basis**：TOOL-006 §6.2 三账对齐断言（`test_tool006_integration.py::test_autonomy_decision_to_world_write_through_outbox`）。
- **自动化**：`test_s4_autonomy_tick_three_ledgers_aligned`

---

## 5. S5 世界契约

### S5.1 世界写入只经 outbox

- **Scenario Name**：`S5.1 工具写世界先落 outbox，消费后才可见`
- **Preconditions**：`ACTION_ENABLED` + `WORLD_ENABLED` + `V2_LIFE_LOOP_ENABLED` + `V2_ACTION_OUTBOX_ENABLED`；总闸 on。
- **Input**：`action_engine.run_action_planning(user, create_reminder, params={content, due_at})`。
- **Execution Flow**：能力实现检测 `v2_action_outbox_enabled` → 返回 `deferred_world_op` → `_integrate_via_outbox` → `action_repository.save_record_with_outbox`；`outbox_consumer.consume_pending` 后才 `world_engine.create_event`。
- **Expected Result**：执行后 `world_events` 计数**不变**；`outbox_events` 含 `idempotency_key == record.id`；消费后计数 +1。
- **Related Modules**：`app/application/action_engine.py`（`_integrate_via_outbox`）、`app/application/outbox_consumer.py`、`app/services/action/capabilities/reminder.py`
- **自动化**：`test_s5_tool_writes_world_only_through_outbox`

### S5.2 直写被静态拦截

- **Scenario Name**：`S5.2 工具实现体直写世界被扫描拦下`
- **Preconditions**：无（静态）。
- **Input**：注入违规样本 `world_repository.create_event(...)`。
- **Execution Flow**：AST 扫描（import 面 + 写方法前缀面）。
- **Expected Result**：样本必被捕获（证明扫描非空转，E4）；生产工具树扫描结果为空。
- **Related Modules**：`tests/v24/test_tool_world_guard.py`
- **自动化**：`test_s5_direct_world_write_in_tool_body_is_statically_blocked`、`test_g_world_static_scan_zero_violations`

---

## 6. S6 记忆分层

### S6.1 读类工具零沉淀

- **Scenario Name**：`S6.1 只读工具结果不落记忆`
- **Preconditions**：总闸 + 记忆闸 on；`ACTION_MEMORY_POLICY_ENABLED=true`。
- **Input**：`world.env.query` 的行动记录（`side_effects=("read",)`）。
- **Execution Flow**：`classify` 硬纪律①（`side_effects ⊆ {read}`）优先于边界表配置。
- **Expected Result**：`deliver` 返回 `None`；`memories` 零新增；`reason="read_only_tool"`。
- **Related Modules**：`app/services/tool/memory_policy.py`、`app/services/action/memory_bridge.py`
- **自动化**：`test_s6_read_only_tool_deposits_nothing`

### S6.2 重要结果沉淀

- **Scenario Name**：`S6.2 重要结果经 R1~R8 后落库`
- **Preconditions**：同 S6.1；`MEMORY_IMPORTANCE_THRESHOLD=0.5`（边界表 `builtin.reminder.cancel` 声明 importance 0.5）。
- **Input**：`builtin.reminder.cancel` 成功记录，`params={"target": "开会"}`。
- **Execution Flow**：边界表命中（deposit True）→ 模板渲染 → `memory_policy.apply_policy` → `memory_repository.create_memory`。
- **Expected Result**：返回 `memory_id`；`memories` 恰 1 行，内容 `用户不想再被提醒：开会`，`type=important_event`、`source=user_derived`。
- **Related Modules**：`app/services/tool/memory_policy.py`、`app/character/asuna/tool.py`（`TOOL_MEMORY_TEMPLATES`）
- **自动化**：`test_s6_important_result_deposits_candidate`

### S6.3 政策拒收即丢弃

- **Scenario Name**：`S6.3 R1 拒收来源为 AI 推测的候选`
- **Preconditions**：同 S6.1。
- **Input**：`builtin.notification.send` 成功记录（边界表 `source=ai_inferred`）。
- **Execution Flow**：`_evaluate` 命中 R1（AI 推测不入库）→ `discarded`，不写库。
- **Expected Result**：`deliver` 返回 `None`；`memories` 零新增。
- **Related Modules**：`app/services/memory_policy.py`（R1）
- **自动化**：`test_s6_untrusted_source_rejected_by_policy`、`test_g_memory_rules_r1_r8_have_no_exemption`

### S6.4 幂等

- **Scenario Name**：`S6.4 已投递的行动不重复沉淀`
- **Preconditions**：同 S6.1。
- **Input**：行动记录的 `result.effects` 已含 `kind="memory"`。
- **Execution Flow**：`has_memory_effect` 为真 → 短路返回 `None`。
- **Expected Result**：`deliver` 返回 `None`；`memories` 零新增。
- **Related Modules**：`app/services/tool/memory_policy.py`（`has_memory_effect`）
- **自动化**：`test_s6_idempotent_redelivery_is_skipped`

---

## 7. S7 反思效能

### S7.1 阈值触发

- **Scenario Name**：`S7.1 同工具同失败类达阈值才进反思窗`
- **Preconditions**：`V2_REFLECTION_ENABLED=true` + `V24_TOOL_SYSTEM_ENABLED=true` + `V24_TOOL_REFLECTION_ENABLED=true`。
- **Input**：连续 `v2_reflection_event_threshold` 次 `observe_tool_evidence(user, tool_id, failure_kind="transient")`。
- **Execution Flow**：reinforce 计数 → 低于阈值返 False → 达阈值触发 `trigger_for_user(channel=tool)`。
- **Expected Result**：返回序列为 `[False] * (threshold-1) + [True]`；仅最后一次触发。
- **Related Modules**：`app/services/reflection/triggers.py`
- **自动化**：`test_s7_tool_failure_evidence_triggers_at_threshold`

### S7.2 反思不改工具状态

- **Scenario Name**：`S7.2 证据窗与工具健康度隔离`
- **Preconditions**：总闸 on。
- **Input**：一次工具失败证据投递。
- **Execution Flow**：证据计数只影响反思通道；不触碰 `ToolRegistry` 健康度与生命周期。
- **Expected Result**：注册表快照（健康度 / 状态 / 描述）逐字节不变；`builtin.notification.send` 仍为 `enabled`。
- **Related Modules**：`app/services/reflection/triggers.py`、`app/services/tool/registry.py`
- **Code Basis**：TOOL-009 §6「Insight 不自动改工具状态」（`registry_snapshot` 断言）。
- **自动化**：`test_s7_tool_insight_does_not_trip_tool_breaker`

---

## 8. S8 通道工具

### S8.1 发送需确认

- **Scenario Name**：`S8.1 通道发送先确认，适配器零调用`
- **Preconditions**：总闸 + 通道闸 + 权限闸 on；`FEISHU_ENABLED=true` + 飞书凭据；通道适配器为打桩。
- **Input**：`channel.feishu.send`，`params={content, recipient}`；快照 `grants=[]`。
- **Execution Flow**：resolve（`effective_status=enabled`，因通道闸开）→ permission ③首次确认 → 短路。
- **Expected Result**：`status="pending_confirmation"`；`permission.reason="first_time_confirmation"`；适配器 `messages` 为空。
- **Related Modules**：`app/services/tool/channel_tools.py`、`app/services/tool/permission.py`
- **自动化**：`test_s8_channel_send_requires_confirmation`

### S8.2 切分不变式

- **Scenario Name**：`S8.2 长文本切分后逐字节可还原`
- **Preconditions**：无（纯函数）。
- **Input**：1000 字文本，`max_chars=200`。
- **Execution Flow**：`split_text` 逐段切分。
- **Expected Result**：`"".join(parts) == text` 且每段长度 ≤ 200。
- **Related Modules**：`app/channels/feishu/outbound.py`
- **自动化**：`test_s8_split_text_invariant_holds`

### S8.3 错误映射完备

- **Scenario Name**：`S8.3 通道错误码 → 失败类型全覆盖`
- **Preconditions**：无（纯函数）。
- **Input**：`ChannelErrorKind` 全部取值。
- **Execution Flow**：`failure_kind_for` / `is_retryable` 查表。
- **Expected Result**：映射表键集 == `ChannelErrorKind` 值集；`auth → permanent`、`rate_limited → transient`；`transient` 可重试、`permanent` 不可重试。
- **Related Modules**：`app/services/tool/channel_tools.py`
- **自动化**：`test_s8_channel_error_maps_to_failure_kind`

---

## 9. S9 扩展性

### S9.1 新增内置工具四步

- **Scenario Name**：`S9.1 只加声明即可进管线`
- **Preconditions**：总闸 on；不复用新代码，仅新增一条 `ToolDefinition`。
- **Input**：新声明 `builtin.tool012.newtool`（绑定既有 `reminder/create`，priority 15）。
- **Execution Flow**：`registry.register` → 工具面投影 → 校验。
- **Expected Result**：注册成功；进入 `foreground_chat` 工具面；`ParamValidator` 通过；管线文件零改动（`executor/validator/surface/permission/normalizer/registry/health/context` 内零工具 id 字面量）。
- **Related Modules**：`app/services/tool/registry.py`、architecture §10.1
- **自动化**：`test_s9_new_builtin_declaration_enters_pipeline`、`test_g_extend_pipeline_modules_have_no_tool_id_literals`

### S9.2 外部 API 工具一个 YAML

- **Scenario Name**：`S9.2 单清单文件产出单工具`
- **Preconditions**：`V24_TOOL_EXTERNAL_API_ENABLED=true`；`V24_TOOL_EXT_ALLOWED_HOSTS` 含清单域名；凭据在环境变量中（测试为占位值）。
- **Input**：`weather.yaml` 一份。
- **Execution Flow**：`ToolManifestLoader.load` → 8 项 manifest 校验 → `parse_manifest` → `registry.register`。
- **Expected Result**：`report.loaded == ["ext.api.weather.current"]`；索引仅 1 个工具；注册表 `ext.api` 命名空间恰 1 条。
- **Related Modules**：`app/services/tool/ext_api.py`
- **自动化**：`test_s9_external_api_tool_costs_one_manifest`、`test_g_extend_external_api_costs_one_manifest`

### S9.3 DSL 负例

- **Scenario Name**：`S9.3 用户自定义工具拒绝任意代码 / 网络`
- **Preconditions**：无（纯函数）。
- **Input**：步骤含 `capability="subprocess"`；以及参数值含 `https://`。
- **Execution Flow**：`dsl.validate_steps` 白名单 + 红线 token 检查。
- **Expected Result**：两者均返回非空错误列表（拒绝）。
- **Related Modules**：`app/services/tool/dsl.py`
- **Code Basis**：`ALLOWED_ACTIONS` 白名单不含 `channel_feishu` / `external_api` / 进程类能力；`FORBIDDEN_VALUE_TOKENS` 含 `https://`。
- **自动化**：`test_s9_user_dsl_rejects_arbitrary_code`

---

## 10. S10 多 tick 韧性

### S10.1 工具失败归一

- **Scenario Name**：`S10.1 失败归一为 failure_kind 并计入健康度`
- **Preconditions**：总闸 + 观测闸 on。
- **Input**：能力返回 `status="failed", payload={"failure_kind": "transient"}`。
- **Execution Flow**：④invoke 返回失败 → ⑤normalize 保留 `failure_kind` → 健康度记一次失败。
- **Expected Result**：`status="failed"`；`result["failure_kind"] == "transient"`；`health.consecutive_failures == 1`。
- **Related Modules**：`app/services/tool/normalizer.py`、`app/services/tool/health.py`
- **自动化**：`test_s10_tool_failure_records_failure_kind`

### S10.2 熔断与半开

- **Scenario Name**：`S10.2 连续失败熔断，冷却后半开`
- **Preconditions**：总闸 on；`V24_TOOL_BREAKER_THRESHOLD=3`、`V24_TOOL_BREAKER_COOLDOWN_SECONDS=300`；时钟可注入。
- **Input**：连续 3 次失败 → 推进时钟越过冷却 → 再 1 次失败。
- **Execution Flow**：`ToolHealthTracker.record_outcome` 达阈值 → `mark_tripped`；`is_tripped` 在冷却后触发半开 → 下一次失败立即重熔。
- **Expected Result**：熔断期 `effective_status="disabled"`；半开后回到 `enabled`；再次失败立即回到 `disabled`。
- **Related Modules**：`app/services/tool/health.py`、`app/services/tool/registry.py`
- **自动化**：`test_s10_breaker_trips_and_half_opens`

### S10.3 长离线追赶

- **Scenario Name**：`S10.3 长离线后自治按 long_gap 折叠`
- **Preconditions**：`V2_LIFE_LOOP_ENABLED=true`。
- **Input**：`last_covered = today - 15d`（长离线）与 `today - 3d`（短间隔）。
- **Execution Flow**：`compute_catch_up_plan` 按 `catch_up_max_days` 判定折叠模式。
- **Expected Result**：长离线 `mode="long_gap"` 且 `days_behind=15`；短间隔 `mode="daily"` 且 `missing_days` 长度 2。
- **Related Modules**：`app/services/world/catch_up.py`
- **自动化**：`test_s10_long_offline_then_autonomy_catch_up`

---

## 11. 与文档的偏差登记

| # | 文档表述 | 实现事实 | 处理 |
|---|---|---|---|
| D1 | architecture §9.5-8「`user.*` 与 `ext.api.*` 默认 `dangerous`」 | `user.*` 下限 `dangerous`；`ext.api.*` 下限 `sensitive`（同 §9.2 表） | **以实现为准**：`ext.api.*` 的不受信性由「默认不沉淀 + observations 打 `ext.untrusted` + 域名白名单」承担；不变量断言按实现口径书写（`test_invariant_08_untrusted_namespaces_behaviour`）。§9.5-8 措辞待后续文档任务收敛 |
| D2 | architecture §5.1 / §7.9「本版本零迁移」 | TOOL-009 新增 `0046_tool_insight_types`（放宽 `insights.type` CHECK 值域） | **零迁移断言已破例一次**：破例点 0046，性质=值域放宽、非破坏性、可降级；需回写 §5.1 与 tasks.md（见 ACCEPTANCE-CHECKLIST §9 R-9.3） |
| D3 | TOOL-012 §1.2 交付物落在 `docs/version/v2.4.0/tool-system/` | 本次落至 `apps/backend/tests/v24/` | 用户级约束「不改文档」优先；偏移登记于本文件与 ACCEPTANCE-CHECKLIST 顶部 |

---

## 12. 执行记录

| 场景段 | 执行方式 | 结果 | 备注 |
|---|---|---|---|
| S1 | `pytest tests/v24/test_tool012_scenarios.py -k test_s1` | PASS（11 例） | 全离线 |
| S2 | `-k test_s2` | PASS（13 例） | 全离线 |
| S3 | `-k test_s3` | PASS（5 例） | 内存 SQLite |
| S4 | `-k test_s4` | PASS（1 例） | 三账对齐 |
| S5 | `-k test_s5` | PASS（2 例） | 静态 + 端到端 |
| S6 | `-k test_s6` | PASS（4 例） | 内存 SQLite |
| S7 | `-k test_s7` | PASS（2 例） | LLM 零调用 |
| S8 | `-k test_s8` | PASS（3 例） | 通道打桩 |
| S9 | `-k test_s9` | PASS（3 例） | 离线 |
| S10 | `-k test_s10` | PASS（3 例） | 时钟注入 |
| 合计 | | **PASS 47 例** | 详见验收报告 |
