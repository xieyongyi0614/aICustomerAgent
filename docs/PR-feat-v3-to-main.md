# feat/v3 → main：V3~V9 角色智能体能力体系 + 后端架构重构

> 本文可直接作为 Pull Request 描述正文使用。所有数据均在 `feat/v3` 分支实测/核对得出（测试与 pylint 为本次实际执行结果，非文档摘录）。

---

## 一、概述（Summary）

本 PR 将 `feat/v3` 分支合并回 `main`，一次性交付 **V3 ~ V9 七个版本的能力体系** 与 **一轮后端架构重构（REF-001~013）**。

主线目标是把「亚丝娜」从一个**只会接话的聊天机器人**，演进为一个**有场景连续性、有长期记忆、有情绪与目标、能主动开口、且行为可观测可评估的角色 Agent**。V8 起补齐了独立的外部世界层，V8.5 深化关系演化，V9 让角色的「承诺」真正落地为可审计的执行。

七个版本之间为**递进且相互独立**的关系：V3~V7 构建角色内在（场景→记忆→情绪→目标→行为→自主），V7.5/V7.8 叠加**只读旁路**（评估与观测，不干预主链路），V8~V9 补齐外在世界与行动闭环。**所有新增能力均可通过开关关闭，关闭后行为与上一版本逐位一致**（有 golden prompt 字节不变测试保障）。

### 变更规模

| 指标 | 数值 |
|---|---|
| 提交数 | 161（领先 `main`） |
| 变更文件 | 581 files changed，+56,266 / −984 |
| 新增后端源文件 | 321 |
| 新增文档 | 164（含 12 个版本目录下共 162 篇设计文档） |
| 数据库迁移 | 0003 ~ 0021，共 19 个 |
| 后端源码 / 测试 | `app/` 178 个 py 文件 / `tests/` 199 个 py 文件 |
| 前端改动 | 24 files，+748 / −71（Debug 面板为主） |
| **自动化测试** | **1499 passed，8 skipped，6 failed** |
| **pylint** | **8.57 / 10** |

---

## 二、分版本交付内容

### V3 · 场景状态与行为连续性
**解决**：让角色知道「正在做什么、做到哪一步」。

- 维护单一主 PendingAction（如「切西瓜」），跨轮持续推进不跑题
- 用户纠正/取消由代码**确定性迁移**（interrupt→cancelled、correct→激活），不依赖 LLM
- 7 类 SceneIntent 识别，异常/低置信降级为普通聊天
- 回复节奏硬约束（单步 ≤1、动作 ≤2），禁止替用户行动
- Debug 面板实时展示 scene 状态与 trace 三步

<details><summary>关键文件与任务</summary>

- `app/models/scene.py`、`app/chains/scene_intent_chain.py`、`app/chains/scene_update_chain.py`
- `app/services/scene_service.py`、`app/repositories/scene_state_repository.py`
- `migrations/versions/0003_scene_state_table.py`
- 任务 V3-001~009 已实现；**V3-010 仅设计文档（默认不实现）**
- 测试：9 文件 + 七大 Case；人工回归清单「西瓜五轮重放」
</details>

### V4 · 长期记忆系统
**解决**：跨会话记住用户，但不无限膨胀、不把 AI 的猜测当成事实。

- 跨会话记住用户偏好/事实（如「不喝咖啡」）并自然引用
- **AI 推测永不入库存**：`source` 限定 `user_stated` / `user_derived`
- 冲突记忆自动 supersede / invalidate，不产生矛盾双条
- 用户「别记了 / 忘了」→ suppress 零写入或硬删除
- 结构化加权召回（0.45 / 0.25 / 0.20 / 0.10），后台异步不阻塞 SSE

<details><summary>关键文件与任务</summary>

- `app/models/memory.py`、`app/repositories/memory_repository.py`
- `app/services/memory_policy.py`、`memory_conflict.py`、`memory_service.py`
- `migrations/versions/0004_memories_v4_columns.py`、`0009_memories_v4_column_rename.py`
- 任务 V4-001~011 已实现；**V4-012 仅设计文档（200 条软上限方案）**；Policy 规则 R1~R8
</details>

### V5 · 情绪与关系动态
**解决**：情绪与关系可解释、不跳变。

- 情绪改为 `intensity` / `cause` 双字段，两段线性衰减，单轮变化 ≤0.4，强情绪保护
- 关系新增 `tension`，>0.5 冻结升级；三层防跳变阈值 0.17 / 0.15 / 0.30
- `relationship_events` 事件账本逐轮记录实际 impact
- 事件检测链输出 Emotion / Relationship 事件，Prompt 注入情绪段与关系段

<details><summary>关键文件与任务</summary>

- `app/models/emotion.py`、`app/services/state_engine.py`、`app/services/state_service.py`
- `app/repositories/relationship_event_repository.py`、`app/chains/turn_analysis_chain.py`
- `migrations/versions/0005/0006/0007_*`
- 任务 V5-001~013；**V5-013（P2 多事件叠加）结论为「维持单主事件」，仅评估文档，无代码改动**
- 8 值情绪模型；17 项必测聚合用例
</details>

### V6 · 目标与意图
**解决**：角色从「被动反应」转向「主动有目的」。

- Goal 模型（4 类型 / 4 态）+ `character_goals` 持久化与闭环生命周期
- Goal 选择 tier 排序 + 冲突裁决，确定性输出 SelectedGoal
- Intention 12 值枚举 + `IntentionPolicy` 表驱动校验降级
- Goal / Intention 段注入 Prompt（预算 120 / 80）；编排四链并行

<details><summary>关键文件与任务</summary>

- `app/models/goal.py`、`app/services/goal_service.py`、`app/services/intention_policy.py`
- `app/chains/intention_chain.py`、`app/repositories/goal_repository.py`
- `migrations/versions/0008_character_goals_table.py`
- 任务 V6-001~009（P0）全部完成；**V6-010（P1）/ V6-011（P2）仅设计，未实现**
</details>

### V6.5 · 行为精化（Character Behavior Refinement）
**解决**：V6 回答「想做什么」，V6.5 回答「怎么做、用什么方式表现」。

- **Behavior Engine**：意图 → 12 行为策略 + 6 修饰规则；`ActionBudget` 7 步约束单轮 `*动作*` 段数
- **Mode Service**：5 条 stabilize 规则，防止每轮跳变
- **动态 Habit**：关系事件沉淀候选，代码预筛 + **人工确认才生效**，绝不自动生效
- **Response Style Controller**：渲染【表现方式】【活动延续】段

<details><summary>关键文件与任务</summary>

- `app/models/behavior_strategy.py`、`app/services/behavior_engine.py`、`app/services/mode_service.py`
- `app/prompts/behavior.py`、`app/services/habit_runtime.py`
- `migrations/versions/0010_conversation_mode.py`
- 任务 V6.5-001~012 **全部完成**；V6.5-012 结论 Keep（保留 V2 行为层）
- 14 Case 测试矩阵；本阶段完成时全量 788 passed
</details>

### V7 · 自主行为（Autonomous Behavior）
**解决**：在用户无消息驱动时，受约束地「合理地主动说一句话」。

- Trigger 纯函数（不活跃 / 时间到期）+ `AutonomyPolicy` 八步三值裁决
- `AutonomyEngine` + Executor：outbox 深度 1、锁内二次校验、delivered / 重试
- lifespan tick Worker + `GET /proactive/pending` + `POST ack`
- Proactive Chain 纯文本生成；`scheduled_followup` 记忆触发
- **三重防护**：五条件门 + 冷却 + 静音 + 退避，V2~V6 零回归

<details><summary>关键文件与任务</summary>

- `app/services/autonomy_policy.py`、`app/services/trigger_evaluator.py`
- `app/application/autonomy_engine.py`、`app/application/autonomy_worker.py`
- `app/chains/proactive_chain.py`、`app/api/v1/proactive.py`
- `migrations/versions/0011_proactive_actions_table.py`
- 任务 V7-001~011；**V7-009（前端 P1）按实现边界跳过**；本阶段完成时全量 858 passed
</details>

### V7.5 · 角色一致性评估（Character Evaluation）
**解决**：回答「这个角色做得好不好」——在开环管线上加**质量闭环旁路**。

- 五维评估（persona / emotion / memory / behavior / autonomy）+ 19 个 IssueCode
- Rule Engine 纯函数 + LLM Judge 单次合并强 schema（一层降级）
- `EvaluationEngine` 挂在 post_process 第 7 步，主动消息 delivered 后 fire-and-forget
- `OfflineEvaluator` 从 DB 重建历史并聚合统计；Debug 查询 API
- 声明式场景测试套件（JSON，五维 12 场景，全确定性）

<details><summary>关键文件与任务</summary>

- `app/models/evaluation.py`、`app/services/evaluation_engine.py`、`evaluation_context.py`
- `app/services/evaluation_rules/`（persona / behavior / emotion / memory / autonomy）
- `app/chains/evaluation_judge_chain.py`、`app/services/offline_evaluator.py`
- `migrations/versions/0012_evaluation_reports.py`
- 任务 V7.5-001~015 全部完成（015 仅文档，人工回归待执行）
- 本阶段完成时全量 963 passed + 3 skipped，pylint 8.59，配置 20 项
</details>

### V7.8 · 角色运行时智能（Runtime Intelligence Layer）
**解决**：回答「它为什么是这样」——为黑盒管线加**过程观测旁路**。

- Runtime Trace 持久化（write-behind、error 必存、DB 回退）
- LLM Call 记录（延迟 / token / 成本 / 错误）、Prompt Snapshot（**字节不变硬闸**）
- Decision History（trigger→policy→action）、Turn 级决策采集
- Metrics 派生聚合 + Evaluation Correlation（`request_id` 贯通，评估报告可反查现场）
- **热路径性能护栏**：无 IO 负向注入 / 开销预算 50ms·轮 / 关闭即现状 / prompt 字节不变
- Prompt 比较 API、低质量下钻查询

<details><summary>关键文件与任务</summary>

- `app/models/observability.py`、`app/application/observability.py`
- `app/services/observability/`（llm_capture / prompt_capture / metrics_aggregator）
- `app/api/v1/debug.py`、`migrations/versions/0013~0016_*`
- 任务 V7.8-001~015；**V7.8-014（P2 Metrics 周期快照）按设计留白，未实现**
- 本阶段完成时全量 1034~1050 绿，pylint 8.52，配置 13 项
</details>

### V8 · 世界状态系统（World State System）
**解决**：给角色一个**独立持久的外部世界层**（时间 / 地点 / 物品 / 环境 / 事件），消除跨轮世界事实不一致。

- **World 与 Character 严格分离**：World 只产出事实，零写回角色状态
- 物品状态机 + 数量 / 过期演化，跨会话持久化
- **确定性规则解释器**（拿 / 切 / 吃 / 买 / 地点迁移 / 天气），LLM 辅助链默认关闭
- 事件全生命周期 + due 触发 + lifespan 维护循环
- 世界切片进 Prompt（**空世界时 golden 字节不变**）；事件完结 → 记忆候选；`world_facts` → 自治只读事实
- 快照回滚 + 历史查询；V8-015 World Consistency 评估规则（`ISSUE_CODE_COUNT` 19→20）

<details><summary>关键文件与任务</summary>

- `app/models/world.py`、`app/application/world_engine.py`、`app/repositories/world_repository.py`
- `app/services/world/`（interpreter / context_selector / time_provider / locations / memory_bridge）
- `app/api/v1/world.py`、`app/character/asuna/world.py`
- `migrations/versions/0017_world_tables.py`（四表）
- 任务 V8-001~015 **全部完成**（015 为实现期新增）；本阶段完成时全量 1120+ 绿；`world_*` 配置 17 项
</details>

### V8.5 · 关系演化系统（Relationship Evolution System）
**解决**：深化 V5 关系域，补齐维度、演化动力学、里程碑与冲突生命周期。

- **5+1 维模型**（新增 respect / comfort），阶段体系冻结不变
- `InteractionSignal` 信号识别（词表启发式，**P0 零新增 LLM 调用**）
- `evolve` 纯函数引擎：动力学修饰 + 三级限速 + 同事务落账，**可重放**
- 里程碑注册表、冲突六态状态机、疏远检测、张力消退
- 关系记忆投递 + 行为 / 自治集成（R 规则）+ 快照回滚；默认态 golden 字节不变

<details><summary>关键文件与任务</summary>

- `app/services/relationship_{signal,evolution,milestone,conflict,memory}.py`
- `app/repositories/relationship_{milestone,conflict,snapshot}_repository.py`
- `app/services/evaluation_rules/relationship.py`、`app/character/asuna/relationship_lexicon.py`
- `migrations/versions/0018/0019/0020_relationship_*`
- 任务 **V8.5-001~008 已实现**（提交 `0c8b230` 001~006、`9649beb` 007、`f9cfa6a` 008）
- `rel_*` 配置 23 项；`tests/v8.5/` 七文件 83 用例
</details>

### V9 · 行动能力系统（Action Capability System）
**解决**：让角色的「承诺」真正落地为可审计的执行 —— **Action ≠ Response**。

- **确定性检出 + 六闸门 + 计划装配**：零新增 LLM 调用，不引入 Tool Calling
- Capability Registry + 四个真实能力（reminder / memory / world_action / environment_query），search / notification 为 `unavailable` 占位
- Executor 超时 / 重试退避 / 幂等；`ActionRecord` 六态生命周期
- 结果四通道整合（世界 / 记忆 / 关系 / 行动上下文段）+ lifespan 重试维护循环
- 行动评估三规则（overclaim 等）+ `/debug/actions` 审计端点；due 提醒 → 自治触发器

<details><summary>关键文件与任务</summary>

- `app/models/action.py`、`app/application/action_engine.py`、`app/repositories/action_repository.py`
- `app/services/action/`（detector / planner / registry / executor / context / time_parse / memory_bridge / relationship_bridge）
- `app/services/action/capabilities/`、`app/api/v1/action.py`、`app/services/evaluation_rules/action.py`
- `migrations/versions/0021_action_records.py`（设计文档原写 0018，因 V8.5 占用 0018~0020 而顺延）
- 任务 **V9-001~010 已实现**（`4027cb0` / `7e353a1` / `d0bf2cb` / `c7bb662` / `2b18409`，另 `3082a2f` 修复 self-duplicate 门控）
- `action_*` 18 项 + `autonomy_action_*` 2 项；`tests/v9/` 十五文件 71 用例、scenarios 三条主线
</details>

---

## 三、后端架构重构（REF-001~013）

与功能版本并行完成的一轮架构治理，目标是**消除上帝对象、收口边界、补齐一致性与可观测性**。全程「功能不变、API 不变、schema 不变、Prompt 行为不变」。

| 阶段 | 任务 | 内容 |
|---|---|---|
| Phase 1 止血 | REF-001 | 修复 Prompt 模板注入崩溃：用户消息含 `{...}` 不再导致 `KeyError` 500 |
| | REF-002 | 日志脱敏：INFO 级不再输出对话原文与记忆候选内容 |
| | REF-003 | forget 隐私指令补偿：删除失败重试并记 error trace，不静默 |
| | REF-004 | 配置收编与死代码清理：阈值/魔法数归位 settings |
| Phase 2 编排与边界 | REF-005 | ChatPipeline 编排拆分：新增 `app/application/chat_pipeline.py`，`agent_service` 瘦身为兼容壳 |
| | REF-006 | PostProcess 编排拆分：`STEP_HANDLERS` 注册表 + `schedule_post_process`，**新步骤零侵入接入**（V8 第 8 步、V9 第 9 步均由此挂载） |
| | REF-007 | Context 总预算：Prompt 总量有硬上界 |
| | REF-008 | API 分层收口：api 不再直连 repository |
| Phase 3 一致性 | REF-009 | 账本-状态同事务：`relationship_events` 与状态不再部分成功 |
| | REF-010 | 并发写串行化：per-user `asyncio.Lock`，消除 lost update |
| | REF-011 | Observability 增强：能回答「这轮为什么 OOC」 |
| Phase 4 清理 | REF-012 | 遗留与边界清理：V1 extract / MemoryDecision 链退役 |
| | REF-013 | 测试分层与 Golden Prompt 回归 |

补充：`memories` 列物理改名（迁移 0009，`memory→content`、`memory_type→type`），删除 V1 兼容层。

> **架构意义**：REF-006 建立的 `STEP_HANDLERS` 扩展点，是后续 V7.5（第 7 步）、V8（第 8 步）、V9（第 9 步）能够以**纯加法**接入的关键——这也是本 PR 能保持「增量、可回滚」的结构性原因。

---

## 四、功能开关与默认值（评审重点）

新增能力**全部可关闭**，关闭后行为与上一版本逐位一致：

| 开关 | 默认值 | 说明 |
|---|---|---|
| `world_enabled` | **true** | V8 世界层默认启用；空世界时 prompt 字节不变 |
| `rel_evolution_enabled` | **true** | V8.5 演化默认启用；默认态与 V5 逐位一致 |
| `action_enabled` | **false** | **V9 行动总开关出厂关闭**（有外部副作用）；关闭时全链路回到 V8.5 |
| `action_detector_enabled` | true | 仅受总开关约束 |
| `action_relationship_enabled` | **false** | 行动 → 关系信号默认关 |
| `autonomy_action_enabled` | **false** | 自治产行动分支默认关，仅接口预留 |

**评审结论**：除 `world_enabled` / `rel_evolution_enabled` 外，有外部副作用或影响关系演化的开关均默认关闭，可安全合并后灰度开启。

---

## 五、测试与质量现状（本次实测）

```
pytest tests/          1499 passed, 8 skipped, 6 failed   (177.67s)
pylint app             8.57 / 10
```

- 测试分层：`tests/unit` 77 + `tests/integration` 57 + `tests/e2e` 28 + 版本套件（`v7.8` 3 / `v8` 7 / `v8.5` 7 / `v9` 14）+ `evaluation` + `golden`
- 每个版本均有独立任务注册表与 `regression-checklist.md`（V3~V9 共 10 份）
- pylint 主要扣分点为 4 处 `R0401 cyclic-import`（`app/services/evaluation_rules/` 与 `app/services/world/` 包间）

---

## 六、⚠️ 合并前必须处理：6 个失败用例（两个缺陷，非同一根因）

自动化测试**当前非全绿**：6 failed。

> **本节已更新**：初版判断这 6 个失败是同一根因（`ValueError` 解包崩溃）。修复后复测发现 6 个仍全部失败，进一步排查确认**主因是另一个更深的缺陷**。下方两个缺陷均已核实。

### 缺陷一：关系状态落库失败（**主因，未修复**）

```
app/services/state_service.py:275          in apply_and_save
app/repositories/relationship_repository.py:95  in commit_relationship_update
    session.refresh(row)
sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<RelationshipStateRow>'
```

- **后果**：每轮关系状态与事件账本**均未写入数据库**，系统退回上一轮状态（日志：`关系状态与事件账本落库失败，保持上一轮`）。
- **隐蔽性**：异常被 `try/except` 吞掉，只打 ERROR 日志，不向上抛出。因此测试表现为「等不到预期结果」而非断言失败，需耗到 `wait_until` 超时——**单个用例约 150 秒**，这是测试套件显得异常缓慢的直接原因。
- **影响面**：涉及关系状态写入的 e2e 路径均受影响；V8.5 的关系演化结果实际未被持久化，等于该能力未真正生效。
- **待查方向**：`RelationshipStateRow` 在 `session` 中处于不可刷新状态（通常为对象未与当前 session 正确关联，或 V8.5 新增字段后 ORM 映射/迁移未同步）。需比对 `app/core/db.py` 的 `RelationshipStateRow` 定义与 `migrations/versions/0018_relationship_v85_state.py`。

### 缺陷二：关系快照 trigger 解包崩溃（**已修复**）

**失败用例**

| 用例 | 隔离复现 |
|---|---|
| `tests/e2e/test_state_e2e.py::test_full_degradation_uses_default_analysis` | ✅ |
| `tests/e2e/test_proactive_api.py::test_pending_lists_delivered_and_ack_transitions` | ✅ |
| `tests/integration/test_autonomy_matrix.py::test_case14_scenario_full_chain` | ✅ |
| `tests/e2e/test_debug_proactive_correlation.py::test_debug_proactive_correlation_bundle` | ✅ |
| `tests/e2e/test_debug_state_history.py::test_state_reflects_turn_and_respects_limit` | ✅ |
| `tests/e2e/test_state_e2e.py::test_stage_upgrade_after_share_goal_turns` | ❌（仅全量跑时失败，疑似顺序/并发相关，需另行确认） |

**根因：类型断言失效导致解包崩溃**

```
app/services/state_service.py:412   in _capture_snapshot_if_needed
    old_status, new_status = conflict_transition
ValueError: not enough values to unpack (expected 2, got 0)
```

- `_capture_snapshot_if_needed` 的形参声明为 `conflict_transition: tuple | None`，按 `(old_status, new_status)` 二元组解包
- 但调用方（`state_service.py:356 / 390`）传入的是 `conflict_outcome.transition`，其定义在 `relationship_conflict.py:29` 为 **`transition: str = ""`**
- 判空逻辑写的是 `elif conflict_transition is not None:`，而**空字符串 `""` 不是 `None`**，因此空串照样进入分支并解包失败

**影响面**：该函数在每轮关系更新末尾被**无条件调用**；凡本轮 stage 未发生跃迁的回合都会命中该分支，V8.5 的「快照回滚」能力在该路径下未真正生效。

**已实施的修复**（采用方案 2，因 `transition` 语义就是具名迁移类型，且已确认无测试断言旧的 `conflict:old→new` 格式）：

```python
# app/services/state_service.py
-    conflict_transition: tuple | None,
+    conflict_transition: str,
...
-    elif conflict_transition is not None:
-        old_status, new_status = conflict_transition
-        trigger = f"conflict:{old_status}→{new_status}"
+    elif conflict_transition:
+        trigger = f"conflict:{conflict_transition}"
```

同时补充了防回归单测 `tests/unit/test_state_service_snapshot.py`（覆盖「无冲突不写快照」「有冲突 trigger 正确」「stage 跃迁优先级高于 conflict」三种情形，4 个用例已通过）。

> **注意**：修复本缺陷**不会**让那 6 个用例转绿——它们的主因是缺陷一。但本修复是必要且正确的，它同时消除了掩盖缺陷一的一层噪声。

---

## 七、其他注意事项

1. **文档状态头已过期**：`AGENTS.md` 与 V8.5 / V9 的 `tasks.md` 状态头仍写「设计完成、待实现」，但 git 提交与磁盘代码证明两者**均已落地**。建议本 PR 一并修正状态头，避免后续误判。
2. **设计留白项**（非缺陷，按设计不做）：V3-010、V4-012、V6-010、V6-011、V7-009、V7.8-014。
3. **人工回归待执行**：V6.5、V7.5、V7.8、V8、V8.5、V9 的真实模型人工回归清单尚未实操（如 V6.5 的「单轮动作 ≤ 预算轮次占比 ≥90%」「违规计数一致率 ≥95%」为目标值，**未实测**）。自动化全绿不等于体验达标，建议合入后按 `docs/roleplay-v*/regression-checklist.md` 逐条执行。
4. **迁移顺序**：0003 → 0021 必须按序执行，V9 迁移号已因 V8.5 占用而顺延至 0021，注意环境间迁移头一致性。
5. **前端**：Debug 面板新增 scene / memory / state / observability 相关展示，24 文件 +748/−71，随后端能力同步。

---

## 八、给 Reviewer 的建议顺序

1. 先看**第四节「功能开关与默认值」**，确认新增能力可关闭、默认态无副作用；
2. 再看**第六节「6 个失败用例」**——这是本 PR 唯一的阻塞项，建议要求修复后再合入；
3. 按版本抽查：`V8`（世界层，改动最大）→ `V9`（有外部副作用，默认关）→ `V8.5`（关系演化，与失败根因相关）→ `V7.5 / V7.8`（只读旁路，风险最低）；
4. 架构关注点集中在 `app/application/`（编排层）与 `post_process.py` 的 `STEP_HANDLERS` 挂载点。

---

## 九、回滚方案

所有新增能力由开关控制，出问题可分级降级、无需回滚代码：

1. 关 `action_enabled` → 回到 V8.5 行为
2. 关 `rel_evolution_enabled` → 回到 V5 关系行为
3. 关 `world_enabled` → 回到 V7.8 行为（空世界时 prompt 字节不变，已验证）

数据库迁移为**纯新增表/列**，无破坏性变更，回滚代码后遗留表不影响旧逻辑运行。
