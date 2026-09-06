# LIFE-006 Task Detail — Goal/Decision Trace 与评估（Observability / Evaluation）

> 上游：[../tasks.md](../tasks.md) LIFE-006 ｜ [../../../architecture/evaluation.md](../../../architecture/evaluation.md) §1 Autonomy/Life Loop 行 ｜ 依赖：LIFE-002（本 Phase 内）

## Task 目标

让「为什么角色主动行动 / 为什么没行动」对任意一次周期可答，并让 autonomy/life-loop 成为可测面：

1. **全链 trace 收口**：trigger→decision→action 全链步骤名注册与关联核对——trigger_registry.trigger_key ↔ loop_runs.trigger_id ↔ decision_records.trigger/action_id 三点连线，任何主动行为可回溯完整链；
2. **评估规则**：Evaluation 新增 life-loop 规则集（周期完整性 / 成本合规 / 触发器生命周期 / 触发溯源 / 风暴与重复）+ IssueCode 扩展；
3. **离线报告**：offline_evaluator 新增 life_loop 统计小节，E-LIFE-01~05 汇总出报告。

只读旁路（Non-Scope）：不写任何业务状态；trace 与规则全部是既有平面的扩展。

## 背景 / 为什么需要

「主动性合理性」是 E-LIFE-05 的核心指标（合理率 ≥0.9、风暴=0），但 v1 的主动行为归因链有三个断点：

- **决策有记录、触发无账**：decision_records 有 PROACTIVE_AUTONOMY 行（trigger 字段只存类型字符串），但 v1 信号无持久化身份——「这次 inactivity 触发对应哪次登记」不可答（LIFE-001 修复后 trigger_key 可溯，本 Task 负责把三点连成可查询的线）；
- **周期无账本**：v1 tick 没有任何结构化运行记录，「这轮跑了什么步骤、每步多久、为什么跳过」无答案（LIFE-002 loop_runs 修复后，本 Task 核对其字段完整性成为验收规则）；
- **评估规则只有 1 条在岗**：`evaluation_rules/autonomy.py` 仅有 `TimingViolationRule`（AUTONOMY_TIMING_VIOLATION，quiet hours 违规）；IssueCode 中的 AUTONOMY_REDUNDANT / AUTONOMY_UNNECESSARY / AUTONOMY_LOW_OUTCOME 三码已定义但无规则实现——主动行为质量实际处于「有码无测」状态。

架构定位（evaluation.md §1）：Autonomy/Life Loop 行的两个指标——主动性合理性（触发有依据、无消息风暴）与成本（周期 LLM ≤ 预算、Idle 零调用）——分别由溯源规则与预算规则量化。Evaluation 铁律沿 V7.5：只产报告不写业务状态。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| LIFE-001 trigger_registry | trigger_key / status / payload / attempt_count | 溯源第一环与孤儿检测数据源（fired/due 滞留、无溯源投递） |
| LIFE-002 loop_runs | steps JSON / llm_call_count / token_total / budget_state / trigger_id | 完整性规则（步骤缺失/aborted 无因）与成本合规规则数据源 |
| LIFE-003 budget_state | loop_runs.budget_state（degraded 轮留痕） | 熔断合规规则：degraded 期间 llm_call_count>0 → 违规 |
| LIFE-004 outbox / trace | `outbox_consume` trace 步骤、outbox 状态 | 死信滞留审计规则数据源 |
| V7.8 trace 体系 | `runtime_traces`（db.py:684-711，kind ∈ turn/proactive/autonomy_tick）+ `TRACE_STEP_NAMES`（trace_collector.py:13-62，48 项）+ `TurnTraceSession` | 步骤名注册收口；autonomy_tick/proactive 两 kind 的步骤完整性核对 |
| V7.5/V2 评估框架 | `EvaluationRule` 基类 + `IssueCode`（models/evaluation.py，现 36 码）+ `evaluation_rules/__init__.py` RULES 汇编 + `penalty_for` 分级 | 新规则模块按同款基类/注册/分级实现（先例：REL-004 relationship 规则） |
| P1 MEM-008 归因模式 | `memory_attribution`（attribution.py:25，扫 runtime_traces 聚合） | 归因查询的组织方式先例（本 Task 的 trigger 溯源查询同款思路） |
| V7.8 decision_records | `DecisionRecordRow`（db.py:516-540）+ `decision_repository` | 溯源第三环（trigger 字段 + action_id 关联既有数据） |
| 各 Phase offline_evaluator 先例 | `_reflection_stats` / `_development_stats` / `_relationship_stats`（offline_evaluator.py:202-234） | `_life_loop_stats` 小节同款模式 |

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/services/trace_collector.py` TRACE_STEP_NAMES | 48 项，缺 life_loop 全家 | 收口核对并补齐：`life_loop_run` / `life_loop_perception` / `life_loop_state_update` / `life_loop_goal_check` / `life_loop_memory_retrieval` / `life_loop_reflection_check` / `life_loop_budget` / `outbox_consume` / `trigger_claim`（LIFE-001~005 实施时已逐个注册的核对收口；缺则本 Task 补） |
| `app/models/evaluation.py` IssueCode | 36 码 | 追加 4 码：`LIFE_LOOP_RUN_INCOMPLETE` / `LIFE_LOOP_BUDGET_OVERRUN` / `TRIGGER_REGISTRY_ORPHAN` / `AUTONOMY_TRIGGER_UNPROVENANCED`（36→40，计数断言第 4 次收口，先例 REL-004 34→36） |
| `app/models/evaluation.py` IssueSeverity | 分级表 | 四码定级：RUN_INCOMPLETE=WARNING、BUDGET_OVERRUN=CRITICAL、TRIGGER_REGISTRY_ORPHAN=WARNING、TRIGGER_UNPROVENANCED=CRITICAL |
| `app/services/evaluation_rules/autonomy.py` | 仅 TimingViolationRule | 追加 4 规则（见设计 2） |
| `app/services/evaluation_rules/__init__.py` RULES | 汇编列表 | 挂载 autonomy 新规则 |
| `app/services/offline_evaluator.py` `_aggregate` L170-199 | 四个 stats 小节 | 追加 `_life_loop_stats`（run 完整率 / 预算合规率 / trigger 终态率 / proactive 溯源率 / 死信数） |
| `tests/unit/test_evaluation_models.py` | IssueCode 计数断言（36） | 36→40 收口 |
| `app/services/evaluation_rules/autonomy.py` 既有 TimingViolationRule | quiet hours 检查 | 零改动（重跑回归） |
| `tests/v2/test_life006_trace_evaluation.py` | — | 新增；`tests/integration/test_observability_*` 回归保持全绿 |

## 设计方案

1. **全链 trace 三点连线（核对收口）**：
   ```text
   trigger_registry.trigger_key (登记/状态/payload)
        ↕ loop_runs.trigger_id + reason（LIFE-002 记账）
        ↕ runtime_traces(kind=autonomy_tick/proactive, steps 含 autonomy_policy/llm)
        ↕ decision_records(trigger, action_id, decision, reason)
        ↕ proactive_actions(action_id → message_id) / outbox_events(action_id)
   ```
   本 Task 交付核对规则而非新链路：数据由 LIFE-001~004 各自落位，本 Task 用测试与评估规则验证「任意 delivered 的 proactive，可沿 trigger_key→loop_run→trace→decision→action 五点走通」（E-LIFE-02/05 的 trace 完整性验收）。发现断点（如 loop_runs.trigger_id 为空但 decision 存在）→ `AUTONOMY_TRIGGER_UNPROVENANCED`。

2. **评估规则集（evaluation_rules/autonomy.py 追加，纯函数只读）**：

   | 规则 | IssueCode | 判定（ctx 输入窗口内） |
   |---|---|---|
   | RunCompletenessRule | LIFE_LOOP_RUN_INCOMPLETE | loop_runs status=done 但 steps 缺关键步骤（autonomy kind 无 decision 步骤）/ aborted 且 reason 为空 / steps JSON 不可解析 |
   | BudgetComplianceRule | LIFE_LOOP_BUDGET_OVERRUN | budget_state.decision=degraded 且 llm_call_count>0 的 run；或日聚合（llm_call_records）超 settings 配额仍存在周期 LLM 调用 |
   | TriggerLifecycleRule | TRIGGER_REGISTRY_ORPHAN | trigger 滞留 due/fired 超时（>2×v2_job_running_timeout）无终态；cancelled 无 reason；attempt_count≥max 仍 pending |
   | TriggerProvenanceRule | AUTONOMY_TRIGGER_UNPROVENANCED | delivered 的 proactive_actions 在窗口内找不到对应 loop_runs.trigger_id 或 decision_records 行（无依据投递=最严重违规） |
   | StormAndRepeatRule | AUTONOMY_REDUNDANT（复用既有码） | 同用户同日 delivered proactive 数 > `autonomy_max_attempts_per_episode × 日 episode 数上界`（实用口径：>3/日告警，可配）；或同 dedupe_key 语义重复投递 |

   Judge 采样（LLM）保留给主动消息内容质量人评/抽评（evaluation.md §3 Judge 面），本 Task 的规则全部确定性计算（Judge 失败 skipped 重跑沿既有）。

3. **offline_evaluator `_life_loop_stats`**：对评估窗口聚合——run 总数/完整率、aborted 率与原因分布、trigger 终态率（done/cancelled 占比）、orphan 数、溯源率、日 LLM 调用 vs 预算比、死信数；并入报告 aggregate（proactive_stats 旁），GATE 判定对齐 E-LIFE-02/03 门槛（完整性 100%、预算合规 100%）。

4. **六问抽查面（文档+测试双落）**：「为什么主动/为什么没动/为什么 Idle/为什么降级/为什么重试/为什么死信」——每问对应一条 Integration 测试断言（数据面：loop_runs.reason / steps[].skip_reason / budget_state / trigger.attempt_count+last_error / outbox.last_error），抽查清单归 regression-checklist 执行步骤（人工面）。

## 数据模型 / 状态变化

- **零 DDL**（tasks.md Data Changes: 无）——全部消费 LIFE-001~004 已建表与既有 trace/decision 平面。
- IssueCode 36→40 + 分级表四行；TRACE_STEP_NAMES 收口（补缺）。
- 离线报告新增 life_loop 小节（报告 JSON 结构扩展，无表）。

## 核心处理流程

```text
在线（零新增运行时行为——trace 步骤由 LIFE-001~005 各自落）:
  周期事件 → 既有 trace/loop_runs/trigger_registry/decision_records 落位
  （本 Task 仅核对收口步骤名与断点测试）

离线:
  offline_evaluator / 规则扫描窗口数据
    → RunCompleteness / BudgetCompliance / TriggerLifecycle /
      TriggerProvenance / StormAndRepeat 五规则（纯函数）
    → Issue 列表 → penalty 分级 → 报告（E-LIFE-01~05 汇总）
  Judge 采样: 主动消息内容质量（既有 evaluation_engine 面）

验收查询（六问）:
  任一 delivered proactive → trigger_key → loop_run → trace → decision → action 五点连线测试
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：溯源面读 memory trace 步骤名（`memory_retrieve_v2` 等）核对「主动消息引用的记忆可溯到 memory 行」——E-LIFE-05 抽样的机器可查部分；不改 Memory 域。
- **Reflection**：无直接交互（REF-006 已有自己的 trace/评估面；life_loop 的 reflection_check 步骤记录消费其 outcome 字符串，只读）。
- **Development**：无直接交互（development_apply 步骤在 Decision 链内已由 P3 记录）。
- **Relationship**：无直接交互（PolicySnapshot 参考已在 decision input_snapshot 落痕）。

## 异常与边界情况

- **窗口内数据缺失**（trigger_registry 行被清理等）：规则按「无法核实」跳过并计入 skipped 统计，不误报（对齐 Judge 失败 skipped 口径）。
- **规则扫描异常**：单规则异常不阻塞其他规则（evaluation_engine 既有逐规则隔离，`run_evaluation` L43-54 try/except 模式）。
- **Judge 失败**：该轮评估记 skipped 重跑（沿 v1/V7.5 既有语义）。
- **风暴阈值误报**：阈值可配（复用 settings 模式），初始保守值 + 观测调参（tasks.md Risk：due 驱动兜底+观测调参同源思路）。
- **可重复执行**：规则纯函数 + 报告覆盖写（离线工具语义），重复跑结果一致（tasks.md Idempotency）。

## 测试要求

- Integration：①trace 完整性——构造完整主动行为链（trigger→run→trace→decision→action）断言五点连线全通；断链注入（删 loop_runs.trigger_id）→ ProvenanceRule 命中；②完整性与预算——缺步骤 run / degraded 有 LLM run → 对应规则命中；③孤儿与风暴——滞留 trigger / 超额投递 → 命中；④offline_evaluator 报告含 life_loop 小节且指标正确。
- Unit：规则纯函数真值表；IssueCode 计数断言 40 收口；severity 分级。
- Regression：无 golden 影响（Flag 无关、只读旁路）；既有 evaluation 测试全绿（TimingViolationRule 重跑 + 各 Phase stats 不回退）。

## 验收标准

- 给定任一主动行为，当查询 trace，那么可回溯完整 trigger→decision→action 链（五点连线测试通过）。
- 给定触发场景集，那么无消息风暴且成本合规（StormAndRepeat/BudgetCompliance 零命中，E-LIFE-05 风暴=0、E-LIFE-03 合规 100%）。
- 给定「为什么没行动」场景（Idle/降级/静默/门槛拦截），那么 loop_runs 与 trace 可回答（六问断言全通）。
- 给定离线评估，那么报告含 life_loop 小节且 E-LIFE-01~05 指标可汇总（Gate 判定可用）。
- 给定重复执行，那么报告结果一致（幂等）。

## Implementation Constraints

- **只读旁路**：不写业务状态（沿 V7.5 铁律）；规则输入全部来自既有表，不新增运行时采集点（trace 步骤落位是 LIFE-001~005 的职责，本 Task 只核对收口）。
- 规则全部确定性计算；LLM 仅 Judge 采样（既有面，本 Task 不新增 Judge 任务类型）。
- IssueCode 追加同步计数断言（36→40，先例收口第 4 次）；severity 定级保守（CRITICAL 仅给「无依据投递」「超预算调用」两个真实性违规）。
- TRACE_STEP_NAMES 收口若发现 LIFE-001~005 漏注册，本 Task 补齐并在 Detail 交付记录中列明（横切注册表职责收口）。
- 风暴阈值与 orphan 超时均为 settings 可调，初始值保守，观测后调参（不改代码语义）。
- 不提前设计 Phase 6：不做 goal consistency 规则（AUT-005）、不做规划质量 Judge（AUT-002 面）。
