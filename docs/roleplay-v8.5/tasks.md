# Roleplay V8.5 任务注册表

> **状态（2026-08-31）**：设计完成，待实现。
> 执行策略：逐 Task 测试 + 全量回归（V1~V8 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：V8.5 是 V5 关系域的深化——默认态下 prompt 字节（golden 守门）、V5 行为、V7 policy 输出三者不变是每个 Task 的底线；一切阈值与开关进 settings rel_* 组；失败只降级；LLM 无分数修改权。

## Task 列表

### V8.5-001 Relationship Model（P0）

- **目标**：5+1 维模型落地——models/relationship.py 扩展（respect/comfort/conflict_status/neglect_active/last_interaction_at/version + InteractionSignal/MilestoneSpec/Conflict 模型）、迁移扩列与账本枚举扩值（type +2 / source +1）、RELATIONSHIP_EVENT_DELTAS 扩 6 列 + promise_kept/broken 行、BEHAVIOR_DELTAS 补 comfort、settings rel_* 扩充（rel_evolution_enabled / rel_repetition_decay / rel_trust_negative_amp / rel_comfort_drift / rel_comfort_baseline_json / rel_milestone_delta_cap 等）、角色资产 relationship_lexicon.py 骨架（档位文案表）。
- **范围**：models/relationship.py、core/constants.py、core/settings.py、migrations/（顺延编号）、core/db.py、repositories/relationship_repository.py（扩列读写）、character/asuna/relationship_lexicon.py、conftest env_map；不碰任何 service/chain 逻辑。
- **依赖**：无。
- **实现要点**：relationship-model.md §1~§5、persistence.md §2；新列全部 server_default；stage 公式与阈值一行不动；affection≡intimacy 映射只在文档与命名注释层声明。
- **验收标准**：迁移往返 + 旧行默认值正确；V5 既有关系测试零改动全绿；6 列 delta 表与 magnitude 联动正确；stage 对新维度不敏感断言。
- **测试**：`tests/unit/test_relationship_model.py`、`tests/integration/test_relationship_migration.py`。

### V8.5-002 Interaction Analyzer（P0）

- **目标**：InteractionSignal 全链——启发式词表检测器（资产表驱动）+ turn_analysis_chain 增可选 interaction_signal 字段（向后兼容）+ 证据窗（内存环形 + 账本重建）+ novelty 计算 + 信号→事件映射矩阵（纯函数表）。
- **范围**：services/relationship_signal.py（新增）、chains/turn_analysis_chain.py（可选字段）、character/asuna/relationship_lexicon.py（词表填充）；采样增强链（通道 C）仅留接口与 rel_signal_llm_enabled=false 配置。
- **依赖**：V8.5-001。
- **实现要点**：interaction-analysis.md §1~§5；敏感词表宁误报不漏报；一轮至多 1 主信号；P0 零新增 LLM 调用（调用计数断言）。
- **验收标准**：词表矩阵逐条正确；LLM 字段缺失降级通道 A；novelty 序列 1.0/0.5/0.25；neutral 降档；证据窗重建等价。
- **测试**：`tests/unit/test_interaction_signal.py`、`tests/unit/test_signal_lexicon.py`。

### V8.5-003 Evolution Engine + 评估护栏（P0，收口）

- **目标**：evolve 纯函数引擎（D1~D5 动力学修饰器 + 三级限速扩 6 维 + clamp）+ EvolutionOutcome + state_update 步骤内接线（同事务状态+账本，V5 主干保留为关闭路径）+ comfort 均衡回归 + Relationship Evaluation（EvaluationDimension/IssueCode 扩展 + 4 条规则 + 权重表 + 开关）。
- **范围**：services/relationship_evolution.py（新增）、services/state_service.py / application/post_process.py（第 2 步内部展开）、services/evaluation_rules/relationship.py（新增）、models/evaluation.py、core/settings.py（evaluation_relationship_*）；**STEP_HANDLERS 列表不变**。
- **依赖**：V8.5-002。
- **实现要点**：evolution-engine.md 全篇；修饰器顺序固定（可重放）；里程碑 bonus 预算接口先行（M4 消费）；重放函数 `replay(state, stream)` 本 Task 交付（M9 回滚复用）。
- **验收标准**：修饰器精确数值断言（含 0.0063）；关闭开关=V5 逐位；**全量回归零失败（P0 收口）**；jump/uncaused/rate 三规则正反例；重放 ×100 终态全等。
- **测试**：`tests/unit/test_evolution_engine.py`、`tests/v8.5/test_relationship_replay.py`、`tests/unit/test_evaluation_relationship.py`、`tests/integration/test_relationship_pipeline.py`。

### V8.5-004 Milestone System（P1）

- **目标**：12 项里程碑目录（注册表 + 谓词）+ relationship_milestones 表与仓储 + 检测接线（演化后同锁小事务）+ bonus 应用（独立 cap）+ 解锁查询（EXISTS 语义）+ 周期 anniversary（period_key）。
- **范围**：services/relationship_milestone.py（新增）、migrations/、repositories/relationship_milestone_repository.py、character/asuna/relationship_lexicon.py（目录数据）；unlocks 消费方留待 007。
- **依赖**：V8.5-003。
- **实现要点**：milestone-system.md §2~§5；UniqueConstraint 幂等；检测异常跳过当轮下轮补检；bonus 不进 events 账本。
- **验收标准**：12 谓词正反例；重复注入零重复行；bonus cap 截断；阶段跃迁刻印与 next_stage 同轮一致。
- **测试**：`tests/v8.5/test_milestone_system.py`、`tests/integration/test_relationship_milestone_repo.py`。

### V8.5-005 Conflict System（P1）

- **目标**：冲突状态机（六态迁移矩阵纯函数 + relationship_conflicts 表 + state.conflict_status 冗余同步）+ recovery 词表通道 + neglect 检测（分档阈值/一次性落账/重逢复位）+ tension 日消退（幂等、冲突期暂停）+ source=system 结算记账。
- **范围**：services/relationship_conflict.py（新增）、migrations/、repositories/relationship_conflict_repository.py、character/asuna/relationship_lexicon.py（恢复词表）；消费方（M7/M8）留待 007。
- **依赖**：V8.5-003。
- **实现要点**：conflict-system.md 全篇；strain 复用 tension>0.5 口径；道歉不加分只开通道；非法迁移拒绝 + 评估 issue。
- **验收标准**：迁移矩阵全格 + 时序四条（注入时钟）；neglect 分档与复位；日消退幂等；ConflictRule 正反例。
- **测试**：`tests/v8.5/test_conflict_system.py`、`tests/integration/test_relationship_conflict_repo.py`。

### V8.5-006 Memory Integration（P1）

- **目标**：路由边界表落地 + to_memory_candidates 纯函数 + 投递既有 memory 仓储（source=relationship_evolution）+ importance 映射 + 角色资产记忆模板 + 24h cause 去重。
- **范围**：services/relationship_memory.py（新增）、character/asuna/relationship_lexicon.py（模板）；**不改 memory_service/extractor/第 5 步**。
- **依赖**：V8.5-003（004/005 提供投递源，未完成时先支持事件级投递）。
- **实现要点**：memory-integration.md 全篇；投递失败不回滚演化；负向记忆照投。
- **验收标准**：边界表逐格断言；模板确定性；去重生效；V4 记忆测试零回归（零侵入）。
- **测试**：`tests/v8.5/test_relationship_memory.py`。

### V8.5-007 Behavior & Autonomy Integration（P1，价值兑现）

- **目标**：关系段深化渲染（条件化追加：维度档/里程碑/冲突指令/neglect note，默认态字节不变）+ 行为修饰 B1~B5（behavior_engine 可选 relationship_ctx）+ 自主门控 R1~R5（PolicySnapshot 扩展 + policy 追加规则）+ /debug/relationship 三端点（state/timeline/rollback）+ 快照表与回滚（关键帧 + 重放）。
- **范围**：prompts/builder.py（build_relationship_section 原地扩展）、services/behavior_engine.py（可选参数）、services/autonomy_policy.py + application/autonomy_engine.py（快照装配）、migrations/（snapshots 表）、repositories/relationship_snapshot_repository.py、api/v1/debug.py；**golden 零重生成是硬闸**。
- **依赖**：V8.5-004、V8.5-005。
- **实现要点**：behavior-integration.md / autonomy-integration.md / persistence.md §4~§6；`relationship_ctx=None` / 不传新快照字段 = 既有输出逐位一致；R5 覆盖 R3 优先级。
- **验收标准**：默认态渲染与 V5 快照逐字节相等；B/R 规则正反例；V6.5/V7 既有测试零回归；回滚幂等可审计；**全量回归零失败（P1 收口）**。
- **测试**：`tests/v8.5/test_relationship_context.py`、`tests/v8.5/test_relationship_autonomy.py`、`tests/integration/test_relationship_snapshots.py`、`tests/e2e/test_debug_relationship.py`。

### V8.5-008 Testing 收口 + 人工回归清单（P2）

- **目标**：tests/v8.5/ 套件补齐归位（九件全绿）+ 长期演化场景（30 天累计 / 冲突全生命周期 / 疏远→召回，声明式注入时钟）+ 性能护栏常驻断言（演化 <10ms、全链 <25ms、回答路径零感知）+ `docs/roleplay-v8.5/regression-checklist.md`（开关矩阵 + 五条真实模型演练 + prompt 抽查 + 回滚演练）。
- **范围**：tests/v8.5/（新增）、docs/roleplay-v8.5/regression-checklist.md（仅文档部分）。
- **依赖**：V8.5-001 ~ V8.5-007。
- **实现要点**：testing.md 全篇；时间敏感全部注入时钟；命名全局唯一（xdist）。
- **验收标准**：单命令全绿；三主线场景终态断言；性能预算守门常驻；全量回归零失败；清单可人工执行。
- **测试**：即本 Task。

## 依赖图

```text
001 模型+迁移+配置 ── 002 信号分析 ── 003 演化引擎+评估护栏（P0 收口）
                                              │
                        ┌─────────────────────┼──────────────────┐
                        004 里程碑            005 冲突            006 记忆桥
                        └────────┬────────────┘                   │
                                 007 行为+自主集成+回滚端点（P1 收口）←┘
                                 008 场景套件+性能+人工回归清单
```

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V8.5-XXX <中文描述>`。
- 两个收口点：**V8.5-003**（P0：演化闭环 + 全量回归零失败）、**V8.5-007**（P1：消费集成 + golden 字节不变 + 全量回归零失败）。
- P0（001~003）完成后系统即具备"信号→动力学→限速→账本→护栏"的完整演化能力；P1 补齐编年史、冲突与消费集成；008 收口并交付人工回归清单。
