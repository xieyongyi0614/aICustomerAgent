# v2.0.0 Domain Boundaries

> 裁决标准：一个「域」必须同时拥有**独立的生命周期、独立的真相源、可被独立测试的不变量**。否则它是 Entity / Value Object / State / Service / Projection / Runtime Context。

## 1. Domain 分类总表

| 名称 | 分类 | 职责 | 数据（真相源） | 生命周期 | 依赖（只允许向下） | 被谁调用 | 不能做什么 |
|---|---|---|---|---|---|---|---|
| **Persona** | 配置域（非运行时） | 角色静态资产（identity/personality/behavior_instructions/modes/stages） | `character/asuna/` 文件 | 不变 | 无 | Context、所有域读取 | 不可被运行时写回 |
| **State** | Domain | 短期内在状态：mood/energy/intensity/inner_state/current_topic；**Emotion 是其内部值对象** | `character_state` 表 | 分钟级，带衰减 | Persona（读） | chat_pipeline、Life Loop、Context | 不持有长期事实；不可直接写 Memory |
| **Memory** | Domain | 长期记忆：Candidate 摄取、评估、存储、检索、排序、强化、合并、取代、衰减、遗忘 | `memories` + `memory_candidates`（业务表为 SoT） | 天～永久 | State（读情绪信号）、Experience 投影（读） | Context、Reflection、Relationship（读叙事事实）、Life Loop | **不可读 Relationship 数值**（防循环依赖）；不可直接改行为 |
| **Reflection** | Domain | 从 Evidence 产出 Insight；管理 Insight 生命周期 | `insights` + `reflection_runs` | 周期任务产出 | Memory（读） | Development、Goal（读）、Context（高置信 Insight 可入选） | 无 Evidence 不出 Insight；**禁止直写 State/Relationship 数值** |
| **Development** | Domain | 角色长期演化：Belief / Preference / Pattern 及其对行为的调制 | `development_state` + `development_changes` | 慢变量，全审计 | Reflection（读 Insight）、Persona（读基准） | BehaviorEngine、goal_service、Context | 不产生 Insight；不持有事件；变更必须可重放 |
| **Relationship** | Domain | 关系数值引擎 + 事件账本 + 里程碑 + 冲突 + 共同经历投影 | `relationship_state/events/milestones/conflicts/snapshots`（数值 SoT）；叙事事实 SoT 在 Memory | 慢变量 | State（读）、Memory（读叙事）、Development（读 Pattern） | chat_pipeline、Autonomy 闸门、Context | 数值数学（D1/D2/D3/D5）零改动；不写 Memory |
| **Goal** | Domain | 目标层级、优先级、生命周期 | `goals` + `goal_plans` | 天～周 | Development（读）、Relationship（读）、Memory（读） | chat_pipeline、Life Loop、Planning | 不写 Scene/World；不被 Memory 反向写 |
| **Decision** | Domain（轻） | 单轮决策：产出 Intention；**Intention 降级为值对象** | `decision_records`（审计） | 轮级 | Goal（读）、State（读）、Persona（读） | chat_pipeline、Life Loop | 不直接执行；不持有长期状态 |
| **Action** | Domain | 行动检定/规划/执行/审计（v9 体系全量复用） | `action_records` + capabilities | 事件级 | Decision（读）、World（写结果）、Memory（写结果回执） | Life Loop、chat_pipeline | 不改 Persona；失败不静默（六态审计） |
| **World** | Domain | 外部世界：时间/地点/物品/环境/事件 | `worlds/world_entities/world_events/world_snapshots` | 持续 | 无（零依赖 Character 域，沿 V8 铁律） | Context（切片）、Action（结果写入）、Life Loop | 不写回 Character 任何域 |
| **Autonomy / Life Loop** | Service 编排域 | 调度一切周期行为；持有 Trigger Registry 与 Budget | `trigger_registry/loop_runs/outbox_events` | 持续 | 调用所有域（编排） | main lifespan | **不持有业务语义**——只决定「何时跑、跑什么、跑多少」 |

## 2. 明确不是 Domain 的东西

| 概念 | 分类 | 说明 |
|---|---|---|
| Emotion | Value Object（State 域内） | 8 值 + intensity + 衰减；独立成域只会复刻 v1 的 state_engine |
| Intention | Value Object（Decision 域输出） | 13 值枚举 + fit 映射；v1 已证明它无独立生命周期 |
| Evidence / Insight | Value Object / Reflection 域实体 | Evidence 是引用（memory_id + span）；Insight 是 Reflection 域的行 |
| MemoryCandidate | Entity（Memory 域内） | 未转正的记忆，不是独立域 |
| Experience | **Projection（读取视图）** | Conversation + ActionRecord + WorldEvent + RelationshipEvent 的统一摄取接口；v2 不建 experience 表 |
| Working Memory | Runtime Context | 每轮重建：最近 N 条 + 本轮结构化信号 + 活跃 Scene/Action；**不落长期表** |
| Context | Runtime Context | Context Architect 的装配结果，轮级，无持久化 |
| Relationship Snapshot / Metrics | Projection | 可重算，非真相源（沿 V8.5「账本即真相」） |
| Shared Experience | Projection（Relationship 域） | 对 Memory `relationship_fact` + relationship_events 的 SQL 视图 |
| Evaluation | 横切质量平面 | 只读旁路，不写业务状态（沿 V7.5 铁律） |

## 3. 依赖矩阵（✓ 允许 / ✗ 禁止）

```text
            Persona State Memory Reflection Dev Rel Goal Decision Action World
Persona       -      ✗      ✗       ✗        ✗   ✗   ✗      ✗      ✗     ✗
State         ✓      -      ✗       ✗        ✗   ✗   ✗      ✗      ✗     ✗
Memory        ✓      ✓      -       ✗        ✗   ✗   ✗      ✗      ✗     ✗
Reflection    ✓      ✗      ✓       -        ✗   ✗   ✗      ✗      ✗     ✗
Development   ✓      ✗      ✓*      ✓        -   ✗   ✗      ✗      ✗     ✗
Relationship  ✓      ✓      ✓       ✗        ✓   -   ✗      ✗      ✗     ✗
Goal          ✓      ✓      ✓       ✓        ✓   ✓   -      ✗      ✗     ✗
Decision      ✓      ✓      ✗       ✗        ✗   ✓   -      ✗      ✗     ✗
Action        ✓      ✗      ✓       ✗        ✗   ✗   ✓      ✓      -     ✓
World         ✗      ✗      ✗       ✗        ✗   ✗   ✗      ✗      ✓     -
LifeLoop      调用一切，但不被业务域调用
```
\* Development 读 Memory 仅限「经 Reflection 验证的 Insight」，禁止直读原始记忆（防绕过反思自嗨）。

**三条关键单向约束（Self Review 项 5 的答案）**：
1. **Relationship → Memory 单向**：关系域读记忆叙事，Memory 永不读关系数值。消除 v1 的双真相源循环。
2. **Development ← Reflection 单向**：行为变化必须经 Insight 编译，Memory 不能直接调制行为。
3. **World 零入度**：World 不依赖任何 Character 域，Event 只对外广播。

## 4. 消解 v1.0.0 概念债

| 债 | v2 裁决 |
|---|---|
| 五种意图/动作模型 | Intention→Decision 值对象；ActionIntent/PendingAction/ProactiveAction→Action 域状态机三张脸；WorldEvent 保持世界域事件语义。禁止再新增第五种 |
| 关系事实双真相源 | 数值/增量→relationship_events 账本；叙事事实→Memory `relationship_fact` 类型（由 Action/事件后台转写）；快照→投影。查询路径在 Relationship 域内收敛 |
| 记忆类型膨胀风险 | 固定 7 类封顶（见 phase-1 design）：preference / fact / experience / relationship_fact / commitment / milestone_event / behavior_pattern。新增类型需架构评审 |
| 评估与观测两套平面 | Evaluation v2 统一规则+Judge 注册表；V7.8 trace 体系扩展为 Memory/Reflection/Goal Trace（复用 runtime_traces） |
