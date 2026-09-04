# v2.0.0 Data Flow & Consistency

## 1. 同步 / 异步边界

```text
【同步关键路径】用户请求（目标 P95 ≤ 3s 首字）
  Context 检索(数据库+向量, <50ms) → Decision(规则/轻量 LLM) → answer 流式生成

【异步后台】
  即时队列:   state_update / memory candidate 评估 / evaluation / scene / summary
  批处理:     embedding / judge 采样
  周期任务:   memory decay+consolidation / reflection / life loop tick / retention
  事件驱动:   outbox 消费(world event 广播) / action retry
```

裁决基准：**影响本轮回答内容的才允许同步；只影响未来轮次的一律异步。**

## 2. 核心链路一致性

### 2.1 Action → World → Event → Memory（P5 起用 Outbox）

```text
ActionExecutor 成功
  ① 同事务写 action_records + outbox_events(event_type, payload, idempotency_key=action_id)
  ② WorldEngine 消费 outbox → 更新 world 状态 → 写 world_events → 标记 outbox done
  ③ 摄取器读 world_events → 生成 MemoryCandidate（source=world_event）
失败恢复：action retry loop 复用；outbox 未完成条目按幂等键重放
```

### 2.2 Memory 生命周期一致性

- Candidate 转正/丢弃、supersede、merge 全部单事务完成且写 memory trace。
- **Vector Index 一致性**：pgvector 列与 memories 业务行同事务更新；embedding 延迟生成时行先入库、embedding 置 NULL、批处理补齐（补齐前该行只走结构化检索，不丢数据）。**SoT 永远是业务表**——向量列损坏可全量重建（rebuild script），不算数据丢失。
- Forget = 状态置 forgotten + 软删窗口 + 保留期后物理删除（修正 v1 硬 DELETE）；向量随行删除。

### 2.3 Insight / Development 一致性

- Reflection 单事务写 insights + evidence_links + reflection_runs。
- Development 编译读 Insight 写 development_state + development_changes（before/after 审计），可重放：重放 = 删 changes 后按 Insight 时间序重编译。

### 2.4 并发模型

沿 v1 裁决：**单用户写串行化**（per-user 写锁）+ 后台任务按 user_id 分片认领（background_jobs 行锁 `FOR UPDATE SKIP LOCKED`）。get→compute→upsert 三段事务的历史缺口仅在快照类投影中允许（可重算），真相源写入一律单事务。

## 3. 幂等与重试

| 机制 | 规则 |
|---|---|
| 幂等键 | outbox=id(action_id)；background job=job_key(task_type+entity_id+周期桶)；candidate 摄取=(source_table, source_id) 唯一约束 |
| 重试 | 指数退避，max 5 次；死信进 job 状态 failed 并留 reason |
| 时钟 | 周期任务一律用数据库时间/世界时间（TimeProvider），禁散落 `datetime.now()`（修 v1 双时钟债） |

## 4. 事务边界总表

| 写入 | 事务范围 |
|---|---|
| answer 落库 | conversation + turn_meta（v1 现状） |
| Memory 转正/更新 | memories + memory_links + trace，单事务；embedding 异步补偿 |
| Reflection | insights + evidence_links + reflection_runs，单事务 |
| Development | development_state + development_changes，单事务 |
| 关系数值 | 沿 V8.5：信号→事件→delta→state 单事务，账本即真相 |
| Goal 变更 | goals + decision_records，单事务 |
| Action 执行 | action_records + outbox_events，单事务；World 消费独立事务 |

## 5. 写放大防护

- 记忆 last_accessed/reinforce 类「读路径写回」**取消直写**，改为内存聚合 + 周期批量 flush（修正 v1 反模式与并发缺口）。
- 快照类（relationship/world/memory snapshot）降频：按日或按显著变更触发，不再每轮。
- embedding 批处理：攒批 ≥ 32 条或 60s 窗口。
