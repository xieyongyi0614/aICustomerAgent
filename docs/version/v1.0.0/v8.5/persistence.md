# V8.5 M9：Persistence（持久化：版本、时间线、回滚）

> 迁移编号从实现时链尾顺延（写作时链尾 0016；若 V8 已落地则继续顺延，本文以 0017 为叙述占位）。JSON 列统一跨方言 `JSON`（项目约定，非 JSONB）。

## 1. 存储总览

| 表 | 性质 | V8.5 动作 |
|---|---|---|
| relationship_state | 单行状态快照 | 扩列（§2） |
| relationship_events | 事件账本（V5） | type/source 枚举扩值（§2） |
| relationship_milestones | 里程碑编年史 | 新表 |
| relationship_conflicts | 冲突历史 | 新表 |
| relationship_snapshots | 关键帧快照 | 新表 |

表命名沿项目惯例：状态快照单数、历史流水复数；约束 `ck_<表>_<列>`、索引 `idx_<表>_<...>`；一表一仓储文件。

## 2. relationship_state 扩列 + 账本扩值

```text
★新增列（全部 NotNull + server_default，旧行零迁移成本）：
  respect            Float  DEFAULT 0.60
  comfort            Float  DEFAULT 0.60
  conflict_status    String DEFAULT 'none'   （ck_relationship_state_conflict_status ∈ none/strain/conflict/cold/recovery/resolved）
  neglect_active     Boolean DEFAULT false
  last_interaction_at DateTime NULL
  version            Integer DEFAULT 0      （演化流水线执行次数，单调递增）
账本扩值（需重建约束）：
  type ∈ 既有 9 值 + promise_kept / promise_broken
  source ∈ conversation / memory_replay / system   （system：冲突结算、张力消退、neglect 等无信号变化的显式"因"）
```

- impact 列语义不变（记录实际生效值，含 system 行）——"账本 = 状态变化的完整对账单"在 6 维上继续成立。
- 不加列：interaction_signal（不落库）、distance_index（派生）、strain_score（用账本当日负向计数替代）。

## 3. 三张新表

```python
relationship_milestones      # 里程碑（一次性，unique 幂等）
  id PK / user_id idx / character_id / milestone_key / period_key(default '')
  title / applied_bonus JSON / unlocks JSON / created_at
  UniqueConstraint(user_id, milestone_key, period_key)

relationship_conflicts       # 冲突历史（闭合行保留）
  id PK / user_id / status（strain|conflict|cold|recovery|resolved）
  trigger_event_id / started_at / last_negative_at / recovery_started_at
  resolved_at / resolution('reconciled'|'time_heals'|'') / created_at
  idx(user_id, status)；单活跃由仓储逻辑保证（同 proactive 深度 1 模式，不用 partial index——SQLite 兼容）

relationship_snapshots       # 关键帧（限频，回滚锚点）
  id PK / user_id / version / dimensions JSON / stage / conflict_status
  trigger(event:<id> | milestone:<key> | conflict:<transition> | manual) / created_at
  idx(user_id, version DESC)
```

## 4. 版本与时间线

- `state.version` 每次演化流水线执行 +1（含无事件轮的 comfort 回归）——version 差即轮数，是 comfort 回归对账与重放的输入。
- **时间线** = events ∪ milestones ∪ conflicts ∪ snapshots 按 created_at 归并的统一视图，`GET /debug/relationship/timeline?user_id=&limit=` 暴露（审计与调参主界面；Debug 面板前端按边界跳过，仅 API）。
- 另提供 `/debug/relationship/state`（当前状态 + 解锁集 + 派生指标）与 `/debug/relationship/rollback`（§5，显式调用）。

## 5. 回滚（前向修正，不删历史）

```text
rollback_to_version(user, target_version):
  1. 校验 target ≥ 最早关键帧 version
  2. 恢复前自动留存"恢复前"快照（trigger=manual，V8-013 同款审计）
  3. 取 version ≤ target 的最新关键帧
  4. 重放其后账本事件（events + milestones bonus + system 结算）→ 确定性重建状态
  5. 写入新 version（> 当前 max），旧行旧账全保留
  6. 不回滚：情绪 / 记忆 / 目标 / 会话（文档化语义，同 V8"Character 状态不回滚"）
```

重放可行性由演化纯函数保证（evolution-engine.md §6）；重放产出与历史快照不一致时（理论不该发生）→ 评估 fail 级 issue + log，回滚中止。

## 6. 快照策略

- 写入时机：stage 跃迁 / 里程碑命中 / 冲突迁移（任一发生即一帧，trigger 标明原因）。
- 限频：每用户保留 ≤ 20 帧（超出淘汰最旧，模式同 V8）；version 连续但无关键事件不写帧（账本已可重放，帧只为加速）。

## 7. 兼容与迁移纪律

- 新列全部 server_default：`alembic upgrade` 对存量行零操作；迁移一致性测试（ORM metadata 比对）纳入 CI（既有 `test_db_migration` 模式）。
- V5 既有列 / 迁移 0006、0007 不动；V2 映射路径不动。
- 测试环境 SQLite：JSON / Boolean / server_default 全部跨方言可跑（既有 V7/V7.5 表同款选型已验证）。

## 8. 验收标准

- alembic upgrade/downgrade 往返；旧行升级后默认值正确、V5 全部行为逐位不变。
- 账本 type/source 新值落库与约束校验；system 行进对账白名单。
- 三新表 CRUD + unique 幂等 + 单活跃约束；JSON 列往返。
- version 单调、时间线归并排序、回滚幂等且可审计（恢复前快照存在）。
- debug 三端点可用（含权限边界与空数据形态）。
