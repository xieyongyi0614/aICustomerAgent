# v2.0.0 TASKS-AUDIT（Tasks 全量审计与重构报告）

> 审计范围：docs/version/v2.0.0 全部 Architecture / Design / Tasks / Evaluation 文档 + v1.0.0 代码事实核对。本次属 Architecture / Planning / Task Design，未写任何业务代码。

## 1. 当前 Tasks 的主要问题（按严重程度）

### P0（阻断 AI Coding 执行 / 验收）

| # | 问题 | 证据 | 处置 |
|---|---|---|---|
| P0-1 | Task Schema 缺 9 个工程字段：Problem / Non-Scope / LLM Usage（调用条件/次数/重试/fallback/前台禁令）/ State Machine / Idempotency / Error Handling / Observability 六问 / Regression / 版本兼容声明 | 原 6 份 tasks.md 仅 12 字段 | 全量按新 Schema 重写（§2） |
| P0-2 | 无 per-Phase Evaluation 门槛与 Regression Gate，验收停留在描述性语句 | 原 evaluation.md 只有全局指标无 Phase Gate | 新增 6 份 evaluation.md + 6 份 regression-checklist.md |
| P0-3 | 无 Dependency Graph：跨 Phase 依赖只散落在各 Task Dependencies 字段 | — | 新增 dependency-graph.md（7 张图） |
| P0-4 | 无 Version Boundary：Task 无法判断「哪些 v1 模块不许动」 | — | 新增 version-boundary.md（Preserve/Extend/Replace/Deprecated 逐模块） |

### P1（影响并行开发 / 闭环完整性）

| # | 问题 | 证据 | 处置 |
|---|---|---|---|
| P1-1 | 可并行性未编码：REF-001/DEV-001/AUT-001 纯存储 Task 被暗示必须等前 Phase 完成 | 原 Dependencies 注释含糊 | dependency-graph.md §1 并行矩阵 + 各 tasks.md 并行声明 |
| P1-2 | Design→Task 断层：domain-boundaries 裁决「Context 读高置信 Insight」，无 Task 承接 | domain-boundaries §1 Reflection「被谁调用」列 | 新增 REF-007 |
| P1-3 | §九主动闭环：Life Loop 周期内 Memory Retrieval / Reflection Check 两步无 Task 承接 | 原 LIFE 集只有 trace 版 LIFE-005 | LIFE-005 明确承载两步（trace 归 LIFE-006） |
| P1-4 | §十四 Autonomy 预算硬顶（深度/数量/LLM 次数/最长周期/失败重试）未入 Task | 原 AUT Task 只有部分 | AUT-002/003 全部硬顶入 Scope 与 Acceptance |
| P1-5 | §十成长闭环（调制→重复行为→新经历→再反思）无验证手段 | — | 新增 DEV-006（验证性 Task） |
| P1-6 | Task 层级平铺，无 Capability 分层与 Milestone 交付序 | — | 各 tasks.md 增 Capability Map + Milestone |

### P2（改进项）

| # | 问题 | 处置 |
|---|---|---|
| P2-1 | 部分 Task 的 Acceptance Criteria 非验证式（如「幂等重放测试」无断言） | 全部改为「给定 X 当 Y 那么 Z」 |
| P2-2 | REL 迁移脚本无归属 | 裁决并入 REL-001 Scope（粒度足够，不独立成 Task） |
| P2-3 | MEM 候选/Job 清理散落 | 明确归 MEM-009（job 状态机含终态） |

## 2. 修改了什么

- **Task 拆分/新增**：+MEM-011（Working Memory 分层装配）、+REF-007（Insight→Context 注入）、+DEV-006（成长闭环验证）；共 11+7+6+4+6+5 = **39 Task**（原 36）。
- **Task 重写**：6 份 tasks.md 全量按 22 字段 Schema 重写，编号保持稳定（不乱改引用）。
- **依赖调整**：dependency-graph.md 区分「运行时启用依赖」（实线）与「开发期结构依赖」（虚线，可并行）；Enablement 串行链（6 个 Flag 顺序）与开发并行解耦。
- **Domain Boundary 调整**：无实质调整（原矩阵已单向化）；本次将「跨域写入只走 Ingest/Outbox/事件订阅」5 条合法路径固化为 dependency-graph §5 + 各 Task Domain Boundary 字段。
- **LLM Boundary 调整**：每个 LLM 调用点补齐 Trigger/Input/Output/Validation/Budget/Fallback/Trace 七要素（REF-004/AUT-002 为样板）；新增「LLM Usage: NONE」显式声明覆盖全部纯规则 Task（约 30/39）。
- **Evaluation 补充**：6 份 Phase Gate（每指标有测法与数值门槛）；场景集编号化（E-MEM/REF/DEV/REL/LIFE/AUT）。
- **Regression 补充**：6 份 checklist（Golden 行为 + v1 版 checklist 映射硬门 + 执行步骤）。
- **Trace 补充**：MEM-008/REF-006/DEV-005/LIFE-006/AUT-005 统一六问要求。

## 3. 哪些内容保持不变（防止无意义重构）

- **六 Phase 划分不变**：依赖真实顺序（Memory→Reflection→Development→Relationship→Life Loop→Autonomy）经审计成立，不调整（README §8 已有调整说明）。
- **Task 编号体系不变**：MEM/REF/DEV/REL/LIFE/AUT 前缀与既有编号全部保留，跨文档引用零破坏。
- **架构文档主体不变**：architecture/ 8 篇、migration、self-review 全部保留；本次仅 1 处同步修改（见 §4）。
- **Feature Flag 清单不变**：6 总闸 + 2 子闸（migration §4）。
- **v1.0.0 目录与代码零改动**。

## 4. 哪些 Architecture / Design 需要同步修改

| 文件 | 章节 | 修改 | 状态 |
|---|---|---|---|
| architecture/context-architecture.md | §1 分层表 | 补注：Insight 经 REF-007 只读接口在 P2 即可注入（高置信、预算内）；「P2 Development 摘要段（P3 后）」指 DEV-003 的调制摘要，两者不冲突 | ✅ 本次已改 |
| architecture/character-runtime.md | §1 Runtime 组成 | 无需改（Action 默认启用由 P5 子闸承载的表述与 migration 一致） | 无需 |
| architecture/evaluation.md | §1 | Phase Gate 拆分下沉至各 phases/*/evaluation.md，全局文件保留为指标体系总纲（不重复维护） | 无需 |
| phases/phase-4 tasks REL-001 | Scope | 迁移脚本归属裁决（原 Design 未提）已在 Task 内记录 Inconsistency 裁决 | ✅ 已记录 |

## 5. 新的 Phase Dependency

见 [dependency-graph.md](dependency-graph.md) §1/§2（Mermaid 图）。摘要：P1 为唯一无依赖起点；REF-001/DEV-001/AUT-001 可在 P1 期间并行；REL-001~002 仅依赖 P1；Enablement 串行链：memory → reflection → development → relationship → life_loop → autonomy_advanced。

## 6. 新的开发顺序

```text
第 1 批（立即可开工，互相并行）:
  MEM-001 ｜ REF-001 ｜ DEV-001 ｜ AUT-001        ← 全部纯存储/Foundation
第 2 批（MEM-001 后）:
  MEM-002 → MEM-003 → {MEM-004, MEM-005} ∥ MEM-009
第 3 批:  MEM-006/007/011 ｜ REF-002→003→004     ← REF 需 MEM-006
第 4 批:  REF-005/007 ｜ DEV-002→003→004 ｜ REL-001→002（仅需 P1）
第 5 批:  P1 验收（MEM-010 + Gate）→ 灰度 v2_memory_enabled
  同时: LIFE-001→002→{003,004}
第 6 批:  REL-003/004 ｜ DEV-005/006 ｜ REF-006 → P2/P3/P4 灰度
第 7 批:  LIFE-005/006 → P5 验收 → v2_life_loop_enabled
第 8 批:  AUT-002→003→004→005 → P6 验收 → v2_autonomy_advanced_enabled → v2.0.0 全量
```

**进入 Coding 的条件**：对应 Task 的全部 Dependencies 达到「运行时启用依赖」或「结构依赖」状态；Architecture References 齐备；对应 Phase 的 evaluation.md 门槛可执行。每个 Task 可直接由本 Schema 生成 Coding Prompt（Objective/Scope/Non-Scope/Data Changes/Runtime Flow 为 Prompt 骨架，Acceptance Criteria + Testing 为验收输入）。

## 7. 风险（本次重构特别关注项）

| 风险 | 防线（Task 级落点） |
|---|---|
| Memory 污染 | MEM-003 评估门槛 + MEM-002 词表拦截（R3）；E-MEM-05 拦截率 100% |
| LLM 成本 | 每个 LLM Task 的 Usage 七要素硬顶 + LIFE-003 日配额熔断；E-LIFE-03 |
| 角色行为漂移 | DEV-002 封顶 + DEV-005 归因率 100% + DEV-006 闭环验证 |
| Autonomy 无限循环 | LIFE-001 attempt_count + LIFE-003 Idle/预算 + R8 |
| Goal 无限重试 | AUT-003 失败阈值→failed + AUT-002 ≤3 次 LLM 封顶 |
| Reflection 幻觉 | REF-004 三闸 + REF-005 回收 + E-REF-03 误报率 0 |
| Development 过度调制 | DEV-002 仲裁与封顶 + DEV-004 回退重放 |
| Relationship 真相源冲突 | REL-001 单向转写（禁直写）+ E-REL-01 审计 + V8.5 字节级硬门 |
| v1 Regression | 6 份 checklist 的 Golden 字节级断言 + Flag OFF 双态验证；version-boundary Preserve 红线 |

## 8. 自检结论（任务书 §二十一）

| 检查项 | 结论 |
|---|---|
| Architecture→Design 一致 | ✅（1 处断层已补 REF-007 并同步 context-architecture.md） |
| Design→Tasks 全覆盖 | ✅ 39 Task 覆盖全部架构能力；无 Task 超出 Architecture（REL-001 迁移脚本裁决已记录） |
| Tasks→Evaluation | ✅ 每能力有编号指标与门槛 |
| Tasks→Coding Prompt | ✅ Schema 22 字段可直接生成 |
| Task→Trace | ✅ 六问 trace 归属 Task 明确 |
| Task→Regression | ✅ 每 Phase 硬门 + Golden 字节级 |
| Cross Domain | ✅ 5 条合法写入路径，其余按违规 |
| LLM 必要性 | ✅ 30/39 Task 显式 NONE；其余有硬顶 |
| Failure / Idempotency / Flag | ✅ 全 Task 字段化 |

