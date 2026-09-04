# V8.5 Architecture

> 先读 [README.md](README.md) 的问题定义与原则，本文讲总体架构：数据流、挂载点、兼容契约、失败契约。

## 1. 总体数据流

```text
                            回合前（既有，零新增调用）
  user message ──→ context_builder ──→ 四链并行（router / turn_analysis / scene_intent / intention）
                                            │
                                            │ turn_analysis_chain 扩展可选字段：
                                            │   relationship_event（V5 既有）
                                            │ + interaction_signal（V8.5 新，可选）
                                            ↓
                            回答生成（answer_chain，零改动）
                                            ↓
                            回合后 post_process（STEP_HANDLERS 不变）
                                            │
                        state_update 步骤内（既有第 2 步，内部展开为演化流水线）：
                        ┌──────────────────────────────────────────────┐
                        │ 1. Interaction Analyzer：启发式 + LLM 字段      │
                        │      → InteractionSignal + EvidenceWindow     │
                        │ 2. Evolution Engine：信号→事件→动力学→限速      │
                        │      → EvolutionOutcome（同事务落账本+状态）    │
                        │ 3. Milestone 检测（M4）→ bonus/解锁/编年史      │
                        │ 4. Conflict 状态机（M5）→ 迁移/疏远/张力消退    │
                        │ 5. Memory 投递（M6）→ 记忆候选→既有 memory 仓储 │
                        │ 6. 评估护栏规则（M3 附属，第 7 步既有评估执行）  │
                        └──────────────────────────────────────────────┘
                                            ↓
                            消费端（下轮起生效）
                        PromptBuilder 关系段（M7）──→ 回答语气/分寸
                        autonomy_policy（M8）──→ 主动行为门控
                        /debug/relationship/* ──→ 时间线/审计
```

关键取舍：**不新增 post_process 步骤**。演化流水线整体在既有 `run_state_update`（第 2 步）内部展开，与 V5 关系/情绪更新共用同一把用户写锁与同一事务边界——避免步骤间可见性问题和"半演化"状态，STEP_HANDLERS 断言类测试零改动。

## 2. 挂载点清单（全部是加法）

| # | 挂载点 | 改动方式 | 默认态影响 |
|---|---|---|---|
| H1 | turn_analysis_chain 输出 schema | 增可选字段 interaction_signal（旧输出缺省走启发式） | 无 |
| H2 | `run_state_update`（post_process 第 2 步） | 内部追加演化流水线（信号→演化→里程碑→冲突→记忆投递） | V5 主干行为不变 |
| H3 | evaluation_rules 注册表 | 增 relationship 维度 + 4 条规则（Rule 子类 + RULES 追加，V7.5 官方扩展方式） | 关闭即无规则 |
| H4 | PromptBuilder.build_relationship_section | 默认态渲染字节不变；偏离态/里程碑/冲突时追加行 | golden 零重生成 |
| H5 | behavior_engine.resolve | 增可选 relationship 入参 + 修饰规则（模式同 V8 的 W1/W2/W3） | 不传参 = V6.5 现状 |
| H6 | autonomy_policy / PolicySnapshot | 增可选字段 + R1~R5 追加规则 | 不传参 = V7 现状 |
| H7 | relationship_repository + 3 个新仓储 | 一表一文件惯例 | 无 |
| H8 | api/v1/debug.py | 增 /debug/relationship/* 端点 | 无 |
| H9 | migrations（0017 叙述占位，实现时从链尾顺延） | state 扩列 + 3 新表 + events 约束扩值 | 旧行 server_default 兼容 |
| H10 | app/character/asuna/relationship_lexicon.py（新资产） | 启发式词表、冲突指令句、记忆模板、里程碑目录数据 | 无 |

不改的：conversation/message/goal/scene/proactive 触发与执行链、memory_service/extractor、emotion 全链、STEP_HANDLERS 列表、身份段资产（IDENTITY/PERSONALITY/RELATIONSHIP_BLOCK）、golden 快照文件。

## 3. 与 V5 的兼容契约（六不变量）

1. **维度兼容**：intimacy/trust/familiarity/tension 四列语义、默认值、clamp 不变；respect/comfort 为新增列（server_default 落地默认值）。
2. **事件账本兼容**：relationship_events 行结构与落库时机不变；type 枚举 9→11（+promise_kept/promise_broken），source 枚举 2→3（+system，供冲突结算/张力消退类无信号变化记账）。
3. **三级限速不变**：单事件 0.17 / 单轮 0.15 / 单日 0.30 原值保留，覆盖维度扩到 6 维；里程碑 bonus 走独立上限 rel_milestone_delta_cap=0.10。
4. **阶段体系冻结**：四级 + 阈值 + 滞回 + tension>0.5 冻结升级，公式与阈值不动；新维度不进 stage 判定。
5. **LLM 无分数权**：LLM 输出仍是"类型 + 档位 + 置信度 + 原因"，数值全部代码计算。
6. **旧路径保留**：`state_engine.apply_relationship`（V2 映射路径）与 `apply_relationship_v5` 主干逻辑保留；V8.5 动力学是 V5 主干上的可选修饰层，`rel_evolution_enabled=false` 时逐项跳过修饰器，退化即 V5 行为。

## 4. 失败契约（降级矩阵）

| 故障 | 行为 |
|---|---|
| LLM 信号字段缺失/解析失败 | 启发式通道独挑（词表 + 既有 relationship_event 映射），质量降级不中断 |
| 演化引擎异常 | 关系停在上一轮，trace 记 error，回合不阻塞（V5 既有语义） |
| 里程碑/冲突检测异常 | 跳过当轮检测，下轮补检（幂等：里程碑 unique 约束、冲突迁移状态校验） |
| 记忆投递异常 | 只影响长期记忆沉淀，账本与状态已落库，不回滚 |
| 评估规则异常 | V7.5 既有 try/except 隔离，单规则失败不拖垮报告 |
| 新表不可用（迁移未跑） | 演化主干（状态+账本）照常；里程碑/冲突/回滚功能禁用并 log |

一切新逻辑**只降级、不冒泡**——关系系统整体宕掉时，聊天回答零感知（与 V5/V8 同一条纪律）。

## 5. 模块职责与依赖

| 模块 | 输入 | 输出 | 依赖 |
|---|---|---|---|
| M1 Model | — | 状态/信号/事件/里程碑/冲突五组 Pydantic 模型 | 无 |
| M2 Analyzer | 用户消息、既有 TurnAnalysis、情绪语境 | InteractionSignal + 更新证据窗 | M1 |
| M3 Engine | Signal、当前状态、证据窗、当日账本 | EvolutionOutcome（delta/事件行/限速审计） | M1、M2 |
| M4 Milestone | Outcome + 状态 + 账本 | 里程碑命中（bonus/解锁/记忆标记） | M3 |
| M5 Conflict | Outcome + 状态 + 时间 | 冲突迁移、neglect、张力消退 | M3 |
| M6 Memory | Outcome + 里程碑 + 冲突 | 记忆候选（投递既有仓储） | M3/M4/M5 |
| M7 Behavior | 状态 + 最近里程碑 + 活跃冲突 | 关系段渲染 + 行为修饰 | M1/M4/M5 |
| M8 Autonomy | 状态 + conflict_status + 解锁集 | policy 追加规则 | M1/M4/M5 |
| M9 Persistence | 上述全部 | 表读写、版本、快照、回滚 | 全部 |

依赖是单向的：Model ← Analyzer ← Engine ← {Milestone, Conflict, Memory} ← {Behavior, Autonomy}；Persistence 横切。

## 6. 配置命名约定

全部新键进 `core/settings.py` 的 `rel_*` 组（V5 前缀续用），评估键进 `evaluation_relationship_*`：

```text
# 动力学（M3）
rel_evolution_enabled / rel_repetition_decay / rel_trust_negative_amp
rel_comfort_drift / rel_comfort_baseline_json / rel_milestone_delta_cap
# 信号（M2）
rel_signal_llm_enabled / rel_signal_evidence_window
# 里程碑（M4）
rel_milestone_enabled
# 冲突（M5）
rel_conflict_enabled / rel_conflict_cold_hours / rel_conflict_max_cold_days
rel_conflict_recover_positive / rel_neglect_days_json / rel_tension_daily_decay
# 评估（M3 附属）
evaluation_relationship_enabled
```

V5 既有键（rel_max_*、rel_tension_freeze、rel_replay_*、stage_*）一律不动。

## 7. 目录落点（新文件清单）

```text
app/
  models/relationship.py            # 扩展：5+1 维 / InteractionSignal / Milestone / Conflict
  services/relationship_signal.py   # M2 启发式检测器 + 证据窗
  services/relationship_evolution.py# M3 演化纯函数
  services/relationship_milestone.py# M4 目录注册表 + 检测
  services/relationship_conflict.py # M5 状态机纯函数 + neglect + 张力消退
  services/relationship_memory.py   # M6 记忆候选 + 投递
  repositories/relationship_milestone_repository.py
  repositories/relationship_conflict_repository.py
  repositories/relationship_snapshot_repository.py
  character/asuna/relationship_lexicon.py  # 词表/指令句/模板/目录数据（资产）
  api/v1/debug.py                   # /debug/relationship/* 追加
tests/v8.5/                         # 专测套件（testing.md）
```
