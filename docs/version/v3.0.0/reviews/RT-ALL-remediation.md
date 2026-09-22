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
| 5. H-1 唯一认知循环裁决 | **未处置 — 需架构裁决**（见 §3） | — |
| 6. H-3 域直读仓储（Must-Fix 子集） | **已修** | `ba25d72` |
| 7. H-5 Run 结束 reset | **已修**（所有权口径见 §4） | `5ca5198` |
| 8. M-4 `run_stage_async` 失败双写 | **已修** | `5ca5198` |
| — C-2 前台收编 kill switch（Critical） | **已修** | `787e215` |

**8 项 Must-Fix 中 7 项已修并验证；1 项（H-1）属架构裁决，不宜由实现方单方面定夺。**

### 验证结果（整改后）

| 套件 | 结果 |
|---|---|
| `tests/v30` | **378 passed**（整改前 357，新增 21 例） |
| `-m "(unit or api) and not slow"` | **1857 passed** |
| `-m e2e` | 1 failed / 157 passed（仅 `test_memory_e2e::test_extractor_failure_does_not_break_sse`，**既存**） |
| `tests/v25` | 1327 passed, 1 skipped |
| `tests/v2 tests/v21 tests/v26` | 2 failed（`aut005` / `agent008`，均**既存**）/ 964 passed |
| 新增回归用例 | 21 例；其中 **8 例在改动前必红**（见 §2.1） |

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

## 3. 待裁决：H-1 唯一认知循环（**本次唯一未处置的 Must-Fix**）

### 3.1 评审结论复核：**成立**

已实测确认两套完整实现并存，且六段路径**生产不接线**：

| 路径 | 状态 | 证据 |
|---|---|---|
| Profile 阶段序列（`run()` → `_run_stages`） | **唯一在跑** | `loop.py::run()` 只调 `_run_stages`；`chat_pipeline` 注入 9 个段本体、自治 Profile 注入 `_autonomous_stage_runner` |
| 六段方法（`observe` / `reason` / `plan` / `act` / `reflect` / `update` → `stages/*.py`） | **休眠** | `run()` **从不调用**这六个方法；仅 `tests/v30` 直接调用 |

`test_all_stage_methods_are_delegated` 亦自述「生产路径未变」。故边界不变量 8/9 在代码级名存实亡。

### 3.2 为什么不由整改方单方面裁决

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

| # | 项 | 来源 | 说明 |
|---|---|---|---|
| R-1 | **H-1 唯一循环裁决** | 评审 H-1 | 见 §3，需架构裁决；建议先 B 后 A |
| R-2 | **H-6 双层 Run 语义** | 本次整改 | 已按评审第二方案修好终态传播；若判定改单层 Run，需同步改 RT-016 断言 |
| R-3 | **C-2 回退路径与 V2.6.1 的残差** | 本次整改 | 回退仍构造内存 `RunContext`；逐字节复刻需剥离段本体签名依赖 |
| R-4 | **H-5 投影所有权口径** | 评审 H-5 | reset 已补；「持有投影 vs 持有句柄」需 architecture 裁决 |
| R-5 | **H-3 剩余直读** | 评审 H-3 | `state.py` / `execution_history.py` 的多域审计读仍在 `application` 直连仓储 |
| R-6 | **H-2 既存反向依赖** | 评审 H-2 | `decision_pipeline` → `llm_gateway`、`planning` → `models`：按评审建议开技术债单 |
| R-7 | **H-7 通道层越界** | 评审 H-7 | `channels/feishu/adapter.py` 直 import `agent_runtime.inbound/outbound` 与 `agent_service` |
| R-8 | **M-1 / M-2** | 评审 | 域映射与角色资产（`app.character.asuna`）下沉；多角色就绪 |
| R-9 | **M-3 / M-5 / M-7 / M-10** | 评审 | `_OBSERVED` 无锁全局态、`loop_runs` RMW 竞态、LLM 按时间窗记账、decision 版本号语义 |
| R-10 | **M-6 / M-8 / M-9** | 评审 | 私有 API（`_GATE_BUDGET` / `_execute_plan_step` / `_day_bucket_key` / `_STATUS_DEGRADED`）公有化；Update 事件与 State Manager 对齐；`promote_degraded` 口径 |
| R-11 | **L-1 ~ L-4** | 评审 | 时区一致性、`state_update` 映射命名、文档滞后、契约事件集版本 bump |
| R-12 | **C-2 补充 e2e** | 评审 C-2 | flags-off 全轮次 golden / 录制流对照、中段 LLM 失败、grounding 缓冲、post_process 失败 |

> R-11 中的文档滞后（`current-system-architecture-baseline.md` 迁移链仍写 `0050`、`AGENTS.md` 同、
> `architecture.md` 仍写「仅设计」）与 `acceptance-report.md` 的 W-1 / W-2 是同一件事，按 RT-020 §6.3
> 需用户确认后回写。

---

## 5. 边界不变量复核（整改后）

| # | 不变量 | 整改前 | 整改后 |
|---|---|---|---|
| 1 | Runtime 只调度，业务语义归各域 | 部分违例（stages 持有映射 / 合成） | **未变**（M-1 属遗留 R-8） |
| 2 | Context / Snapshot / Event 只读投影、不落真相源 | 部分违例（域内容冻结进 `run.data` 且不 reset） | **改善**：Run 结束必 reset（H-5）；所有权口径待裁决（R-4） |
| 3 | 长期变化可经 Execution History 指认 | 通过 | 通过（`debug_view.replay_bundle` 组合不变） |
| 4 | LLM 四问只在 Gateway | 通过 | 通过 |
| 5 | 跨域可靠投递仍走 Outbox | 通过 | 通过（outbox 读面改门面，一致性模型零改动） |
| 6 | ChannelAdapter 契约零改动 | 通过 | 通过 |
| 7 | Tool 治理零改动 | 通过 | 通过 |
| 8 | 前后台共用同一认知循环 | 违例 | **未变**（H-1 / R-1 待裁决） |
| 9 | 无第二套 Agent / Pipeline | 违例 | **未变**（H-1 / R-1 待裁决） |

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

---

> **结论**：评审 8 项 Must-Fix 中 7 项已整改并配「改动前必红」回归用例，`tests/v30` 378 例、
> Fast 1857 例全绿，e2e 仅剩既存失败。**唯一未处置项 H-1 属架构裁决**（§3 已给出建议：先 B 后 A），
> 另 12 项遗留按 §4 登记。建议复审范围：`5ca5198` / `fe3a422` / `ba25d72` / `787e215` 四个提交。
