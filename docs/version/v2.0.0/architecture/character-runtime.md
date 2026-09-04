# v2.0.0 Character Runtime

> Character Runtime 是角色本身；LLM 只是它借用的三个引擎。v1.0.0 的 Runtime「每轮醒来、回答、遗忘」；v2.0.0 的 Runtime「持续在场」。

## 1. Runtime 组成

```text
Character Runtime
│
├── Persona                    静态资产（v1 复用）
├── State                      情绪/能量/内在状态（v1 复用 + 衰减）
├── Working Memory             每轮重建的上下文窗口（Runtime Context）
├── Long-term Memory           P1：双层记忆 + 生命周期
├── Reflection                 P2：Evidence → Insight
├── Development                P3：Belief / Pattern → 行为调制
├── Relationship               V8.5 复用 + P4：Shared Experience / Patterns
├── Goal                       v1 复用 + P6：层级化
├── Decision                   v1 复用（Intention 归并为值对象）
├── Action                     v9 复用（默认启用）
├── World                      V8 复用
└── Life Loop                  P5：统一生命周期控制器
```

## 2. 两个存在时刻

### 2.1 交互时刻（用户在场）

```text
消息 → Working Memory 组装（含 Long-term 检索）→ Decision → Generation → 
落库 → Experience 摄取 → （后台）Memory Candidate / State 更新 / Evaluation
```

角色在此时刻「感知—回应」，长期化全部后置。

### 2.2 生活时刻（用户不在场）

```text
Trigger（调度 / 事件 / 阈值）
 → Perception（读 World 变化 + 未读 Event）
 → State Update（能量/情绪自然衰减恢复，纯规则）
 → Goal Evaluation（到期/受阻检查，纯规则）
 → Memory Retrieval（想起与当前状态相关的记忆，仅高显著度）
 → Reflection Check（证据是否达到反思门槛，达到才调 LLM）
 → Decision（是否主动行动，AutonomyPolicy 复用）
 → Action / Proactive Message
 → World Event → Experience 摄取 → 下一周期
```

成本铁律：生活时刻每一环默认纯规则，**LLM 只在 Decision 命中且预算允许时发生**；Idle 判定（无待办 Trigger、无到期 Goal、状态平稳）直接跳过整轮。

## 3. 闭环维持机制

| 闭环环节 | v2 保障 |
|---|---|
| Action → World | Outbox：行动结果先写 outbox_events，World 消费后标记完成（幂等键 = action_id） |
| World Event → Experience | 摄取器监听 world_events 落库事件，生成 MemoryCandidate（source=world_event） |
| Experience → Memory | Candidate 评估（规则优先，LLM 兜底）→ 转正/丢弃，全部有 trace |
| Memory → Reflection | 周期任务扫描 Evidence 窗口 |
| Reflection → Development | Insight 编译为行为参数（纯函数） |
| Development → Goal/Decision | DevPolicy 调制 goal 权重与 BehaviorPolicy |
| Goal → Action | Life Loop 每周期检查到期 Goal → Decision → Action |

## 4. 不变量（Invariants）

1. **前台永远不写长期域**：Memory/Insight/Development/Goal 的写入只发生在后台或显式命令。
2. **一切长期变化可归因**：Memory 有 source，Insight 有 evidence_links，Development 有 development_changes 审计，Goal 变更有 decision_records。
3. **任何域可独立禁用**：每个域挂 Feature Flag；关闭时 Runtime 退化为 v1.0.0 行为（字节级 golden 不变）。
4. **数值数学不动**：V8.5 关系引擎、V5 情绪衰减、V6.5 行为策略的纯函数本体在 v2 不修改，只被新域「调制」（参数注入，不改公式）。
5. **重启无状态丢失**：Trigger Registry、Candidate 队列、Outbox 全部持久化；内存只做缓存。

## 5. 与 LLM 的关系

```text
Character Runtime ──选择任务──> LLM Orchestration
   Reasoning Engine:  Reflection / 复杂 Decision / Goal Planning
   Generation Engine: answer / proactive message
   Evaluation Engine: memory 判定兜底 / Evaluation Judge
```

Runtime 决定「问什么、给什么证据、信多少」；LLM 从不直接持有真相（真相只在 Postgres）。详见 [llm-orchestration.md](llm-orchestration.md)。
