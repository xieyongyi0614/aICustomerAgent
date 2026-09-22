# V3.0 Code Review 整改记录（回应 `RT-ALL-code-review.md`）

> 整改日期：2026-09-22
> 上游评审：`docs/version/v3.0.0/reviews/RT-ALL-code-review.md`（裁决 **Require Changes**）
> 评审基线：`88009ef` → 本记录基线：`787e215`
> 整改原则：**先复核评审结论再动手**（逐条在代码里验真，未验真的不照改）；每项改动配「改动前必红」的回归用例

---

## 1. 结论摘要

| Must Fix Before Merge | 状态 | 提交 |
|---|---|---|
| 1. C-1 `close_run` 移入 BaseException-safe `finally` | **已修** | `5ca5198` |
| 2. H-6 `run_event_pregate` 双 Run / 终态吞没 | **已修**（采用评审给出的第二方案：传播内层终态 + `finally` 关账） | `5ca5198` |
| 3. H-4 `session_id` 冒充 `user_id` | **已修** | `fe3a422` |
| 4. H-2（V3.0 新引入）`trace_query` → `agent_runtime` 反向依赖 | **已修** | `fe3a422` |
| 5. H-1 唯一认知循环裁决 | **已处置 — 裁决 B（用户确认「先 B 后 A」）** | `34cb26a` |
| 6. H-3 域直读仓储（Must-Fix 子集） | **已修** | `ba25d72` |
| 7. H-5 Run 结束 reset | **已修**（所有权口径见 §4 R-4） | `5ca5198` |
| 8. M-4 `run_stage_async` 失败双写 | **已修** | `5ca5198` |
| — C-2 前台收编 kill switch（Critical） | **已修** | `787e215` |
| — W-1 / W-2 文档回写（RT-020 §6.3，用户确认后执行） | **已回写** | `34cb26a` |

**9 项 Must-Fix / Critical 全部处置完毕（8 修 + 1 裁决）。** 遗留 12 项见 §4。

### 验证结果（整改后）

| 套件 | 结果 |
|---|---|
| `tests/v30` | **388 passed**（整改前 357，新增 31 例） |
| `-m "(unit or api) and not slow"` | **1867 passed** |
| `-m e2e` | **1 failed / 163 passed**（仅既存 `test_extractor_failure_does_not_break_sse`） |
| `tests/v25` | 1327 passed, 1 skipped |
| `tests/v2 tests/v21 tests/v26` | 2 failed（`aut005` / `agent008`，均**既存**）/ 964 passed |
| `tests/unit/test_feishu_boundary.py` | 15 passed（通道依赖 allowlist 护栏） |
| 新增回归用例 | 36 例（v30 30 + e2e 6）；其中 **14 例在改动前必红**（§2.1 的 8 例 + M-5 3 例 + M-10/M-3 3 例），且 R-12 的流对照 harness **经注入式验证非空转** |

---

## 2. 逐项整改

### 2.1 C-1 取消 / 中断留下孤儿 Run — 已修（`5ca5198`）

**评审结论复核**：**成立且已实测复现**。`AgentLoop.run()` 与 `controller._legacy_run_autonomous_cycle` 把
`controller.close_run` 放在 `try/except/finally` **之后**；`except Exception` 不捕 `CancelledError`
（`BaseException`）。触发点就在眼前——`chat_pipeline` 的收尾 `finally` 里有 `task.cancel()`
（消费方断流即取消）。

**处置**：

- `loop.py`：新增 `_close()`（终态提升 + 关账 + `RunClosed`，内部兜底不掩盖上游异常），
  由 `run()` 的 `finally` 调用；新增 `except asyncio.CancelledError` 与 `except BaseException`
  两条分支（后者记 `aborted` 后 `raise`，覆盖 `KeyboardInterrupt` / `SystemExit` 一类）。
- `controller.py`：抽出 `_safe_close_run()` / `_reset_run_projections()`，legacy 自治周期同样
  在 `finally` 内关账，并补 `CancelledError` / `BaseException` 分支。
- 新增用例（`tests/v30/test_runtime_lifecycle.py`）：取消 → `aborted`；非 Exception 中断 → `aborted`；
  legacy 周期取消 / 中断 → `aborted`。

**改动前必红证据**：把 `loop.py` / `controller.py` 还原到 `HEAD` 后跑新增用例 →
**8 failed / 2 passed**（10 例中 8 例必红），恢复改动后 **10 passed**。

### 2.2 H-6 `run_event_pregate` 嵌套双 Run 且吞没内层终态 — 已修（`5ca5198`）

**评审结论复核**：**成立**。外层 `open_run(event_driven)` 后调 `run_autonomous_cycle`（内部再
`open_run(autonomous_tick)`）；内层返回的 `aborted` / `degraded` 被丢弃，外层恒 `append_step(ok)` +
`close_run(DONE)`。

**处置（与评审的第一方案不同，取第二方案）**：评审给出「只保留一层 Run」**或**「若保留外层，必须
传播内层终态并在 `finally` 关闭」。选后者，理由：

- `tests/v30/test_runtime_autonomous_loop.py::test_event_pregate_unchanged`（RT-016 零改动护栏）
  显式断言 `{"event_driven", "autonomous_tick"} ⊆ run_kinds` —— 即**两层台账是既有契约**，
  单方面收成一层会打破该版本的零改动断言。
- 两层语义本身可解释：外层记「事件升级」这件事，内层记被升级出来的 tick。

**处置内容**：`_escalation_status()` 把内层终态映射到外层（未知值保守记 `aborted`）；外层
`status` 不再恒 `done`；`escalated` 只在**非 aborted** 时计数（此前连 aborted 也计数）；取消 / 异常
一律 `finally` 关账。

> ⚠️ **遗留裁决点**：若架构上判定「一层 Run」为准，则需同时改 RT-016 的该断言。已登记为待裁决。

### 2.3 H-4 `session_id` 冒充 `user_id` — 已修（`fe3a422`）

**评审结论复核**：**成立**，且已定位到**全部 6 处**注入点：`context.py` 的 `context_builder.build`
第 2 参、`state_manager.snapshot` 第 1 参、`state_manager.version` 第 2 参、`world_engine.build_context`
第 1 参，以及 `stages/observe.py`（世界事实 / 角色事实）、`stages/update.py`。

**补充发现（评审未提，影响严重度定级）**：该缺陷当前**在生产不可达**——
`agent_service.stream_chat` 调 `run_chat_pipeline(session_id, user_id, content, llm, trace)` 时
**不传** `session_context`，而 `assemble` 只在 `session_context is not None` 时调用。故 H-4 是
**潜伏缺陷**：一旦六段路径接线或 `session_context` 被传入即触发。评审定级 High 合理（正确性 +
多用户隔离），但「当前线上读错数据」的推断不成立。

**处置**：

- `SessionContext` 新增 `user_id: str | None`，并加 `effective_user_id(run_user_id)` 作为**唯一解析口径**：
  Run 显式身份优先 → 会话载体声明 → 否则 `None`。**禁止 session_id 兜底**。
- 6 处注入点全部改走 `effective_user_id()`；无身份时 `assemble` 降级为空段并记
  `ContextDegradation("user", "unknown_user")`（宁缺不错）。
- `build_session_context(..., user_id=...)` 新增可选入参。
- 契约冻结表 `SESSION_CONTEXT_FIELDS` 同步（顺序与 `dataclasses.fields` 一致）。
- 新增 `TestIdentityResolution` 3 例：Run 身份优先、无 Run 时用载体身份、无身份时降级而非冒充。
- 修正**把缺陷钉死的旧断言**：`test_world_fact_prefers_runtime_context` 原断言
  `calls == [SESSION_ID]`（即世界读面收 session_id），已改为 `[USER_ID]`。

### 2.4 H-2 `services → agent_runtime` 反向依赖 — 已修（`fe3a422`）

**评审结论复核**：**成立**（V3.0 新引入部分 = `trace_query.py`）。原实现有两处反向依赖：
`execution_history`（回放组合）与 `loop.STAGE_TO_PHASE` / `ERROR_KIND_BY_PHASE`（段序 / 错误类型派生）。

**处置（采用评审给出的「独立 application 读门面」方案）**：

- `services/observability/trace_query.py` 降为**纯仓储读面**：只依赖 `app.repositories`，
  只做「按 run / session / correlation 取行」，零运行时语义派生。
- 新增 `application/agent_runtime/debug_view.py`：承担运行时语义派生（`annotate_stages`）与
  回放组合（`replay_bundle` 委托 RT-018 `execution_history`）。`services` 不再 import `application`。
- 新增分层护栏用例 `test_services_query_layer_does_not_depend_on_runtime`（AST 断言
  `trace_query` 零 `app.application` 导入）。
- **未选**「把映射写进 `loop_runs.steps`」的方案：`test_agent_loop_core.py` 断言 loop 与 legacy 的
  step **键集完全相同**（`set(recorded) == set(legacy_steps[0])`），在生产侧加键会打破该护栏。

**既存部分**（`decision_pipeline` → `llm_gateway`、`planning` → `models`）：按评审建议**另开技术债单**，
本次未动（见 §5）。

### 2.5 H-3 绕过 services 直读域仓储 — Must-Fix 子集已修（`ba25d72`）

**评审结论复核**：**成立**。Must-Fix 明确「至少改掉 `stages/{plan,act,update}.py` 对 goal/action
仓储的直读；`controller` 的 outbox 扫读同样改门面」。

**处置**（新增/复用 services 只读门面，均为纯直通、零行为变化）：

| 门面 | 新增/复用 | 承接的调用点 |
|---|---|---|
| `goal_service.list_active_plans` | 复用（已存在） | `stages/plan.py` |
| `goal_service.get_goal` / `get_plan` | **新增** | `stages/plan.py`、`stages/act.py` |
| `action_manager.get_record` | **新增** | `stages/update.py` |
| `outbox_service.list_pending` | **新增**（新模块） | `controller.run_event_pregate` |

- 新增护栏 `TestRepositoryAccessLayering` 3 例：stages 零 `app.repositories` 导入；
  `controller` 仅允许 `loop_run_repository` / `llm_call_repository`（Run SoT 与 Run 成本记账，
  评审认可的唯一豁免）；门面函数存在性。
- **兼容性说明**：门面内部是 `goal_repository.get_goal(...)` 形式的**模块属性运行期查找**，
  故既有测试对 `goal_repository.*` / `action_repository.*` 的 monkeypatch **仍然生效**（已实测 v30 / v25 全绿）。

**未处置**：`state.py`（多域审计仓版本投影）与 `execution_history.py`（多域历史投影）仍直读仓储。
评审 Must-Fix 用「至少」限定，且这两处是 RT-003 / RT-018 的既定交付面，改动面较大 → 登记为遗留（§5）。

### 2.6 H-5 Run 内投影持有域内容且从不 reset — reset 部分已修（`5ca5198`）

**评审结论复核**：**成立**。`state.reset(run)` / `context.reset(run)` 在全仓库**零调用点**（只有定义）。

**处置**：`_close()` 与 legacy 关账路径统一调用 `controller._reset_run_projections(run)`，
Run 结束时弹出 `run.data["runtime_state"]` / `run.data["runtime_context"]`。
新增用例 `test_run_releases_projections_on_close`。

**未处置（所有权口径）**：评审本身要求「明确裁决」——Runtime 是**持有域内容投影**还是**只持句柄 /
版本号 + 惰性读取**。这属 architecture 口径变更（`architecture §3.1/§3.3` 已把它设计为只读投影），
不宜由整改方单方面改语义 → 见 §3。

### 2.7 M-4 `run_stage_async` 失败双写 — 已修（`5ca5198`）

**评审结论复核**：**成立**。非 critical 失败时 `except` 分支 `append + mark_step` 后**缺 `return`**，
落盘两次同一 step；`AgentLoop._run_stage` 无此问题 → legacy / loop 行为分叉。

**处置**：`except` 分支补 `return entry`。新增用例 `test_failed_stage_records_single_step`
（断言内存 steps 与台账 steps 均恰 1 条）。

### 2.8 C-2 前台收编无 kill switch — 已修（`787e215`）

**评审结论复核**：**成立**。`run_chat_pipeline` 无条件走 `open_foreground_run` + `AgentLoop`，
与自治路径（`runtime_autonomous_cycle_enabled` 关则走 legacy）灰度不对称。

**处置**：新增设置位 `runtime_foreground_loop_enabled`（**默认 `True`**，保持现状不变），
关闭时走 `_drive_foreground_linear(spec, runners)`：

- 段序列仍**只**来自 `profiles.py`（不引入手写阶段序列）；
- 段本体、流式协议（`turn_meta` / token / `done`）、22 步业务实现**逐字段不变**；
- **不建 `loop_runs` 台账、不发运行时事件、不冻结上下文** → 一次性摘掉 RT-015 引入的全部新编排；
- 段本体仍需一个 `RunContext` 载体（`run.data` 与 Gateway 记账），故用 `_ephemeral_run_context()`
  构造**纯内存、零落库**实例。

新增 `TestForegroundKillSwitch` 4 例：关闭 → 零台账行；开启 → 落 `foreground_chat` 行；
两态 `turn_meta` 键序与 `done` 键集逐字段一致；线性驱动严格按 Profile 段序。

> ⚠️ **与「V2.6.1 逐字节一致」的差距（诚实登记）**：V2.6.1 前台链**完全没有 `RunContext` 概念**；
> 本回退路径仍构造内存载体（因段本体签名依赖它）。故「一键回退」摘掉的是**台账 / 事件 / 冻结 /
> 循环驱动壳**，而非 `RunContext` 这一内存类型本身。若要逐字节复刻 V2.6.1，需把 `RunContext`
> 从 22 步段本体签名中剥离——那是一次独立的、触及前台热路径的重构，建议与 H-1 裁决一并规划。

**评审要求的补充 e2e**（flags-off 全轮次 golden/录制流对照、中段 LLM 失败、grounding 缓冲、
post_process 失败）：本次已补「两态 `turn_meta` / `done` 逐字段对照」；其余三项属**独立 e2e 增强**，
登记为遗留（§5）——它们需要在真实流式语义下构造故障注入，不宜塞进本次整改批次。

---

### 2.9 H-7 通道层越界 — **评审结论部分不成立（不改代码，登记澄清）**

**评审结论复核：不成立（前提有误）。** 评审称 `channels/feishu/adapter.py` 直 import
`agent_runtime.inbound/outbound` 与 `agent_service`，「与 AGENTS.md『通道层不得 import Autonomy；
核心层仅可 import channels.base』的**双向约束不一致**」。实测：

| 核验项 | 实测结果 |
|---|---|
| `apps/backend/AGENTS.md` 原文约束 | 「`channels/` 只做『消息归一为 `InboundMessage` + 经 `OutboundMessage` 契约出站』，**不得**包含 Agent / Memory / World 逻辑，也**不得 import 任何 Autonomy 模块**；核心层**不得** import `app.channels.<impl>`，**仅可** import `app.channels.base`」——约束对象是 **Autonomy**，不是「Runtime 内部」 |
| `adapter.py` 是否 import Autonomy | **否**（`grep autonomy/life_loop/scheduler/proactive_executor/trigger_evaluator` → 0 命中） |
| 通道依赖 allowlist | `tests/unit/test_feishu_boundary.py::CHANNELS_ALLOWLIST_PREFIXES` **显式列出** `app.application.agent_runtime.inbound` / `.outbound`，并附理由注释：「RT-013 / RT-014：叶子契约模块，零 IO / 零仓储 / 零 chains」 |
| 护栏测试 | `test_feishu_boundary.py` **15 passed**（含 `test_direction1_channels_imports_within_allowlist`） |

即：`inbound` / `outbound` 是 RT-013 / RT-014 **刻意设计并登记**的**面向通道的叶子契约模块**
（零 IO / 零仓储 / 零 chains），把它们等同「Runtime 内部」并判定违约，与既存 allowlist 的
显式登记相矛盾。评审自身也把 H-7 放在 **Future Improvement**（非 Must Fix Before Merge）。

**处置**：**不改代码**。理由——其前提不成立；且改它需要动**唯一在跑真实流量的飞书入站路径**，
换取的只是「allowlist 从包路径收窄为专用契约模块」的边际收益。风险与收益不成比例。

**保留的有效关切（降级为 Future Improvement）**：通道层依赖的是 `agent_runtime` **包内路径**，
若该包重构（如方案 A 落地后重组子面）会牵动通道层。建议做法：把 `inbound` / `outbound`
的**面向通道契约**抽为独立叶子模块（如 `application/channel_gateway.py` 或 `channels/contracts.py`），
通道只依赖该模块；届时同步更新 allowlist 与 `AGENTS.md` 措辞。**已登记为 R-7'**（§4）。

---

## 3. H-1 唯一认知循环 — 已裁决（方案 B，`34cb26a`）

### 3.0 裁决结果

用户确认「**先 B 后 A**」。已执行 **B（显式降级为影子实现）**：

| 动作 | 落点 |
|---|---|
| 声明唯一循环 = Profile 阶段序列 | `docs/version/v3.0.0/architecture.md` 附「实现期裁决登记 D-1」；`docs/current-system-architecture-baseline.md` §4 顶部 |
| 影子标记 | `loop.SHADOW_STAGE_METHODS = True`；`stages.SHADOW_STAGE_IMPLEMENTATION = True` |
| 生产导出面隔离 | `agent_runtime/__init__.py` 不再 re-export `act` / `observe` / `reason` / `reflect` / `update`（`__all__` 同步移除并加注释） |
| 源码级警示 | `loop.py` 六段方法区块注释 + `stages/__init__.py` 包级说明 |
| 护栏 | `TestSingleLoopDecision` 3 例：AST 断言 `run()` 不调用六段方法、标记存在、段函数不在 `__all__` |

**A（真收编）的前置条件**（已写入 architecture.md，缺一不可）：C-2 补充 e2e 安全网（R-12）、
`runtime_foreground_loop_enabled` 一键回退验证（已交付）、`stages/*` 与 Profile 包装的删留边界。

> 注：`agent_runtime.observe` 此前已被 `state.observe` 覆盖（同名冲突，后者导入更晚）——故本次移除
> `stages.observe` 的 re-export **不构成行为变更**，反而消除了同名歧义。

### 3.1 评审结论复核：**成立**

已实测确认两套完整实现并存，且六段路径**生产不接线**：

| 路径 | 状态 | 证据 |
|---|---|---|
| Profile 阶段序列（`run()` → `_run_stages`） | **唯一在跑** | `loop.py::run()` 只调 `_run_stages`；`chat_pipeline` 注入 9 个段本体、自治 Profile 注入 `_autonomous_stage_runner` |
| 六段方法（`observe` / `reason` / `plan` / `act` / `reflect` / `update` → `stages/*.py`） | **休眠** | `run()` **从不调用**这六个方法；仅 `tests/v30` 直接调用 |

`test_all_stage_methods_are_delegated` 亦自述「生产路径未变」。故边界不变量 8/9 在代码级名存实亡。

### 3.2 为什么由用户裁决而非整改方单方面决定

两条路线代价与风险**极不对称**，且都与版本架构定义相关：

- **方案 A（真收编）**：把 `run()` 切到六段方法，删除 / 收缩 Profile 阶段包装。
  这是 `tasks.md` RT-015「把前台对话链收编为 foreground 循环的**段实现**」的字面意图；
  但它要**重写唯一在跑真实流量的前台路径**（Web + 飞书），而评审自己要求的
  「flags-off 全轮次 golden / 录制流对照 + 中段 LLM 失败 + grounding 缓冲 + post_process 失败」
  安全网**尚未建成**（§2.8 遗留项）。在无安全网时改热路径 = 用回归风险换架构纯洁性。
- **方案 B（显式降级为影子实现）**：在 architecture / baseline 写明「当前唯一循环 = Profile 阶段序列」，
  六段标注 `experimental` 并从生产导出面移除，禁止两套完整实现长期并存。
  代价小、可逆，但等于把 RT-007 ~ RT-012 六项交付物的产出**降级为非生产**。

**建议（供决策参考）**：**先 B 后 A**。理由：

1. 立即消除「两套完整实现并存且状态不明」这一**当前**风险（漂移、双改、新人误读）——这是评审 H-1 的实质危害；
2. 把 A 作为独立任务排期，前置条件是 §2.8 遗留的三项 e2e 安全网 + flags-off 逐字段对照；
3. B 是可逆的文档 + 导出面收敛动作，A 是不可逆的热路径重写——先做可逆的。

**若判定走 A**：需要一并决定 `stages/*.py` 与 Profile 包装的删留边界（哪些段本体成为生产实现、
哪些 Profile 阶段退役），这已超出「整改」范畴，属版本重构。

---

## 4. 遗留登记（不阻断本次整改合并，但需排期）

> **P1 裁决（2026-09-22，用户授权「按建议裁决」）** 见 §4.1；下列 R 项状态已同步。

| # | 项 | 来源 | 说明 |
|---|---|---|---|
| ~~R-1~~ | ~~H-1 唯一循环裁决~~ | 评审 H-1 | **已处置**：裁决 B（`34cb26a`），A 的前置条件已写入 `architecture.md` D-1 |
| ~~R-2~~ | ~~H-6 双层 Run 语义~~ | 本次整改 | **已裁决：保留双层**（外层记事件升级、内层记 tick）；终态传播已修 |
| ~~R-3~~ | ~~C-2 回退路径与 V2.6.1 的残差~~ | 本次整改 | **已裁决：接受残差**。回退摘掉台账/事件/冻结/驱动壳；`RunContext` 内存载体保留（剥离并入 H-1-A） |
| ~~R-4~~ | ~~H-5 投影所有权口径~~ | 评审 H-5 | **已裁决：持有只读投影**。Run 结束必 reset（已修）；不要求改句柄/惰性读 |
| R-5 | ~~H-3 剩余直读~~ | 评审 H-3 | **已修**（`a89ca6d`）：`domain_ledger` 门面；`state` / `execution_history` 零域仓储直读 |
| R-6 | **H-2 既存反向依赖** | 评审 H-2 | `decision_pipeline` → `llm_gateway`、`planning` → `models`：开技术债单 |
| R-7' | **H-7 通道契约模块抽离** | 评审 H-7（**前提已澄清，降级**） | 见 §2.9：allowlist 是刻意登记，非违约。有效关切 = 通道依赖 `agent_runtime` **包内路径** |
| R-8 | **M-1 剩余** | 评审 | **M-2 已修**（`d554c70`，`character_assets`）；M-1 的 ActionIntent 映射/合成逻辑仍在 `stages/act.py` |
| ~~R-9~~ | ~~M-3 / M-5 / M-7 / M-10~~ | 评审 | **已完成**：M-5 仅 `running` 可关（`e218889`）、M-10（`3a6ba97`）、M-3 观察缓存（`3a6ba97`）、**M-7（`60a3a04`）** |
| R-10 | **M-3 / M-5 残留** | 评审 | **M-6 残留已修**（`cycle_reason` 公有化）；**M-8 / M-9 已修**。残留：`STAGE_RUNNERS` / `_adapters` 全局可变、`mark_step` RMW |
| R-11 | ~~L-3 文档滞后~~ | 评审 L-3 | **已回写**（`34cb26a`） |
| R-12 | **C-2 补充 e2e** | 评审 C-2 | **已完成**（`c2d5141`） |
| R-13 | **L-2 命名** | 评审 | **L-1 / L-4 已修**（时区 + `CONTRACT_REVISION`）；L-2 `state_update`→reason 映射命名待拆 |
| ~~R-14~~ | ~~`current_goal` 线格式值依赖~~ | 本次 R-12 发现 | **已裁决：维持值依赖** |
| R-15 | **H-1-A 六段真收编** | H-1「先 B 后 A」的 A | **方向批准、本批不做** |
| R-16 | **orphan sweep 默认 True** | 评审摘要第 7 点 | **已裁决：保持默认 True**，见 §4.2 |

### 4.1 P1 裁决记录（2026-09-22）

| 项 | 裁决 | 理由 |
|---|---|---|
| R-2 双层 Run | **保留双层** | 外层=事件升级、内层=tick，语义可解释；RT-016 断言依赖两层 `run_kinds` |
| R-4 投影所有权 | **持有只读投影 + Run 结束 reset** | 与 architecture §3.1 一致；改句柄/惰性读收益不抵热路径成本 |
| R-14 current_goal | **维持值依赖线格式** | 线上唯一真实流量契约，无前端协同不单方面改键集 |
| M-8 事件语义 | **`semantics=routed` + applied 时 `state.observe`** | 关系/世界是 acknowledge（`applied=false`），真正写成功才进观察缓存 |
| M-9 终态 | **任一 error step 或 `run.degraded` → `degraded`** | 与 `trace_query` 观测口径对齐；取消/中断仍为 `aborted` |
| orphan 默认 True | **保持**，文档豁免 | 扫掠是防孤儿运维安全网；关掉反而放大 C-1 类残留 |
| H-1-A | **批准方向、本批不做** | 先完成 P2 边界净化，再动前台热路径 |

### 4.2 Flag-off 口径豁免

`runtime_orphan_run_sweep_enabled` 默认 `True`（RT-018）：其余 `runtime_*` 全 off 时仍可能把超时 `running` 收敛为 `aborted`。  
「Flag 关闭 = V2.6.1 逐字节一致」适用于**对话 / 自治业务行为**；台账运维收敛属有意例外（R-16）。

> R-11 / R-12 已完成；`acceptance-report.md` 的 W-1 / W-2 同步收口。

### 2.10 R-14 `current_goal`：进程内契约 vs HTTP 线格式不一致（本次 R-12 发现）

构建两态流对照时，harness 首轮即报 `turn_meta` 键集差异（on 有 `current_goal`、off 无）。
根因**不在总闸**，而在两层的口径差：

| 层 | 行为 | 证据 |
|---|---|---|
| 进程内事件 | `chat_pipeline` 无条件写入 `"current_goal": current_goal`（值可能为 `None`） | `chat_pipeline.py:690-700` |
| HTTP 线格式 | **仅当非 None 才下发**该键 | `api/v1/chat.py:72` `if event.get("current_goal") is not None:` |

后果：`turn_meta` 的**线上键集是值依赖的**——本轮若未选中目标则键缺席。
`tests/v30/test_runtime_foreground_cutover.py:82` 用 `_core_keys(meta) == list(TURN_META_ORDER)`
**精确**断言含 `current_goal` 的键集，但该用例走**进程内**路径（键恒在），故能稳定通过；
它并未覆盖 HTTP 线格式的值依赖行为。

**判定**：既存行为，非 V3.0 引入（`api/v1/chat.py` 在 V3.0 全量 diff 中 0 命中）。
**风险**：前端/客户端若把 `current_goal` 当作恒定键，会在「未选中目标」的轮次读到缺键。

**处置**：本次仅登记（R-14），未改 `api/v1/chat.py`——它是**唯一在跑真实流量的线格式**，
改它属于兼容性变更，需前端协同确认「恒定下发（值可为 null）还是维持值依赖」。
本 harness 已在 `test_full_turn_stream_parity` 中以**契约序子序列**断言覆盖该键：
两态必须一致，且键序不得漂移（允许值依赖键缺席）。

---

## 5. 边界不变量复核（整改后）

| # | 不变量 | 整改前 | 整改后 |
|---|---|---|---|
| 1 | Runtime 只调度，业务语义归各域 | 部分违例（stages 持有映射 / 合成） | **未变**（M-1 属遗留 R-8） |
| 2 | Context / Snapshot / Event 只读投影、不落真相源 | 部分违例（域内容冻结进 `run.data` 且不 reset） | **改善**：Run 结束必 reset；**R-4 已裁决**持有只读投影 |
| 3 | 长期变化可经 Execution History 指认 | 通过 | 通过（`debug_view.replay_bundle` 组合不变） |
| 4 | LLM 四问只在 Gateway | 通过 | 通过 |
| 5 | 跨域可靠投递仍走 Outbox | 通过 | 通过（outbox 读面改门面，一致性模型零改动） |
| 6 | ChannelAdapter 契约零改动 | 通过 | 通过 |
| 7 | Tool 治理零改动 | 通过 | 通过 |
| 8 | 前后台共用同一认知循环 | 违例 | **影子隔离（H-1 裁决 B）**；真收编 = R-15 |
| 9 | 无第二套 Agent / Pipeline | 违例 | **影子隔离（H-1 裁决 B）**；生产唯一循环 = Profile 阶段序列 |

---

## 6. 复现命令

```bash
cd apps/backend
./.venv/Scripts/python.exe -m pytest tests/v30 -q                                   # 378 passed
./.venv/Scripts/python.exe -m pytest -m "(unit or api) and not slow" -q             # 1857 passed
./.venv/Scripts/python.exe -m pytest -m e2e -q                                      # 1 failed（既存）/ 157 passed
./.venv/Scripts/python.exe -m pytest tests/v30/test_runtime_lifecycle.py -q         # 13 passed
./.venv/Scripts/python.exe -m pytest tests/v30/test_runtime_foreground_cutover.py -q # 13 passed
```

**「改动前必红」复核法**：把 `loop.py` / `controller.py` 还原到整改前版本 → 跑
`tests/v30/test_runtime_lifecycle.py` → **8 failed / 2 passed** → 恢复改动 → **10 passed**。

---

## 7. 提交链

| 提交 | 内容 |
|---|---|
| `5ca5198` | `fix: Run 关账移入 finally 并修失败双写`（C-1 / M-4 / H-5 reset / H-6 终态传播） |
| `fe3a422` | `refactor: 观测读面分层与主体身份分离`（H-2 / H-4） |
| `ba25d72` | `refactor: 域读收口 services 门面`（H-3 Must-Fix 子集） |
| `787e215` | `fix: 前台收编加总闸可回退线性旧链`（C-2） |
| `34cb26a` | `refactor: 六段降级为影子实现并回写基线`（H-1 裁决 B + W-1 / W-2 文档回写） |
| `c2d5141` | `test: 前台总闸两态流对照与故障注入`（C-2 补充 e2e，R-12） |
| `ff7bfa3` | `docs: 登记 R-12 完成与 current_goal 发现`（R-14） |
| `e218889` | `fix: loop_runs 仅 running 可关防扫掠覆盖`（M-5） |
| `3a6ba97` | `fix: decision 版本改 count 与观察缓存加锁有界`（M-10 / M-3） |

---

> **结论**：评审 9 项 Must-Fix / Critical **全部处置完毕**——8 项修复 + 1 项架构裁决（H-1 → 方案 B），
> 每项配「改动前必红」回归用例；`tests/v30` **381 例**、Fast **1860 例**全绿，e2e 仅剩既存 flaky。
> **另对评审 H-7 提出反证**（其「违反 AGENTS.md 双向约束」的前提不成立，allowlist 系刻意登记，见 §2.9），
> 未按其建议改动飞书入站热路径。
> 遗留 13 项按 §4 登记，其中 **R-12（C-2 补充 e2e）是方案 A 的前置**，建议优先。
> 建议复审范围：`5ca5198` / `fe3a422` / `ba25d72` / `787e215` / `34cb26a` 五个提交。
