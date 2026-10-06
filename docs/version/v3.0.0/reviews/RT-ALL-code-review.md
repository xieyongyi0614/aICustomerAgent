# V3.0 Agent Runtime Code Review（RT-001 ~ RT-020）

> 评审日期：2026-09-22
> 评审范围：V3.0 当前实现（`apps/backend/app/application/agent_runtime/**` 及接线点）+ `docs/version/v3.0.0/tasks.md` + `docs/version/v3.0.0/tasks/RT-XXX.md` + `docs/current-system-architecture-baseline.md` + `AGENTS.md`
> 评审目标：Agent Runtime 是否以编排层方式正确引入，且不破坏架构边界
> 方法：静态代码审查 + 分层依赖扫描 + 与 architecture/tasks/acceptance 对照；**不修改任何代码**
> 实现基线：`feat/feishu_bot` @ `88009ef`（含 RT-001~RT-020 与 RT-020 验收材料）

---

# 1. Review Summary

**NEED FIX**

V3.0 在「包装既有域、不重造器官」这一主线上总体成立：Decision / Planning / Action / Reflection / Memory / World / Relationship 的业务数学未见第二套实现，Preserve 清单在验收报告中记录为 diff 为空。Runtime 以 `application/agent_runtime/` 收编 Run 生命周期，契约（contracts）、Session、Context / State / Event 四组件、六段映射、入出站网关、孤儿回收与观测查询面均已落地，`tests/v30` 约 357 例覆盖较全。

但相对 `architecture.md` 边界不变量 1/2/8/9 与本次评审维度（编排层纯净性、依赖方向、Runtime State 所有权、生命周期无孤儿、可回退灰度），存在 **2 项 Critical + 多项 High**，尚不足以无条件合并：

1. **Critical — 取消孤儿 Run**：`close_run` 未置于 `BaseException`/`CancelledError` 安全的 `finally`，流式取消留下 `running` 孤儿 Run。
2. **Critical — 前台收编无 kill switch**：`run_chat_pipeline` 始终经 `AgentLoop`，Web 与飞书全量暴露；相对自治路径 flag 灰度不对称，驱动壳无法一键回退。
3. **High**：**休眠的第二套认知循环**（`AgentLoop.observe/reason/plan/act/reflect/update` + `stages/*.py`）未接入生产 `run()`；RT-007~012 验收实际落在非生产路径。
4. **High**：`services → agent_runtime` 反向依赖（含 RT-019 新引入 `trace_query`）；stages 直读 domain repositories / 私有 service API。
5. **High**：`session_id` 被当作 `user_id` 注入上下文装配；`RuntimeContext`/`RuntimeState` 将记忆/世界/关系内容冻结进 `run.data`，且生产路径从不 `reset`。
6. **High**：`run_event_pregate` 嵌套双 Run 且忽略内层终态，外层恒记 `done`。
7. **High**：`runtime_orphan_run_sweep_enabled` 默认 True，在其余 Flag 全 off 时仍改写 `loop_runs`，与「Flag 关闭 = V2.6.1 逐字节一致」及回归清单 B-1 措辞冲突。

多数 Flag 默认 off 的灰度策略本身合理；G7 既存失败非 V3.0 引入，已在 acceptance-report 证明零回归。阻断合并的是前台无回退、生命周期正确性、边界回归与生产路径测试空洞。

---

# 2. Architecture Findings

## 2.1 Runtime 是否只做编排？

**结论：对域引擎是；对「认知循环编排」不是纯编排层。**

| 判据 | 结论 | 证据 |
|---|---|---|
| 是否重造 Memory/World/Relationship/Planning/Action/Reflection 业务逻辑 | **否** | 各段委托既有服务（`decision_pipeline.run_pipeline`、`PlanningEngine.plan`、`action_engine.run_action_planning`、`reflector.run_queued_reflections`、`memory2.ingest`、`world_engine.collect_facts`） |
| 是否替换既有系统 | **否** | `chat_pipeline` 仍拥有前台 22 步业务闭包；`life_loop` 仍拥有自治阶段本体；`action_engine` / `autonomy_engine` / `world_engine` 仍是唯一编排器 |
| Runtime 是否只调度/路由/装配/记账 | **部分偏离** | `stages/act.py` 做 Intention→ActionIntent 映射、参数完备性、ActionResult 合成；`state.reconcile` 持有快慢变量冲突策略；`update.routes_for` 持有写路径策略 |

## 2.2 是否存在重复 Agent Pipeline？

**是（实质问题）。**

```text
生产路径（唯一在跑）
  AgentLoop.run()
    └─ resolve_stages(profile) → STAGE_RUNNERS / chat_pipeline 注入 runners
         └─ life_loop._step_* / chat_pipeline 22 步闭包

休眠路径（未接入 run()）
  AgentLoop.observe/reason/plan/act/reflect/update
    └─ stages/{observe,reason,plan,act,reflect,update}.py
```

- `loop.py` 的 `run()` **从不调用**六段方法；测试 `test_all_stage_methods_are_delegated` 也写明「生产路径未变」。
- RT-015/RT-016 的「收编」只把既有阶段包进 `AgentLoop` 驱动壳，**没有把前台/后台收敛到六段实现**。
- 结果：认知循环编排实现两套——一套是 Profile 阶段序列，一套是六段方法。后者完整但未接线，构成不变量 9「无第二套 Pipeline」的代码级违例（即使当前只有一套在跑）。

**灰度双路径（可接受，但需登记）**：`controller.run_autonomous_cycle` 在 `runtime_autonomous_cycle_enabled` 下走 AgentLoop，否则走 `_legacy_run_autonomous_cycle`。这是显式灰度位，不是暗中双写；默认 off。

**记忆摄取双调用点（若六段路径启用则高危）**：

| 调用点 | 位置 |
|---|---|
| `post_process.run_memory_extract` → `ingest_from_action_record` | 生产后处理 |
| `stages/update._apply_memory` → `ingest_from_action_record` | 六段 Update |

关系域更安全：Update 只 acknowledge，不重复调用 `relationship_bridge`。

## 2.3 边界不变量对照

| # | 不变量 | 判定 | 说明 |
|---|---|---|---|
| 1 | Runtime 只调度；业务语义归各域 | **部分违例** | 域数学未改，但 stages 持有映射/合成/冲突策略 |
| 2 | Context/Snapshot/Event 只读投影、不落真相源 | **部分违例** | 不写业务表（好），但把域内容冻结进 `run.data` |
| 3 | 长期变化可经 Execution History 指认 | **通过** | RT-018/RT-019 投影与 `correlation_id` 就位 |
| 4 | LLM 四问只在 Gateway | **通过** | `llm_gateway.acquire` 为唯一闸；reason 不直接 acquire |
| 5 | 跨域可靠投递仍走 Outbox | **通过** | events 零 DB 写；outbox 路径零改动 |
| 6 | ChannelAdapter 契约零改动 | **通过** | `channels/base.py` Preserve |
| 7 | Tool 治理零改动 | **通过** | `services/tool/**` Preserve；Act 不直调 Capability |
| 8 | 前后台共用同一认知循环 | **违例** | 只共用驱动壳；段本体仍是 chat_pipeline vs life_loop 两套 |
| 9 | 无第二套 Agent/Pipeline | **违例** | 六段 `stages/*.py` 为第二套循环形状 |

## 2.4 与 architecture.md 的偏差

| # | 架构要求 | 实现现状 |
|---|---|---|
| 1 | 「不另开第二套 Pipeline」 | 六段方法 + stages 完整存在但未进 `run()` |
| 2 | 「前后台共用同一认知循环」 | 驱动共用，业务步未共用 |
| 3 | 「Reason/Plan/Act 只串循环、业务语义零改动」 | 各段重新编排域入口（decision/action/plan），非仅标注既有阶段 |
| 4 | architecture 状态仍写「仅设计，未实现」 | 代码已实现；文档状态滞后 |

---

# 3. Code Issues

> 按严重度排列。Location 为 `file:line`（相对 `apps/backend/`）。

## Critical

### C-1 `close_run` 不在 BaseException 安全的 finally 中 → 取消孤儿 Run

- **Severity**: Critical
- **Location**: `app/application/agent_runtime/loop.py:530-558`；`app/application/agent_runtime/controller.py:223-245`；接线 `app/application/chat_pipeline.py:863-868`
- **Problem**: `AgentLoop.run()` 与 `_legacy_run_autonomous_cycle` 把 `controller.close_run` 放在 `try/except/finally` **之后**。`except Exception` 不捕获 `CancelledError`。客户端断开导致流式任务取消时，`finally` 做清理后直接退出，**台账行保持 `status='running'`**，直到孤儿扫掠（默认 30 分钟）才收敛。同理任意 `BaseException` 也会留下孤儿。
- **Recommended Fix**: 将 `close_run`（及 `emit_run_closed`）移入 `try/finally`，并用 `except BaseException` 或独立 `finally` 保证关闭；取消时写 `aborted`（或专门 `cancelled` 语义映射到既有三终态）。`open_run` 到 `close_run` 全程配对，中间异常也必须关闭。

### C-2 前台收编无条件生效，无 kill switch

- **Severity**: Critical（回归面）
- **Location**: `app/application/chat_pipeline.py:347-869`（`open_foreground_run` :359 + `AgentLoop` :832-843）；对照 `controller.py:249-266`（自治有 flag）
- **Problem**: Web 与飞书皆经 `agent_service.stream_chat` → `run_chat_pipeline`。RT-015 将整链**无条件**包进 `AgentLoop`，不存在前台收编总闸。与自治「开关关走 legacy」不对称。中段失败时流式队列可能已吐出 `turn_meta`/token 再 `stage_error` 重抛，通道表现与旧「失败即整段 fallback」不完全一致；且 `stage_error` 在 Run 关账之后才冒泡到通道，Run 终态可与通道结局不一致。前台收编套件仅约 9 例，无 flags-off 全轮次字节级对照。
- **Recommended Fix**: 增加前台收编总闸（默认可 on，但必须可一键回退线性旧链）；补 flags-off 全轮次 golden/录制流对照、中段 LLM 失败、grounding 缓冲、post_process 失败等 e2e。

## High

### H-1 第二套认知循环（休眠 dual pipeline）

- **Severity**: High
- **Location**: `app/application/agent_runtime/loop.py:384-498`（六段方法）vs `loop.py:513-532`（`run()`）；`app/application/agent_runtime/stages/*.py`；`tests/v30/test_agent_loop_core.py:337-341`
- **Problem**: RT-007~RT-012 交付的段本体完整实现，但生产 `run()` 仍按 Profile 驱动既有阶段。违反不变量 8/9；后续维护者会误以为六段在生产生效，或同时改两套导致漂移。
- **Recommended Fix**: 二选一并在 architecture 登记裁决：**(A)** 把 `run()` 切到六段方法（真正的收编），删除/收缩 Profile 阶段包装；**(B)** 明确六段为「影子/测试实现」，从生产包导出面移除或标注 `experimental`，并在 baseline 写明「当前唯一循环 = Profile 阶段序列」。禁止长期并存两套完整实现。

### H-2 services → application.agent_runtime 反向依赖

- **Severity**: High
- **Location**:
  - `app/services/observability/trace_query.py:25`（`execution_history`）、`:106`（`loop.ERROR_KIND_BY_PHASE` / `STAGE_TO_PHASE`）— **V3.0 RT-019 新引入**
  - `app/services/decision_pipeline.py:380`（`llm_gateway`）— 既存
  - `app/services/planning/context.py:73`、`executor_bridge.py:63`（`agent_runtime.models`）— 既存
- **Problem**: 允许方向是 `application → services`。`services` 依赖 `application.agent_runtime` 构成反向依赖；其中 `trace_query` 还依赖 **loop 内部映射表**，把运行时内部结构泄漏到查询层。
- **Recommended Fix**:
  1. RT-019 的 `trace_query`：把 `execution_history` 投影与段序/错误类型映射下沉到 `services/observability/`（或独立 `application` 读门面由上层调用），`services` 不得 import `agent_runtime`。
  2. 既存 `decision_pipeline` → `llm_gateway`、`planning` → `models` 单独开技术债单：把 `RunContext`/触发常量/预算协议抽到无环的共享契约层（如 `core` 或 `channels.base` 风格的纯契约模块）。

### H-3 stages 绕过 service 层直读 domain repositories

- **Severity**: High
- **Location**:
  - `app/application/agent_runtime/stages/plan.py:28,123,189`（`goal_repository`）
  - `app/application/agent_runtime/stages/act.py:280-285`（`goal_repository`）
  - `app/application/agent_runtime/stages/update.py:39,160`（`action_repository`）
  - `app/application/agent_runtime/state.py:22-28,120-147`（多域审计仓）
  - `app/application/agent_runtime/execution_history.py:17-25`（多域历史仓）
  - `app/application/agent_runtime/controller.py:29,363`（`outbox_repository`）
- **Problem**: 评审维度明确禁止 runtime bypassing service layer。`goal_service.list_active_plans` 等门面已存在。`controller` 对 `loop_run_repository` 的写是合法的（Run SoT / 唯一写面），但 goal/action/outbox/decision/relationship 等 **domain 读** 应走 services。
- **Recommended Fix**: 域读统一经 services 只读门面；`state.py` 的版本投影改为调用各域 `*_service` / 专门的版本查询服务。`loop_run_repository` / orphan sweep 保持不变。

### H-4 `session_id` 被当作 `user_id` 注入

- **Severity**: High
- **Location**: `app/application/agent_runtime/context.py:108-186`；`app/application/agent_runtime/stages/observe.py:197,237`；`app/application/agent_runtime/stages/update.py:307`
- **Problem**: 装配时把 `session_context.session_id` 传入 `context_builder.build` / `state_manager.snapshot` / `world_engine.build_context` 的 `user_id` 参数。生产 chat 路径正确区分 `session_id` 与 `user_id`。当二者不等时（`agent_service.run_chat_pipeline(session_id, user_id)` 可分离），会读到错误主体的记忆/世界/角色状态。
- **Recommended Fix**: `SessionContext` 显式带 `user_id`（或复用 `external_user_id` 映射后的 internal id），禁止用 `session_id` 兜底充当 `user_id`；所有段统一 `user_id = run.user_id or session_context.user_id`。

### H-5 Runtime State / Context 持有域真相内容

- **Severity**: High（相对本次评审判据；architecture 将其设计为只读投影，属设计口径冲突）
- **Location**: `app/application/agent_runtime/context.py:38-56,73-85,242-265`；`app/application/agent_runtime/state.py:56-62,240-265`；`app/application/agent_runtime/models.py:34-46`
- **Problem**: `RuntimeContext` 内嵌记忆内容、世界 payload、关系与角色 `AgentStateSnapshot`；`RuntimeState` 同样持有完整快照；二者冻结进无类型的 `run.data`。评审判据要求 Runtime State 只含 execution context / lifecycle / correlation。虽然不落真相源表，但运行时对象持有域内容，且 `state.reset` / `context.reset` **生产路径从不调用**。
- **Recommended Fix**:
  1. 明确裁决：若投影可缓存，改为持有 **句柄/版本号 + 惰性读取**，不在 `run.data` 固化域 payload；或在 architecture 写明「Runtime 允许持有只读投影，但不拥有写权、Run 结束必须 reset」。
  2. `close_run` 路径调用 `state.reset` / `context.reset`。
  3. 为 `RunContext.data` 收敛键名契约，禁止各模块随意塞业务字段。

### H-6 `run_event_pregate` 嵌套双 Run 且忽略内层终态

- **Severity**: High
- **Location**: `app/application/agent_runtime/controller.py:356-387`
- **Problem**: 先 `open_run(event_driven)`，再 `run_autonomous_cycle` **内部再 open** 一次 `autonomous_tick`。一次工作两条台账；内层返回的 `aborted`/`degraded` 被丢弃，外层仍 `append_step(status=ok)` + `close_run(DONE)`。
- **Recommended Fix**: 只保留一层 Run（event 升级作为 trigger 而不是外层独立 Run），或外层不 open、只记 trigger；若保留外层，必须传播内层终态并在 `finally` 关闭。

### H-7 channels 导入 runtime 内部与 services（跳过 application）

- **Severity**: High
- **Location**: `app/channels/feishu/adapter.py:19-20,28-29`；`app/channels/feishu/delivery.py:27`
- **Problem**: 通道层应只做消息归一 + Adapter.send，不得 import Autonomy/Runtime 内部。当前 adapter 直接 import `agent_runtime.inbound/outbound` 以及 `agent_service` / `channel_identity_service`。与 AGENTS.md「通道层不得 import Autonomy；核心层仅可 import channels.base」的双向约束不一致（核心不得 import 具体渠道已满足；渠道 import 运行时未满足）。
- **Recommended Fix**: 入站归一调用点上移到 `api`/`application` 薄层，或提供 `application` 门面供 adapter 调用；`channel_identity_service` 若属通道无关身份映射，可视为 services 依赖但需在 AGENTS 显式豁免，否则经 application 中转。

## Medium

### M-1 stages 持有域映射 / 结果合成 / 冲突策略

- **Severity**: Medium
- **Location**: `stages/act.py:103-196,260-267`；`state.py:201-237`（reconcile）；`stages/reason.py:201-223`；`stages/plan.py:102-126`
- **Problem**: ActionIntent 映射、REQUIRED_PARAMS、ActionResult 合成、快慢变量冲突裁决属于域策略，放在 Runtime 段内超出「只调度」。
- **Recommended Fix**: 映射/合成下沉 `services/action/`；reconcile 策略下沉状态域服务；Runtime 段只调用。

### M-2 硬编码角色资产 `app.character.asuna`

- **Severity**: Medium
- **Location**: `stages/act.py:38`（`ACTION_TOOL_MAP`, `REQUIRED_PARAMS`）；`contracts.py:35` / `update.py:68`（`DEFAULT_CHARACTER_ID = "asuna"`）
- **Problem**: Runtime 段依赖具体人设包，阻碍多角色预留（architecture §10.4）。
- **Recommended Fix**: 经 `character_id` 解析能力映射（现有人设注册/装配门面），Runtime 零 `character.asuna` import。

### M-3 隐藏全局可变状态

- **Severity**: Medium
- **Location**: `state.py:43`（`_OBSERVED`，无锁、生产未接线）；`loop.py:193-203`（`STAGE_RUNNERS` 可变注册表）；`state.py:120-149`（`DOMAIN_SOURCES`）；`outbound.py:43`（`_adapters`）
- **Problem**: `_OBSERVED` 无锁且仅测试使用，却可无限增长；注册表并发注册无同步。事件总线 `_SUBSCRIBERS` 有锁，对比鲜明。
- **Recommended Fix**: 删除或正式接线 `_OBSERVED` 并加锁/TTL；注册表用不可变快照或加锁。

### M-4 `controller.run_stage_async` 失败步骤双写

- **Severity**: Medium
- **Location**: `app/application/agent_runtime/controller.py:104-109`
- **Problem**: 非 critical 失败时 except 分支 `append + mark_step` 后缺少 `return`，落盘两次相同 step。`AgentLoop._run_stage` 无此问题 →  legacy / loop 行为分叉。
- **Recommended Fix**: except 分支 `return entry`。

### M-5 `loop_runs` 台账 RMW 与孤儿扫掠竞态

- **Severity**: Medium
- **Location**: `app/repositories/loop_run_repository.py:96-129`；`app/application/agent_runtime/recovery.py:44-75`
- **Problem**: `mark_step` / `finish_run` 非原子读改写；`finish_run` 无 `WHERE status='running'`。扫掠与真实 close 可能互相覆盖。
- **Recommended Fix**: `finish_run` 条件更新（仅 running 可关）；steps 用 JSONB append 或乐观锁 version。

### M-6 私有 API 渗透

- **Severity**: Medium
- **Location**: `stages/reason.py:206`（`decision_pipeline._GATE_BUDGET`）；`stages/act.py:291`（`life_loop._execute_plan_step`）；`stages/reflect.py:94`（`triggers._day_bucket_key`）；`controller.py:320`（`life_loop_budget._STATUS_DEGRADED`）
- **Problem**: Runtime 依赖 service/application 私有名，重构易断。
- **Recommended Fix**: 各域导出只读公有门面（budget verdict、plan step executor、day bucket key）。

### M-7 LLM 成本按时间窗计入 Run

- **Severity**: Medium
- **Location**: `app/application/agent_runtime/controller.py:133-136`
- **Problem**: `llm_call_repository.count_calls_between(start, finish)` 是全局窗口计数，并发 Run 会互相重复记账。
- **Recommended Fix**: 按 `run_id` 归因（`llm_calls` 已有 run 维度则用之），窗口计数仅作调试。

### M-8 Update 段事件与 State Manager 叙事不一致

- **Severity**: Medium
- **Location**: `stages/update.py:62-66,258-278` vs `state.py:172-189`
- **Problem**: 发出 `MemoryUpdated` / `RelationshipUpdated` / `StateVersionBumped`，但从不调用 `state.observe()`（仅测试调用）。事件名暗示域版本推进，State Manager 未记录。
- **Recommended Fix**: Update 成功后 `state.observe(domain, event)`，或改事件语义为「已路由」而非「版本已推进」。

### M-9 `promote_degraded=False` 导致台账终态失真

- **Severity**: Medium
- **Location**: `app/application/agent_runtime/controller.py:307`；`loop.py:545-550`
- **Problem**: 自治循环禁用 degraded 提升后，段级错误可使台账 `done` 而 steps 含 error。
- **Recommended Fix**: 与 legacy 对齐：任一 error step → `degraded`（或文档化差异并加测试锁定）。

### M-10 decision 域版本号用 `len(search(limit=1000))`

- **Severity**: Medium
- **Location**: `app/application/agent_runtime/state.py:135`
- **Problem**: 用结果条数当单调版本，不是版本语义，且截断在 1000。
- **Recommended Fix**: 用 `decision_records` 自增 id / count 查询，或 domain 专用 version 字段。

## Low

### L-1 `SessionContext.started_at` / 多处 `datetime.now()` 无时区

- **Severity**: Low
- **Location**: `contracts.py:158`；`events.py:106` 等
- **Problem**: `RuntimeInput.received_at` 强制 tz-aware，但 `SessionContext.started_at` 默认 naive `datetime.now()`，契约内部不一致。
- **Recommended Fix**: 统一 `datetime.now(timezone.utc)` 或沿用逻辑时钟。
- **处理结论（2026-10-06，**已关闭**）**：全库时间口径统一为 aware UTC（`docs/refactor/datetime-normalization-plan.md` 收官批），`app/core/timeutil.py::now()` 为唯一取时口；`SessionContext.started_at` / `closed_at`（`session.py`）、`contracts.py` 的 `started_at` 默认值均为 aware UTC，契约内部已一致。静态护栏 `tests/unit/test_datetime_discipline.py` + `tests/unit/test_timeutil.py`；基线登记见 `docs/current-system-architecture-baseline.md` §6.4 / ADR-18。

### L-2 `STAGE_TO_PHASE` 将 `state_update`/`state_snapshot` 映射到 reason

- **Severity**: Low
- **Location**: `loop.py:81-102`
- **Problem**: 名称含 `state_update` 的阶段映射到 Reason 环节，与「Update = 回写」叙事易混淆（可能刻意对应「决策前状态准备」）。
- **Recommended Fix**: 在映射表旁注明语义，或拆名（`state_refresh` vs `update`）。

### L-3 architecture.md / AGENTS.md 状态滞后

- **Severity**: Low
- **Location**: `docs/current-system-architecture-baseline.md`（迁移链仍写 0050）；`AGENTS.md` 同；`architecture.md` 仍写「仅设计」；acceptance W-1/W-2 已登记
- **Problem**: 基线唯一真相源落后于实现（实际链尾 `0052`，Runtime 已落地）。
- **Recommended Fix**: 按 W-1/W-2 回写 baseline 与 AGENTS（迁移链尾、V3.0 能力面）。

### L-4 契约事件集追加

- **Severity**: Low
- **Location**: `contracts.py:47-55`（`EVENT_DECISION_MADE` 等为契约追加）
- **Problem**: 相对 RT-001 冻结集有追加；已用测试登记，属可接受「契约追加」流程。
- **Recommended Fix**: 在契约冻结表版本中显式 bump。

---

# 4. Risk Assessment

| 级别 | 项 | 影响 |
|---|---|---|
| **Critical** | C-1 取消孤儿 Run | 线上断流/取消导致台账长期 `running`，成本与恢复语义失真；扫掠前无法区分「活着」与「已死」 |
| **High** | H-1 休眠双循环 | 架构红线（不变量 8/9）名存实亡；双实现漂移与错误修复落空 |
| **High** | H-2 反向依赖 | 分层腐蚀；观测层绑死 Runtime 内部，后续 Runtime 重构必炸 services |
| **High** | H-3 绕过 services 读库 | 域读口径分叉；无法统一缓存/审计/权限 |
| **High** | H-4 session/user 混用 | 多用户或 session≠user 时读错记忆/世界/状态 |
| **High** | H-5 状态所有权 | 与评审判据冲突；内存持有域内容 + 不 reset，泄漏与一致性风险 |
| **High** | H-6 嵌套双 Run + 状态吞没 | 审计不可信；事件升级失败被记成成功 |
| **High** | H-7 通道层越界 | 新渠道复制粘贴越界；与文档双向约束矛盾 |
| **Medium** | M-1~M-10 | 域策略渗入 Runtime、竞态、记账失真、私有 API、全局缓存 |
| **Low** | L-1~L-4 | 时区/命名/文档滞后/契约追加（L-1 已于 2026-10-06 关闭，见 §3 L-1 处理结论） |

**回归风险（对既有功能）**：Flag 全 off 路径与 Preserve diff（验收报告 G4）表明 **V3.0 自身零回归**；飞书/Web/Memory/Planning/Action/World/Relationship 在关闭开关时行为对齐 V2.6.1。风险集中在开关开启后的运行时正确性（H-1/H-6/C-1），而非静默改写域数学。

---

# 5. Refactoring Recommendations

## Must Fix Before Merge

1. **C-1**：`close_run` / `emit_run_closed` 全部移入 `BaseException`-safe `finally`；取消路径必须关账。
2. **H-6**：消除 `run_event_pregate` 双 Run，或正确传播内层终态并在 `finally` 关闭外层。
3. **H-4**：修正 `session_id` 充当 `user_id`；`SessionContext` 携带真实 `user_id`。
4. **H-2（V3.0 新引入部分）**：切断 `services/observability/trace_query.py` → `agent_runtime` 的依赖（循环/错误映射下沉或上移调用）。
5. **H-1**：给出并执行「唯一认知循环」裁决（收敛到六段 **或** 明确降级为非生产影子实现并从默认导出面隔离）；禁止两套完整循环并存。
6. **H-3 中 domain 直读**：至少改掉 `stages/{plan,act,update}.py` 对 goal/action 仓储的直读（改走 services）；`controller` 的 outbox 扫读同样改门面。
7. **H-5**：Run 结束调用 `state.reset` / `context.reset`；在 architecture/baseline 明确投影持有策略。
8. **M-4**：`run_stage_async` 失败路径补 `return`，消除双 step。

> 完成后重跑：`pytest tests/v30 -q`、`pytest -m "(unit or api) and not slow" -q`、相关 integration；并补「取消流式 → Run 非 running」用例。

## Future Improvement

1. **H-7**：通道层与 Runtime/Services 依赖净化（application 门面中转）。
2. **M-1 / M-2**：域映射与角色资产依赖下沉；Runtime 多角色就绪。
3. **M-3 / M-5 / M-7 / M-10**：全局状态、台账并发、LLM 归因、版本语义。
4. **M-6 / M-8 / M-9**：私有 API 公有化、事件与 State Manager 对齐、degraded 提升策略。
5. **L-3**：按 acceptance W-1/W-2 回写 `current-system-architecture-baseline.md` 与 `AGENTS.md`（迁移链尾 `0052`、V3.0 形态）。
6. **H-2 既存部分**：`decision_pipeline` / `planning` → `agent_runtime` 反向依赖抽公共契约。
7. **I-2 / I-7（acceptance）**：既存失败簇与 PG 用例债独立排期。
8. 前端可视化（correlation 回放 UI）按 backlog。

---

# 6. Final Decision

**Require Changes**

理由：存在 **1 项 Critical**（取消孤儿 Run）与多项 **High**（休眠双循环违反不变量 8/9、services 反向依赖、绕过 services、session/user 混用、事件升级双 Run 状态吞没），触及「Runtime 只做编排」「依赖单向」「状态所有权」「无孤儿执行」四条评审主目标。Preserve 零改动与 Flag-off 对齐 V2.6.1 的努力值得肯定，但不足以覆盖上述边界与生命周期缺陷。

合并前须完成第 5 节 **Must Fix Before Merge** 清单；完成后可复审为 Approved 或 Approved with Minor Fixes（视 H-1 最终裁决收敛程度）。

---

## 附：评审覆盖说明

| 维度 | 覆盖 | 备注 |
|---|---|---|
| 1 架构合规 | 完整 | 含 dual pipeline / 替换 vs 包装 / 不变量 9 条 |
| 2 依赖边界 | 完整 | 分层 + 反向依赖 + channels 越界 |
| 3 状态管理 | 完整 | 所有权 / 所有权冲突 / run.data |
| 4 生命周期 | 完整 | init/exec/complete/fail/recover；孤儿与全局状态 |
| 5 既有回归 | 以 acceptance-report G4/零回归 + 接线点审查为主 | 真实模型人工回归仍按 `regression-checklist.md` 待执行 |
| 6 代码质量 | 完整 | 命名/抽象/重复/复杂度/错误处理；测试面 `tests/v30` 357 例评价为充分但未覆盖取消关账与双 Run 语义 |

**Sign-off**

- 自动化证据复核：引用 `docs/version/v3.0.0/acceptance-report.md`（G1~G12，G7 既存失败）
- 本报告不修改生产代码
- 裁决：**Require Changes**
