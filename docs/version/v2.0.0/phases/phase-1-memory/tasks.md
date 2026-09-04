# Phase 1 Tasks — Memory 2.0

> 编号 MEM-xxx。Task 描述「做什么」，不写代码。所有 Task 完成后需通过 evaluation.md 的 Memory 场景集（离线）。

## MEM-001 数据库与向量基础

- **Priority**: P0
- **Goal**: 建立 Memory 2.0 的存储与索引基座
- **Scope**: alembic 迁移（memories 扩列 + memory_candidates + memory_links + background_jobs）；pgvector 扩展启用与 HNSW 索引；settings 新增开关与参数
- **Dependencies**: 无
- **Input**: design.md §2 数据模型
- **Output**: 迁移 up/down 全可用；NULL embedding 检索可降级
- **Implementation Boundary**: 只增列不改义；不触碰业务代码
- **Acceptance Criteria**: 迁移在 SQLite 兜底库上等价执行（vector 列在 SQLite 走兼容路径）；downgrade 后 v1 行为零差异
- **Testing**: 迁移往返测试；扩列后 v1 全量回归
- **Risk**: pgvector 在开发 SQLite 环境不可用 → 兼容层 + 文档声明生产仅 Postgres

## MEM-002 摄取通道（Ingest）

- **Priority**: P0
- **Goal**: 四源统一生成幂等 MemoryCandidate
- **Scope**: post_process 原记忆抽取步骤改造为 ingest 调用；ActionRecord/WorldEvent/RelationshipEvent 三源接入
- **Dependencies**: MEM-001
- **Input**: turn_analysis 输出、ActionRecord、完结 WorldEvent、RelationshipEvent
- **Output**: memory_candidates 行（带 source_ref 与幂等键）
- **Implementation Boundary**: 不新增 LLM 调用（复用既有抽取输出）；hypothetical/瞬时请求词表拦截在规则层
- **Acceptance Criteria**: 同源重复摄取不产生第二条候选；Roleplay 样本 100% 被标记 hypothetical
- **Testing**: 四源各构造用例 + 幂等重放测试
- **Risk**: 事件源噪声大 → 显著度词表预筛，候选量上限/轮

## MEM-003 评估器（规则优先 + LLM 兜底）

- **Priority**: P0
- **Goal**: 候选 → Active/Rejected，控制 LLM 调用
- **Scope**: 规则打分（显著度/新颖性/类型亲和/源权重）；灰色区间调轻量 LLM 一次；显式 remember 直通
- **Dependencies**: MEM-002
- **Input**: memory_candidates
- **Output**: 转正/拒绝 + reason + trace
- **Implementation Boundary**: LLM 兜底仅限灰色区间；决策记录进 memory trace
- **Acceptance Criteria**: 离线标注集上「用户明确说记住」0 LLM 转正；总体 LLM 兜底率 ≤ 30% 候选
- **Testing**: 标注集（偏好/事实/瞬时/假设/错误信息各 20 条）
- **Risk**: 规则词表覆盖不足 → 兜底兜住 + 词表随评估迭代

## MEM-004 Embedding 批处理

- **Priority**: P0
- **Goal**: 向量列回填且与业务行一致
- **Scope**: embeddings 攒批（≥32 条或 60s）；NULL 补齐；失败重试走 background_jobs
- **Dependencies**: MEM-001, MEM-003
- **Input**: 新转正记忆
- **Output**: embedding 列填充
- **Implementation Boundary**: embedding 服务经 llm_factory 配置；不阻塞前台
- **Acceptance Criteria**: 转正后 5 分钟内向量可用；服务不可用时行保留 NULL 且检索降级正常
- **Testing**: 批量注入 1000 条压测；故障注入
- **Risk**: embedding 服务配额 → 批量 + 退避 + 结构化兜底

## MEM-005 生命周期引擎（Lifecycle）

- **Priority**: P0
- **Goal**: reinforce/merge/supersede/decay/forget 全链路
- **Scope**: lifecycle.py 状态机；衰减周期任务；显式 forget 全通道清除（软删 + 30 天物理删）
- **Dependencies**: MEM-001, MEM-003
- **Input**: 检索命中（reinforce 信号）、新转正记忆（冲突检测）、时钟
- **Output**: 状态迁移 + memory_links + trace
- **Implementation Boundary**: 冲突保守并存（pending）；不硬删
- **Acceptance Criteria**: 用户改口场景旧条目 superseded 且链可溯；显式忘记后向量/结构/上下文全不可见
- **Testing**: 冲突/改口/遗忘场景集；衰减公式数值测试
- **Risk**: 误 supersede 正确记忆 → 保守并存策略 + 评估集回归

## MEM-006 混合检索与排序（Retriever）

- **Priority**: P0
- **Goal**: 语义 + 结构混合检索进入 Context
- **Scope**: retriever.py；context_builder 接线（Flag 内）；检索 trace（各项分数）
- **Dependencies**: MEM-004, MEM-005
- **Input**: query（用户消息 + 意图）
- **Output**: top-k 记忆 + 分数解释
- **Implementation Boundary**: 遵守 context 合并预算 800；不注入 hypothetical
- **Acceptance Criteria**: 改述召回（离线集 recall ≥ 0.8）；v1 关键词路径在子闸关闭时行为不变
- **Testing**: 检索质量标注集；消融（纯结构 vs 混合）
- **Risk**: 向量分数与结构分数失衡 → 权重进 settings 可调 + 离线校准

## MEM-007 显式命令通道（Commands）

- **Priority**: P1
- **Goal**: 「记住/忘掉 X」即时生效
- **Scope**: 意图识别复用 turn_analysis 信号；commands.py 直通生命周期
- **Dependencies**: MEM-005
- **Input**: 用户消息中的显式指令
- **Output**: 立即 Active(salience=1.0) / forgotten
- **Implementation Boundary**: 识别失败静默降级为普通候选（不误删）
- **Acceptance Criteria**: 显式忘记后任何检索通道 0 命中；误识别率 ≤ 评估集阈值
- **Testing**: 指令表述变体集
- **Risk**: 误判「忘记」删除正确记忆 → forget 仅对高匹配度条目生效，其余进候选

## MEM-008 Memory Trace

- **Priority**: P1
- **Goal**: 六问之「为什么记住/没记住/召回这条」可答
- **Scope**: trace_collector 新增 memory_* 步骤；debug API 扩展
- **Dependencies**: MEM-003, MEM-005, MEM-006
- **Input**: 各环节决策
- **Output**: runtime_traces 记录 + debug 查询
- **Implementation Boundary**: 复用 V7.8 trace 体系，不新建存储
- **Acceptance Criteria**: 任一记忆可查「源、转正原因、最近强化、召回分数」
- **Testing**: 端到端 trace 完整性测试
- **Risk**: 无（只读旁路）

## MEM-009 周期任务接入 background_jobs

- **Priority**: P1
- **Goal**: 衰减/补 embedding 任务持久化、可恢复
- **Scope**: 周期任务迁移到 background_jobs 调度；幂等键与重试
- **Dependencies**: MEM-001, MEM-005
- **Input**: 时钟
- **Output**: 可恢复的后台任务
- **Implementation Boundary**: 不改变单进程执行模型（P5 才重构执行器）
- **Acceptance Criteria**: 重启后未完成任务继续执行且不重复
- **Testing**: kill -9 重启演练
- **Risk**: 无

## MEM-010 离线评估与回归清单

- **Priority**: P1
- **Goal**: Phase 验收闭环
- **Scope**: offline_evaluator 扩展 memory 场景集；v2.0.0 regression-checklist 建立
- **Dependencies**: MEM-006, MEM-008
- **Input**: 标注场景集（evaluation.md §2）
- **Output**: 评估报告 + checklist
- **Implementation Boundary**: 只读
- **Acceptance Criteria**: precision/recall/冲突/遗忘四项达标；Flag 关闭 golden 不变
- **Testing**: 全场景集
- **Risk**: 标注集规模不足 → 先 100 条起，随 Phase 累积
