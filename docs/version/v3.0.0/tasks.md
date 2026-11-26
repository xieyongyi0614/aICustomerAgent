# V3.0.0 Agent Runtime System Tasks

> **上游**：`docs/version/v3.0.0/architecture.md`（唯一架构依据；本注册表之外的任何能力均不得进入 Task Detail）
> **基线**：`docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线，描述已实现的真实系统）
> **状态**：Task Registry（任务定义，未实现、未排 Detail）
> **主干**：RT-001 ~ RT-020（依赖顺序即文档顺序）
> **说明**：本文档只做任务级拆分，不含代码、不含 DDL 与迁移脚本；各 Task 的 Task Detail 后续独立生成（`docs/version/v3.0.0/tasks/RT-XXX.md`），本注册表冻结 **ID / 名称 / 优先级 / 依赖 / 交付面**。
> **定位复述**：V3.0 = **Agent Runtime Core（运行时内核）**。把 V2.1.0 的「Run Controller（阶段调度器）」升级为**显式的认知闭环运行时**：`Observe → Reason → Plan → Act → Reflect → Update` 六段循环 + Session 生命周期 + 四个运行时组件（Context Manager / Agent Loop / State Manager / Event System）+ 统一接口契约 + Run / Trace / Execution History 三层持久化。**只显式化与契约化，不重造任何器官。**
> **任务命名**：`RT-001 ~ RT-020`（RT = Runtime）。任务按 **系统能力** 拆分，不按文件拆分。

---

## 0. 关键前提裁决（先读）

> 本版本全部任务建立在以下五条前提之上；任一 Task 的 Detail 与实现不得绕过。

### 0.1 裁决 1：收编既有 Runtime，不建第二套

V3.0 的落点是 `app/application/agent_runtime/`（既有：`controller.py` / `profiles.py` / `trigger_router.py` / `llm_gateway.py` / `models.py`）——把它**推广**为运行时内核，而不是新增引擎：

| 既有资产 | V3.0 处置 |
|---|---|
| `RunController`（`open_run` / `run_stage_async` / `close_run`） | 收编为 **Agent Loop** 的 Run 底座（生命周期语义、`loop_runs` 唯一写面不变） |
| `ProfileSpec`（`profiles.py` 唯一阶段序列声明处） | **Extend**：阶段映射到六段循环，新增可选段与预算档，禁止另开阶段序列 |
| `trigger_router`（四类触发源归一为 run_kind + trigger_type） | **Extend**：成为 Trigger → Session → Run 的统一挂接点 |
| `llm_gateway`（能力注册 / 四问裁决 / 两级记账） | **Preserve**：循环内一切 LLM 调用仍只经此门 |
| `agent_state_assembler`（规则投影，0 LLM） | 收编为 **State Manager** 的投影门面 |

**禁止**：新增 `agents/` / `runtime2/` / 第二套 Pipeline；嫁接 LangGraph / CrewAI 等第三方编排引擎（architecture §0.3 Non-Goal）。新增运行时子模块一律落在 `application/agent_runtime/` 包内（契约 / 会话 / 循环 / 事件 / 上下文 / 状态六个子面）。

### 0.2 裁决 2：Schema 只扩展一次，单迁移 `0052`

| 需求 | 处置 | 归属 | 理由 |
|---|---|---|---|
| Session 挂接 | `loop_runs` 扩列 `session_id`（可空，配索引） | RT-002 交付、RT-018/RT-019 消费 | architecture §7.3 唯一扩展之一 |
| 因果链关联 | `runtime_traces` 扩列 `correlation_id`（可空，配索引） | RT-005/RT-019 消费（列同批建） | architecture §7.3 唯一扩展之二 |
| 新表 | **零新建表**（不建 `sessions` / `runtime_states` / `agent_events` / 执行历史表） | — | 「Run/Trace/History 三层复用既有承载」+ Q1/Q3 裁决 |

- 迁移链：`0052_runtime_session_trace_links.py`（`down_revision = "0051"`，当前链尾 `0051`），单链、可空跑、可回滚。
- **两列合并为一次迁移**：迁移链头钉测散落在 `v24/v25/v26` 共 15 个测试文件（`MIGRATION_HEAD` / `test_migration_chain_head_is_still_00NN` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`），FEISHU-010 加 `0050` 时实测 **22 个用例由绿转红**（baseline §9 P1 技术债）。合并后把钉测升级成本压到一次。
- 一切新增状态先问「SoT 在哪、谁可写」；Context / Snapshot / RuntimeEvent **不落真相源**（architecture 附：边界不变量 1/2）。

### 0.3 裁决 3：architecture 遗留问题 Q1~Q5 逐项裁决

| # | 问题 | 本版本裁决 | 落点 |
|---|---|---|---|
| Q1 | `session_id` 扩列还是新表 `sessions` | **扩列起步**（`loop_runs.session_id` 可空 + 索引），不建会话表；会话独立表待多角色/多会话需求成熟再评估 | RT-002 |
| Q2 | Event System 订阅注册是代码还是配置 | **代码静态注册**（沿 `ToolRegistry` / Trigger Registry 模式），避免过度配置化 | RT-005 |
| Q3 | State Manager 版本号是投影还是独立版本表 | **投影聚合**（各域审计行 + `agent_state_snapshots`，零新表）；跨域事务写需求出现前不建版本表 | RT-003 |
| Q4 | `reflect()` 慢时钟段挂接方式 | **Profile 显式可选段 + 预算裁决**，与既有周期反思任务**幂等共存**（共享证据窗去重键） | RT-006 / RT-011 |
| Q5 | Inbound Gateway 的 Web 迁移顺序 | **Flag 内逐渠道切**：飞书先切、Web 后切、Discord 仅留注册点（不实现） | RT-013 |

### 0.4 裁决 4：设置项命名（无版本前缀）

- 新增设置全部落 **既有** `app/core/settings/agent_runtime.py`（扩展该领域模块，不新增第 22 个设置模块）；字段名按领域语义，env 名 = 字段名大写（无 alias 层），改名须同批同步部署侧 `.env`。
- `vXX_` 版本前缀体系已删除（2026-09-19 收官），**不得复用 `v30_` 旧范式**。本批开关是**灰度位 / 策略位 / 调试位**，不是版本门控。
- 首批字段（实现期以 Task Detail 冻结，数量上限 4 个「总闸」+ 若干数值策略）：

| 字段 | 语义 | 默认 | 归属 |
|---|---|---|---|
| `runtime_session_tracking_enabled` | 会话生命周期与 `loop_runs.session_id` 写入总闸 | `False` | RT-002 |
| `runtime_event_bus_enabled` | 进程内事件总线总闸 | `False` | RT-005 |
| `runtime_state_versioning_enabled` | 状态版本化视角与 Run 内时点强制总闸 | `False` | RT-003 |
| `runtime_autonomous_cycle_enabled` | 后台自治循环收编总闸 | `False` | RT-016 |
| `runtime_context_freeze_enabled` | Context 装配后 Run 内冻结 | `False` | RT-004 |
| `runtime_loop_optional_stages` | 可选段清单（csv，如 `plan,reflect`） | `""` | RT-006 |
| `runtime_inbound_gateway_channels` | 已纳管入站归一渠道（csv） | `""` | RT-013 |
| `runtime_reflect_in_loop_enabled` | 循环内 Reflect 慢时钟段 | `False` | RT-011 |
| `runtime_orphan_run_timeout_minutes` | 孤儿 Run 判定阈值 | `30` | RT-018 |
| `runtime_orphan_run_sweep_enabled` | 孤儿 Run 扫描（挂既有维护步） | `True` | RT-018 |

- **Flag 关闭时行为必须与 V2.6.1 逐字节一致**：这是每个 Task 的必测项（对齐 v2.1.0 §3 全局约束第 3 条的做法）。

### 0.5 裁决 5：Preserve 清单（零改动，git diff 可证）

Decision Pipeline / Goal Stack / Planning System（V2.5）/ Action Execution（V2.6）/ Tool System（V2.4）/ World（V8 + V2.3）/ Memory（V4 + Memory 2.0，7 类封顶与 R1~R8）/ Relationship（V8.5 数值数学）/ Reflection（V2.6.1 三闸）/ Development / Evaluation 全部 **Preserve**：Runtime 只做**调用、读取、路由、记账**。

- Runtime **不写**：`personality_state`（唯 Evolution 编译）、`memories`（唯候选摄取）、`relationship_state`（唯关系引擎）、`world_*`（唯 `deferred_world_op → outbox → world_engine`）、计划（唯 `goal_repository` 计划面）。
- **Runtime 不直接调工具**：工具意图由 Reason/Plan 产出，Act 段经 Action Execution → Tool Registry（architecture §9.3）。
- **ChannelAdapter 契约零改动**：新增渠道 = 实现 Adapter + 注册，不改 Runtime（architecture §8.2）。

---

## 1. V3.0.0 Task Overview

### 1.1 总览表

| ID | Task Name | 能力域 | Priority | Dependencies | Phase |
|---|---|---|---|---|---|
| RT-001 | Agent Runtime Interface Contract | Runtime Core | P0 | 无 | Phase 1 运行时地基 |
| RT-002 | Session Lifecycle & Session Context | Runtime Core | P0 | RT-001 | Phase 1 运行时地基 |
| RT-003 | Runtime State Manager | Runtime Core | P0 | RT-001 | Phase 1 运行时地基 |
| RT-004 | Runtime Context Manager | Runtime Core | P0 | RT-001, RT-003 | Phase 1 运行时地基 |
| RT-005 | Runtime Event System | Runtime Core | P0 | RT-001 | Phase 1 运行时地基 |
| RT-006 | Agent Loop Core | Runtime Core | P0 | RT-001 ~ RT-005 | Phase 2 认知循环内核 |
| RT-007 | Perception Layer（Observe 段） | Perception | P0 | RT-006, RT-004 | Phase 2 认知循环内核 |
| RT-008 | Reasoning Layer（Reason 段） | Reasoning | P0 | RT-006, RT-007, RT-003 | Phase 2 认知循环内核 |
| RT-009 | Planning Integration（Plan 段） | Planning Integration | P1 | RT-006, RT-008 | Phase 2 认知循环内核 |
| RT-010 | Action Coordination（Act 段） | Action Coordination | P0 | RT-006, RT-008 | Phase 2 认知循环内核 |
| RT-011 | Reflection Stage（Reflect 段） | Autonomous Loop | P1 | RT-006, RT-010 | Phase 2 认知循环内核 |
| RT-012 | Update / Feedback Stage（Update 段） | Runtime Core | P0 | RT-006, RT-010, RT-005 | Phase 2 认知循环内核 |
| RT-013 | Inbound Gateway（入站归一） | Runtime Core（通道归一） | P0 | RT-002, RT-006 | Phase 3 通道归一 |
| RT-014 | Outbound Gateway（出站归一） | Runtime Core（通道归一） | P1 | RT-002, RT-013 | Phase 3 通道归一 |
| RT-015 | Foreground Loop Cutover（前台循环收编） | Runtime Core | P0 | RT-006 ~ RT-014 | Phase 4 前后台统一与自治 |
| RT-016 | Autonomous Loop Scheduler（后台思考周期） | Autonomous Loop | P0 | RT-006 ~ RT-014, RT-015 | Phase 4 前后台统一与自治 |
| RT-017 | Autonomous Behavior Triggering（自主行为触发与投递） | Autonomous Loop | P1 | RT-016, RT-014 | Phase 4 前后台统一与自治 |
| RT-018 | Runtime Persistence & Recovery | Runtime Persistence | P0 | RT-002, RT-012 | Phase 5 持久化与可观测 |
| RT-019 | Runtime Observability（Trace / Debug / Replay） | Observability | P0 | RT-005, RT-012, RT-018 | Phase 5 持久化与可观测 |
| RT-020 | Testing & Validation | 全能力域（验收） | P0 | RT-001 ~ RT-019 | Phase 6 验收 |

**Priority 语义**：P0 = 版本发布阻断项（缺一不可上线）；P1 = 版本价值主体；P2 = 可延后至版本内末尾或下一版本。
**Priority ≠ 顺序**：RT-020 为 P0 但必须最后执行（验收性质决定）。
**Dependencies 记法**：只列**直接**前置；传递依赖不重复罗列（如 RT-015 已含 RT-006 ~ RT-014）。RT-017 依赖 RT-014 是**跨 Phase 直接前置**（投递出口必须先归一），非笔误。
**Priority 分布**：本文档无独立 P2 任务——architecture 中唯一的「可延后」面（Discord 适配器、前端可视消费）已作为 RT-013 / RT-019 的显式 Out of Scope 处理，不进入本版本任务。

### 1.2 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| **Phase 1 运行时地基** | RT-001 ~ RT-005 | 契约冻结；Session 一等生命周期；状态版本化与 Run 内时点一致；不可变上下文装配；进程内事件总线 |
| **Phase 2 认知循环内核** | RT-006 ~ RT-012 | 六段循环状态机可驱动；Observe/Reason/Plan/Act/Reflect/Update 六段全部接线且有独立降级语义 |
| **Phase 3 通道归一** | RT-013, RT-014 | 任意渠道入站归一为 `RuntimeInput`、出站统一经 `ChannelAdapter.send`；`ChannelAdapter` 契约零改动 |
| **Phase 4 前后台统一与自治** | RT-015 ~ RT-017 | 前台对话链收编进同一循环（零回归）；后台思考周期与自主行为触发显式化 |
| **Phase 5 持久化与可观测** | RT-018, RT-019 | 孤儿 Run 回收与恢复语义；Run/Trace/Execution History 三层可 Debug / 可 Replay / 可 Evaluation |
| **Phase 6 验收** | RT-020 | 全部 Gate 全绿；边界不变量 9 条复检；回归清单与验收报告就位 |

### 1.3 能力域覆盖矩阵（覆盖 architecture 的运行时职责）

| 运行时职责 | 承载任务 |
|---|---|
| perception（感知） | RT-007（Observe 段）/ RT-013（入站归一） |
| reasoning（推理） | RT-008（Reason 段） |
| decision making（决策） | RT-008（决策管线唯一入口）/ RT-017（自主行为触发裁决） |
| planning coordination（规划协调） | RT-009（Plan 段） |
| action execution orchestration（行动编排） | RT-010（Act 段）/ RT-014（投递出口） |
| state update（状态更新） | RT-003（状态门面）/ RT-012（Update 段回写路由） |
| autonomous behavior（自主行为） | RT-011（慢时钟反思）/ RT-016（后台思考周期）/ RT-017（触发与投递） |
| 生命周期与运行时骨架 | RT-001（契约）/ RT-002（Session）/ RT-006（循环）/ RT-005（事件总线） |
| 持久化与可观测 | RT-018（Run/Trace/History + 恢复）/ RT-019（Debug / Replay） |

---

## 2. Task Dependency Graph

### 2.1 依赖关系图

```text
Phase 1 运行时地基
─────────────────────────────────────────────────────────────────
RT-001 Agent Runtime Interface Contract
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  ▼
RT-002              RT-003             RT-005
Session Lifecycle   Runtime State      Runtime Event
& Session Context   Manager            System
                       │
                       ▼
                    RT-004 Runtime Context Manager
                       │
                       ▼
Phase 2 认知循环内核
─────────────────────────────────────────────────────────────────
RT-006 Agent Loop Core（契约 + 地基 + 四组件收口）
    │
    ├──────────────┬──────────────────────┐
    ▼              ▼                      ▼
RT-007          RT-008               （可选段裁决同批）
Perception      Reasoning                │
（Observe）     （Reason）               │
    │              │                     │
    ├──────────────┼───────────┐         │
    ▼              ▼           ▼         ▼
RT-009          RT-010      RT-011（慢时钟，依赖 006 + 010）
Planning        Action           │
Integration     Coordination     │
（Plan）        （Act）           │
                   │             │
                   └──────┬──────┘
                          ▼
                    RT-012 Update / Feedback（依赖 005 事件总线）

Phase 3 通道归一
─────────────────────────────────────────────────────────────────
RT-013 Inbound Gateway
    │
    ▼
RT-014 Outbound Gateway

Phase 4 前后台统一与自治
─────────────────────────────────────────────────────────────────
RT-015 Foreground Loop Cutover（扇入 006~014）
    │
    ▼
RT-016 Autonomous Loop Scheduler
    │
    ▼
RT-017 Autonomous Behavior Triggering（另依赖 RT-014 投递出口）

Phase 5 持久化与可观测
─────────────────────────────────────────────────────────────────
RT-018 Runtime Persistence & Recovery（依赖 002 + 012）
    │
    ▼
RT-019 Runtime Observability（依赖 005 + 012 + 018）

Phase 6 验收
─────────────────────────────────────────────────────────────────
RT-020 Testing & Validation
    ▲ 全量扇入：RT-001 ~ RT-019
```

### 2.2 关键路径

```text
RT-001 → RT-002 → RT-006 → RT-007 → RT-008 → RT-010 → RT-012
      → RT-013 → RT-014 → RT-015 → RT-016 → RT-017 → RT-020
```

（**13 个任务**，为本版本最长依赖链。）

并行支链长度对照：

| 支链 | 长度 |
|---|---|
| RT-001 → RT-003 → RT-004 → RT-006 | 4（在 RT-006 前并入主干） |
| RT-001 → RT-005 → RT-012 | 3 |
| RT-006 → RT-008 → RT-009 | 3（在 RT-015 前并入） |
| RT-006 → RT-010 → RT-011 | 3（在 RT-015 前并入） |
| RT-001 → RT-002 → RT-018 → RT-019 → RT-020 | 5 |

### 2.3 并行建议

| 组 | 可并行任务 | 前提 |
|---|---|---|
| A | RT-002 ‖ RT-003 ‖ RT-005 | RT-001 完成（会话 / 状态 / 事件三个面互不依赖） |
| B | RT-004 可与 RT-002 / RT-005 并行启动 | RT-003 完成（Run 内时点一致性由 State Manager 强制） |
| C | RT-007 ‖ RT-008 | RT-006 完成（Observation 契约先行后即可并行） |
| D | RT-009 ‖ RT-010 ‖ RT-011 | RT-008 完成（RT-011 另需 RT-010） |
| E | RT-013 ‖ RT-018 | RT-006 / RT-012 完成（通道归一与持久化恢复无交集） |
| F | RT-014 ‖ RT-016 | RT-013 / RT-015 完成（出站归一与后台调度互不阻塞） |

**关键风险点排序**（实现顺序上不可颠倒的三处）：

1. **RT-001 契约冻结必须先于一切**——契约字段一旦进入实现，后续 19 个任务全部承压；契约冻结表未评审不得开工 RT-006。
2. **RT-006 循环状态机必须先于六段接线**——六段各自的调用面与降级语义都由循环承载，先接线会造成段级错误语义反复返工。
3. **RT-015 前台收编必须晚于 RT-013 / RT-014**——前台链路是唯一在跑真实流量的路径，出入站未归一时收编会引入双路径并存与双写。

---

## 3. Detailed Task List

> 字段约定：**Task ID / Task Name / Priority / Goal / Scope（含 Out of Scope）/ Dependencies / Expected Output**。
> `Expected Output` = 交付物 + 可判定断言（Task Detail 阶段展开为正式 Acceptance Criteria 与测试用例清单）。
> 「交付面」给出落点以便实现，但**不得据此把 Task 再拆成按文件的任务**。

## RT-001 Agent Runtime Interface Contract

Priority: P0

Goal: 冻结 Runtime Core 对外**唯一契约面**（`AgentRuntime.run` + Input / Output / Event / Error 四类契约）与运行期配置基线，使 Channel、触发源与未来多角色能以统一契约接入，而不必感知内部阶段与域语义（architecture §5）。

Scope:

- **契约落点**：既有包 `application/agent_runtime/` 新增 `contracts.py`——`RuntimeInput` / `SessionContext` / `RunResult` / `RuntimeEvent` / `RuntimeError` 五类值对象 + `AgentRuntime` Protocol + `TriggerKind` / `RunStatus` / `ErrorKind` 枚举。
- **复用既有语义**：`models.py` 的 `RunContext` / `RunKind` / `TRIGGER_TYPES`（四类触发源：`channel_message` / `world_event` / `schedule` / `threshold`）语义零变化；`RunStatus` 复用既有三终态（`done` / `aborted` / `degraded`）；`ErrorKind` 对应六段（perception / decision / planning / execution / feedback / state / session）。
- **契约纪律**：值对象 `frozen` 不可变、零 IO、零 LLM、零 `repositories` 依赖；`RuntimeError.recoverable` 是**唯一降级裁决位**（`True` → 该段降级跳过、Run 记 degraded；`False` → Run 记 aborted）；一切错误落 Trace。
- **配置基线**：扩展 `core/settings/agent_runtime.py`（§0.4 字段清单），默认全 off，关闭时行为与 V2.6.1 逐字节一致。
- **Out of Scope**：不实现任何段逻辑（`run()` 内各段仅占位）；不新建目录树 / 不改 `profiles.py` 三 Profile；不引入 Pydantic 之外的序列化依赖；不做契约的运行时校验器（校验归各 Task）。

Dependencies: 无

Expected Output:

- `contracts.py`（五类契约 + Protocol + 枚举）与 `agent_runtime.py` 设置字段就位（env 名 = 字段名大写，无 alias）。
- **契约冻结表**（字段 → 语义 → 拥有者 → 是否可变）：随 Task Detail 冻结并评审，后续 Task 不得私改字段名/语义。
- 单元测试 `tests/v30/test_runtime_contracts.py`：值对象不可变、必填校验、序列化往返、`RunStatus` 值域、`ErrorKind` × `recoverable` 语义表。
- **契约面零依赖断言**：`contracts.py` 零 `repositories` / `services` / `chains` / `prompts` 依赖（静态断言）。
- Flag 全 off：既有 `application/agent_runtime/` 测试零修改通过。

---

## RT-002 Session Lifecycle & Session Context

Priority: P0

Goal: 把 Session 建立为 Run 的宿主**一等生命周期**（Start → Context Build → … → Close），完成「渠道身份 → session_id → Run」的挂接与 `loop_runs.session_id` 落库，解决 L1 / C2（architecture §2.2）。

Scope:

- **交付面**：`application/agent_runtime/session.py`（`open_session` / `resume_session` / `close_session` / `build_session_context`）+ `repositories/loop_run_repository.py` 扩参（`create_run(session_id=...)`）+ `core/db.py::LoopRunRow.session_id` + 迁移 `0052`（同批含 `RuntimeTraceRow.correlation_id`，见 §0.2）。
- **会话载体**：`SessionContext` = `session_id` + `character_id`（默认单角色，多角色仅预留）+ `channel` + `external_user_id` + `thread_id` + 触发源 + Run 挂接信息。
- **挂接规则**：`external_thread_id → session_id` 的映射在会话入口完成**一次**，Runtime 不感知渠道线程语义（architecture §8.2）；飞书既有派生 `session_id = f"feishu:{open_id}"` 与 Web 的请求级 `session_id` 都纳入同一契约，**派生结果不变**。
- **Session 与 Run 关系**：一个 Session 内可有多个 Run（前台 chat + 后台 tick 共用 `session_id`）；Run 关闭**不**关闭 Session；Session 关闭只做终态记账。
- **Out of Scope**：不建 `sessions` 表（Q1 裁决）；不做上下文内容装配（归 RT-004）；不改飞书 per-session FIFO 串行与并发闸门；不做会话级写锁。

Dependencies: RT-001

Expected Output:

- Session 生命周期模块 + `0052` 迁移（可空跑、可回滚）+ `MIGRATION_HEAD` 钉测同批升级。
- **多 Run 单会话断言**：同一 `session_id` 下前台 Run 与后台 Run 各自台账独立、`session_id` 一致。
- **向后兼容断言**：无渠道身份的既有调用（Web 无 user 头、测试直调）仍可开 Run；`session_id` 可空，空值不破坏 `loop_runs` 既有查询。
- **零新表断言**：库表清单仅新增两列（`SCHEMA_TABLE_COUNT` 不变、`SCHEMA_COLUMNS_DIGEST` 按预期变更并钉测）。
- 测试：`tests/v30/test_runtime_session.py`（生命周期状态机 + 挂接 + 派生兼容）。

---

## RT-003 Runtime State Manager

Priority: P0

Goal: 把 V2.1 Agent State Assembler 的「规则投影」升级为**带版本、带时点一致性**的状态门面，统一「读哪一版 / 当前到哪一版 / 两版差什么」，解决 S1 / S2 / S3（architecture §3.3）。

Scope:

- **交付面**：`application/agent_runtime/state.py`——`snapshot(character_id, now)` / `version(domain, character_id)` / `observe(domain, event)` / `reconcile(snapshot, writes)`；底层复用 `application/agent_state_assembler.py` 与 `agent_state_snapshots`（V2.1 既有表）。
- **版本模型（零新表，Q3 裁决）**：`StateVersion` = 各域审计行的**只读聚合**（`development_changes` / `relationship_events` / `decision_records` / `action_records` / `agent_state_snapshots`）；`snapshot_version` 沿用既有列；时点一致性对齐 `run_started_at`。
- **强制语义**：`runtime_state_versioning_enabled` 开启后，Run 内所有状态读对齐同一时点并冻结；关闭时退回既有「Run 开始时刻」约定（行为与 V2.6.1 一致）。
- **Out of Scope**：不新增真相源、不写业务值（写回只经 RT-012 的合法通道）；不做跨域分布式事务；不新增表/列；不改 State 域数值数学与情绪衰减。

Dependencies: RT-001

Expected Output:

- State Manager 门面 + 各域版本投影读取面（`StateVersion` 值对象）。
- **零写入断言**：`state.py` 对业务表零 `INSERT/UPDATE/DELETE`（静态 + 打桩断言）。
- **Run 内一致性断言**：同一 Run 内两次 `snapshot()` 返回相同 `snapshot_version` 且内容哈希一致；跨 Run 版本单调递增。
- **降级断言**：某域审计不可读时该域版本标记缺失，snapshot 仍返回最小可用快照，错误落 Trace。
- 测试：`tests/v30/test_runtime_state_manager.py`（纯规则、零 LLM、零网络）。

---

## RT-004 Runtime Context Manager

Priority: P0

Goal: 为一次认知循环装配**不可变运行时上下文**（用户 / 世界 / 角色 / 记忆四段），统一 V2.1 Context Architect 与 Agent State Assembler 门面，补上「上下文装配」的一等组件边界（architecture §3.1）。

Scope:

- **交付面**：`application/agent_runtime/context.py`——`assemble(session_context, observation) → RuntimeContext`，底层复用 `services/context_builder.build`（历史窗 / 摘要 / 记忆召回）、`application/world_engine.build_context`（世界切片，只读）、`services/memory2/retriever`（混合检索，只读）、State Manager（角色段）。
- **装配规则**：四段来源与 SoT 依 architecture §3.1 表；`runtime_context_freeze_enabled` 控制 Run 内冻结（默认 off = 逐段即时读，保持 V2.6.1 行为）；超预算裁剪沿用 `context_total_char_budget` 与固定优先级（身份 / 场景 / 情绪 / 关系段**不裁**）。
- **降级**：世界切片失败 → 空段；记忆检索失败 → 空段；任一失败不阻断装配（对齐 world 旁路纪律），错误落 Trace。
- **Out of Scope**：不实现检索/排序算法（用既有 retriever 与 memory_policy）；不做世界推演；不做 prompt 文本拼接（PromptBuilder 归 `prompts/`）；Context 不落表。

Dependencies: RT-001, RT-003

Expected Output:

- `RuntimeContext` 值对象（四段 + `snapshot_version` 标记 + 预算账户 + `correlation_id`）与装配门面。
- **冻结断言**：开关开启时同 Run 内 `assemble` 幂等（内容哈希一致，不受中途域写入影响）；关闭时与既有装配路径**逐字段等价**（对照测试）。
- **裁剪断言**：超 `context_total_char_budget` 时按固定优先级裁剪，且不可裁段逐字节完整。
- **降级断言**：四段分别打桩失败 → 装配仍返回可用 context、失败段为空、错误落 Trace。
- 测试：`tests/v30/test_runtime_context_manager.py`。

---

## RT-005 Runtime Event System

Priority: P0

Goal: 建立**进程内同步事件总线**，把「模块通信语义缺位」显式化（何时同步调用 / 何时发事件 / 何时落 Outbox），并承载 Run 生命周期通知与段级通知；不替换既有 Outbox 一致性模型（architecture §3.4 / §6）。

Scope:

- **交付面**：`application/agent_runtime/events.py`——`emit` / `subscribe` / `dispatch` + 事件常量（`RunOpened` / `StageCompleted` / `RunClosed` / `StateVersionBumped` / `ObservationRecorded` / `UserMessageReceived` / `ActionExecuted` / `ActionCompleted` / `MemoryUpdated` / `RelationshipUpdated`）；订阅**代码静态注册**（Q2 裁决，沿 `ToolRegistry` / Trigger Registry 模式）。
- **边界**：事件**不落业务表**，只落 Trace（`correlation_id` 关联因果链，列由 `0052` 建）；跨域可靠投递仍走 `outbox_events`，世界广播仍走 `world_events`（两者零改动）；`runtime_event_bus_enabled` 控制启用。
- **订阅示例（只读不改）**：State Manager ← `StateVersionBumped`；Context Manager ← `ObservationRecorded`；记忆摄取器 / 关系桥 / 决策面 ← `ActionCompleted`；Reflection ← `ActionCompleted` 聚集（证据窗）。
- **Out of Scope**：不引入消息队列 / Redis / Event Sourcing；不做事件持久化与回放引擎（回放取材归 RT-019）；不做异步队列化（同进程同步派发 + 单订阅者失败隔离）。

Dependencies: RT-001

Expected Output:

- 事件总线 + 订阅注册表 + 事件落 Trace 接线（复用 `services/trace_collector`）。
- **隔离断言**：单个订阅者抛异常不影响其他订阅者与主循环；订阅失败记错误但不使 Run aborted。
- **边界断言**：`events.py` 对 `outbox_events` / `world_events` 零写入（静态 + 打桩）；零新增事件表。
- **订阅链断言**：一次 `ActionCompleted` 触发既有记忆摄取、关系桥、决策面三条订阅路径各一次，且幂等键不变。
- 测试：`tests/v30/test_runtime_event_bus.py`。

---

## RT-006 Agent Loop Core

Priority: P0

Goal: 把「按 Profile 线性执行阶段」升级为**显式六段认知循环状态机**（Observe → Reason → Plan → Act → Reflect → Update），Profile 仍是段组成唯一声明处；前后台共用同一循环形状，只在 Decision / Execution 候选构成与预算档分叉（architecture §2.1 / §3.2）。

Scope:

- **交付面**：`application/agent_runtime/loop.py`——`AgentLoop`（`observe` / `reason` / `plan` / `act` / `reflect` / `update` / `run`）+ 段状态机 + 段级降级；`profiles.py` 扩展（`ProfileSpec` 增 `optional_stages` 与「段 → 循环环节」映射，既有三 Profile 的 `stages` 语义不变）。
- **执行语义**：段间中间值（`Observation` / `Intention` / `Plan` / `ActionResult` / `list[Insight]` / `Feedback`）一律为值对象，只落 Trace **不落业务表**；段失败按 `RuntimeError.recoverable` 裁决 degraded 跳过或 aborted；`critical` 语义沿用 V2.1（`reply_generation` 仍为前台关键段）。
- **可选段**：Plan / Reflect 由 Profile + `runtime_loop_optional_stages` + 预算共同裁决（Q4 裁决）；前台最小快路径 = Observe → Reason → Act。
- **收编既有**：`controller.py` 的 `run_stage_async` / `append_step` / `close_run` 语义收编进循环的段执行原语（`loop_runs` 唯一写面与 `steps` 记账口径不变）。
- **Out of Scope**：不实现任何段的业务语义（段本体归 RT-007 ~ RT-012）；不新增 Run Profile 之外的编排路径；不改 `RunContext` / `loop_runs` 模型语义。

Dependencies: RT-001 ~ RT-005

Expected Output:

- 循环状态机 + Profile 段映射 + 段级错误契约实现（`RuntimeError` 落 Trace 与 `loop_runs.steps`）。
- **唯一声明处断言**：段序列只能来自 `profiles.py`，循环内零硬编码段顺序（静态断言 + 用例）。
- **降级断言**：非关键段异常 → Run `degraded` 且循环继续；关键段（回复生成 / 会话不可恢复）异常 → Run `aborted`；四类终态与 V2.1 语义一致。
- **观测断言**：每段产出 `StageCompleted` 事件与 Trace 条目（含 `duration_ms`、输入输出摘要、降级原因）。
- **零回归断言**：Flag 全 off 时既有三 Profile 行为与 V2.6.1 逐字节一致（对照测试）。
- 测试：`tests/v30/test_agent_loop_core.py`。

---

## RT-007 Perception Layer（Observe 段）

Priority: P0

Goal: 把四类触发增量（用户消息 / 世界事件 / 状态阈值 / 调度）归一为 `Observation` 值对象，作为循环唯一输入面；只做**感知归一与只读投影**，不实现记忆 / 世界 / 关系 / 行动逻辑（architecture §2.1 Observe）。

Scope:

- **交付面**：`application/agent_runtime/stages/observe.py`——`observe(...) → Observation`，复用 `channels/base.InboundMessage`（通道无关入站）、`application/world_engine.collect_facts`（世界事实，只读）、`services/memory2/retriever`（高显著度记忆信号，只读）、State Manager 的关系 / 状态投影（只读）。
- **四类感知**：用户输入感知（消息文本、渠道身份、线程）；世界状态感知（时间 / 场景 / 地点 / 活跃事件）；记忆检索信号（最近记忆摘要与高显著度信号）；关系与状态感知（关系阶段 / 边界 / 情绪与能量投影）。
- **归一规则**：按 `correlation_id` / `dedupe_key` 去重；时间对齐 `run_started_at`；任一类失败降级为空事实集。
- **Out of Scope**：不直写 `memories` / `world_*` / `relationship_*` / `character_state`；不新建感知表；不调用 LLM；不做记忆打分算法与冲突消解。

Dependencies: RT-006, RT-004

Expected Output:

- Observe 段 + `Observation` 值对象（四类事实 + 来源 + 去重键 + 时点）。
- **零写入断言**：四类域表零 `INSERT/UPDATE`（静态 + 打桩）。
- **零 LLM 断言**：Observe 段不触碰 LLM Gateway / chains。
- **四来源一致断言**：四类触发源各产出同 schema 的 `Observation`（结构一致、来源标记不同）。
- **降级断言**：世界 / 记忆 / 关系任一读取失败 → 对应事实集为空，`Observation` 仍产出。
- 测试：`tests/v30/test_runtime_observe_stage.py`。

---

## RT-008 Reasoning Layer（Reason 段）

Priority: P0

Goal: 建立**角色驱动的推理段**：情境分析 → 决策管线（候选 → 评估 → 风险 → 选择）→ `Intention` 值对象，把「此刻做什么」的裁决收口到单一入口；决策数学零改动（architecture §2.1 Reason / §4）。

Scope:

- **交付面**：`application/agent_runtime/stages/reason.py`，复用 `services/decision_pipeline`（`collect_candidates` / `score_candidates` / `run_risk_gates` / `select` / `run_pipeline`）、`services/goal_stack`（只读）、`services/intention_policy`（意图确定性校验）、决策面投影（`autonomy_engine.collect_tool_facts` / `_collect_action_facts` / `_collect_plan_facts`，只读）。
- **角色驱动约束**：人格闸（`_persona_gate`）、关系闸、目标栈对齐、Persona 硬边界全部复用既有裁决；LLM 使用只在 LLM Gateway 四问下发生（`llm_gateway.acquire` 记账 + 可熔断降级规则路径）。
- **分叉点**：前台与后台仅在候选构成（前台「回复用户」优先）与预算档不同，循环形状同一套；前台目标栈只读（长期化写入只在后台）。
- **Out of Scope**：不改决策权重 / 风险闸 / 选择规则；不新增候选来源；不写 `decision_records`（落库仍经 `observability.on_decision`）；不实现 mode / scene / behavior 裁决本体（沿用既有服务）。

Dependencies: RT-006, RT-007, RT-003

Expected Output:

- Reason 段 + `Intention` 值对象（意图类型 / 目标引用 / 置信度 / 来源候选 / 是否 LLM 参与）。
- **零数学改动断言**：`decision_pipeline` 纯函数与阈值零差异（对照测试），`Diff` 为空。
- **单入口断言**：前后台决策均经 `decision_pipeline.run_pipeline`，仓库内无第二决策实现（静态断言）。
- **预算断言**：LLM 调用经 `llm_gateway.acquire` 记账，熔断时规则路径兜底且 Run 记 degraded。
- **分叉断言**：同一 `Observation` 下前后台候选集差异仅体现在「回复用户」候选与预算档。
- 测试：`tests/v30/test_runtime_reason_stage.py`（FakeLLM）。

---

## RT-009 Planning Integration（Plan 段）

Priority: P1

Goal: 把 Planning System（V2.5）接入循环 Plan 段：目标 / 意图 → Plan（Goal → Plan → Task）→ `PlanStep` 供 Act 段消费；规划仍**只编排不执行**（architecture §4.4）。

Scope:

- **交付面**：`application/agent_runtime/stages/plan.py`，复用 `services/planning/engine.py`（规划引擎）、`decompose`（拆解）、`scheduler`（只读消费）、`goal_contract` / `goal_observation`（目标契约）、`goal_repository` 计划单一写面；`Plan` 值对象在 Run 内传递。
- **可选段语义**：由 RT-006 的可选段裁决决定是否进入；未进入时 Act 段直接消费 `Intention`；进入但规划失败时该段 degraded、循环继续。
- **修订回流**：`PlanRevisionPolicy` / `revision_listener` 既有机制保留，Plan 段只读其结论并落 Trace。
- **Out of Scope**：不重写拆解 / 观察 / 修订算法；不新增计划表（落库仍只经 `goal_repository` 计划面）；不在前台做长期化计划写入（前台只读）。

Dependencies: RT-006, RT-008

Expected Output:

- Plan 段接线 + `Plan` / `PlanStep` 值对象（Run 内传递，不落新表）。
- **零改动断言**：`services/planning/*` 与 `GoalPlanRecord` 数学 / 状态机零差异。
- **单一写面断言**：计划落库仍只经 `goal_repository`（静态断言）。
- **可选段断言**：可选段关闭时循环不进入 Plan 段且 Act 段仍可执行；开启但预算不足时跳过并记 degraded。
- **事务边界断言**：规划失败不留半成品计划（无中途落库残留）。
- 测试：`tests/v30/test_runtime_plan_stage.py`。

---

## RT-010 Action Coordination（Act 段）

Priority: P0

Goal: 把 Action Execution（V2.6）接入循环 Act 段：`Intention` / `PlanStep` → Action → 执行 → `ActionResult` 回流，形成 Run 内**可观测的行动闭环**；Action 六态状态机、检定、Executor 不决策等语义零改动（architecture §4.5）。

Scope:

- **交付面**：`application/agent_runtime/stages/act.py`，复用 `application/action_engine.py::ActionEngine`（create_record → evaluate_gates → assemble_plan → execute_plan → integrate_result）、`services/action/manager.py`（生命周期唯一入口）、`services/action/executor.py`（`ActionExecutor` / `CapabilityExecutor`）、`ToolExecutor` 五段短路。
- **结果回流**：Act 段输出 `ActionResult`，进 Feedback（RT-012）与决策面（`action_facts` / `tool_facts`）；`loop_runs` 仍只写自身台账。
- **调度归属**：延迟 / 定时 / 重试仍归 `action_schedules` + 既有维护循环（`action_retry` / `action_schedule`），循环内**不做**重试决策。
- **Out of Scope**：不新建 Action 抽象与执行器（V2.6 已建）；不改六态状态机 / `GateReason` / `FailureKind`；不绕过 Tool 治理直调 `Capability.execute`；不实现具体外部能力。

Dependencies: RT-006, RT-008

Expected Output:

- Act 段接线 + 「每次执行必产 `ActionResult`」断言（成功 / 失败 / 超时 / 异常四类均非空）。
- **唯一入口断言**：行动创建与状态变更只经 `ActionManager` / `ActionEngine`，零直写 `action_records` 状态列（静态断言）。
- **不决策断言**：Act 段不调决策管线、不做重试（零 `next_retry_at` 写入）。
- **不阻塞断言**：行动失败 / 超时不影响前台回复链路；Run 记 degraded 而非 aborted。
- **治理不绕过断言**：工具路径经 `ToolExecutor.run` 五段短路，零直调能力。
- 测试：`tests/v30/test_runtime_act_stage.py`。

---

## RT-011 Reflection Stage（Reflect 段 / 慢时钟）

Priority: P1

Goal: 在循环内显式化 Reflect **慢时钟段**：收集证据窗 → 触发 Reflection → 归集 `Insight`；与既有周期反思任务**幂等共存**，慢时钟产物调制之后每一轮快时钟（architecture §2.1 / Q4）。

Scope:

- **交付面**：`application/agent_runtime/stages/reflect.py`，复用 `services/reflection/triggers.py`（触发）、`reflector.py`（结构化推理）、`evidence.py`（证据窗）、`lifecycle.py`（Insight 生命周期）；证据源含 `ActionCompleted` 事件窗与 `agent_metric_snapshots`。
- **幂等并存**：`runtime_reflect_in_loop_enabled` 控制启用；与 `life_loop_reflection_check_interval_minutes` 周期任务共享证据窗去重键，避免重复 Insight。
- **预算**：慢时钟 LLM 调用走 LLM Gateway 后台档；预算不足 → 跳过该段并记 degraded（不抛错）。
- **Out of Scope**：不改三闸（confidence 校准 / 复检）与 Insight 生命周期数学；不做「循环内嵌持续反思 + 目标导向反思」（V3.2 范围）；不改 Development 编译（唯 Evolution）。

Dependencies: RT-006, RT-010

Expected Output:

- Reflect 段 + Insight 归集接口；启用 / 关闭行为对照用例。
- **幂等断言**：同一证据窗内循环段与周期任务不产生重复 Insight（去重键命中即跳过）。
- **零改动断言**：`services/reflection/*` 数学与阈值零差异。
- **预算断言**：后台档预算耗尽 → 段跳过 + degraded，无 LLM 调用产生。
- 测试：`tests/v30/test_runtime_reflect_stage.py`。

---

## RT-012 Update / Feedback Stage（Update 段）

Priority: P0

Goal: 建立 Feedback / Update 段：把 Act 与 Reflect 的产物**路由回各域合法写通道**（记忆候选摄取 / 关系信号 / 状态 / 成长），前台只读、长期化写入只发生在后台异步（architecture §2.1 Update / §4.2~§4.6）。

Scope:

- **交付面**：`application/agent_runtime/stages/update.py`——`update(...) → Feedback`（回写事件流 + 目标域 + 是否后台）；复用 `services/memory2/ingest`（候选摄取，R1~R8 唯一裁决）、`services/action/relationship_bridge.py`、`services/action/memory_bridge.py`、`state_service`、`outbox`（跨域可靠投递）。
- **路由规则**：同 Run 内必需副作用直调各域服务；跨域延迟投递走 `outbox_events`（零改动）；世界写仍走 `deferred_world_op → outbox → world_engine` 唯一写面。
- **前台约束**：前台 Run 的 Update 段只做「交接后台任务」（复用 `application/post_process` 既有步骤，独立容错），不阻塞回复。
- **Out of Scope**：不直写 `memories` / `relationship_state` / `personality_state` / `world_*` / 计划；不做 Development 编译；不改 post_process 步骤内部实现。

Dependencies: RT-006, RT-010, RT-005

Expected Output:

- Update 段 + `Feedback` 值对象（回写事件流、目标域、后台标记）。
- **单一写面断言**：四类域写全部经既有合法通道（静态 + 打桩，零直写）。
- **前台不阻塞断言**：前台 Run 的 Update 段耗时不含后台任务执行时间（交接即返回）。
- **Outbox 零改动断言**：`outbox_events` 结构与消费路径（`outbox_consumer`）零差异。
- **错误隔离断言**：后台步骤失败不影响已产出回复与 Run 终态（对齐 post_process 独立容错纪律）。
- 测试：`tests/v30/test_runtime_update_stage.py`。

---

## RT-013 Inbound Gateway（入站归一）

Priority: P0

Goal: 建立**统一入站网关**：Web / 飞书（未来 Discord）入站一律归一为 `RuntimeInput` 并挂接 Session，消除 C1 / C2；`ChannelAdapter` 契约零改动（architecture §8）。

Scope:

- **交付面**：`application/agent_runtime/inbound.py`（`normalize(inbound) → RuntimeInput` + `resolve_session(channel, external_user_id, thread_id) → SessionContext`）；`channels/` 侧仅薄适配（Feishu 既有 `events` / `identity` 复用）。
- **逐渠道切换**：`runtime_inbound_gateway_channels`（csv）控制已纳管渠道；飞书先切、Web 后切（Q5）；未纳管渠道走既有路径，行为逐字节一致。
- **边界纪律**：Web 仍走 `api/v1/chat.py`（HTTP + SSE 语义），飞书仍走 webhook 验签 / 去重 / 立即 200 + 后台 task（`feishu/inbox.py`、`feishu_dedupe_ledger` 保留）；Gateway 只做归一，不做鉴权 / 去重 / 串行。
- **Out of Scope**：不改 `channels/base.py` 契约与 `api/v1/schemas.py`；不实现 Discord 适配器（仅留注册点）；不改流式响应结构；核心层禁止 import `app.channels.feishu`。

Dependencies: RT-002, RT-006

Expected Output:

- Inbound Gateway + 四类触发源统一入口（`RuntimeInput` 归一）。
- **契约零改动断言**：`channels/base.py` 与 `ChannelAdapter.send` 签名零差异；核心层不 import 具体渠道实现（静态断言）。
- **等价断言**：飞书渠道纳管前后，同一条消息产生的 `session_id` / `user_id` / 回复内容逐字节一致（对照用例）。
- **渠道无关断言**：Web 与飞书入站产出同 schema 的 `RuntimeInput`（仅 `source` / `channel_identity` 不同）。
- 测试：`tests/v30/test_runtime_inbound_gateway.py` + 飞书链路回归（`tests/e2e`）。

---

## RT-014 Outbound Gateway（出站归一）

Priority: P1

Goal: 建立**统一出站网关**：回复投递与主动投递都收敛到 `OutboundMessage → ChannelAdapter.send` 唯一出口，消除 C3 半直连，支撑自主行为与多渠道（architecture §8.1）。

Scope:

- **交付面**：`application/agent_runtime/outbound.py`（`deliver(OutboundMessage) → SendResult` + channel → adapter 解析 + 幂等键策略），复用既有 Feishu `delivery` / `outbound` / `channel_identity_service.resolve_recipient`。
- **幂等与失败语义**：`idempotency_key` 由调用方提供（回复 = `(reply_ref, index)`；主动 = `(channel, external_id, idempotency_key, index)`）；返回 `SendResult` 而非抛异常；投递失败**不冒泡**、不阻断 Run。
- **Out of Scope**：不做文案生成与消息模板（归各域与 `prompts/`）；不新增渠道实现；不改 `feishu_deliveries` 幂等台账语义；不做流式分片。

Dependencies: RT-002, RT-013

Expected Output:

- Outbound Gateway + 适配器解析（channel → adapter）+ 幂等键契约。
- **半直连消除断言**：回复投递与主动投递均经 Gateway，零旁路 `adapter.send`（静态断言）。
- **失败语义断言**：投递失败返回 `SendResult(ok=False, error=...)`，不抛异常、不影响 Run 终态。
- **幂等断言**：同 `idempotency_key` 重复投递不产生重复外部消息（沿用 `feishu_deliveries`）。
- 测试：`tests/v30/test_runtime_outbound_gateway.py`。

---

## RT-015 Foreground Loop Cutover（前台循环收编）

Priority: P0

Goal: 把前台对话链（`chat_pipeline` 现行阶段序列）收编为 **foreground 循环的段实现**，使前后台共用同一认知循环（「不得再出现平行编排路径」），并处置 `agent_service` 兼容壳（architecture 附：边界不变量 8 / baseline §9 P2 技术债）。

Scope:

- **交付面**：`application/chat_pipeline.py` 收敛为「段调用薄壳」+ `application/agent_runtime/profiles.py` 的 `foreground_chat` Profile 映射到六段（Observe → Reason〔含 mode / scene / behavior 裁决〕→ Act〔行动意图检测〕→ Update〔落库 + 交接后台〕；`reply_generation` 仍在关键段）。
- **流式契约冻结**：`turn_meta` 键集与顺序、token 流、`done` 字段、错误 → HTTP 映射**零变化**（前端与飞书解析不动）。
- **兼容壳处置**：`services/agent_service.py` 双入口收敛——调用方直连 `chat_pipeline` / Run 入口，壳的退役需显式登记（不得静默保留双入口）。
- **零回归**：22 步内部业务实现逐字节保留，仅「调用方与顺序声明」收编。
- **Out of Scope**：不改提示词与 PromptBuilder；不改前端控制台；不改既有步骤内部实现；不改错误文案。

Dependencies: RT-006 ~ RT-014

Expected Output:

- 前台循环收编完成 + **唯一路径断言**（前后台共用同一循环实现，零平行编排，静态断言）。
- **零回归断言**：`tests/e2e/test_chat_http_integration.py`、`tests/e2e/test_turn_meta_stream.py`、golden prompt 快照全绿。
- **流式契约断言**：`turn_meta` 键集 / 顺序、`done` 字段、错误映射与 V2.6.1 逐字段一致。
- **入口收敛断言**：`agent_service.stream_chat` 调用点清单与去向登记完成，无未登记双入口。
- 测试：`tests/v30/test_runtime_foreground_cutover.py`。

---

## RT-016 Autonomous Loop Scheduler（后台思考周期 / 定时认知）

Priority: P0

Goal: 把 `life_loop` 的工作发现 + `run_autonomous_cycle` 收编为 **autonomous 循环调度（Background Thinking Cycle）**：保留快慢分离、预算三道闸、维护步与节流语义（architecture §2.2 / baseline §4.2）。

Scope:

- **交付面**：`application/life_loop.py`（tick / worker 收编为调度器）+ `controller.run_autonomous_cycle` 迁移为 `loop.py` 驱动的 autonomous Profile；维护步（`world_maintenance` / `world_simulation` / `action_retry` / `action_schedule` / `outbox_consume` / `trigger_reconcile`）**零改动**保留。
- **触发与节流**：四类触发源（schedule / threshold / world_event / channel_message）统一经 Trigger Router 与 `runtime_autonomous_cycle_enabled`；tick 节拍、storm 限流、cooldown、idle 判定语义零改动。
- **预算**：`life_loop_cycle_llm_budget` / `life_loop_daily_llm_call_budget` / `life_loop_daily_llm_token_budget` + LLM Gateway 三道闸保持；超预算跳过决策段并记 degraded。
- **Out of Scope**：不改自治决策数学（`autonomy_policy` / `trigger_evaluator`）；不新增自治行为类型；不做「世界自治时钟产事件」（V2.3 已实现，Non-Goal）；不新增常驻循环。

Dependencies: RT-006 ~ RT-014, RT-015

Expected Output:

- 后台思考周期调度器 + autonomous Profile 段映射（`perception → state_update → … → world_experience` 语义等价迁移）。
- **零改动断言**：维护步清单 / 间隔语义、cooldown / idle / storm 判定零差异（对照测试）。
- **预算断言**：三道闸逐级生效；超预算 Run 记 degraded 且零 LLM 调用。
- **空转断言**：无 due 工作时 0 LLM（工作发现阶段零消耗）。
- 测试：`tests/v30/test_runtime_autonomous_loop.py`。

---

## RT-017 Autonomous Behavior Triggering（自主行为触发与投递协调）

Priority: P1

Goal: 让自主行为（主动消息 / 主动动作）成为循环的**显式触发结果**：trigger → Run → Reason → Act → 出站投递协调，全链可观测、可追溯（architecture §2.2 Feedback / §6.2）。

Scope:

- **交付面**：`application/agent_runtime/trigger_router.py` 扩展（四类触发源 + 自主行为触发标识）+ 触发结果到 Outbound Gateway 的投递协调（复用 `proactive_actions` / `proactive_delivery` / `action_schedules`）。
- **触发条件**：沿用既有 trigger 评估、`life_loop_storm_daily_limit`、免打扰窗口与 `_should_skip_user_facing` 语义；本任务只把「触发 → Run → 投递」串成显式路径并落 Trace。
- **观测**：`ProactiveTriggered` / `ProactiveDelivered` 事件落 Trace（挂 `run_id` / `correlation_id`）；决策与投递仍入 `decision_records` / `runtime_traces`（既有表，零新增）。
- **Out of Scope**：不改触发评估数学与去重键生成；不做多角色 / 多用户广播；不新增通知渠道；不做消息文案排版（归各域）。

Dependencies: RT-016, RT-014

Expected Output:

- 触发链路显式化（trigger → Run → decision → action → delivery）+ 投递协调 + Trace 落点。
- **免打扰断言**：静默窗口内不产生投递（既有判定零差异）。
- **幂等断言**：同 `dedupe_key` 重复触发不重复投递（沿用 `proactive_actions.dedupe_key`）。
- **可追溯断言**：任取一次主动行为，可由 `run_id` 追溯 trigger → decision → action → delivery 全链。
- 测试：`tests/v30/test_runtime_autonomous_behavior.py`。

---

## RT-018 Runtime Persistence & Recovery

Priority: P0

Goal: 交付 Run / Trace / Execution History 三层持久化的**读取与恢复语义**：孤儿 Run 回收、中断恢复、执行历史投影查询面；不新增表（architecture §7）。

Scope:

- **交付面**：`application/agent_runtime/recovery.py`（孤儿 Run 扫描与终态收敛：`running` 超 `runtime_orphan_run_timeout_minutes` → `aborted` + 原因保留）+ 执行历史**只读投影**查询面（`loop_runs` / `runtime_traces` / `decision_records` / `action_records` / `development_changes` / `relationship_events` / `agent_state_snapshots`）。
- **恢复语义**：进程重启后**不重放**未完成 Run（不引入任务重放机制），只做终态收敛与台账一致性；「中断恢复」= 从 Session 视角续接下一次 Run，不恢复 Run 内中间态。
- **维护接线**：孤儿扫描挂入既有维护步 / worker（`runtime_orphan_run_sweep_enabled`），不新增常驻循环。
- **回放锚点**：`agent_state_snapshots`（V2.1 既有）作为时点对齐锚点，不新增快照表。
- **Out of Scope**：不做分布式锁 / 多实例 Run 抢占（飞书多实例已有 shard 路由）；不做状态快照回放执行（只读查询）；不新增表或列。

Dependencies: RT-002, RT-012

Expected Output:

- 孤儿 Run 回收 + 恢复语义 + 执行历史投影查询面（供 Debug / Replay / Evaluation 取材）。
- **恢复断言**：人为遗留 `running` Run → 扫描后收敛为 `aborted` 且 `steps` 保留最后一步；重复扫描幂等。
- **不重放断言**：重启后零自动重放（无未完成 Run 的重复执行，静态 + 集成断言）。
- **投影一致性断言**：给定 `run_id` 可关联 trace / decision / action / 状态变更，关联链完整。
- **零新表断言**：schema 无新增表（只消费 `0052` 两列）。
- 测试：`tests/v30/test_runtime_recovery.py`（集成，内存 SQLite）。

---

## RT-019 Runtime Observability（Trace / Debug / Replay）

Priority: P0

Goal: 让每次循环的每一段**可观测、可回放**：段级 Trace、决策日志、调试信息与 Replay / Evaluation 只读取材；消费 `runtime_traces.correlation_id`（architecture §7.2）。

Scope:

- **交付面**：`application/observability.py` 扩展（`StageCompleted` → trace steps；`correlation_id` 贯穿 Run / Session / Action / Plan）+ `services/trace_collector` 接线 + Trace 消费面（按 `run_id` / `session_id` / `correlation_id` 回溯）。
- **调试信息**：Run 级 debug 视图（各段输入输出摘要、`duration_ms`、token usage、降级原因、`ErrorKind` / `stage`）。
- **回放取材**：以 `agent_state_snapshots` 为时点锚点的**只读**回放查询（不执行副作用）；Evaluation 仍为只读旁路（V7.5 铁律）。
- **脱敏与保留**：沿用 `observability_prompt_capture_mode` / `observability_prompt_redact` / 各 retention 设置；新增字段不破坏既有清理策略。
- **Out of Scope**：不新增观测表；不改前端控制台；不新增 Evaluation 规则（V2.1 AGENT-006 已有）；不做 trace 可视化 UI。

Dependencies: RT-005, RT-012, RT-018

Expected Output:

- 段级 Trace + 决策日志 + 调试视图 + 只读回放查询面。
- **全链可观测断言**：任取一次前台 Run 与一次后台 Run，可用 `run_id` 还原六段顺序、耗时、降级与错误。
- **抽样与保留断言**：沿用既有采样率与 retention，新增字段不改变清理行为。
- **只读断言**：回放 / 调试查询零写入（静态 + 打桩）。
- 测试：`tests/v30/test_runtime_observability.py`。

---

## RT-020 Testing & Validation

Priority: P0

Goal: 对 V3.0 全量能力做 **Gate 化验收**：契约、循环、通道、持久化、可观测五面全绿；出具回归清单与验收报告；复检 architecture「边界不变量清单」9 条。

Scope:

- **验收面**：RT-001 ~ RT-019 全部 Expected Output 断言汇总执行；零回归（既有 unit / api / e2e / golden / integration 全绿）；预算与性能（段级耗时、Run 开销、0 LLM 段零调用）。
- **交付文档**：`docs/version/v3.0.0/acceptance-report.md` + `docs/version/v3.0.0/regression-checklist.md`（真实模型人工回归：前台对话 / 后台 tick / 主动行为 / 渠道切换 / 孤儿恢复 / 回放取材）。
- **边界复检**：architecture 附「边界不变量清单」9 条逐条断言；Preserve 清单（§0.5）零改动以 **git diff 可证**。
- **Out of Scope**：不新增功能；不修改任何 Preserve 模块；不做性能优化（仅记录基线）。

Dependencies: RT-001 ~ RT-019

Expected Output:

- 全量 Gate 结果 + 验收报告 + 回归清单（对齐 V2.6.0 / V2.5.0 验收文档体例）。
- **零回归断言**：`pytest -m "(unit or api) and not slow"`、`pytest -m integration`、`pytest -m e2e`、golden 快照全绿。
- **边界断言**：Preserve 模块 diff 为空；分层依赖方向零违规；核心层零 import `app.channels.feishu`。
- **迁移断言**：`MIGRATION_HEAD == "0052"`、`SCHEMA_TABLE_COUNT` 不变、列摘要钉测全绿、迁移可空跑回滚。
- **影子断言**：Flag 全 off 时全量回归与 V2.6.1 逐字节一致（影子路径可证）。

---

## 4. Implementation Order Recommendation

### 4.1 推荐批次（Batch）

| 批次 | 任务 | 并行度 | 批次出口（可判定） |
|---|---|---|---|
| **B0 契约冻结** | RT-001 | 串行（评审门禁） | 契约冻结表评审通过；Flag 字段与 env 名登记；`contracts.py` 单测全绿 |
| **B1 地基三面** | RT-002 ‖ RT-003 ‖ RT-005 | 3 并行 | `0052` 迁移落地且钉测升级完成；Session 可开可关；状态版本可读；事件总线可发可订 |
| **B2 上下文装配** | RT-004 | 串行（依赖 RT-003） | 四段装配 + 冻结/裁剪/降级用例全绿 |
| **B3 循环内核** | RT-006 | 串行（门禁：B1+B2 全绿） | 六段循环可驱动（段为占位）；三 Profile 影子路径零回归 |
| **B4 六段接线** | RT-007 ‖ RT-008 → RT-009 ‖ RT-010 ‖ RT-011 → RT-012 | 先并行后收口 | 六段各自「零写入 / 零决策 / 零改动」断言全绿；段级降级用例全绿 |
| **B5 通道归一** | RT-013 → RT-014 | 串行（飞书先切） | 飞书渠道纳管前后等价；出站零旁路 |
| **B6 前台收编** | RT-015 | 串行（门禁：B5 全绿） | 流式契约逐字段一致；e2e + golden 全绿；入口收敛登记完成 |
| **B7 自治收编** | RT-016 → RT-017 | 串行 | 后台 tick 零回归；主动行为全链可追溯 |
| **B8 持久化与观测** | RT-018 → RT-019 | 串行（可与 B7 并行） | 孤儿 Run 收敛幂等；`run_id` 全链可还原 |
| **B9 验收** | RT-020 | 串行（末端） | Gate 全绿；验收报告 + 回归清单归档 |

### 4.2 灰度与开关开启顺序（部署侧）

1. `runtime_session_tracking_enabled`（只加列与写值，读路径不变）
2. `runtime_state_versioning_enabled` → `runtime_context_freeze_enabled`（读路径增强）
3. `runtime_event_bus_enabled`（旁路通知，失败隔离）
4. `runtime_inbound_gateway_channels=feishu` → 观察 → `feishu,web`
5. 前台收编（RT-015）随第 4 步之后同批发布，**不单独灰度**
6. `runtime_autonomous_cycle_enabled`（后台收编，观察一个完整 tick 周期）
7. `runtime_loop_optional_stages=plan` → 观察 → 追加 `reflect` + `runtime_reflect_in_loop_enabled`
8. `runtime_orphan_run_sweep_enabled`（建议始终保持 `True`，仅阈值为可调项）

**回滚顺序**：与开启顺序严格逆序；开关关闭后必须回到 V2.6.1 行为（每个 Task 均已断言），故回滚不需要数据迁移回退——`0052` 两列可空，保留不回滚。

### 4.3 人力与节奏建议（按单 Agent 串行实现视角）

| 阶段 | 建议投入 | 说明 |
|---|---|---|
| B0 ~ B2 | 版本 35% 工时 | 地基不牢则后续全部返工；RT-003/RT-004 的「零写入 + 冻结」断言是质量分水岭 |
| B3 ~ B4 | 版本 30% 工时 | 六段接线中 RT-007/RT-008/RT-010 最重（感知归一 / 决策收口 / 行动闭环） |
| B5 ~ B6 | 版本 15% 工时 | 通道归一 + 前台收编；**唯一涉及真实流量的批次，必须配 e2e 与 golden 双回归** |
| B7 ~ B8 | 版本 15% 工时 | 自治与观测；可与 B5/B6 部分并行 |
| B9 | 版本 5% 工时 | 验收与文档 |

---

## 5. Risk Analysis

### 5.1 风险清单

| # | 风险 | 影响 | 概率 | 缓解措施 | 归属 |
|---|---|---|---|---|---|
| R1 | 迁移链头钉测机械升级成本（15 文件 / 约 22 用例）漏改 | 迁移落地后大面积用例转红，阻塞交付 | 高 | 单迁移 `0052` 合并两列；同批一次性升级 `MIGRATION_HEAD` / 列摘要钉测；作为 RT-002 验收硬项 | RT-002 |
| R2 | 前台收编引入行为回归（turn_meta / 流式 / 错误映射） | 真实用户可见故障（Web + 飞书双通道） | 中高 | 流式契约逐字段对照；e2e + golden 双回归；RT-015 前置 RT-013/014 完成；收编后先保持开关可退 | RT-015 |
| R3 | 双路径并存（新旧编排同时活） | 「第二套 Pipeline」违铁律，行为不可预测 | 中 | 唯一声明处断言（段序列只在 `profiles.py`）+ 入口收敛登记 + Flag 关闭即回旧路径 | RT-006 / RT-015 |
| R4 | Event System 过度抽象（演化成 Event Sourcing / MQ） | 引入不必要技术，违背 Non-Goal 与「不引入 MQ」纪律 | 中 | 进程内同步 + 事件不落业务表 + Outbox 零改动三重断言；订阅代码静态注册 | RT-005 |
| R5 | State Manager 变成第二真相源 | 跨域双写、状态漂移 | 中 | 零新表 / 零写入 / 只读聚合断言；Q3 投影裁决；写回只经 RT-012 合法通道 | RT-003 |
| R6 | Session 语义与既有 `user_id` 派生混用（飞书 `session_id = user_id`） | 会话隔离错位、串会话 | 中 | 兼容既有派生结果（不改值）；`external_thread_id → session_id` 映射只在入口做一次；隔离仍由 `user_id` 承载 | RT-002 / RT-013 |
| R7 | 循环收编后预算膨胀（tick 频率 × 段数上升） | LLM 成本与延迟上升 | 中 | LLM Gateway 四问 + 三道闸；快慢分离；0 LLM 段零调用断言；空转 0 消耗断言 | RT-006 / RT-016 |
| R8 | 降级语义漂移（degraded 与 aborted 混用） | 故障被吞或过度中断，排障困难 | 中 | `RuntimeError.recoverable` 单一裁决位；四类终态契约测试；一切错误落 Trace | RT-001 / RT-006 |
| R9 | 六段接线时越界写域（Runtime 直写记忆 / 世界 / 关系 / 人格） | 破坏 Preserve 清单与单一写面纪律 | 中 | 每段「零写入 / 零直写」静态 + 打桩断言；Preserve diff 为空作为验收 Gate | RT-007~012 |
| R10 | 循环内 Reflect 与周期反思重复产 Insight | 记忆/认知污染，评估误判 | 中低 | 共享证据窗去重键；幂等断言；默认开关 off | RT-011 |
| R11 | 孤儿 Run 扫描误杀长跑 Run | 正常 Run 被标记 aborted | 低 | 阈值可配（默认 30 分钟远大于现有 Run 时长）；仅收敛 `running` 且超时；`steps` 保留 | RT-018 |
| R12 | 新仓储 / 新服务未注册进 `tests/conftest.py` | 测试连真实 PG 挂起（已知坑） | 中 | 新增仓储 → `_REPO_MODULES`、模块级 `SessionLocal` 服务 → `_SERVICE_DB_MODULES`；列为每个 Task 的实现清单项 | 全部 |
| R13 | 预留面被过度实现（多角色 / 多用户 / Discord） | 版本发散、Non-Goal 失控 | 中低 | `character_id` 只贯穿不启用；Discord 仅注册点；多角色/多用户列入 Out of Scope | 全部 |
| R14 | `agent_service` 兼容壳长期残留 | 双入口符号残留，新人误入旧路径（baseline P2 债） | 中 | RT-015 显式登记入口收敛与壳的去向；不得静默保留 | RT-015 |

### 5.2 不可接受风险（触发即暂停实现并回到架构评审）

1. 任何 Task 需要修改 Preserve 清单（§0.5）中模块的语义或数学。
2. 任何 Task 需要第二套 Pipeline / 第二套 Agent / 外部编排框架。
3. 任何 Task 需要新增 MQ / Redis / Event Sourcing / 分布式锁。
4. 任何 Task 需要新建表承载执行语义（超出 `0052` 两列）。
5. 任何 Task 使 Channel 直接控制 Runtime（绕过 `RuntimeInput` / `SessionContext` 契约）。

---

## 6. Acceptance Criteria

### 6.1 版本级 Gate（缺一不可上线）

| Gate | 判据 | 验证方式 |
|---|---|---|
| **G1 契约冻结** | `AgentRuntime.run` + Input / Output / Event / Error 四类契约字段与语义冻结，后续零私改 | 契约冻结表评审记录 + `tests/v30/test_runtime_contracts.py` |
| **G2 单一循环** | 前后台共用同一六段循环；零平行编排路径；段序列只来自 `profiles.py` | 静态断言 + 依赖图 |
| **G3 边界不变量** | architecture 附「边界不变量清单」9 条逐条成立（Runtime 只调度 / 只读投影 / Outbox 唯一可靠投递 / ChannelAdapter 零改动 / Tool 治理零改动 / 无第二套 Agent） | 逐条用例 + 静态断言 |
| **G4 Preserve 零改动** | §0.5 清单模块语义与数学零差异 | git diff 为空 + 对照测试 |
| **G5 零新表** | 无新增表承载执行语义；仅 `loop_runs.session_id` + `runtime_traces.correlation_id` 两列 | `SCHEMA_TABLE_COUNT` 不变 + 列摘要钉测 |
| **G6 迁移可逆** | `0052` 可空跑、可回滚；`MIGRATION_HEAD == "0052"` | 迁移测试（需 `TEST_DATABASE_URL`） |
| **G7 零回归** | 既有 unit / api / integration / e2e / golden 全绿；Flag 全 off 时行为与 V2.6.1 逐字节一致 | Fast Test + integration + e2e + golden |
| **G8 降级语义** | 段级降级（degraded）与不可恢复中断（aborted）判定一致；行动失败 ≠ Run 失败 | 契约测试 + 打桩用例 |
| **G9 预算纪律** | 循环内一切 LLM 调用经 LLM Gateway 记账；0 LLM 段零调用；超预算降级不抛错 | 用例 + 记账断言 |
| **G10 全链可观测** | 任取前台 / 后台各一次 Run，可由 `run_id` 还原六段顺序、耗时、降级与错误 | `tests/v30/test_runtime_observability.py` |
| **G11 恢复语义** | 孤儿 Run 收敛幂等；进程重启零自动重放 | `tests/v30/test_runtime_recovery.py` |
| **G12 多渠道可扩展** | 新渠道 = 实现 `ChannelAdapter` + 注册，不改 Runtime；核心层零 import 具体渠道实现 | 静态断言 + 入站归一用例 |

### 6.2 每个 Task 的 Definition of Done（统一要求）

1. Expected Output 中的**全部断言**有可执行用例（不允许「口头保证」）。
2. Flag 关闭时行为与 V2.6.1 逐字节一致（影子路径可证）。
3. 分层依赖方向零违规；`api` 不依赖 `repositories` / langchain；核心层不 import 具体渠道实现。
4. 新增仓储 / 使用模块级 `SessionLocal` 的服务已注册进 `tests/conftest.py`（`_REPO_MODULES` / `_SERVICE_DB_MODULES`）。
5. 测试执行遵守 `docs/TESTING.md`：Focused → Module → 必要时 Fast；不默认跑全量。
6. 无临时文件残留（`git status` 干净）；提交信息符合 `feat:` / `fix:` / `refactor:` / `docs:` 约定（单行 ≤ 30 字）。
7. Task Detail 文档就位（`docs/version/v3.0.0/tasks/RT-XXX.md`），本次实现与 Detail 的偏差已回写。

### 6.3 版本级验收产物

| 产物 | 位置 | 说明 |
|---|---|---|
| 验收报告 | `docs/version/v3.0.0/acceptance-report.md` | Gate 结果 + 证据（用例名 / 命令 / 输出摘要） |
| 回归清单 | `docs/version/v3.0.0/regression-checklist.md` | 真实模型人工回归：前台对话 / 后台 tick / 主动行为 / 渠道切换 / 孤儿恢复 / 回放取材 |
| 架构基线更新 | `docs/current-system-architecture-baseline.md` | 按项目纪律：**架构演进先更新基线**，V3.0 落地后回写已实现形态 |
| 文档链接同步 | `AGENTS.md` / `apps/backend/AGENTS.md` | 版本入口指向 V3.0.0；迁移链尾由 `0051` 更新为 `0052` |

---

## 7. 附录

### 7.1 架构追溯矩阵（architecture 章节 → 任务）

| architecture 章节 | 承载任务 |
|---|---|
| §1 问题定义（C1~C3 / M1~M3 / S1~S3 / L1~L3） | C1~C2 → RT-013；C3 → RT-014；M1 → RT-015 / RT-016；M2 → RT-005；M3 → RT-006；S1~S3 → RT-003；L1~L3 → RT-002 / RT-018 |
| §2.1 认知闭环（六段） | RT-006（循环）+ RT-007 ~ RT-012（六段） |
| §2.2 运行时生命周期 | RT-002（Session）+ RT-006（Run） |
| §3.1 Context Manager | RT-004 |
| §3.2 Agent Loop | RT-006 |
| §3.3 State Manager | RT-003 |
| §3.4 Event System | RT-005 |
| §4 模块集成 / 边界裁决总表 | §0.5 Preserve 清单 + RT-007 ~ RT-012 的 Out of Scope |
| §5 接口设计（四类契约） | RT-001 |
| §6 事件驱动架构 | RT-005（订阅规则）+ RT-017（生命周期事件） |
| §7 持久化设计（三层 + 三种消费场景） | RT-018（Run/History/恢复）+ RT-019（Trace/Debug/Replay/Evaluation） |
| §8 多渠道兼容 | RT-013（Inbound）+ RT-014（Outbound） |
| §9 工具 / 函数调用兼容 | RT-010（Act 段经 Action Execution → Tool Registry） |
| §10 未来演进（V3.1 / V3.2 / V3.3） | 不在本版本；预留点由 RT-005 / RT-011 / RT-019 的订阅面与 Execution History 承载 |
| 附：边界不变量清单 9 条 | G3（RT-020 复检） |
| 附：遗留问题 Q1~Q5 | §0.3 已逐项裁决 |

### 7.2 命名与文档约定

- **任务编号**：`RT-001 ~ RT-020`，冻结后不重排；新增任务追加为 `RT-021+` 并登记依赖。
- **Task Detail**：`docs/version/v3.0.0/tasks/RT-XXX.md`，体例对齐 `docs/version/v2.6.0/tasks/TASK-XXX.md`（Priority / Goal / Description / Dependencies / Acceptance Criteria）。
- **本注册表的权威性**：Task 的 ID / 名称 / 优先级 / 直接依赖 / 交付面以本文档为准；Detail 只能细化，不得扩权到 Out of Scope 之外的模块。
- **架构变更**：任何超出 architecture 的变更须**先更新 `docs/version/v3.0.0/architecture.md` 与 `docs/current-system-architecture-baseline.md`**，再回到本文档改任务（对齐项目纪律：架构演进先改基线再进开发）。

### 7.3 本版不做的显式登记（Backlog）

| 项 | 归属版本 | 依据 |
|---|---|---|
| Episodic / Semantic 记忆双通道 | V3.1 | architecture §10.1 |
| 循环内嵌持续反思 + 目标导向反思 | V3.2 | architecture §10.2 |
| Self Improvement（评估 → 演化反馈闭环深化） | V3.3 | architecture §10.3 |
| 多角色并行（`character_id` 实例化多循环） | 未排期 | architecture §0.3 / §10.4 |
| Discord 适配器 | 未排期 | architecture §8.2（本版本仅留注册点） |
| Function Calling / MCP 对齐 | 未排期 | architecture §9.3 |
| 前端可视消费（循环回放 UI） | 未排期 | RT-019 Out of Scope |

> **文档结束**。本文档为 V3.0.0 的唯一任务注册表；实现顺序、依赖与验收以本文档 + architecture 为准。


