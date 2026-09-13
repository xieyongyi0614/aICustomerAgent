# V2.1.0 Autonomy 2.0 Code Review

> 范围：AGENT-001 ~ AGENT-007（commit `970cf29` → `2ff88ea`，62 files / +4941 −299）
> 依据：`architecture.md`、`tasks.md`、`AGENT-001.md`（含各 Task §12 实施记录）
> 验证：`pytest tests/v21` → **95 passed**（19.93s）
> 结论：**NEED FIX**

---

## 1. Review 结果

**NEED FIX**

骨架正确、Flag 设计干净、迁移可回滚、单元测试全绿；但**「Evolution Loop 的慢时钟在运行系统中不存在」**与**「前后台并未共用同一条决策管线」**两处与 architecture 的版本核心承诺直接冲突，另有 1 处跨用户数据泄漏。属「模块已建成、闭环未接通」，不可按现状验收。

---

## 2. 架构问题

### A1 [P0] Evolution Engine 与 Evaluation 在生产系统中零调用方

- **文件**：`app/services/evolution.py`（`compile_personality` L36 / `rebalance_goals` L98 / `rollback_personality_for_insight` L58）、`app/services/agent_evaluation.py`（`run_daily_snapshot` L32）、`app/main.py`（lifespan）、`app/application/life_loop.py`、`app/api/v1/*`
- **问题**：三个入口在整个 `app/` 内**没有任何调用方**（全仓仅 `tests/v21/*` 调用）。lifespan 未注册日/周级周期任务；无 API 出口；`run_life_loop_tick` 只挂了 `run_event_pregate`。
- **风险**：architecture §1.2 的慢时钟（反思→记忆整合→**演化**）整段缺失：
  - 人格永不漂移（AGENT-005 验收 1/2/5 不成立）
  - Goal Rebalance 永不执行
  - `agent_metric_snapshots` 永不落库、演化议题永不产生（AGENT-006 验收 2/3/4 不成立）
  - AGENT-007 验收 1「全链各环节在 trace/台账中可逐段指认」在真实系统中不可达
  - `regression-checklist.md` 主线 B（B1/B3）与主线 C（C1/C2）**无法执行**
- **修改建议**：在 lifespan 注册日级/周级 worker（复用 `run_worker_loop` + per-user 遍历，或挂既有 job worker），或在 `_run_maintenance` 内按间隔触发；补集成测试断言「Flag 开启 + tick 后 `agent_metric_snapshots` / `personality_state.current` 出现变化」。

### A2 [P0] 前台与后台未共用同一决策管线

- **文件**：`app/application/chat_pipeline.py` L257-590、`app/services/decision_pipeline.py` L203、`app/application/autonomy_engine.py` L208
- **问题**：`run_pipeline` 唯一调用方是 `autonomy_engine._pipeline_intention`（后台）。`chat_response=True` 与 `capabilities=` 两个参数**无任何调用方**；`chat_response` 候选源与 `capability` 候选源均为死代码。前台 Run 仍走 v2.0.0 的四链 + `intention_policy.enforce` 路径，只是外面包了一层 Run 记账。`profiles.py` 中 `foreground_chat` 声明的 8 个 stages 亦未被执行。
- **风险**：违反 §5.1「前台与后台共用同一条五段管线」与 §9.3 不变量 5「不得再出现平行决策路径」；AGENT-004 验收 1（「构造用例可证明走同一代码路径」）未达成；前台 `decision_records` 无 `candidates` 审计（§12 已登记为 trace 暂记，但 AGENT-007 未收口）。
- **修改建议**：二选一，不可两处都声称——(a) 在 `chat_pipeline` 内以 `run_pipeline(chat_response=True, capabilities=...)` 产出意图（回复候选恒 P0），(b) 修订 architecture §5.1/§9.3 与 AGENT-004 验收，明确「管线当前仅服务后台，前台为独立路径」。

### A3 [P1] Profile Registry 与实际执行序列不一致，台账 profile 快照失真

- **文件**：`app/application/agent_runtime/profiles.py` L42-59 vs `controller.py` L183-228；测试 `tests/v21/test_agent001_profiles_gateway.py` L39-45
- **问题**：`autonomous_tick` profile 声明 10 个 stages（**缺 `goal_stack`**），实际执行 11 个。`run_autonomous_cycle` **硬编码**阶段序列，不遍历 `profiles.get_profile(...).stages`。测试把错误的 10 项序列固化为断言。
- **风险**：`loop_runs.profile` 回放快照与实际轨迹不符（AGENT-001 验收 2 失真）；§5.3「新 Profile 的加入点是本注册表，而不是新的编排代码路径」未落实——新增阶段仍需改 controller，架构验收 6「无第二套 Agent Pipeline」的落点被架空。
- **修改建议**：profiles 补 `goal_stack`；controller 改为按 `profile.stages` 顺序驱动（阶段函数映射表）；测试断言 `profile["stages"] == [s["step"] for s in run.steps]`。

### A4 [P1] Goal Rebalance 直写 `goals` 表

- **文件**：`app/services/evolution.py` L106-116
- **问题**：`rebalance_goals` 调 `goal_repository.finish_goal` 直接改 goals 行状态。architecture §6.6 明确「建议进入既有 supply 审核规则后才成目标，**0 直接写入 goals 表**」；AGENT-005 验收 4「Goal Rebalance 只产生建议且经 supply 审核生效，goals 表无直写路径」。§12.4 自称「复用既有 finish_goal 出口，0 直写」——自相矛盾。
- **风险**：绕过 supply 审核通道；验收项不成立；「建议」与「执行」边界消失。
- **修改建议**：改为写入建议队列（复用 `goal_planning` / `background_job` 的 supply 出口），由审核规则消费；或在 architecture/验收中明确修订该口径。

### A5 [P1] Evolution Ledger 跨用户数据泄漏 + 未按设计成视图

- **文件**：`app/services/evolution.py` L119-165（查询 L122-133）、`migrations/versions/0042_evolution_ledger.py`
- **问题**：
  1. personality 变更查询仅过滤 `DevelopmentChangeRow.personality_state_id.isnot(None)`，**无 `user_id` 过滤** → `ledger("user-A")` 返回全库所有用户的人格变更（`user_id` 取自 join 出的 personality 行）。
  2. 0042 docstring 声称「Evolution Ledger 只读视图（四源投影）」，实际**未创建任何 SQL 视图**；§6.5 要求的 `relationship_events`、memory supersede 链两源缺失（仅 personality + goal）。
- **风险**：多用户隔离破坏（隐私/串数据，本项目多用户隔离是既有硬约束）；迁移文档与代码不符；AGENT-005 验收 3 仅覆盖 2/4 源。
- **修改建议**：补 `PersonalityStateRow.user_id == user_id` 过滤；补跨用户隔离测试；修正 0042 docstring（或按 §6.5 补视图 + 两源）。

### A6 [P1] 后台 Run 不复位 Agent State contextvar（快照跨 Run 泄漏）

- **文件**：`app/application/agent_runtime/controller.py` L158-239 vs `app/application/chat_pipeline.py` L586
- **问题**：前台 `finally` 调 `agent_state_assembler.reset_run_state(run_ctx)`；后台 `run_autonomous_cycle` 只 reset `memory_digest_var`，**未 reset `agent_state_context`**（全仓 `reset_run_state` 仅 1 处调用）。
- **风险**：违反 AGENT-002 §12.2「Run 结束时调用方负责 reset」。若某 Run 的 `state_snapshot` 阶段异常（`assemble` 失败被 `run_stage` 吞掉），上一 Run（甚至上一用户）的快照仍驻留，被后续 `decision` 步骤的 proactive prompt 读到 → 跨 Run/跨用户状态污染。
- **修改建议**：在 `run_autonomous_cycle` 的 finally 中调用 `reset_run_state(run)`；补「阶段异常后 contextvar 为空」的测试。

### A7 [P2] Gateway 调用权未真正收归（仅 3 个接线点）

- **文件**：`app/application/agent_runtime/llm_gateway.py`、`chat_pipeline.py` L310/L464、`controller.py` L214
- **问题**：12 个能力全部注册，但实际经 Gateway 裁决的只有 `answer`、4 条前台决策链、后台 `proactive` 闸。其中 `account_turn_decisions` 是**调用完成后的补记账**（链已用原 `llm` 执行完），并非事前裁决。`scene_update` / `state_update` / `extractor` / `summary` / `judge` / `reflection` 六个调用点未接（`post_process.py` 零改动）。
- **风险**：AGENT-001 验收 3「全部 LLM 调用经 Gateway」未达成；§0.2 铁律 3「域服务不再自行决定是否调用 LLM」只部分落实。§12.3 登记为「渐进迁移」，但 AGENT-007（收口任务）未收口。
- **修改建议**：至少按 AGENT-001 §9 Step 3 原计划把 `post_process` 内 LLM 调用点接上；或把验收 3 修订为「注册表全覆盖 + 已接线点清单」。

### A8 [P2] Snapshot 组装在后台同步阻塞事件循环

- **文件**：`controller.py` L186（同步 `run_stage`）→ `agent_state_assembler.assemble`（含 `world_engine.collect_facts` / `memory_repository.list_top_salience` / `action_repository.list_records` 三次 DB 读）
- **问题**：同一逻辑前台走 `asyncio.to_thread`，后台走同步直调（在 async 函数内、持有写锁时执行）。
- **风险**：阻塞事件循环；性能口径不一致（checklist 要求 Snapshot ≤150ms）。
- **修改建议**：后台阶段改为 `await asyncio.to_thread(...)`，或登记为显式同步开销并纳入性能预算实测。

---

## 3. 代码问题

| # | 文件 | 问题 | 优先级 |
|---|---|---|---|
| C1 | `app/services/evolution.py` L122-133 | `ledger` 查询缺 `user_id` 过滤（见 A5） | **P0** |
| C2 | `app/services/evolution.py` L197-201 | `_constrain_drift` 逻辑反向：`base_delta = 0.02 × min(len(evidences),3)` 最高 0.06 > `v21_evolution_max_drift_per_week=0.05`，`abs(recent)+base_delta > max_week` 直接 `return None`。默认配置下窗口内 ≥3 条证据（常见）→ **永不演化**；证据越多越无法漂移 | **P1** |
| C3 | `app/services/decision_pipeline.py` L130-142、L145-170 | 六维评分中 `state_fit`/`relationship_fit`/`timing`/`cost` 恒为常量 0.5；风险闸仅实现 persona（恒 `"pass"`, reason=`no_conflict_rule`）与预算两闸，Relationship 闸门与 Action 检定未实现。§5.2③④ 要求逐维取自 Snapshot/Relationship/Trigger Registry/Budget，「逐闸留痕」记的是常量 | **P1** |
| C4 | `app/models/goal.py` L46 | `validate_parent_chain` 生产代码零调用（仅测试引用）；`create_hierarchical_goal` 不校验父层，L3→L2→L1 层深约束实际未生效 | **P1** |
| C5 | `app/services/goal_stack.py` L85-86 | `low_energy` 抑制是空操作：只写 `stack.suppressed`，`primary()` 仍优先返回 `short_term`。§4.2「激活需状态许可（energy/scene）」未生效 | **P1** |
| C6 | `app/models/goal.py` L32 / `goal_repository.py` L330 | `GOAL_ORIGINS` 定义后未用于校验，`create_hierarchical_goal(origin=...)` 接受任意字符串 | P2 |
| C7 | `app/application/agent_state_assembler.py` L156-173 | 读路径写库：`get_all_or_seed` 在只读组装中播种 `personality_state`。违反「投影不写」与 AGENT-002 验收 4「除 AGENT-005 写入方外无任何写入通路」 | P2 |
| C8 | `app/services/evolution.py` L62/122/169/210/233 | 绕过仓储层直接 `SessionLocal()` 读写（含 `DevelopmentChangeRow` / `InsightRow` / `GoalRow`），与项目其余服务统一走 repository 的约定不一致 | P2 |
| C9 | `app/application/agent_state_archiver.py` L36 | 死赋值：`version = snapshot.snapshot_version if changed else last.version` 紧接被 `if changed: version = last.version + 1` 覆盖 | P2 |
| C10 | `app/services/goal_stack.py` L99/L101 | `__import__("datetime").timedelta` 动态导入，应为 `from datetime import datetime, timedelta` | P2 |
| C11 | `app/services/evolution.py` L27-32、L185 | `_AXIS_EVIDENCE_RULES` 的 direction 恒 `+1.0` 且解包后未使用（`keywords, _direction`）→ 人格轴只能单向上升；§6.2「连续同向漂移需多窗口证据」隐含的双向能力未实现 | P2 |
| C12 | `app/services/decision_pipeline.py` L31、L159-161 | `chat_response = P0` 与 §5.3 铁律（P0 = 安全与用户显式指令）冲突；`run_risk_gates` 用 background 能力 `"proactive"` 做闸，且 `llm_gateway.acquire` 在 granted 时会自增 `run.llm_calls` —— 闸带副作用，run 传入时会重复计费 | P2 |
| C13 | `app/services/agent_evaluation.py` L138-159 | `_trend` 未实现「连续 N 窗口越限」：只看前 1 个窗口，`v21_metric_trend_windows` 仅用于取历史行数，未参与判定 | P2 |
| C14 | `app/application/agent_runtime/controller.py` L140-147 | `close_run` 用时间窗计数（`count_calls_between(started_at, finished)`）统计 run 级 LLM 调用，多用户并发 Run 会互相计入；AGENT-001 §5.4「后台调用点 `request_id = run_id`」的归因约定未落实 | P2 |
| C15 | `controller.py` L242-274 | 一次事件产生两行 `loop_runs`（`event_driven` + `autonomous_tick`）且无父子关联字段；`escalated` 计数口径落在 pregate 行；事件 `event_driven` 行的 `profile.stages` 仅 `("event_pregate",)`，与真实工作量不符 | P2 |
| C16 | `migrations/versions/0040_goal_stack.py` | docstring 称「layer 值域扩展 medium 为代码层枚举（无 DB 约束）」，实际迁移重建了 DB CheckConstraint 纳入 `medium` —— 文档与代码不符 | P2 |
| C17 | `app/services/agent_evaluation.py` L48-57 | `memory_accuracy` 恒 `None`（未实现计算），宣称的六指标实际只有 5 项 | P2 |

---

## 4. 测试问题

### 4.1 缺失的关键测试

1. **依赖方向 / 边界测试**：AGENT-001 验收 7 明确要求「域层零感知…（依赖方向测试）」，仓库中不存在（仅飞书有 boundary 测试）。建议 AST fail-closed 断言 Memory/Reflection/Relationship/Action/World 域模块无 `agent_runtime` import。
2. **Evolution/Evaluation 被周期任务触发的集成测试**：当前所有 v21 测试均**直接函数调用** `compile_personality` / `run_daily_snapshot`，因此完全掩盖了 A1（零调用方）。这是本次测试覆盖最致命的盲区。
3. **profile.stages 与实际执行 steps 一致性测试**：现有 `test_agent001_profiles_gateway.py` L39-45 反而把错误序列固化为断言。
4. **前后台共用决策管线的证明用例**：AGENT-004 验收 1 要求「构造用例可证明」，实际只测了后台侧。
5. **Ledger 跨用户隔离测试**：`test_agent005` L188 断言 `all(e["user_id"] == USER)` 在单用户数据集下恒真，无法发现 A5。
6. **parent-chain 在生产创建路径的强制测试**（`create_hierarchical_goal` 拒绝非法父层）。
7. **low_energy 抑制对 `primary()` / 候选生成的实际影响测试**。
8. **Gateway 熔断下前台 answer 的真实链路测试**：现有仅单测 `resolve_answer_llm`，缺「熔断 + enforced + light profile」经 TestClient 的端到端分支。
9. **迁移 0038~0043 upgrade/downgrade 往返测试**：V2.0.0 有 0035 round-trip 测试先例，本次 6 个迁移无同类覆盖（`0042` downgrade 含 `DELETE FROM development_changes WHERE reason='personality'`，属破坏性回滚，更需用例）。
10. **快照 contextvar 生命周期测试**：阶段异常后 contextvar 是否为空（A6）。

### 4.2 测试质量问题（恒真断言，零信号）

- `tests/v21/test_agent005_evolution.py` L148：`assert personality_state_repository.seed_if_absent(...) is False or True` → 恒真。
- `tests/v21/test_agent003_goal_stack.py` L189：`assert run.data if hasattr(run, "data") else True` → `LoopRunRow` 无 `data` 属性，恒真。
- `tests/v21/test_agent007_integration.py` L213-230：`test_rollback_chain_downgrade_safe` 只按 `run_kind="foreground_chat"` 查询，未断言 flag-off 请求**未新增**台账行（回滚安全性的核心断言缺失）。

---

## 5. 最终建议

**NEED FIX BEFORE ACCEPTANCE**

验收前必须处理：

1. **A1** — 把 Evolution / Evaluation 接入周期任务（否则 V2.1.0 的版本核心闭环在真实系统中不存在）。
2. **A2** — 前台接入统一决策管线，或修订 architecture §5.1/§9.3 与 AGENT-004 验收口径（不可两处都声称）。
3. **A5 / C1** — 修 `ledger` 的 `user_id` 过滤（跨用户泄漏）。
4. **A4** — Goal Rebalance 改走 supply 建议通道，或修订 §6.6 与验收 4。
5. **A3** — profiles 补 `goal_stack` + controller 改为按注册表驱动。

建议随本轮一并处理：A6、C2、C3、C4、C5、C7 与 §4.1 第 1/2/3/9 项测试。

其余 P2（A7/A8、C6、C8-C17）可作为 P2 技术债登记，不阻塞验收。

> 补充说明：AGENT-001~007 的 §12 实施记录**主动登记**了若干偏差（Ledger 非视图、两源缺失、前台审计落 trace、软排序与 P0 识别未接、memory_accuracy 留白），这种自我披露值得肯定。但 §12 未登记 A1（零调度）、A2（前台未接管线）、A5（跨用户泄漏）、A3（注册表漂移）、A4（直写 goals）——即「已登记项之外仍有关键缺口」，这是本轮判 NEED FIX 的直接依据。

---

## 6. 修复记录（Review 后处置）

> 本节记录评审结论的处置结果；§1~§5 保留评审当时的事实描述。

### 6.1 已修复

| # | 问题 | 处置 | 落点 |
|---|---|---|---|
| A1 [P0] | 慢时钟无生产调用方 | 新增 `application/agent_evolution_worker.py`（`run_evolution_tick` + `run_agent_evolution_worker`），lifespan 注册常驻循环：日级指标快照（同窗口已有行则跳过）+ 人格编译 + Goal Rebalance，全部置于 v21 子闸之后 | `agent_evolution_worker.py`、`main.py` |
| A2 [P0] | 前后台未共用决策管线 | 前台 Run 经 `chat_pipeline._run_foreground_decision` 调用同一 `run_pipeline`；回复候选携带既有意图链的 L0 意图（恒 P0 胜出，行为零回归）；审计随 `TURN_INTENTION` 行异步落 `decision_records.candidates` | `chat_pipeline.py`、`decision_pipeline.py`、`observability.py` |
| A3 [P1] | Profile Registry 与执行序列不一致 | `autonomous_tick` 声明补齐 `goal_stack`；controller 改为**按注册表驱动**阶段执行（未注册阶段 fail-closed 抛错）；测试改为断言 `profile.stages == 实际 steps` | `profiles.py`、`controller.py` |
| A4 [P1] | Rebalance 直写 goals / 阈值不可达 | 拆为 `propose_rebalance`（纯读，0 写 goals）+ `apply_rebalance`（supply 审核侧出口）；应用点落在后台 `goal_stack` 阶段。**顺带修复**：原「2× 窗口」阈值被 `retire_overdue` 的 1× 硬超时抢先，建议永不命中 → 改为半程窗口（4 天 / 12 小时） | `evolution.py`、`goal_stack.py` |
| A5 [P1] | Ledger 跨用户泄漏 + 两源缺失 | personality 查询补 `user_id` 过滤；补齐 relationship_events 与 memory supersede 两源；条目补 before/after | `evolution.py` |
| A6 [P1] | 后台 Run 不复位 contextvar | `run_autonomous_cycle` finally 中调用 `reset_run_state`，与前台对称 | `controller.py` |
| C2 [P1] | 证据越多越不漂移 | 限速改为「单窗口至多一次 + 单次幅度 ≤ 周级上限」，不再在提案超上限时整体拒绝 | `evolution.py` |
| C3 [P1] | 六维评分 4/6 为常量、闸门冒充通过 | 六维全部改为真实规则取值 + 归一权重表；四闸补齐（Persona 含意图合法性/FIT/人格轴界内、Relationship 含高张力拒绝、Action 检定显式 `delegated`、预算硬闸） | `decision_pipeline.py` |
| C4 [P1] | `validate_parent_chain` 生产零调用 | 新增 `validate_parent_layer` 落库校验（禁层深倒挂，同层嵌套按 V2.0.0 Preserve 放行），`create_hierarchical_goal` 调用 | `models/goal.py`、`goal_repository.py` |
| C5 [P1] | 低能量抑制为空操作 | 抑制改为真正生效：L1 不再挂活跃层，`primary()` 顺延 L2/L3 | `goal_stack.py` |
| C6 [P2] | `GOAL_ORIGINS` 未校验 | `validate_origin`（允许 `标签:子标签` 复合形式） | `models/goal.py` |
| C7 [P2] | 读路径写库 | 播种移出组装路径 → `ensure_personality_baseline` 由 Run Open 调用；`_load_personality` 纯只读 | `agent_state_assembler.py`、`controller.py` |
| C9 [P2] | 存档版本死赋值 | 改为显式 if/else | `agent_state_archiver.py` |
| C10 [P2] | 动态 `__import__("datetime")` | 改为模块级 `timedelta` 导入 | `goal_stack.py` |
| C11 [P2] | 证据方向字段未使用 | `_match_axis_evidence` 返回方向并参与漂移计算（为双向规则留出通道） | `evolution.py` |
| C12 [P2] | 闸门副作用 / 前台候选走后台档 | `acquire` 增 `account=False`（只问不记账）；闸门能力按候选预算档选择 | `llm_gateway.py`、`decision_pipeline.py` |
| C16 [P2] | 0040/0042 docstring 与代码不符 | 两处 docstring 更正 | `migrations/versions/` |
| — | 文档链尾漂移 | 根/后端 `AGENTS.md` 迁移链尾 0035 → 0043；根 `AGENTS.md` 登记 v2.1.0 文档与 V7.8-014 关闭 | `AGENTS.md` ×2 |
| — | 测试盲区 | 新增 `tests/v21/test_agent008_review_fixes.py`（25 例）：依赖方向 AST 守门、慢时钟接线与幂等、Ledger 多用户隔离、Rebalance 建议/应用分离与供给阶段消费、漂移限速、低能量抑制、六维与闸门、前台共用管线、父层守卫、contextvar 生命周期、**0038~0043 迁移链往返** | `tests/v21/` |

### 6.2 遗留（未修复，需产品/架构裁决）

| # | 问题 | 说明 |
|---|---|---|
| A7 [P2] | Gateway 未完全收口 | `scene_update`/`state_update`/`extractor`/`summary`/`judge`/`reflection` 六个调用点仍未接 Gateway。AGENT-001 验收 3 已按「注册表全覆盖 + 已接线点清单」重新表述。 |
| A8 [P2] | 后台 Snapshot 同步组装 | 仍在 async 上下文同步执行（前台走 `to_thread`）。性能口径待实测裁决。 |
| C8 [P2] | evolution 绕过仓储层 | 仍直接用 `SessionLocal` 读写（沿用实施记录 §12.5 的测试基建约束）。 |
| C13 [P2] | 趋势「连续 N 窗口」未实现 | 仅比较前 1 个窗口，`v21_metric_trend_windows` 未参与判定。 |
| C14 [P2] | run 级 LLM 记账为时间窗口径 | 并发 Run 互相计入；`request_id = run_id` 归因约定未落实。 |
| C15 [P2] | 一次事件两行台账且无父子关联 | `event_driven` + `autonomous_tick` 无 parent 关联字段。 |
| C17 [P2] | `memory_accuracy` 恒 None | 六指标实为 5 项，待事实回查材料接入。 |
| 新 | P0 用户显式指令 / P1 承诺候选源、软排序轻量模型 | 沿 Q5 遗留。 |
| 新 | `test_observability_overhead_within_budget` 间歇失败 | 经 worktree 对照确认为**存量缺陷**（`970cf29` 同样间歇失败）；失败模式是 SQLAlchemy resultproxy `IndexError`（**非**计时抖动），但**非必现**——同一提交多次运行可失败亦可通过。原 §12.4 归因为「xdist 计时抖动」不准确，需单独立项定位。 |

### 6.3 验证

- `pytest tests/v21` → **121 passed**（原 95 + 新增 25 + 拆分 1）
- `pytest tests/v21 tests/v2` → **779 passed / 8 skipped**
- `pytest tests --ignore=tests/e2e` → **2830 passed / 18 skipped / 0 failed**（该轮存量 flaky 用例恰好通过；多次运行中它间歇失败，非本次改动引入）

### 6.4 结论更新

**PASS（可进入验收）** —— 两处 P0（慢时钟接线、前后台共用管线）与跨用户泄漏已闭环，P1 全部处置；§6.2 遗留均为 P2 或已重新表述验收口径，不阻塞验收。
