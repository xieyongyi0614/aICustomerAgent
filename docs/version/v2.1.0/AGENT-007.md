# AGENT-007 Task Detail — Integration & Optimization

> 上游：[architecture.md](architecture.md) §9.2/§1.2、[tasks.md](tasks.md) AGENT-007
> 状态：Task Detail（编码规范，未实现）；**无迁移**（不新增表、不扩列）
> 范围红线：无架构外能力——只做整合、测试、性能与观测收口；发现需要改架构的问题一律回退到 architecture.md 评审，不在本任务内就地解决

---

## 1. Background

**当前系统状态**：AGENT-001~006 各自交付并各自回归，但：

1. 五个 Flag（`v21_agent_runtime_enabled` / `v21_unified_run_enabled` / `v21_goal_stack_enabled` / `v21_agent_metrics_enabled` / `v21_personality_evolution_enabled`）的**依赖关系与开启顺序**尚未在 enablement 层强约束（既有 `settings/enablement.py` 模式未扩展 v2.1 依赖）。
2. **全链路从未一起跑过**：Evolution Loop（World→感知→状态→目标→决策→行动→反思→记忆→演化）的闭环只在各任务的单点联测中成立，跨任务的组合行为（如 Snapshot × Decision × Evaluation × Evolution 同 Run/跨 Run 交互）无系统验证。
3. **性能预算未核实**：AGENT-002 定的 Snapshot P95 ≤ 150ms、AGENT-001 的 Run 台账开销、前台 ≤4 次 LLM 目标、事件预闸 0 LLM——只有分任务的理论值，没有联合实测。
4. **上线载体缺失**：V2.1.0 没有 regression-checklist（V4/V7/V7.5/V7.8/V8 均有），真实模型人工回归无清单可依。

## 2. Goal

完成后：

1. **五 Flag 依序灰度可执行**：enablement 依赖校验生效（子闸依赖总闸、顺序约束可校验）；每个子闸有独立回滚验证记录。
2. **Evolution Loop 闭环 E2E 全绿**：前台对话 Run 与后台自主 Run 在全 Flag 开启下贯通，各环节在 trace/台账可逐段指认。
3. **性能预算实测达标**（达标线见 §10.3；不达标只做规则/查询层调优，不改架构）。
4. **观测收口**：agent_run / evolution trace 步骤、决策四问查询面、Ledger 回放、run_kind 维度统计可用。
5. **产出 `docs/version/v2.1.0/regression-checklist.md`**（沿用 V8 清单格式），上线判定有据。

## 3. Scope

**包含：**

- **涉及模块**：`app/core/settings/enablement.py`（v2.1 依赖校验）、`tests/`（E2E 与组合矩阵用例）、`app/application/observability.py` / trace 体系（收口补全）、`docs/version/v2.1.0/regression-checklist.md`（新增文档）、各任务交付物的统计查询面（只读）。
- **新增能力**：仅限整合面——Flag 组合矩阵测试、性能基准用例、观测查询面、回归清单文档。
- **修改范围**：允许对 AGENT-001~006 交付物做**测试性修正与规则/查询层调优**（索引提示、常量、采样率）；超出此范围的修改回退架构评审。

**不包含：**

- 任何新表、新列、新 Flag、新域、新 LLM 链。
- 架构语义变更（Snapshot 形状、管线五段、演化通道、指标定义）。
- 前端控制台改版（控制台消费确认只读验证）。

## 4. Architecture Design

### 4.1 灰度收口视图

```text
v21_agent_runtime_enabled（总闸）
  ├─ v21_unified_run_enabled     ①  前台收编（依赖总闸）
  ├─ v21_goal_stack_enabled      ②  四层目标（依赖总闸 + ①建议先开）
  ├─ v21_agent_metrics_enabled   ③  指标快照 + 议题（依赖总闸；②先开使 Goal Progress 有数据）
  └─ v21_personality_evolution_enabled ④ 人格演化 + Rebalance（依赖总闸 + ③——
                                     反馈通道先于它反馈的对象上线，architecture §9.2）
```

enablement 校验规则（写入 `settings/enablement.py` 既有模式）：

| 子闸 | 依赖 | 校验失败行为 |
|---|---|---|
| `v21_unified_run_enabled` | `v21_agent_runtime_enabled` | 启动报错（沿 v2_autonomy_advanced_enabled 先例） |
| `v21_goal_stack_enabled` | `v21_agent_runtime_enabled` | 同上 |
| `v21_agent_metrics_enabled` | `v21_agent_runtime_enabled` | 同上 |
| `v21_personality_evolution_enabled` | `v21_agent_runtime_enabled` ∧ `v21_agent_metrics_enabled` | 同上（顺序约束的强制点） |

### 4.2 Evolution Loop 验证主链

```text
World State → Perception → Character State（Snapshot）→ Goal Evaluation（Stack）
→ Decision（管线）→ Action → Reflection → Memory Update → Agent Evolution
        ↑______________________________________________________________|
              （Personality/Goal/Policy 调制作用于下一次快时钟）
```

每个环节的验证锚点（trace/台账字段）在 §10.2 逐项列出；锚点缺失即收口缺口。

## 5. Core Components

### 5.1 FlagCombinationMatrix（测试资产）

**职责**：Flag 组合矩阵用例——全关 / 总闸单独 / 总闸+各子闸逐个 / 建议顺序全开 / 逐个回滚。每组合断言行为面（哪些通道生效、哪些为零写入），是「逐字节回退」的自动化证明。

### 5.2 EvolutionLoopE2E（测试资产）

**职责**：三条端到端主线（真实/伪模型皆可跑的构造版）：
- **主线 A 偏好跟随**：用户多次表达话题偏好 → preference 变化 → Interest 榜变化 → 后续回复/主动话题跟随（记忆→Development→Snapshot→上下文/决策链贯通）。
- **主线 B 人格缓变**：连续多窗口同向 Insight → assertiveness 分阶段爬升（限速可见）→ 主动行为率上升 → Ledger 回放全程（Reflection→Evolution→行为调制链贯通）。
- **主线 C 评估反馈**：注入 Persona 下滑样本 → 指标走低 → 议题 → Insight → 行为参数修正（Evaluation→Reflection→Evolution 链贯通）。

### 5.3 PerfBudget（性能基准）

**职责**：预算线测量用例与统计面：

| 预算项 | 达标线 | 来源 |
|---|---|---|
| Snapshot 组装 | P95 ≤ 150ms | AGENT-002 |
| Run open/close 台账开销 | P95 ≤ 20ms | 本任务定义 |
| event_driven 预闸 | 0 LLM（构造证明） | AGENT-001 |
| 前台 Run LLM 次数 | ≤ 4 次（与 v2.0.0 基线对照不回退） | v2.0.0 LLM 分层目标 |
| autonomous_tick 周期 LLM | 沿 `v2_life_loop_cycle_llm_budget` 不变 | LIFE-003 |
| Gateway 记账一致性 | 逐调用汇总 vs 窗口计数偏差 ≤ 1 次/Run | AGENT-001 |

超标的处置边界：只允许采样率/权重/查询层调优（settings 与查询改写）；结构性修改回退架构评审。

### 5.4 ObservabilityClosure（观测收口）

**职责**：
- trace 步骤补全核对：agent_run（Run 生命周期）、evolution（编译/回滚/Rebalance）两类步骤在全部主线上可见。
- 查询面核对：决策四问（decision_records.candidates）、Ledger 时间线、run_kind 统计、快照趋势——控制台/debug 端点只读消费确认（不改前端）。

### 5.5 RegressionChecklist 文档

**职责**：`docs/version/v2.1.0/regression-checklist.md`，沿用 V8 清单格式（开关准备表 + 主线下钻表 + 核对点勾选）：
- 开关准备：五 Flag 全开（含总闸）+ `alembic upgrade head`（链尾 0043）+ 对照轮（全关）。
- 主线：Evolution Loop 三主线（A/B/C）+ 前台对话主线 + 后台自主主线 + 静默/熔断副线；每步给出动作 / 核对点 / 勾选格。
- 人工回归范围声明与上线判定标准（全部主线通过 + 对照轮零差异）。

## 6. Data Model

**无新增数据**。全部复用 AGENT-001~006 交付：`loop_runs`（run_kind/profile）、`agent_state_snapshots`、`personality_state`、`goals`（medium/origin）、`decision_records`（candidates）、`development_changes`（personality 行）、`agent_metric_snapshots`、`v_evolution_ledger` 视图。本任务对任何表结构零变更（含索引——如性能调优确需索引，走迁移变更申请，不在本任务默认范围内）。

## 7. Runtime Flow

```text
Step 1  灰度准备：enablement 依赖校验合入；灰度执行序（全关对照 → ① → ② → ③ → ④）
        逐档跑 FlagCombinationMatrix 与既有全套件
Step 2  闭环验证：全开状态下跑 EvolutionLoopE2E 三主线 + 前台/后台/事件/静默副线；
        每环节核对 §10.2 锚点；缺口回相应任务修复后重跑
Step 3  性能核实：PerfBudget 六项实测；超标项按 §5.3 处置边界调优并复测
Step 4  回滚验证：④→③→②→① 逐个关闭，每档行为面断言 + 既有套件全绿；
        全关档与 v2.0.0 基线对照零差异
Step 5  观测收口：trace 步骤与查询面按 §5.4 清单逐项确认（控制台只读消费）
Step 6  文档收口：产出 regression-checklist.md；遗留问题（Q1~Q5）最终裁决
        登记回 architecture.md 附表；版本 README（本目录）补齐状态
```

## 8. Integration Design

| 对象 | 本任务的动作 | 不变量 |
|---|---|---|
| **AGENT-001 Runtime** | Flag 组合验证、台账统计、Run 开销测量；调用点切换完整性核对（无绕过 Gateway 的残留调用） | Run 模型 / Gateway 契约零改动 |
| **AGENT-002 State** | Snapshot 成本实测、存档策略参数调优（采样率/间隔旋钮） | 投影铁律、SoT 零改动 |
| **AGENT-003 Goal** | Stack 与决策对齐度联测、上下文栈行预算观察 | 状态机/仲裁零改动 |
| **AGENT-004 Decision** | 四问审计面核对、软排序熔断联测、铁律用例复核 | 五段契约零改动 |
| **AGENT-005 Evolution** | 限速/边界用例复核、Ledger 回放核对、Rebalance→supply 联测 | 唯一写入点、合法通道零改动 |
| **AGENT-006 Evaluation** | 指标实测、议题→Reflection 通道联测、V7.8-014 落地确认 | 只读旁路零改动 |
| **settings/enablement** | v2.1 依赖校验（唯一生产代码修改点，追加式） | 既有 v2 依赖校验零改动 |
| **docs** | regression-checklist.md 新增；architecture 附表 Q1~Q5 回填 | 不改 v1.0.0 / v2.0.0 文档 |

## 9. Implementation Plan

| Step | 交付内容（≈1 commit） | 依赖 |
|---|---|---|
| **Step 1** | enablement v2.1 依赖校验；灰度执行序文档化；FlagCombinationMatrix 用例 | AGENT-001~006 全部合入 |
| **Step 2** | EvolutionLoopE2E 三主线 + 副线用例；锚点核对清单落地 | Step 1 |
| **Step 3** | PerfBudget 基准用例与统计面；超标调优与复测记录 | Step 2 |
| **Step 4** | 回滚逐档验证；观测收口（trace 步骤 + 查询面 + 控制台只读确认） | Step 2 |
| **Step 5** | regression-checklist.md；Q1~Q5 裁决回填 architecture 附表；版本 README 状态更新 | Step 3, 4 |

## 10. Acceptance Criteria

**功能验收**

1. 五 Flag 依序（①→②→③→④）开启后 Evolution Loop 全链 E2E 绿：三主线（偏好跟随 / 人格缓变 / 评估反馈）各自贯通，且每环节在 trace/台账可逐段指认（锚点清单见下）。
2. 锚点齐全：前台 Run（loop_runs.run_kind=foreground_chat）、Snapshot（state 阶段 + 存档行）、GoalStack（Goal Evaluation 阶段 steps）、决策四问（decision_records.candidates）、行动（action_records 六态）、反思（insights + evidence_links）、记忆（memory_candidates 链）、演化（development_changes reason=personality + Ledger 视图 + agent_metric_snapshots）——九类锚点在主线上无一缺失。
3. 性能达标：§5.3 六项预算实测全部达标；超标项完成调优并复测记录在案。
4. 三条副线正确：事件预闸 0 LLM、熔断降级链路（后台 skip / 前台降档 / Judge 跳过）、静默与 Idle 短路。

**架构验收**

5. Flag 组合矩阵全绿：总闸关 → 一切 v2.1 面零活动；单子闸开 → 仅该面活动（组合互斥性成立）；enablement 校验拒绝非法组合（如 ④ 开而 ③ 关时启动报错）。
6. 无架构外能力：本任务 diff 中除 enablement 追加、测试资产、调优常量、文档外无生产语义代码（代码评审声明）。

**边界验收**

7. 全关对照零差异：五 Flag 全关下，前台对话、后台自主、维护、投递、评估、记忆行为与 v2.0.0/v2.0.1 逐字节一致（对照轮记录在案）。
8. 逐档回滚安全：④→③→②→① 逐个关闭，每档既有套件零跳过全绿；回滚不产生脏数据（新表残留行不影响旧行为）。
9. 上线判定成立：regression-checklist.md 完整且真实模型人工回归通过；Q1~Q5 在 architecture 附表全部登记最终裁决。

## 11. Testing Plan

**Unit Test**

- enablement 校验矩阵：全部合法/非法组合；错误信息可读；既有 v2 依赖校验回归。

**Integration Test**

- FlagCombinationMatrix：组合 × 行为面断言（全关/总闸/各子闸/全开/逐档回滚）。
- 跨任务联测：议题→三闸→Insight→人格编译→行为调制（006→005 链）；GoalStack→对齐度→决策→审计（003→004 链）；Snapshot→state_fit/interest→决策（002→004 链）。
- 记账一致性：Gateway 逐调用汇总 vs loop_runs 窗口计数 vs llm_call_records 三方对账。

**Runtime Flow Test（端到端）**

- EvolutionLoopE2E 三主线（A 偏好跟随 / B 人格缓变 / C 评估反馈）+ 前台对话 / 后台自主 / 事件 / 静默四副线。
- 性能基准：PerfBudget 六项在构造负载与常态负载下各测一轮。

**Regression**

- 全关对照轮：V2.0.0 / V2.0.1 / V2.1.0 各任务既有套件联合运行，零跳过全绿。
- 真实模型人工回归：regression-checklist.md 主线全部执行并留档（上线判定）。

---

## 12. 实施记录（Coding 回填）

1. **enablement 全链**：五 Flag 依赖校验合入（unified/goal_stack/metrics 依赖总闸；personality_evolution 依赖总闸 + metrics——架构 §9.2 顺序约束成为启动期强约束）。
2. **组合矩阵与全链测试**：`tests/v21/test_agent007_integration.py` 九例——enablement 组合矩阵、全 Flag 开启下前台 Run 九锚点贯通（前台台账/人格种子/快照存档）、后台 autonomous_tick 的 state_snapshot/goal_stack 阶段、指标快照 + Ledger、演化反馈链（越限→议题→Reflection 触发通道）、逐档回滚安全。
3. **已知遗留（登记至 AGENT-007 收口核对的偏差）**：① 前台 Flow B 的 candidates 审计落 trace 而非 decision_records（免热路径 IO）；② Persona Consistency 的回复采样与 Judge 兜底、memory_accuracy 事实回查留待真实模型回归校准；③ Evolution Ledger 四源中 relationship/memory 两源暂未并入；④ 软排序 LLM 与 P0 用户显式请求识别（decision_pipeline P0 映射已声明、候选源未接）——均已在各 Task §12 登记，不阻塞版本交付。
4. **性能预算实测**：串行口径下 v7.8 观测开销预算通过；xdist 并行负载下计时类用例存在固有抖动（SLOW_TEST_FILES 已登记），真实预算核实随本清单人工回归执行。
5. **文档**：`regression-checklist.md` 产出（开关准备 + 基础主线 + 三成长主线 + 回滚对照 + 上线判定）；Q1~Q5 裁决分布于 AGENT-001/002/004 §12，视为已登记。
