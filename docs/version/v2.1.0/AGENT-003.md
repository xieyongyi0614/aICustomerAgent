# AGENT-003 Task Detail — Goal & Motivation System

> 上游：[architecture.md](architecture.md) §4/§8.3、[tasks.md](tasks.md) AGENT-003
> 状态：Task Detail（编码规范，未实现）；迁移 **0040**（goals 扩列）
> 范围红线：既有两层语义与 0032 仲裁零改动；L0 不落表；Evolution 建议通道本任务只留接口不接写入方（AGENT-005）

---

## 1. Background

**当前系统状态**：V2.0.0 P6 已交付目标层级雏形——

- `goals` 表已有 `layer`（short_term/long_term）、`domain`（personal/relationship/world）、`parent_goal_id`、`failure_reason`、`arbitration_state` 列；六语义状态机（`GOAL_TRANSITIONS`）与 v1 行兼容（`layer IS NULL` 走旧出口）。
- 供给：`goal_planning.materialize`（纯规则 0 LLM）从 World 事件 / 显著度记忆等来源产候选 → 层级 goal → planning job 入队（LLM 规划在后台 job 内）。
- 推进：`goal_arbitration`（复活/冲突/放弃）→ `goal_observation`（观察调整）→ `goal_execution`（Sub-Goal 经 V9 闸门执行尝试），由 life_loop `goal_advance` 步骤驱动。
- 前台：`chat_pipeline._select_goal → goal_service.select(...)` 按张力/情绪/场景/深夜/development_weights 选目标；`context_builder` 装配目标段时**只注入 `layer IS NULL` 的目标**——层级目标至今不进上下文、不进前台选择。

**问题（「为什么做这个行为」答不上来）**：
1. 层级只有两层，缺 Medium（天～周）层，Long Term 与 Short 之间断层；「当前意图」没有运行时表达。
2. 层级目标不进上下文、不进前台目标选择——目标存在但基本不驱动对话行为。
3. 目标对行为的权重影响没有结构化出口（决策侧无法消费「目标对齐度」）。
4. 目标来源不可解释（definition/policy/scene 三值无法区分 Insight/承诺/用户请求/演化建议）。

## 2. Goal

完成后：

1. Goal Stack 四层运转：L3 Long（周～月）/ L2 Medium（天～周）/ L1 Short（小时～天）/ L0 Current Intent（轮级运行时）；既有两层语义零变化。
2. 激活规则生效：每层至多一个活跃主目标，按时间窗 + 前置条件 + 状态许可选出。
3. 目标→行为四通道全通：上下文栈式注入、决策对齐度接口（AGENT-004 消费）、L1 行动候选编译、对话风格调制。
4. 目标来源可解释：`origin` 列区分 insight/commitment/user/world/evolution。
5. L2/L1 供给扩展与超时退役规则生效；Evolution 建议入口预留。

## 3. Scope

**包含：**

- **涉及模块**：`app/models/goal.py`（枚举与校验扩展）、`app/services/goal_service.py`（激活/主目标裁决）、`app/services/goal_planning.py`（供给来源扩展）、`app/services/goal_alignment.py`（新增：对齐度评分）、`app/services/context_builder.py`（栈式注入）、`app/application/chat_pipeline.py`（`_select_goal` 层级扩展）、`app/repositories/goal_repository.py`、Snapshot 扩展（`recent_intent` 字段，追加式）。
- **新增能力**：`medium` 层；L0 运行时意图（Intention 值对象 + Snapshot.recent_intent，不落表）；激活规则引擎（纯规则）；对齐度评分接口；栈式上下文段；来源 origin 列。
- **修改范围**：`goals` 表扩列（layer 枚举值域 + origin）；`goal_service.select` 支持层级目标（保留 v1 路径）；上下文目标段从「仅 layer NULL」扩展为「v1 目标 + 层级栈」。

**不包含：**

- 状态机六语义、`GOAL_TRANSITIONS`、v1 行（layer NULL）行为路径、0032 仲裁语义的任何修改。
- Evolution Rebalance 建议的生成与写入（AGENT-005；本任务 supply 审核通道接受 `origin=evolution` 候选但不激活）。
- LLM 规划链本体（planning job 内既有链不动）。
- 决策管线实现（AGENT-004）。

## 4. Architecture Design

### 4.1 Goal Stack

```text
L3 Long Term（周~月）   来源: Persona 长期设定(definition) / Insight 编译 / 关系里程碑沉淀 / Evolution 建议(预留)
        ↓ 分解
L2 Medium（天~周）      来源: L3 分解(planning) / commitment 记忆 / 用户显式请求
        ↓ 分解
L1 Short（小时~天）     来源: L2 分解 / commitment / World 事件机会(既有 supply)
        ↓ 编译
L0 Current Intent（轮级，不落表）  来源: Decision Pipeline 当前轮 Intention + Snapshot.recent_intent
```

层与既有枚举的映射：L3 = `long_term`（沿用）、L1 = `short_term`（沿用）、L2 = `medium`（新增枚举值）、L0 = 运行时值对象（无表行）。`GOAL_TIER`（scene=0 < user_care=1 < relationship=2 < conversation=3）继续承担层内优先级权重，与 P0~P4 决策优先级（AGENT-004）正交。

### 4.2 四条影响通道

```text
                    ┌─ 通道① 上下文注入：context_builder 栈式段
活跃主目标集 ──────┼─ 通道② 对齐度评分：goal_alignment.score(candidate, stack) → AGENT-004
（每层 ≤1）        ├─ 通道③ 行动候选：L1/L2 Sub-Goal 经 goal_execution（既有 V9 闸门）
                    └─ 通道④ 风格调制：goal domain → development_weights（既有 select 入参）扩展
```

### 4.3 Run 内位置

Goal Evaluation 阶段（AGENT-001 插槽）= 既有 goal_check + goal_supply + goal_advance 步骤基础上，新增「Stack 激活裁决」纯规则步骤：按层选出主目标、产出驱动分数集，写入 RunContext 供决策插槽消费；前台在 `_select_goal` 内消费同一 Stack 结果。

## 5. Core Components

### 5.1 GoalStackEvaluator

**职责**：
- 每 Run 执行（Goal Evaluation 阶段内，纯规则 0 LLM）：读取 active 目标按层分组 → 激活裁决（时间窗：`expires_at_turn`/horizon；前置条件：父层主目标存在且非 suspended；状态许可：energy/scene 门限，规则常量）→ 每层选出主目标（优先级 > GOAL_TIER > 创建时间）→ 产出 `GoalStack` 值对象（L3/L2/L1 主目标 + 各层驱动分 + 激活/抑制原因）。
- 抑制规则沿用 `goal_service.select` 的 suppressed 语义（深夜、scene pending 等既有判据扩展到层级目标）。

### 5.2 GoalAlignmentScorer（新增 `services/goal_alignment.py`）

**职责**：
- `score(candidate, goal_stack) -> float`：候选行动与活跃栈的对齐度（规则：候选能力域/类型 × 目标 domain/type 映射 + L1 计划步骤直接命中加权）。
- 纯函数、可单测；接口契约（输入/输出/分值区间）在本任务冻结，AGENT-004 按契约消费；本任务内以「空栈 → 恒 0 分」实现兜底。
- 分值写入决策审计由 AGENT-004 落 `decision_records`；本任务在 trace 中先行观测。

### 5.3 ContextStackInjector（context_builder 扩展）

**职责**：
- 目标段从「仅 layer NULL」扩展为「v1 目标行 + 层级栈三行」（L3 意图一句 / L2 当前一句 / L1 本轮一句；层无主目标则跳过该行）。
- 追加段不改变既有分段顺序与预算分配；预算不足时先裁剪 L3 行（保留 L1）。

### 5.4 Supply 来源扩展（goal_planning）

**职责**：
- 候选来源在既有基础上补齐 L2 级：commitment 记忆（Memory `commitment` 类型 active 行）、用户显式请求（近期对话中用户请求类事实，规则识别，0 LLM）；L3 级：Insight 编译候选（高置信 Insight 的 goal 类 ModulationProposal，既有通道）。
- 每候选携带 `origin`（insight/commitment/user/world/evolution）落列。
- `origin=evolution` 候选本任务只允许进入审核队列并留痕（无人写入它——AGENT-005 接入），审核规则与既有 supply 一致。

### 5.5 超时退役

**职责**：L2/L1 增加时间窗退役规则（`v21_goal_l*_timeout_*` settings）：超窗未推进 → `expired`（走既有状态机出口）；退役沉淀失败原因（failure_reason），可作反思证据（既有通道）。

## 6. Data Model

迁移 **0040**（仅 goals 扩列，可空跑回滚）：

### Entity: GoalRow（`goals`，既有表扩列）

| 字段 | 类型 | 说明 |
|---|---|---|
| `layer` | String | 枚举值域扩展：short_term / **medium**（新增） / long_term；NULL 兼容不变 |
| `origin` | String, nullable | 新增：insight / commitment / user / world / evolution / NULL（v1 行语义） |

### Entity: GoalStack / CurrentIntent（运行时值对象，不落表）

- `GoalStack`：L3/L2/L1 主目标引用 + 驱动分 + 激活原因；存 RunContext，随 Run 生命周期。
- `recent_intent`：Snapshot 追加字段（AGENT-002 值对象模型追加式扩展，不迁移），记录上一轮 Intention 摘要（类型 + 描述），供 L0 连续性。

### Relation

- `parent_goal_id` 既有列承载 L3→L2→L1 分解链；L2 的父必须是 L3、L1 的父必须是 L2 或 L3（校验规则，Detail 定非法组合处理）。
- 不新增表、不新增索引（`layer+status` 既有查询路径够用，Detail 实施时如 EXPLAIN 需要再申请）。

## 7. Runtime Flow

```text
Step 1  Run 的 Goal Evaluation 阶段：既有 goal_check/goal_supply/goal_advance 照旧执行
Step 2  Stack 激活裁决（新增纯规则步骤）：按层分组 → 激活条件过滤 →
        每层主目标选出 → GoalStack 写入 RunContext；抑制/未激活原因留痕
Step 3  通道①：context_builder 依 GoalStack 产出栈式三行（前台）；
        proactive 链经既有 recent_context 追加段获得同源信息（后台）
Step 4  通道②：decision 插槽调用 goal_alignment.score(...)（AGENT-004 接线前
        以 trace 观测运行，不参与选择）
Step 5  通道③：L1/L2 主目标的 Sub-Goal 执行尝试沿用 goal_advance（既有）
Step 6  通道④：goal_service.select 的 development_weights 扩展 goal domain 维度
        （层级行并入权重计算）
Step 7  L0：前台轮内 Intention 照旧产生；结束后 Snapshot.recent_intent 更新
Step 8  台账：Goal Evaluation 阶段 steps 记录 Stack 摘要（各层主目标 id + 驱动分）
```

## 8. Integration Design

| 系统 | 连接方式 | 不变量 |
|---|---|---|
| **Goal 域本体** | 枚举/校验/激活/退役扩展 | 六状态机、v1 行路径、0032 仲裁、`GOAL_TIER` 语义零改动 |
| **Memory** | commitment 类型读取（既有类型，不新增类型） | 7 类封顶、Memory 域零写 |
| **Reflection** | 高置信 Insight → L3 候选（经既有 ModulationProposal 通道） | Insight 生命周期、三闸零改动 |
| **Development** | goal 类调制目标（`ModulationTarget=goal` 既有）扩展 domain 维度 | Insight 唯一输入、审计零改动 |
| **AGENT-002 Snapshot** | GoalStack 主目标进 Current Focus（既有字段读取）；Snapshot 追加 recent_intent | Snapshot 投影铁律不变 |
| **AGENT-004 Decision** | 冻结 `goal_alignment.score` 接口契约；不实现决策消费 | 候选/选择逻辑零改动 |
| **AGENT-005 Evolution** | 预留 `origin=evolution` 候选进审核队列的入口与留痕 | 本任务无写入方、goals 无直写 |
| **chat_pipeline** | `_select_goal` 层级扩展（flag 内）；v1 选择路径保留 | 降级路径（动机层降级）保持 |

## 9. Implementation Plan

| Step | 交付内容（≈1 commit） | Flag 依赖 |
|---|---|---|
| **Step 1** | 迁移 0040（layer 值域 + origin 列）；models 枚举/校验扩展（medium、非法父子组合校验）；`v21_goal_stack_enabled` settings | 总闸 + goal_stack |
| **Step 2** | GoalStackEvaluator（激活裁决 + 主目标选举 + 抑制）接入 Run Goal Evaluation 阶段；GoalStack/recent_intent 值对象；超时退役规则 | 总闸 + goal_stack |
| **Step 3** | 通道①③④：context_builder 栈式注入；`_select_goal` 层级扩展；development_weights domain 维度；对齐度评分接口（trace 观测） | 总闸 + goal_stack |
| **Step 4** | 供给扩展（commitment/user/insight 来源 + origin 落列 + evolution 预留入口）；观测与回归收口 | 总闸 + goal_stack |

## 10. Acceptance Criteria

**功能验收**

1. 四层目标可创建、激活、推进、退役；同一时刻每层至多一个活跃主目标（并发到达时裁决可复现）；层无合格目标时该层空缺、上层不受阻。
2. 激活抑制正确：深夜/scene pending/状态门限命中时 L1/L0 被抑制，原因留痕。
3. 上下文出现栈式三行且层缺省时跳过；前台 `_select_goal` 能选中层级目标并给出选择理由。
4. `goal_alignment.score` 对构造候选产出可解释分值（命中 L1 计划步骤 > domain 映射 > 无关=0），接口契约与 AGENT-004 消费一致；空栈恒 0。
5. 供给来源可解释：每条层级 goal 的 `origin` 正确（commitment 记忆触发 → commitment；Insight 编译 → insight）；`origin=evolution` 候选只入审核队列且无生产写入方。
6. L2/L1 超窗退役走既有状态机出口（expired），failure_reason 留痕。

**架构验收**

7. 「为什么做这个行为」可回答：任一 L1 驱动行为可沿 L1→L2→L3 父链指认动机，且每层来源 origin 可查。
8. 无第二套目标路径：前台与后台消费同一 GoalStack 结果（同一 evaluator 代码路径）。

**边界验收**

9. 既有两层行为零回归：v1 行（layer NULL）目标的选择/推进/过期与 v2.0.0 逐字节一致；`GOAL_TIER`/状态机/仲裁回归全绿。
10. `v21_goal_stack_enabled=False`：上下文无栈式段、`_select_goal` 走 v1 路径、无 medium 层写入，行为与 v2.0.0 一致。
11. 迁移 0040 可空跑回滚；存量行零语义变更。

## 11. Testing Plan

**Unit Test**

- GoalStackEvaluator：层分组、激活条件矩阵（时间窗/前置/状态许可）、主目标选举优先级、抑制判据、空层处理。
- GoalAlignmentScorer：分值区间、映射表命中、L1 步骤直接命中、空栈恒 0、纯函数性（无 IO）。
- 退役：超窗边界（恰好到期/差一 turn）、failure_reason 写入。
- 供给：origin 标注正确性；evolution 候选只入队列；描述长度/优先级约束沿既有校验。

**Integration Test**

- 父子链一致性：L2 无 L3 父时创建被拒；L3 完成后 L2 孤儿处理（既有仲裁语义回归）。
- 上下文装配：Stack 变化 → 栈式三行变化；预算挤压时 L3 先裁。
- Snapshot 联动：recent_intent 在轮后更新；Current Focus 的 L1 引用与 Stack 主目标一致。

**Runtime Flow Test（端到端）**

- 动机链 E2E：commitment 记忆 → L2 目标供给 → L1 分解 → goal_advance 执行尝试 → 上下文注入 → 回复内容体现目标。
- 目标完成 E2E：L1 完成判据（criterion）达成 → 状态迁移 → 下层聚合推进。

**Regression**

- `v21_goal_stack_enabled=False`：既有 goal 全套件（含 V2.0.0 P6 AUT-001~005 测试）零跳过全绿。
- v1 行目标（layer NULL）全路径行为对照一致。
