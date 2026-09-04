# v2.0.0 Architecture Self Review

> 任务书 §三十八要求：全部文档生成后自审一次。本文件逐条回答 18 问；每条答案指向对应设计文档的证据位置。审查日期：2026-09-04。

| # | 问题 | 结论 | 依据 |
|---|---|---|---|
| 1 | Domain 是否重复？ | **无重复**。14 个概念裁决后只有 10 个真域：Emotion=State 内值对象、Intention=Decision 输出值对象、Experience=Ingest 投影、Working Memory/Context=Runtime Context、Snapshot/Shared Experience=Projection，均明确「不是 Domain」。 | [domain-boundaries.md](domain-boundaries.md) §1/§2 |
| 2 | 是否存在循环依赖？ | **无**。依赖矩阵全单向：Relationship→Memory 单向、Development←Reflection 单向、Memory 不可读 Relationship 数值、World 零入度、Life Loop 只被 lifespan 调用不被业务域调用。 | [domain-boundaries.md](domain-boundaries.md) §3 |
| 3 | Memory 是否错误控制 Action？ | **否**。Action 只读 Decision 与 Goal；Memory 只以检索结果进入 Context 影响 Generation/Decision 的输入，不直接触发或拦截 Action；周期内 Memory Retrieval 仅提供「想起」，决策权在 AutonomyPolicy（LIFE-005 边界：不写任何域）。 | [character-runtime.md](character-runtime.md) §2.2、[phase-5 README](../phases/phase-5-life-loop/README.md) |
| 4 | Reflection 是否可能产生 False Fact？ | **已三闸拦截**：证据数量门槛（≥3 独立来源）、confidence 阈值、结论类型约束 + 反例字段强制；Insight 可 invalidated/superseded；禁止直写 State/Relationship 数值；Evaluation 有误报率指标；风险条目 R6 持续跟踪。 | [phase-2](../phases/phase-2-reflection/README.md)、[risk.md](risk.md) R6、[evaluation.md](evaluation.md) |
| 5 | Relationship 是否与 Memory 无限互相调用？ | **不可能**。依赖单向化：Relationship 读 Memory 叙事，Memory 域禁止读 relationship 数值；关系事实写入 Memory 走摄取器（ingest），Relationship 域永不直写 memories 表。 | [domain-boundaries.md](domain-boundaries.md) §3（原「Self Review 项 5 答案」即此条） |
| 6 | Life Loop 是否可能无限调用 LLM？ | **不可能**。Idle 判定纯规则 0 调用；周期内 LLM 仅 Decision 命中且预算允许时发生；全局日配额熔断；每周期 loop_runs 记账；周期任务禁止再排周期任务（R8/R9）。 | [phase-5 README](../phases/phase-5-life-loop/README.md) 成本铁律表、[risk.md](risk.md) |
| 7 | Context 是否可能无限增长？ | **不能**。总预算 12000 硬顶不分版本上调；检索是唯一入口；检索类合并预算 800；新增注入段必须申报预算并挤占既有段（R12）。 | [context-architecture.md](context-architecture.md)、[risk.md](risk.md) R12 |
| 8 | 是否存在明显 Token 浪费？ | **已裁剪**：router 并入 turn_analysis（4 链→3 链）；记忆抽取规则预筛（多数轮 0 LLM）；Persona 段前缀缓存；反思证据组窗口截断；目标 Token 成本 ≤ 基线 ×1.2，超线触发重审。 | [llm-orchestration.md](llm-orchestration.md) §3/§4 |
| 9 | 是否存在明显数据库写放大？ | **已防护**：v1 的 last_accessed/reinforce 读路径直写改为内存聚合+批量 flush；快照降频（按日/显著变更）；embedding 攒批（≥32 条或 60s）。 | [data-flow.md](data-flow.md) §5 |
| 10 | Vector DB 是否被错误当成 Source of Truth？ | **否**。SoT 永远是业务表；pgvector 是 Memory 的 Retrieval Index，列可 NULL（降级结构化检索）、可全量重建（rebuild script，R11）。 | [data-flow.md](data-flow.md) §2.2、[risk.md](risk.md) R11、[phase-1 design](../phases/phase-1-memory/design.md) §1 |
| 11 | v2 是否破坏 v1？ | **否**。全部为新增迁移（扩列不改义/新表）；旧代码保留一个观察期；Flag 关闭 = v1 路径字节级恢复；alembic downgrade 仅回滚本 Phase；灾难层有 Postgres 快照。 | [v1-to-v2.md](../migration/v1-to-v2.md) §1/§5 |
| 12 | 每个 Phase 是否可以独立开发？ | **是**。P1 无依赖；REF-001/DEV-001/AUT-001 标注「可提前开发、启用依赖前序」；每个 Phase 有独立 Flag、独立迁移路径、独立完成标准与评估集。 | [roadmap.md](../roadmap.md)、各 phase tasks.md Dependencies |
| 13 | 每个 Phase 是否有明确完成标准？ | **是**。6 个 Phase 各有 4~5 条可验收完成标准（golden 不变 + 指标达标 + 成本红线），并与 evaluation.md 指标一一对应。 | 各 phase README、[roadmap.md](../roadmap.md) |
| 14 | 是否支持 Feature Flag？ | **是**。6 总闸 + 2 必要子闸（v2_memory_vector_enabled / v2_action_outbox_enabled），并明确「禁止碎 Flag」纪律。 | [v1-to-v2.md](../migration/v1-to-v2.md) §4 |
| 15 | 是否支持灰度？ | **是**。影子运行 → 内部账号 → 单用户 → 全量四段灰度，每次推进前过验收门 4 项。 | [v1-to-v2.md](../migration/v1-to-v2.md) §3/§6 |
| 16 | 是否支持回滚？ | **是**。功能（关 Flag）/数据（扩列 NULL 无害 + 幂等键清理）/Schema（downgrade）/灾难（卷快照）四层回滚。 | [v1-to-v2.md](../migration/v1-to-v2.md) §5 |
| 17 | 是否可以逐步上线？ | **是**。Phase 顺序即依赖图（P1→P2→P3→P4→P5→P6），每 Phase 独立可验收可灰度可回滚；前序 Phase 落地后后续 Phase 才能启用的边界已在依赖矩阵中写死。 | [roadmap.md](../roadmap.md)、[README](../README.md) §9 |
| 18 | 当前架构是否为 3.0 留出扩展空间？ | **是**。Domain 经接口对接编排层（多角色可插）；LLM Orchestration 屏蔽模型细节（路由平台可插）；background_jobs/outbox 表即协议（Worker 进程可外移）；Memory SoT 与 Index 分离（独立向量库可换）。 | [overview.md](overview.md) §5 |

## 结论

18 问中无未决项。设计期识别的风险集中在 [risk.md](risk.md) 登记册（R1–R15），实现期每 Phase 复核；本文件在后续 Phase 完成时需重新过一遍并更新结论。
