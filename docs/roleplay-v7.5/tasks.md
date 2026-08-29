# Roleplay V7.5 任务注册表

> 优先级：**P0 = V7.5 必须，P1 = 推荐，P2 = 延期**。
> 执行策略：逐 Task 测试 + 全量回归（V1~V7 零回归）+ commit/push，连续执行，最后统一汇报。
> 全局约束：评估是观察者——任何 Task 不得改变聊天 / 主动链路的既有行为；评估失败只降级不抛出；阈值一律进 `core/settings.py` evaluation_* 组。

## Task 列表

### V7.5-001 Evaluation 域模型 + 配置组（P0）

- **目标**：`EvaluationReport / DimensionScore / Issue / IssueCode / EvaluationSubjectKind` 全套域模型 + settings `evaluation_*` 配置组（20 项）。
- **前置**：无。
- **涉及文件**：`app/models/evaluation.py`（新增）、`app/core/settings.py`。
- **实现内容**：evaluation-model.md §1~§3、§6；IssueCode 枚举是全系统唯一事实源（19 个编码 + 默认 severity 映射）。
- **验收**：模型构造与校验（score 边界、verdict 阈值判定、subject 必填）；配置组默认值加载、`override_settings` 可覆盖。
- **测试**：`tests/unit/test_evaluation_models.py`。

### V7.5-002 evaluation_reports 表 + Repository（P0）

- **目标**：迁移 0012 建表（subject/verdict CheckConstraint 收敛、session_id 列、scores/issues/context_digest/meta JSON 列 + 两索引）+ `EvaluationRepository`（save / get_by_subject / list_by_user / prune_before）。
- **前置**：V7.5-001。
- **涉及文件**：`migrations/versions/0012_evaluation_reports.py`（新增）、`app/repositories/evaluation_repository.py`（新增）。
- **实现内容**：persistence.md §1、§4、§5。
- **验收**：`alembic upgrade/downgrade` 往返；JSON 列读写往返；retention 清理幂等；同 subject 多报告取最新语义。
- **测试**：`tests/integration/test_evaluation_repository.py`。

### V7.5-003 EvaluationContext 收集器 + digest（P0）

- **目标**：从 PostProcessContext / 仓储切片构造 `EvaluationContext`（含历史窗口数据）与有界 `context_digest`。
- **前置**：V7.5-001。
- **涉及文件**：`app/services/evaluation_context.py`（新增）。
- **实现内容**：evaluation-model.md §4；architecture.md §4 复用清单（emotion_history / behavior_meta / memories / 角色资产引用）。
- **验收**：digest 总字符 ≤ `evaluation_max_digest_chars`（超限按低优先级字段截断）；任一切片缺失容错（None 不抛）；收集器零写操作。
- **测试**：`tests/unit/test_evaluation_context.py`。

### V7.5-004 Rule Engine 框架（P0）

- **目标**：`EvaluationRule` 协议 + RULES 注册表 + 逐条异常隔离 + severity→penalty 扣分推导（纯函数）。
- **前置**：V7.5-001。
- **涉及文件**：`app/services/evaluation_rules/__init__.py`（新增）。
- **实现内容**：rule-engine.md §2~§4。
- **验收**：单规则抛异常不影响其余规则；空规则集 / 维度禁用 → 维度缺席（非满分）；扣分表只读配置。
- **测试**：`tests/unit/test_evaluation_rule_engine.py`。

### V7.5-005 Behavior 规则集（P0）

- **目标**：BUDGET_EXCEEDED / CONTACT_VIOLATION / ACTION_MONOTONY / EXPRESSION_MISMATCH 四规则，复用 `observe_budget` 观测口径。
- **前置**：V7.5-004。
- **涉及文件**：`app/services/evaluation_rules/behavior.py`（新增）、`app/services/evaluation_rules/lexicons.py`（新增，动作类别词表）。
- **实现内容**：behavior-evaluation.md §2~§4；本维无 LLM。
- **验收**：表驱动矩阵（命中/不命中/边界/ctx 缺失）全过；滑窗参数来自 settings。
- **测试**：`tests/unit/test_evaluation_rules_behavior.py`。

### V7.5-006 Persona 规则集 + 角色评估资产（P0）

- **目标**：ABUSIVE_LANGUAGE（critical 硬信号）+ CONTRADICTION_PATTERN（人设矛盾模式，mode 白名单豁免）。
- **前置**：V7.5-004。
- **涉及文件**：`app/services/evaluation_rules/persona.py`（新增）、`app/services/evaluation_rules/lexicons.py`（辱骂词表）、`app/character/asuna/evaluation.py`（新增，人设资产）。
- **实现内容**：persona-evaluation.md §2；词表锚定防子串误命中。
- **验收**：辱骂命中 → critical；模式命中带 mode 白名单场景正确豁免；词表按人设加载。
- **测试**：`tests/unit/test_evaluation_rules_persona.py`。

### V7.5-007 Emotion 规则集（P1）

- **目标**：UNTRIGGERED_SHIFT（弱/无事件下 mood 切换）+ TEXT_STATE_CONFLICT（文本-状态冲突候选）。
- **前置**：V7.5-004。
- **涉及文件**：`app/services/evaluation_rules/emotion.py`（新增）、`app/services/evaluation_rules/lexicons.py`（情绪信号词）。
- **实现内容**：emotion-evaluation.md §2；不复算 state_engine 钳制公式，只审计结果。
- **验收**：strong/normal 事件驱动切换不误报；候选 issue 供 judge 确认语义成立。
- **测试**：`tests/unit/test_evaluation_rules_emotion.py`。

### V7.5-008 Memory 规则集（P1）

- **目标**：FABRICATION_CANDIDATE（recall-marker × 注入记忆/近期对话无支撑）+ MISSED（高重要度漏用 info）。
- **前置**：V7.5-004。
- **涉及文件**：`app/services/evaluation_rules/memory.py`（新增）、`app/services/evaluation_rules/lexicons.py`（recall-marker 词表）。
- **实现内容**：memory-evaluation.md §2；规则只产候选不定罪。
- **验收**：有注入支撑的引述不报；候选与 judge 确认的吸收关系（FABRICATION 吸收 CANDIDATE）在合并器侧可验证。
- **测试**：`tests/unit/test_evaluation_rules_memory.py`。

### V7.5-009 LLM Judge 链（P0）

- **目标**：`evaluation_judge_chain`——TurnJudgeResult / ProactiveJudgeResult schema（三道闸：code 枚举、evidence 子串校验、memory_ids 受限引用）、评估 prompt 模板、一层降级。
- **前置**：V7.5-001、V7.5-003。
- **涉及文件**：`app/chains/evaluation_judge_chain.py`（新增）、`app/prompts/evaluation_judge.py`（新增）。
- **实现内容**：llm-judge.md §1~§5；角色基准引用 `character/<persona>/` 资产常量。
- **验收**：FakeLLM 按 schema 类名分发可用；非法 evidence 清空降级；score 出界拒收；失败上抛由调用方容错（链自身不吞）。
- **测试**：`tests/unit/test_evaluation_judge_chain.py`。

### V7.5-010 EvaluationEngine + post_process 挂载（P0）

- **目标**：`EvaluationEngine.evaluate(EvaluationCase)` 两阶段（锁内规则判定 → 采样 judge 锁外派发 → min 合并 → verdict → 落库）+ `run_evaluation` 成为 post_process 第 7 步 + request_id 确定性采样。
- **前置**：V7.5-002 ~ V7.5-009。
- **涉及文件**：`app/services/evaluation_engine.py`（新增）、`app/application/post_process.py`、`app/services/trace_collector.py`（TRACE_STEP_NAMES 增 `evaluation`；step 恒记录、不纳入 `_BACKGROUND_STEPS`）。
- **实现内容**：architecture.md §2/§3/§5（写锁两阶段）；evaluation-model.md §2 分数语义；rule-engine.md §2 主体过滤。
- **验收**：FakeLLM 全链出报告并落库；judge 采样命中时 judge 在锁外任务执行（写锁持有时间不含 LLM 调用）；judge 失败 → 规则版报告 + trace degraded；`evaluation_enabled=False` 时第 7 步仅记 skipped step，既有 `is_complete` e2e 语义不变；**既有全量测试零回归**（trace 断言同步逐条列明）；评估异常不冒泡。
- **测试**：`tests/integration/test_evaluation_pipeline.py`。

### V7.5-011 Proactive 评估挂载 + Autonomy 规则（P1）

- **目标**：executor delivered 后 fire-and-forget 评估；TIMING_VIOLATION 时点审计规则；ProactiveJudgeResult 变体（autonomy + persona）。
- **前置**：V7.5-010。
- **涉及文件**：`app/services/evaluation_rules/autonomy.py`（新增）、`app/services/proactive_executor.py`、`app/chains/evaluation_judge_chain.py`（变体分支）。
- **实现内容**：autonomy-evaluation.md §1~§4；评估在写锁外，失败只 log。
- **验收**：delivered → subject=proactive_action 报告落库；评估失败不影响发送链路（既有 V7 集成测试零回归）；静态音/活跃/间隔审计矩阵通过。
- **测试**：`tests/integration/test_proactive_evaluation.py`。

### V7.5-012 Debug 查询 API（P1）

- **目标**：`GET /api/v1/debug/turns/{turn_id}/evaluation`、`GET /api/v1/debug/proactive/{action_id}/evaluation`（只读，最新一条，无则 404）。
- **前置**：V7.5-010。
- **涉及文件**：`app/api/v1/debug.py`。
- **实现内容**：persistence.md §6。
- **验收**：404 语义与 trace 端点一致；不泄露非 debug 信息；只读无副作用。
- **测试**：`tests/e2e/test_debug_evaluation.py`。

### V7.5-013 Offline 离线评估器（P1）

- **目标**：`OfflineEvaluator`——从 DB 重建 EvaluationCase（fidelity=reconstructed）批量评估历史会话/窗口 + 聚合摘要（均值 / verdict 分布 / issue 直方图 / 主动 ack 率，AUTONOMY_LOW_OUTCOME）。
- **前置**：V7.5-010。
- **涉及文件**：`app/services/offline_evaluator.py`（新增）。
- **实现内容**：persistence.md §3（聚合派生不建表）；autonomy-evaluation.md §3.2。
- **验收**：种子历史数据批量出报告；聚合统计口径单测固定；重建模式标记正确写入 meta。
- **测试**：`tests/integration/test_offline_evaluator.py`。

### V7.5-014 场景化评估测试套件（P1）

- **目标**：`tests/evaluation/` 声明式场景套件——五维各 ≥2 场景（正例 + 反例），参数化 runner，judge_override 固定 judge 行为。
- **前置**：V7.5-010。
- **涉及文件**：`tests/evaluation/`（新增：conftest / scenarios/*.json / test_scenarios.py）。
- **实现内容**：testing.md §3~§5。
- **验收**：expect_issues 集合相等断言；全部确定性（无真实 LLM）；单命令可跑。
- **测试**：`tests/evaluation/test_scenarios.py`。

### V7.5-015 真实模型人工回归清单（P2，仅文档）

- **目标**：`docs/roleplay-v7.5/regression-checklist.md`——五维人工场景核对表（OOC / 情绪 / 记忆 / 动作 / 主动各一组，轮次表格 + 核对点），含词表误报率抽查项。
- **前置**：V7.5-014。
- **实现内容**：testing.md §7；组织方式沿用 V4 回归清单。
- **验收**：清单文档化。

## 依赖图

```text
V7.5-001 域模型+配置 ─┬─ 002 表+仓储 ─────────────────────────┐
                      ├─ 003 Context 收集 ──┬─ 009 Judge 链 ┐ │
                      └─ 004 Rule 引擎 ──┬─ 005 Behavior 规则 │ │
                                         ├─ 006 Persona 规则 │ │
                                         ├─ 007 Emotion 规则 │ │
                                         └─ 008 Memory 规则  │ │
                                                             ▼ ▼
                                        010 Engine + post_process 挂载（P0 收口）
                                                             │
                              ┌──────────────┬───────────────┼──────────────┐
                              ▼              ▼               ▼              ▼
                        011 Proactive   012 Debug API   013 Offline    014 场景套件
                              └──────────────┴───────────────┴──────────────┘
                                                             ▼
                                                   015 真实回归清单（P2，仅文档）
```

## 提交节奏

- 每 Task 独立 commit + push，格式 `feat: V7.5-XXX <中文描述>`。
- V7.5-010 是 P0 收口点：合并前必须全量回归零失败（既有约 795 测试 + 新增）。
- P0 链（001→010）完成后系统即具备实时评估能力；P1 六项可连续推进；015 最后执行。
