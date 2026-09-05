# Phase 2 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) REF-001~007 一一对应，无遗漏。所有 Detail 锚定 Phase 1 真实实现（基线：`feat/v2.0.0` @ 7a763d7，MEM-001~011 已全部提交；并行会话在本文档撰写期间落地了 MEM-008~011，相关登记已按新基线更新，见下方记录），未与 v2.0.0 Architecture / Phase 2 architecture.md 冲突，未提前设计 Phase 3~6 能力。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| REF-001 | [REF-001.md](REF-001.md) | Foundation | 无（启用依赖 P1） | migrations/versions 0023→0024、core/db.py Memory ORM 模式、memory2/lifecycle.py 状态机模式（TRANSITIONS/transition）、core/settings.py L92 |
| REF-002 | [REF-002.md](REF-002.md) | Core/Evidence | P1 MEM-006, REF-001 | memory_repository.list_active（L89）、memory_conflict.same_topic（L20）、memory2/retriever.py（cosine/向量解析复刻）、core/settings.py |
| REF-003 | [REF-003.md](REF-003.md) | Core/Triggers | REF-001, REF-002, P1 MEM-009 | memory2/job_worker.py（register_job_type L39 / run_job_tick L52）、repositories/background_job_repository.py（L17）、application/post_process.py `_run_memory_evaluate_v2`（L223）、memory2/lifecycle.py flush_reinforce_buffer（L109） |
| REF-004 | [REF-004.md](REF-004.md) | Core/Reflector | REF-002, REF-003 | chains/structured.py build_structured_chain（L47）、memory2/evaluator.py（结构化链/重试/转正事务模式）、prompts/memory2_evaluator.py 模式、models/memory2.py |
| REF-005 | [REF-005.md](REF-005.md) | Integration | REF-001, REF-004 | memory_conflict.py（同主题/裁决风格）、memory2/ingest.py relation 透传（L142）、memory2/lifecycle.py on_promoted negate 分支（L285）、application/post_process.py |
| REF-006 | [REF-006.md](REF-006.md) | Observability/Evaluation | REF-004（覆盖全链） | trace_collector.py TRACE_STEP_NAMES（L13）、api/v1/debug.py + memory2/attribution.py（MEM-008 已交付）、services/evaluation_rules/__init__.py（RULES L118）、chains/evaluation_judge_chain.py、services/offline_evaluator.py |
| REF-007 | [REF-007.md](REF-007.md) | Integration | REF-001, REF-005 | services/context_builder.py（L40 Flag 分支 + MEM-011 双层装配）、prompts/builder.py（`_fit_variable_parts` L186 / 记忆段 L310）、models/conversation.py（L17）、core/settings.py v2_memory_retrieval_budget（L115） |

---

## 与 Phase 1 实现 / 既有架构的核对记录（冲突与口径登记，不修改架构）

> 按「发现冲突先记录、不自行修改架构」的要求逐条登记。各项均为 Task Detail 内已给出落地口径的偏差/缺口，供实施前评审确认。

1. **MEM-009 已落地（c39cb6e），REF-003 直接复用其执行器协议**。`memory2/job_worker.py` 提供 `register_job_type`（一行注册，处理器须幂等）/ `run_job_worker_loop`（lifespan 第 6 循环，Flag 门控）/ 认领退避重试死信 / 僵尸回收；现有 handler：`memory_decay`、`embedding_backfill`。REF-003 的执行消费以 `register_job_type("reflection_run", ...)` 注册（触发判定与入队协议不变），不再需要自建 lifespan 循环。
2. **reinforce flush 缺口已在 MEM-009 闭合，事件计数的接口扩展仍需**。`run_job_tick`（c39cb6e）每轮先 `flush_reinforce_buffer()` + `embeddings.flush_if_due()` 再认领执行——原「MEM-006 检索路径 reinforce 永不落库」缺口不存在了。REF-003 的事件计数需要 flush 返回**落库 memory_id 列表**（现有返回值 int，job_worker 调用点不读返回值），`int → list[str]` 的最小兼容扩展仍按 REF-003 设计 3 执行。
3. **`memories.type` CHECK 仅 4 类，design.md §3 宣称 7 类**。DB 约束 `ck_memories_type` 与 evaluator `VALID_MEMORY_TYPES` 均只允许 user_preference/user_fact/important_event/relationship_event；`behavior_pattern` 等 3 类未落（Phase 1 实现与 design 的偏差）。Phase 2 不受阻塞（Insight 的 type 是 insights 表自身列）；**P3 需要行为模式供给时必须先扩该约束**，实施前复核最新迁移链（类型扩列已在并行推进中）。
4. **Phase 2 architecture §1 的 `reflection_runs` 列集为最小示意**（id/trigger/evidence_summary/outcome/llm_used/created_at），缺 `user_id/character_id/status` 等多用户隔离与状态机列。REF-001 按「补全不改语义」处理（全库既有隔离惯例 + tasks.md REF-003 状态机必需），已在 REF-001 Detail 中显式标注。
5. **MEM-008 已提交（219d244），REF-006 依赖已满足**。memory/candidate 归因端点与 `memory_*` 步骤族 payload 规范均已交付（`memory2/attribution.py` + debug API）；REF-006 沿同一模式扩展 Insight 归因端点，无前置阻塞。
6. **REF-005 验收「当轮退出 Context」的时序口径**。澄清类识别位于 post_process（后台），当轮回答已用旧 Context 生成——invalidated 的可保证生效点为「处理该澄清之后的所有 Context 装配 0 出现」（REF-007 每轮实时查询 active，天然满足）。REF-005/007 Detail 按此口径落地，tasks.md 验收文本不改动。
7. **「≥3 独立来源」落地口径 = ≥3 个不同 `source_ref`**（不同原始消息/事件），而非 3 个不同 `memories.source` 类型。核心验收场景「10 天内 5 次说累」的记忆全部经 turn_analysis 抽取（source 同为 user_stated），按 source 类型判独立则 E-REF-02 自相矛盾、永远无法达标。source 类型分布保留为统计信号与 REF-004 confidence 折算输入。
8. **MEM-011 已落地（acfbf69），REF-007 直接在其分层装配上接入**。`context_builder.py` 已实现 Working/Long-term 双层装配、检索段 Freshness 序与合并预算 800 贪心裁定（`context_assemble_v2` 预算占用 trace）。REF-007 的 insight 段从「在现有结构上承载、落地后平移」改为**直接在 MEM-011 的合并预算裁定中新增 insight 段参与**（记忆段 + insight 段联合 ≤800 语义不变）。
9. **REF-007「scope 匹配」的具体化**：默认仅注入 `scope ∈ {user, relationship}` 的 Insight（settings 参数化）；`scope=world` 的世界认知注入对话属 P6 Goal 调制范围，P2 不注入。此为对 tasks.md「scope 匹配」的落地解释，不改变其验收语义。

---

## 一致性终检结论（生成时点）

- tasks.md REF-001~007 每个Task 均有 Detail，Task ID 完整一致；M1→M4 交付序与各 Detail 依赖声明吻合。
- 全部 Detail 与 v2.0.0 README/architecture（domain-boundaries/context-architecture/llm-orchestration/data-flow/evaluation/risk）及 Phase 2 architecture.md 的边界裁决一致：Reflection 只写本域三表、只读 memories（active 且非 hypothetical）、禁写 Memory/State/Relationship、LLM 无权定 confidence 终值、每用户每日 ≤1 次反思。
- 全部 Detail 基于 Phase 1 已提交实现（基线 7a763d7，MEM-001~011 齐）设计，未假设不存在的接口；MEM-009/011 落地带来的实施口径变化已按上方记录 1/2/8 回填到对应 Detail。
- 未提前设计 Phase 3~6：Detail 中出现的 Development/Goal/DEV-004 均仅以「订阅点/后续消费方」身份出现，无任何前置实现设计。
