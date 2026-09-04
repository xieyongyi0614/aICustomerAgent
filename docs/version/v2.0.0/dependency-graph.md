# v2.0.0 Dependency Graph

> 单一事实来源：所有 Task 的 `Dependencies` 字段必须与本图一致。图中 Task 编号见各 `phases/*/tasks.md`。

## 1. Phase Dependency Graph

```mermaid
flowchart TD
    P1["P1 Memory 2.0<br/>(mem-*)"] --> P2["P2 Reflection<br/>(ref-*)"]
    P2 --> P3["P3 Development<br/>(dev-*)"]
    P1 --> P4["P4 Relationship<br/>(rel-*)"]
    P3 --> P4
    P1 --> P5["P5 Life Loop<br/>(life-*)"]
    P3 --> P5
    P4 --> P5
    P5 --> P6["P6 Advanced Autonomy<br/>(aut-*)"]
    P3 --> P6
    BASE["既有 Goal/Intention/Action/World 引擎"] --> P5
    BASE --> P6
```

**可并行矩阵**（Runtime Enablement = 代码合入但 Flag OFF；Enablement 顺序严格串行）：

| 可并行开发组 | 前置条件 | 说明 |
|---|---|---|
| P1 全部 ∥ REF-001 存储 ∥ DEV-001 存储 ∥ AUT-001 存储扩展 | 无 | 纯 DDL + 服务壳，互不依赖（schema 风格对齐 REF-001 评审） |
| REF-002~004 ∥ DEV-002~004（开发） | P1 MEM-006 语义检索可用 | DEV 只读 REF-001 表结构即可编译，启用依赖 REF-004 |
| P4 REL-001~002 ∥ P5 LIFE-001~003 | P1 完成 | Relationship 与 Life Loop 无表依赖交集 |
| Enablement 串行链 | 对应 Phase 验收过 | v2_memory → v2_reflection → v2_development → v2_relationship_evolved → v2_life_loop → v2_autonomy_advanced |

## 2. Task Dependency Graph（P0 主干）

```mermaid
flowchart LR
    MEM001[MEM-001 存储基座] --> MEM002[MEM-002 Ingest]
    MEM001 --> MEM003[MEM-003 Evaluator]
    MEM003 --> MEM004[MEM-004 Embedding]
    MEM003 --> MEM005[MEM-005 Lifecycle]
    MEM004 --> MEM006[MEM-006 Retriever]
    MEM005 --> MEM006
    MEM005 --> MEM007[MEM-007 Commands]
    MEM003 --> MEM008[MEM-008 Trace]
    MEM001 --> MEM009[MEM-009 background_jobs]
    MEM006 --> MEM010[MEM-010 Eval/Reg]
    MEM001 --> MEM011[MEM-011 Working Memory 接线]

    MEM001 -.-> REF001[REF-001 Insight 存储 ∥]
    REF001 --> REF002[REF-002 Evidence Window]
    MEM006 --> REF002
    REF001 --> REF003[REF-003 触发器]
    MEM009 --> REF003
    REF002 --> REF004[REF-004 Reflector]
    REF004 --> REF005[REF-005 反驳通道]
    REF004 --> REF006[REF-006 Trace/Eval]
    REF006 --> REF007[REF-007 Context 注入段]

    REF001 -.-> DEV001[DEV-001 Dev 存储 ∥]
    DEV001 --> DEV002[DEV-002 DevPolicy]
    REF004 --> DEV002
    DEV002 --> DEV003[DEV-003 行为接线]
    REF005 --> DEV004[DEV-004 回退重放]
    DEV003 --> DEV005[DEV-005 Trace/Eval]

    MEM002 --> REL001[REL-001 真相源转写]
    MEM005 --> REL001
    REL001 --> REL002[REL-002 SharedExp 投影]
    DEV003 --> REL003[REL-003 Patterns 接入]
    REF004 --> REL004[REL-004 叙事里程碑]

    MEM001 --> LIFE001[LIFE-001 Trigger Registry]
    LIFE001 --> LIFE002[LIFE-002 Loop Controller]
    LIFE002 --> LIFE003[LIFE-003 Idle/Budget]
    MEM002 --> LIFE004[LIFE-004 Outbox]
    LIFE002 --> LIFE004
    LIFE002 --> LIFE005[LIFE-005 周期检索/反思检查]
    LIFE002 --> LIFE006[LIFE-006 Goal/Decision Trace]

    LIFE002 --> AUT002[AUT-002 Planning]
    AUT001[AUT-001 Goal 扩展 ∥] --> AUT002
    AUT002 --> AUT003[AUT-003 观察/调整]
    AUT001 --> AUT004[AUT-004 冲突仲裁]
    AUT003 --> AUT005[AUT-005 Eval/Reg]
```

实线 = 运行时启用依赖；虚线 `-.->` = 开发期结构依赖（可并行，启用需等上游）。

## 3. Runtime Dependency（调用方向，沿 domain-boundaries §3 矩阵）

```text
Life Loop(编排) → 调用所有域服务，不被业务域调用
Reflection → Memory(读)              Development → Reflection(读 Insight)
Relationship → State/Memory/Dev(读)   Goal → Dev/Rel/Memory(读)
Decision → Goal/State/Persona(读)     Action → Decision/World/Memory(读或经 Ingest)
World → 零入度                        Memory → State(读情绪信号)/Experience 投影(读)
禁止：Memory→Relationship；Relationship→Memory(直写)；任何人→World(写，除 Action 结果经 outbox)
```

## 4. Data Flow（闭环主链）

```mermaid
flowchart LR
    C[Conversation] -->|turn_analysis 产物| MC[(memory_candidates)]
    AR[ActionRecord] -->|Ingest| MC
    WE[WorldEvent 完结] -->|Ingest| MC
    RE[RelationshipEvent] -->|Ingest| MC
    MC -->|Evaluate| M[(memories)]
    M -->|检索 top-5| CTX[Context] --> LLM[answer] --> C
    M -->|Evidence Window| INS[(insights)] --> DEV[(development_state)] --> BP[BehaviorPolicy/Goal 调制] --> CTX
    BP -->|行为变化→新对话| C
    ACT[ActionExecutor] --> OB[(outbox_events)] --> W[World] --> WEV[world_events] --> MC
```

要点：`BP → 新对话 → C` 是 §十「反复行为→新经历→再反思」闭环的落点——调制结果改变对话行为，对话经 P1 Ingest 再变 Candidate，Dev 不自证。

## 5. Event Flow（跨域写入全部经 Ingest / Outbox，禁止直写）

```text
Action 成功 → 同事务(action_records + outbox_events) → WorldEngine 消费 → world_events
  → Memory Ingest → memory_candidates            【Action 永不直接 INSERT memories】
RelationshipEvent 变更 → Memory Ingest → relationship_fact 记忆   【Relationship 永不直写 memories】
Insight invalidated → Development 订阅 → development_changes 回退 【Reflection 永不直写 development_state】
用户消息 → chat_pipeline → 显式 remember/forget → Memory Commands   【chat_pipeline 永不直写 memories】
```

## 6. LLM Flow（前台 ≤4 次，其余后台/条件触发）

```text
前台: router+turn_analysis(合并, lite) → scene_intent(lite, 歧义时) → intention(lite, 歧义时) → answer(main, 流式)
后台即时: state_update(lite) → memory 评估兜底(lite, 灰区才调) → evaluation judge(采样)
后台批: embedding(非 chat) / judge 采样
后台周期: reflection(main, ≤1 次/日/用户, 门槛后才调) → goal planning(main, 每 goal ≤3 次/生命周期)
熔断: 全局日配额超限 → 后台降级为只记 Candidate；前台永不熔断
```

## 7. Cross-Domain Write Flow

```mermaid
flowchart TD
    A[Source Domain] -->|Event/Command| I[Ingest / 目标域 Service]
    I --> T[(Target Domain 表)]
    A -.禁止直写.-> T
```

合法写入路径共 5 条（见 §5），其余任何跨域写入在 Code Review 中按违规处理。
