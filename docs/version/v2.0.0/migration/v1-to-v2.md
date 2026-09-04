# Migration: v1.0.0 → v2.0.0

> 原则：**不一次性破坏 v1 数据。** Backward Compatibility + Incremental Migration + Feature Flag + Rollback。

## 1. 迁移总策略

```text
v1.0.0 (现状)
  │  ① 仅新增迁移（扩列/新表），v1 代码与新列互不可见
  ▼
Dual-ready（v1 行为 + v2 结构就位）
  │  ② Flag 逐 Phase 开启：数据回填 → 影子运行 → 灰度切换
  ▼
v2.0.0 全量
```

- 所有 v2 表为**新增**；v2 对既有表**只增列不改义**；v1 数据永不删除、永不重写语义。
- 每个 Phase 独立迁移路径，可单独回滚（关 Flag = 回 v1 路径，旧代码保留至 v2 全量稳定后一个版本才允许清理）。

## 2. 各数据域迁移方案

| v1 数据 | v2 去向 | 方案 | 风险与对策 |
|---|---|---|---|
| conversation 消息 | 不动（Working Memory 源） | 无需迁移 | — |
| memories（4 类） | v2 memories（7 类，扩列） | 迁移脚本：类型映射（relationship_event→relationship_fact）；旧数据 salience 按重要性与时间估算初始化；embedding 分批回填 | 类型映射遗漏 → dry-run 报告 + 双读校验窗口 |
| relationship_events/milestones/conflicts | 不动（数值 SoT 不变） | 仅按需转写叙事事实为记忆（REL-001，幂等，可重跑） | 转写遗漏可重放（source_ref 回指） |
| goals（4 类扁平） | v2 goals（扩列层级） | 旧行 layer=conversation_level 语义保持；不自动升级为层级目标 | 旧行误入新逻辑 → 层级字段默认空 = 走 v1 路径 |
| ActionRecord（v9，默认关） | 直接启用（LIFE-004 子闸） | 无历史数据（表为空），无迁移 | 首次开启行为变化 → 独立子闸灰度 |
| character_state / emotion / world / scene | 不动 | 无迁移 | — |
| runtime_traces 等观测数据 | 不动，retention 照常 | — | — |

## 3. 增量迁移执行流程（每 Phase 通用）

```text
1. Alembic 迁移（up/down 全可用，SQLite 兜底库等价）
2. Backfill 脚本（幂等、dry-run 模式、分批、可断点续跑）
3. 影子运行：Flag 开、流量双跑（v1 结果为准，v2 只记差异）
4. 灰度：内部账号 → 单用户 → 全量；观察 evaluation 指标与成本红线
5. 全量后旧路径保留一个观察期
```

## 4. Feature Flag 清单（总闸 + 必要子闸，刻意保持少量）

| Flag | Phase | 子闸 |
|---|---|---|
| v2_memory_enabled | P1 | v2_memory_vector_enabled（向量检索） |
| v2_reflection_enabled | P2 | — |
| v2_development_enabled | P3 | — |
| v2_relationship_evolved_enabled | P4 | — |
| v2_life_loop_enabled | P5 | v2_action_outbox_enabled（outbox 链 + v9 默认启用） |
| v2_autonomy_advanced_enabled | P6 | — |

**禁止再增加碎 Flag**；新需求先问能否并入所属域总闸。

## 5. 回滚方案

| 层级 | 操作 |
|---|---|
| 功能 | 关总闸（子闸跟随）——代码旁路，v1 行为字节级恢复 |
| 数据 | 扩列可 NULL 不影响 v1；新表留存无害；backfill 出错按幂等键清理 |
| Schema | alembic downgrade（仅回滚本 Phase 迁移） |
| 灾难 | Postgres 定期快照（docker volume），回滚到迁移前快照 |

## 6. 验收门（每次灰度推进前必须全过）

1. Golden 回归：Flag 关闭字节级一致；Flag 开启时 v7.5/V7.8/V8 既有 checklist 不回退。
2. 评估指标达 Phase 完成标准（evaluation.md）。
3. 成本红线：每轮 LLM ≤ 基线 ×1.2；周期任务在日预算内。
4. 可归因抽查：任一 Memory/Insight/Goal/主动行为可回答「为什么」。
