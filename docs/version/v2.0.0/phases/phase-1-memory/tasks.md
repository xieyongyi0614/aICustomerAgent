# Phase 1 Tasks — Memory 2.0

> Schema：每个 Task 含 Objective/Problem/Scope/Non-Scope/Inputs/Outputs/Dependencies/Architecture References/Domain Boundary/Data Changes/Runtime Flow/LLM Usage/State Machine/Idempotency/Feature Flag/Error Handling/Observability/Testing/Acceptance Criteria/Regression/Evaluation/Risk。
> Capability 分层：Foundation → Core → Integration → Observability → Evaluation。依赖图见 [../../dependency-graph.md](../../dependency-graph.md)。

## Capability Map

```text
Foundation:   MEM-001（存储/索引/开关）
Core:         MEM-002 Ingest / MEM-003 Evaluator / MEM-004 Embedding / MEM-005 Lifecycle
Integration:  MEM-006 Retriever→Context / MEM-007 显式命令 / MEM-011 Working Memory 接线
Infra:        MEM-009 background_jobs
Observability:MEM-008 Trace
Evaluation:   MEM-010 Eval + Regression Gate
```

---

## MEM-001 存储与向量基座（Foundation）

- **Priority**: P0
- **Objective**: 建立 Memory 2.0 全部存储、索引与开关基座
- **Problem**: 后续所有 Memory Task 依赖扩列、三张新表与 pgvector 索引；无基座则 Ingest/Evaluator 无处落笔
- **Scope**: alembic 迁移（memories 扩列 embedding/salience/last_reinforced_at/merge_chain/source_ref/visibility + memory_candidates/memory_links/background_jobs 三新表）；pgvector 与 HNSW 索引；settings 全量 v2_memory_* 开关与参数
- **Non-Scope**: 不写业务逻辑；不改既有列语义；不引入独立向量库（version-boundary Preserve 约束）
- **Inputs**: [design.md](design.md) §2；settings 现有结构
- **Outputs**: 可 up/down 的迁移 + 全量配置项
- **Dependencies**: 无
- **Architecture References**: design.md §2；[../../architecture/data-flow.md](../../architecture/data-flow.md) §2.2；[../../version-boundary.md](../../version-boundary.md) §1 memories 行
- **Domain Boundary**: Infrastructure（表属 Memory Domain；background_jobs 为横切基础设施）
- **Data Changes**: memories 扩 6 列；新表 3 张；唯一键 candidates(source_table,source_id)、jobs(idempotency_key)；downgrade 完整还原
- **Runtime Flow**: alembic upgrade → 扩列/建表 → 索引生效（无运行时行为变化）
- **LLM Usage**: NONE
- **State Machine**: background_jobs.status: pending→running→done|failed（定义供 MEM-009 使用）
- **Idempotency**: 迁移按 alembic 版本号幂等；扩列 NULL 兼容 v1 代码
- **Feature Flag**: 定义 `v2_memory_enabled`/`v2_memory_vector_enabled`，default=false
- **Error/Failure**: 迁移失败→downgrade 干净；SQLite 兜底库走 vector 兼容路径
- **Observability**: alembic 既有日志
- **Testing**: Unit=迁移往返；Integration=扩列后 v1 全量回归零差异
- **Acceptance Criteria**: 给定 v1 数据库，当 upgrade→downgrade→upgrade，那么 v1 表数据逐行相等且 v1 服务全部测试通过
- **Regression**: v1 全量 pytest（基线）
- **Evaluation**: 无（结构 Task）
- **Risk**: pgvector 与 SQLite 兜底不兼容→兼容层 + 文档声明生产仅 Postgres

## MEM-002 统一摄取通道（Core / Ingest）

- **Priority**: P0
- **Objective**: Conversation/ActionRecord/WorldEvent/RelationshipEvent 四源统一生成幂等 MemoryCandidate
- **Problem**: v1 只有对话抽取单源，事件经历沉淀通道断裂（v1 审计问题 2）；不统一则 Reflection/Relationship 无证据来源
- **Scope**: post_process 抽取步骤改造为 ingest 调用；ActionRecord/WorldEvent/RelationshipEvent 三源接入；Roleplay/瞬时请求词表拦截；visibility 标记
- **Non-Scope**: 不做评估判定（MEM-003）；不新增 LLM 调用；P5 前事件源直读表（outbox 属 LIFE-004）
- **Inputs**: turn_analysis 输出、ActionRecord、完结 WorldEvent、RelationshipEvent 变更
- **Outputs**: memory_candidates 行（content/proposed_type/source/source_ref/salience 初值/visibility）
- **Dependencies**: MEM-001
- **Architecture References**: [architecture.md](architecture.md) §2；design.md §5；[../../architecture/data-flow.md](../../architecture/data-flow.md) §3
- **Domain Boundary**: Memory（只写 memory_candidates；读四源投影；禁止读 relationship_state 数值）
- **Data Changes**: 无新表；写 memory_candidates
- **Runtime Flow**: 源事件 → 词表预筛(hypothetical/瞬时拦截) → source_ref 组装 → 幂等查重 → INSERT candidate → trace
- **LLM Usage**: NONE（复用既有 turn_analysis/extractor 产物；v1 extractor 链保留并前置规则预筛）
- **State Machine**: memory_candidates.status: pending（唯一合法初始态）
- **Idempotency**: key=(source_table, source_id)；重放=已存在直接返回；重启=无内存态天然恢复
- **Feature Flag**: `v2_memory_enabled`，OFF=走 v1 extractor 原路径（baseline 字节级不变）
- **Error/Failure**: DB 失败→回滚，post_process 该轮记 failed 不阻塞；source 缺失→丢弃+trace
- **Observability**: trace 步骤 memory_ingest（源/拦截原因/候选 id）；debug API 列候选
- **Testing**: Unit=词表拦截表驱动；Integration=四源用例；Idempotency=同源重放两次行数不变；FailureInjection=DB 断连恢复
- **Acceptance Criteria**: 给定「假装我是国王」，当摄取发生，那么候选 visibility=hypothetical；给定同一 ActionRecord 重复摄取，那么 candidates 行数恒为 1
- **Regression**: V4 memory checklist；Flag OFF golden 字节级
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-05
- **Risk**: 事件源噪声大→显著度词表预筛 + 每轮候选量上限

## MEM-003 候选评估器（Core / Evaluator）

- **Priority**: P0
- **Objective**: 候选→Active/Rejected，规则优先、LLM 只兜灰区
- **Problem**: 不设门槛则 v1「什么都存」问题原样带入 v2，Memory 污染（risk.md R3）不可避免
- **Scope**: 规则打分（显著度/新颖性/类型亲和/源权重）；灰区调 lite LLM 一次；显式 remember 直通（与 MEM-007 协作）；决策全量 trace
- **Non-Scope**: 不做生命周期迁移（MEM-005）；不做向量（MEM-004）；LLM 不决定 type（规则映射）
- **Inputs**: memory_candidates（pending）
- **Outputs**: approved（同事务转正入 memories）/rejected（带 reason）/留 pending
- **Dependencies**: MEM-002
- **Architecture References**: design.md §5；[../../architecture/llm-orchestration.md](../../architecture/llm-orchestration.md) §1 记忆转正行；[../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Memory 行
- **Domain Boundary**: Memory（写 memories/candidates/trace；禁写其他域）
- **Data Changes**: 更新 memory_candidates.status；INSERT memories
- **Runtime Flow**: pending 候选 → 规则分 → [≥阈值→转正 | 灰区→Lite LLM ×1 | <门槛→拒绝] → memory trace
- **LLM Usage**: 条件调用；lite 档；触发=规则分落灰区；≤1 次/候选；重试 2 次指数退避；fallback=留 pending；禁止前台调用
- **State Machine**: pending→approved|rejected|pending(重试)；approved 与 memories.active 同事务
- **Idempotency**: 以候选 id 为键；重复评估同一候选不产生第二条 memories
- **Feature Flag**: `v2_memory_enabled`，OFF=整条跳过
- **Error/Failure**: LLM 失败/超时→候选留 pending 重试（max 5 后 rejected+reason）；DB 失败→回滚+job 重试
- **Observability**: memory_evaluate trace（分数明细/LLM 调用与否/决策 reason）——回答「为什么记住/为什么没记住」
- **Testing**: Unit=打分表驱动；Integration=标注集（偏好/事实/瞬时/假设/错误信息各 20 条）；FailureInjection=LLM 500/超时；Idempotency=重放
- **Acceptance Criteria**: 给定显式「记住 X」候选，当评估，那么 0 次 LLM 转正且 salience=1.0；给定离线标注集，当批量评估，那么 LLM 兜底率 ≤30% 且错误信息类 100% 被拦或标低置信
- **Regression**: V4 memory checklist；Flag OFF golden 字节级
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-01/02/03
- **Risk**: 词表覆盖不足→灰区兜底兜住，词表随离线集迭代

## MEM-004 Embedding 批处理（Core）

- **Priority**: P0
- **Objective**: 转正记忆向量回填且与业务行一致
- **Problem**: 语义检索（MEM-006）依赖向量；无批处理则逐条同步 embedding 阻塞后台且写放大
- **Scope**: 攒批（≥32 条或 60s 窗口）；NULL 回填；失败走 background_jobs 重试
- **Non-Scope**: 不做检索打分；不阻塞前台；不把 embedding 当 SoT
- **Inputs**: 新转正 memories（embedding IS NULL）
- **Outputs**: embedding 列填充
- **Dependencies**: MEM-001, MEM-003
- **Architecture References**: design.md §1/§6；[../../architecture/data-flow.md](../../architecture/data-flow.md) §2.2/§5
- **Domain Boundary**: Memory（只更新 memories.embedding）
- **Data Changes**: 无新表；批量 UPDATE embedding
- **Runtime Flow**: 周期扫描 NULL → 攒批 → embedding 服务 → 同事务回填 → 失败入 job
- **LLM Usage**: embedding API（非 chat）；批量；指数退避；fallback=保持 NULL（检索降级结构化）
- **State Machine**: embedding NULL→filled；失败行保持 NULL 可重扫
- **Idempotency**: 以 memory_id+内容 hash 为键；已填行跳过；重启=重新扫描
- **Feature Flag**: `v2_memory_vector_enabled`，OFF=不启动批处理
- **Error/Failure**: 配额/网络失败→退避+批量降小；数据异常→跳过该行+trace
- **Observability**: trace 记批大小/耗时/失败数；job 表留 last_error
- **Testing**: Unit=攒批窗口；Integration=批量注入 1000 条；FailureInjection=服务不可用；Idempotency=重启不重复回填
- **Acceptance Criteria**: 给定转正记忆，当批处理周期完成，那么 ≤5 分钟向量可用；给定 embedding 服务宕机，当检索发生，那么结构化路径正常返回且无数据丢失
- **Regression**: Flag OFF 时无行为
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-04
- **Risk**: 配额成本→批量+退避+结构化兜底

## MEM-005 生命周期引擎（Core / Lifecycle）

- **Priority**: P0
- **Objective**: reinforce/merge/supersede/decay/forget 全状态机
- **Problem**: v1 记忆只有 TTL 与硬删（version-boundary §2），无强化/合并/衰减则长对话记性必然退化
- **Scope**: lifecycle.py 状态机；指数衰减周期任务；冲突保守并存（pending 标记）；显式 forget 全通道清除（软删+30 天物理删）
- **Non-Scope**: 不做检索打分；不写其他域；不改 v1 硬删代码（旧路径保留待清理期）
- **Inputs**: 检索命中信号（reinforce）、新转正记忆（冲突检测）、时钟、显式 forget 指令
- **Outputs**: 状态迁移 + memory_links + trace
- **Dependencies**: MEM-001, MEM-003
- **Architecture References**: design.md §4/§7；[../../architecture/data-flow.md](../../architecture/data-flow.md) §2.2；[../../architecture/risk.md](../../architecture/risk.md) R4
- **Domain Boundary**: Memory（只写 memories/memory_links/trace）
- **Data Changes**: memories.status/salience/last_reinforced_at/merge_chain；memory_links 增删
- **Runtime Flow**: 周期任务→衰减公式 `salience·exp(-λΔt)`→状态判定；检索命中→reinforce；新记忆冲突→contradicts/merge 链
- **LLM Usage**: NONE
- **State Machine**: design.md §4（Candidate/Active/Superseded/Invalidated/Decayed/Forgotten + 合法转换表）；非法转换（如 Forgotten→Active）代码拒绝
- **Idempotency**: 衰减按日桶幂等（同日重跑不叠加）；forget 幂等（已 forgotten 再 forget 无操作）
- **Feature Flag**: `v2_memory_enabled`，OFF=不跑周期任务
- **Error/Failure**: DB 失败→回滚+job 重试；计算异常→跳过该行+trace
- **Observability**: memory_lifecycle trace（迁移原因/公式参数）——「为什么这条记忆消失/被合并」可答
- **Testing**: Unit=状态机全转换+非法转换拒绝；数值=衰减公式；Integration=改口/冲突/遗忘场景；Idempotency=同日重跑
- **Acceptance Criteria**: 给定用户改口「其实我不吃辣」，当同主题新记忆转正，那么旧条目 superseded 且 memory_links 可溯；给定显式 forget，那么向量/结构/上下文三通道检索均 0 命中
- **Regression**: V4 memory checklist；Flag OFF golden 字节级
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-02/03
- **Risk**: 误 supersede 正确记忆→保守并存策略 + 评估集回归

## MEM-006 混合检索与排序（Integration / Retriever）

- **Priority**: P0
- **Objective**: 语义+结构混合检索进入 Context 并带分数解释
- **Problem**: v1 关键词检索同义改述即失效（v1 审计问题 1）；这是 P1 完成标准「改述召回」的承载 Task
- **Scope**: retriever.py；context_builder 接线（Flag 内）；混合打分 `w1·cosine + w2·structured − w3·penalty`；top-5 + 合并预算 800；检索 trace
- **Non-Scope**: 不做记忆写入；不注入 hypothetical/低置信 Insight；不改 12000 总预算
- **Inputs**: query（用户消息+本轮意图）、memories（active 非 hypothetical）
- **Outputs**: top-k 记忆 + 各项分数解释 → Context 检索段
- **Dependencies**: MEM-004, MEM-005
- **Architecture References**: design.md §6；[../../architecture/context-architecture.md](../../architecture/context-architecture.md) §2/§3；[../../architecture/evaluation.md](../../architecture/evaluation.md) §1 Context 行
- **Domain Boundary**: Memory（只读 memories；写 trace；输出经 Context Architect，禁止直改 prompt）
- **Data Changes**: 无（读路径写回 reinforce 信号走批量 flush，见 data-flow §5）
- **Runtime Flow**: query → 向量检索(可降级) ∥ 结构化打分 → 融合排序 → 去重/过滤 → 预算截断 → 注入 Context → 检索 trace
- **LLM Usage**: NONE
- **State Machine**: 无（纯函数式检索；embedding NULL 行自动降级）
- **Idempotency**: 同 query 同数据结果确定（缓存窗口内）
- **Feature Flag**: `v2_memory_vector_enabled`（语义通道）；总闸 OFF=走 v1 关键词路径行为不变
- **Error/Failure**: 向量服务失败→降级纯结构化；结果为空→正常空段不报错
- **Observability**: memory_retrieve trace（命中/未命中原因、各项分数）——「为什么召回这条/为什么没召回那条」可答
- **Testing**: Unit=融合打分；Integration=改述召回标注集；消融=纯结构 vs 混合；Performance=P95 <200ms
- **Acceptance Criteria**: 给定改述表达（同义不同词）查询，当检索，那么离线集 recall ≥0.8；给定子闸关闭，那么输出与 v1 路径逐字节一致
- **Regression**: V4 checklist + Flag OFF golden 字节级
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-04/06
- **Risk**: 向量/结构分数失衡→权重进 settings + 离线校准

## MEM-007 显式命令通道（Integration / Commands）

- **Priority**: P1
- **Objective**: 「记住/忘掉 X」即时生效
- **Problem**: 用户显式指令是最高置信信号（任务书 §十六），必须绕过普通评估直达生命周期
- **Scope**: 意图识别复用 turn_analysis 信号；commands.py 直通 MEM-005 生命周期
- **Non-Scope**: 不新增意图链；不做批量遗忘；识别失败静默降级为普通候选（不误删）
- **Inputs**: 用户消息中的显式指令、turn_analysis 输出
- **Outputs**: 立即 Active(salience=1.0) / forgotten
- **Dependencies**: MEM-005
- **Architecture References**: design.md §5 首两行；[../../architecture/evaluation.md](../../architecture/evaluation.md) §2 显式记住/忘记场景
- **Domain Boundary**: Memory（写 memories/candidates/trace）
- **Data Changes**: memories 状态/新行；无新表
- **Runtime Flow**: 用户消息 → 命令识别 → [remember→直通 Active | forget→全通道清除 | 未命中→普通候选] → trace
- **LLM Usage**: NONE（复用既有意图信号；不新增调用）
- **State Machine**: 同 MEM-005；forget 仅对高匹配度条目生效，其余进候选（防误删）
- **Idempotency**: 同消息重复命令幂等
- **Feature Flag**: `v2_memory_enabled`，OFF=命令按普通对话处理（v1 行为）
- **Error/Failure**: 识别歧义→降级普通候选；DB 失败→事务回滚
- **Observability**: memory_command trace（命中与否/目标条目）
- **Testing**: Unit=指令表述变体集；Integration=端到端；Idempotency=重放
- **Acceptance Criteria**: 给定「忘掉那件事」，当匹配到唯一高匹配记忆，那么该记忆立即 forgotten 且三通道 0 命中；给定模糊指令，那么不删除任何记忆只产生候选
- **Regression**: V4 checklist；Flag OFF golden 字节级
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-02/03
- **Risk**: 误判「忘记」→高匹配度门槛 + 误删率评估指标

## MEM-008 Memory Trace（Observability）

- **Priority**: P1
- **Objective**: 「为什么记住/没记住/召回这条」六问可答
- **Problem**: 无归因则 Evaluation 无法定位失败环节，灰度期无法回答「为什么行为变了」
- **Scope**: trace_collector 新增 memory_* 步骤（ingest/evaluate/lifecycle/retrieve/command）；debug API 扩展
- **Non-Scope**: 不新建存储（复用 runtime_traces）；不阻塞主链路（trace 失败只记日志）
- **Inputs**: 各环节决策事件
- **Outputs**: runtime_traces 记录 + debug 查询接口
- **Dependencies**: MEM-003, MEM-005, MEM-006
- **Architecture References**: [../../architecture/context-architecture.md](../../architecture/context-architecture.md) §5；[../../architecture/evaluation.md](../../architecture/evaluation.md) §3 可归因配套
- **Domain Boundary**: 横切观测平面（只读旁路，不写业务状态）
- **Data Changes**: 无新表（runtime_traces 扩步骤类型）
- **Runtime Flow**: 各 Memory 步骤 → trace 事件（含输入摘要/决策/分数/LLM 调用数）→ runtime_traces
- **LLM Usage**: NONE
- **State Machine**: 无
- **Idempotency**: 每轮 trace 唯一（trace_id 继承 v1）
- **Feature Flag**: 无（观测始终开启，成本可忽略）
- **Error/Failure**: trace 写失败→日志降级，不影响业务
- **Observability**: 即本 Task；debug API 支持按 memory_id 查全链
- **Testing**: Integration=端到端 trace 完整性；Unit=步骤序列化
- **Acceptance Criteria**: 给定任一已转正记忆，当查询 debug API，那么可返回其源、转正原因、最近强化时间、历次召回分数
- **Regression**: trace 扩展不影响 golden
- **Evaluation**: 全部 E-MEM 依赖本 Task
- **Risk**: 无（只读旁路）

## MEM-009 周期任务接入 background_jobs（Infra）

- **Priority**: P1
- **Objective**: 衰减/补 embedding 任务持久化、可恢复（P5 复用底座）
- **Problem**: v1 周期任务重启即丢、无重试策略（v1 审计问题 6）；不先落 Job 表则 P5 Life Loop 无可复用执行协议
- **Scope**: 周期任务迁移到 background_jobs 调度；幂等键与指数退避；死信状态 failed+reason
- **Non-Scope**: 不改变单进程执行模型（P5 才重构执行器）；不引外部队列
- **Inputs**: 时钟、job 定义（decay/embedding backfill）
- **Outputs**: 可恢复的后台任务执行
- **Dependencies**: MEM-001, MEM-005
- **Architecture References**: [../../architecture/data-flow.md](../../architecture/data-flow.md) §3；[../../architecture/overview.md](../../architecture/overview.md) §5（Job 表即协议）
- **Domain Boundary**: Infrastructure（不持业务语义）
- **Data Changes**: 读写 background_jobs
- **Runtime Flow**: 调度扫描 due job → FOR UPDATE SKIP LOCKED 认领 → 执行 → done/failed(重试) 
- **LLM Usage**: NONE
- **State Machine**: pending→running→done|failed；failed→pending(attempts<5)；attempts≥5→failed(终态)
- **Idempotency**: job_key(task_type+entity_id+周期桶) 唯一；重复入队被约束拦截
- **Feature Flag**: 无（基础设施，Flag 关闭时周期任务本身不注册）
- **Error/Failure**: 执行异常→attempts+1 退避重试；进程被 kill→running 超时回收后重跑（幂等保证安全）
- **Observability**: job 状态可查；失败带 last_error
- **Testing**: Unit=状态机；Integration=kill -9 重启演练；Idempotency=重复入队
- **Acceptance Criteria**: 给定执行中进程被 kill -9，当进程重启，那么未完成 job 继续执行且不重复产生副作用
- **Regression**: 无行为面变化
- **Evaluation**: 无（供 P5/LIFE 验收复用）
- **Risk**: 无

## MEM-010 离线评估与回归清单（Evaluation）

- **Priority**: P1
- **Objective**: Phase 1 验收闭环（Eval Gate + Regression Gate）
- **Problem**: 无量化验收则「记忆变好」不可证明，灰度推进无依据（migration §6 验收门）
- **Scope**: offline_evaluator 扩展 memory 场景集；建立 v2.0.0 regression-checklist（见本目录 [regression-checklist.md](regression-checklist.md)）
- **Non-Scope**: 只读；不产业务写入；不新建评估存储
- **Inputs**: [evaluation.md](evaluation.md) 场景集、标注数据
- **Outputs**: 评估报告 + checklist 通过记录
- **Dependencies**: MEM-006, MEM-008
- **Architecture References**: [../../architecture/evaluation.md](../../architecture/evaluation.md) §1/§2/§3
- **Domain Boundary**: 横切质量平面（只读旁路）
- **Data Changes**: 无
- **Runtime Flow**: 场景注入 → 交互模拟 → 指标计算 → 报告
- **LLM Usage**: Judge 采样（复用既有 evaluation_judge，离线批量）
- **State Machine**: 无
- **Idempotency**: 场景集可重复执行
- **Feature Flag**: 分别在 Flag ON/OFF 两种状态跑（golden 对比）
- **Error/Failure**: Judge 失败→该场景记 skipped 并重跑
- **Observability**: 报告即产物
- **Testing**: 即测试本身
- **Acceptance Criteria**: precision/recall/冲突处理/遗忘四项达 [evaluation.md](evaluation.md) 门槛；Flag OFF golden 字节级一致
- **Regression**: 本目录 regression-checklist 全项
- **Evaluation**: 汇总 E-MEM-01~06
- **Risk**: 标注集规模不足→先 100 条起随 Phase 累积

## MEM-011 Working Memory 装配接线（Integration）

- **Priority**: P1
- **Objective**: 双层记忆成型——Working Memory（每轮重建）与 Long-term 检索在 Context 中分层装配
- **Problem**: 任务书 §十一要求 Working + Long-term 双层；若不显式分层，检索结果与最近消息混装则 Freshness/预算策略无法作用
- **Scope**: context_builder 内将「最近 N 条+本轮结构化信号+活跃 Scene/Action」与「MEM-006 检索段」分层装配；分层预算（Working 沿 v1 分段、检索段 800）
- **Non-Scope**: Working Memory 不落任何长期表；不新增 LLM；不改 v1 summary 滚动逻辑
- **Inputs**: 最近消息、本轮 turn_analysis 信号、MEM-006 检索结果
- **Outputs**: 分层装配后的 Context sections（记入 prompt_snapshots）
- **Dependencies**: MEM-006
- **Architecture References**: [../../architecture/context-architecture.md](../../architecture/context-architecture.md) §1/§3；[../../architecture/domain-boundaries.md](../../architecture/domain-boundaries.md) §2 Working Memory 行
- **Domain Boundary**: Runtime Context（无持久化；装配在编排层内完成）
- **Data Changes**: 无
- **Runtime Flow**: 消息 → Working 段组装 ∥ 检索段 → 分层预算裁定 → sections + snapshot
- **LLM Usage**: NONE
- **State Machine**: 无（轮级，每轮重建）
- **Idempotency**: 同输入同装配
- **Feature Flag**: `v2_memory_enabled`，OFF=装配退化为 v1 单层（字节级一致）
- **Error/Failure**: 检索空→检索段为空不报错；超预算→按 P2 优先级截断
- **Observability**: prompt_snapshots 记录每层实际内容与预算占用
- **Testing**: Unit=分层预算裁定；Integration=长对话轮装配；Regression=Flag OFF golden
- **Acceptance Criteria**: 给定 50+ 轮对话，当装配当轮 Context，那么 Working 段仅含预算内近期消息、检索段仅含 top-5 且总量 ≤12000；给定 Flag OFF，那么 sections 与 v1 逐字节一致
- **Regression**: V7.5/V4 checklist（prompt 结构相关项）
- **Evaluation**: [evaluation.md](evaluation.md) E-MEM-06
- **Risk**: 分层装配引入 prompt 结构漂移→snapshot 对比测试兜底

---

## Phase 1 Milestone（交付序）

```text
M1 Foundation:   MEM-001 完成即 unlock 全部并行开发
M2 Core:         MEM-002→003→{004,005} 串行主干（可 ∥ REF-001/DEV-001/AUT-001）
M3 Integration:  MEM-006/007/011 + MEM-009
M4 Acceptance:   MEM-008/010 → Eval Gate + Regression Gate 全过 → 申请开启 v2_memory_enabled
```



