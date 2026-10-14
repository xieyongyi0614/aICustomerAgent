# Agent 演进规划（2026-10）

> **性质**：评审级规划稿。对「角色对话 Agent」三项能力做现状审核并给出下一步演进设计：**记忆系统**、**规划系统的交互式澄清（human-in-the-loop）**、**subAgent 可行性**。
> **纪律**：现状小节全部基于当前代码，附「相对仓库根路径 + 行号」证据；规划小节显式标注「规划（未实现）」。本文档**不改动任何代码、配置、迁移与测试**，也**不改动** `docs/current-system-architecture-baseline.md`（仅在第 5 节给出同步建议）。
> **证据复核**：全文行号已由独立代码检索复核一次；复核中发现的原稿偏差已在下文更正（见 §2.1 注、§3.1 注、§4.2 注）。
> **生成时间**：2026-10-14。

---

## 1. 结论速览

### 1.1 三项审核结论

| 主题 | 一句话结论 | 工程成熟度 | 建议动作 |
|---|---|---|---|
| 记忆系统 | 记忆已是**落地的 Memory 2.0**（四源摄取 → 候选 → 三段评估转正 → 混合检索 → 六态生命周期 → 后台衰减/补扫 → 产品读面），幂等/降级/trace/评估门槛齐备；但架构仍是**扁平 9 类型 + 单跳「向量 + 结构化」检索**，无分层、无图谱、无 LLM 重排 | 高（可运行、可观测） | 先做**检索质量**（重排/改写/亲和词表）与**产品面补全**，再做**分层（Episodic/Semantic）**，图谱多跳最后 |
| 规划系统 | 规划是**后台批处理**（`life_loop` + `goal_planning` job），生成是**一次 LLM 提案即落库**：`PlanContext` 与规划 prompt 均无「澄清问答」槽位，**不存在**任何 `ask_user` / `human_in_the_loop` / LangGraph 式 `interrupt`；计划级人工闸门（审批）已落地但**无客户端 UI**；工具级确认是唯一「提问→等答复→恢复」机制，语义是**授权**而非规划输入 | 中（链路完整、交互缺失） | 新增「计划级澄清挂起」：**零迁移**优先（复用 `validated` 停靠语义 + `trigger_registry` 载体），恢复路径优先走**前台对话轮次** |
| subAgent | **无任何 subAgent / 多 Agent / 委派雏形**（全库搜索 `subagent`、`ask_user` 等 0 命中）；可复用的三块原材料是 Profile Registry、`AgentRuntime` 协议、`background_jobs` + `worker_loop`；但**架构红线明确禁止**「第二套 Agent / 多 Agent 并行 / 引入外部编排框架」 | 低（仅原材料） | **本稿不裁决**。若要做，必须先解红线、补 Agent 身份抽象、补父子 Run 观测三件事 |

### 1.2 三处文档漂移（现状描述与代码不符，建议随本规划同批修正基线）

| # | 漂移 | 基线原文 | 代码实际 |
|---|---|---|---|
| D1 | **记忆实现路径** | `docs/current-system-architecture-baseline.md:169` 写 `services/memory_service.py`；`:170` 写 `services/memory2/` | 两个路径均**不存在**（全后端无 `memory2` 文本）。真实实现为**单包** `apps/backend/app/services/memory/`（14 个模块 + `__init__.py`）；v1 硬规则策略在 `apps/backend/app/engines/memory_policy.py` |
| D2 | **七闸规划引擎未接管主路径** | 基线 §3.4（`docs/current-system-architecture-baseline.md:135-148`）以 `PlanningEngine`（七道闸）作为规划引擎描述 | 生产主路径是 `apps/backend/app/services/goal/planning.py::plan_goal`（由 `life_loop` → `run_planning_jobs` 驱动）；`PlanningEngine.plan()` **仅**被可选段 `apps/backend/app/application/agent_runtime/stages/plan.py:214` 调用，而该段默认永不进入（`plan_enabled` 见同文件 `:81`，`profiles.py` 的 `optional_stages` 默认 `frozenset()`，见 `apps/backend/app/application/agent_runtime/profiles.py:30`） |
| D3 | **`draft` 计划状态无写入路径** | 基线 §3.4 列出 `draft / validated / active / rejected / superseded` | `GoalPlanStatus` 定义确含 `draft`（`apps/backend/app/models/goal.py:29`，值集 `PLAN_STATUS_VALUES` `:100-106`），但两条规划路径都直接落 `validated`，`draft` 当前未被任何写入路径使用 |

### 1.3 推荐推进顺序与依赖（详见 §5）

```
阶段 M（记忆）  ──►  阶段 P（交互式澄清）  ──►  阶段 S（subAgent，仅评估）
   M1 检索质量           P1 澄清挂起态 + 前台恢复        S0 红线裁决（用户决定）
   M2 分层                P2 客户端 UI                  S1 Agent 身份抽象
   M3 图谱/产品面         P3 超时策略 + 审计
```

依赖关系：**P 不依赖 M**（可并行），但 P 的澄清上下文需要消费记忆检索结果（`PlanContext._assemble_memory`），故 M1 的检索质量提升会直接改善 P 的澄清质量；**S 依赖 P 的「挂起态 + 恢复」范式**（子 Agent 的委派链本质是一种挂起/恢复编排）。

---

## 2. 记忆系统

### 2.1 现状审核（已实现）

**注（复核更正）**：真实实现包为 `apps/backend/app/services/memory/`，共 **14 个模块**（不含空 `__init__.py`）：

```
ingest.py 358 行 | sources.py 41 | evaluator.py 512 | embeddings.py 216
lifecycle.py 428 | retriever.py 380 | commands.py 237 | attribution.py 201
job_worker.py 216 | offline_metrics.py 92 | product_view.py 371 | refs.py 40
types.py 57 | migration.py 83
```

#### 2.1.1 写入链路（摄取 → 候选 → 评估转正）

| 环节 | 落点与证据 | 说明 |
|---|---|---|
| 摄取触发 | `apps/backend/app/application/post_process.py:170`（`_run_memory_ingest_v2`） | 会话轮后处理入口；**显式命令优先** `:177` → `extract_candidates` `:188` → `ingest_from_conversation` `:197`；随后四源补扫：action `:204`、world `:209`、relationship `:214`、milestone `:219` |
| 另一接入点 | `apps/backend/app/application/agent_runtime/stages/update.py:205` | 调 `ingest_from_action_record` |
| 旁路写源 | `apps/backend/app/services/ledger/memory_bridge.py:47`、`apps/backend/app/services/planning/memory_policy.py:398`、`apps/backend/app/services/relationship/evaluation.py:269` | 账本洞察（仅 `behavior_pattern`）、目标完成、关系里程碑 |
| 候选唯一入口 | `apps/backend/app/services/memory/ingest.py:67`（`create_candidate`） | 文件内注释明确「禁止直写 memories」 |
| 幂等/去重 | 候选级按 `(source_table, source_id)` 查重（`ingest.py:89-90`）；DB 层 `UniqueConstraint("source_table","source_id")`（`apps/backend/app/core/db/memory.py:104`） | 命中即返回不更新；命令级幂等键 `apps/backend/app/services/memory/commands.py:199` |
| 提取器 | `apps/backend/app/chains/extractor_chain.py` + `apps/backend/app/prompts/extractor.py` | LLM 提取候选（每题上限 `memory_ingest_max_per_turn`） |
| 评估转正 | `apps/backend/app/services/memory/evaluator.py:227`（`_promote`）；灰区兜底 `_decide_gray_zone` `:324` → `_ask_llm_with_retry` `:340`，lite profile 取 `:81` | 规则三段确定性打分；仅灰区用 lite LLM，受 `memory_llm_fallback_rate_cap` 护栏 |
| **直写例外** | `apps/backend/app/services/action/capabilities/memory.py:49`（`remember_fact` → `memory_repository.create_memory`，`source=user_stated`） | 唯一绕过候选表的写入；`ingest.py:183` 对 `remember_fact` 显式跳过以防双写 |

#### 2.1.2 读取链路（召回打分 → prompt 注入）

**打分公式**（`apps/backend/app/services/memory/retriever.py:265` `retrieve`）：

```
score = w_semantic·cosine
      + w_structured·(recency + importance + salience) / 3
      + w_affinity·affinity
      (+ w_temporal_boost·recency，当查询含时间词)
```

| 项 | 证据 |
|---|---|
| 权重来源 | `apps/backend/app/core/settings/memory.py`：`memory_weight_semantic` `:56`（0.45）、`memory_weight_structured` `:57`（0.35）、`memory_weight_affinity` `:58`（0.20）、`memory_temporal_recency_boost` `:63`（0.2） |
| 结构化分 | `retriever.py:106`（`_structured_score`）；recency `0.5^(days/half_life)` 由 `_recency` `:98` 计算，`memory_recency_half_life_days` 默认 30 天 |
| 亲和分 | `apps/backend/app/services/memory/types.py:30`（`TYPE_AFFINITY_KEYWORDS`，仅覆盖 4 类实体类型） |
| 候选池 | `list_active` 结构路（`memory_candidate_pool_limit` 默认 200）∪ pgvector ANN 向量路（`memory_vector_recall_k` `:62` 默认 20） |
| 三元降级 | 模式常量 `retriever.py:30-32`，赋值 `:282` / `:286` / `:294`：`hybrid` / `structured` / `degraded`（**embedding 未配置时默认降级为纯结构化**，`embedding_model` 默认空串，见 `apps/backend/app/core/settings/memory.py:48`） |
| 硬过滤 | hypothetical 剔除；被拒/被纠正 24h 冷却（cutoff `retriever.py:121`，过滤 `_filter_reasons` `:177`，应用 `:306`） |
| 注入位置 | `apps/backend/app/services/conversation/context.py:253`（调 retrieve）→ `:40`（`_select_retrieval_segment` 贪心装入，预算 `memory_retrieval_budget` 默认 800 字符）→ `:294`（写 `ConversationState.memories`） |
| prompt 段 | `apps/backend/app/prompts/builder.py:449`（system 追加段「【你记得关于用户的事】」）；切片格式 `:442-445`（`- ({类型中文标签}) {content}`），类型标签表 `MEMORY_TYPE_LABELS` 起始 `:35`；二次总预算裁剪 `_fit_variable_parts` `:297` |
| 时间锚 | `context.py` 给内容前缀相对时间「（N天前）」 |
| 主动回忆（跨会话） | `apps/backend/app/application/life_loop.py:545`（`_step_memory_retrieval`）取 `list_top_salience` 生成 digest 注入 proactive 上下文 |

**检索本体无 LLM 参与**：无 rerank、无 query 改写、无多轮检索（`retrieve` 单次单跳）。

#### 2.1.3 生命周期与后台 job

| 项 | 落点与证据 |
|---|---|
| 状态机 | `apps/backend/app/services/memory/lifecycle.py:48`（`TRANSITIONS` 表）：`active/reinforced`、`superseded`、`invalidated`、`decayed`、`forgotten`；非法转换抛 `IllegalTransitionError` |
| 衰减 | `lifecycle.py:188-195`（公式 `:194`）：`salience = salience · exp(-λ_type · Δdays)`，λ 按类型来自 `memory_decay_lambda_json`（`core/settings/memory.py:39`）；按日桶幂等（`last_decayed_at` 游标）；压到 `memory_salience_floor`（`:37` 默认 0.1）转 `decayed` |
| 遗忘与物理删 | 软删 `explicit_forget` `lifecycle.py:358`（置 `forgotten`、清 embedding）；物理删 `purge_expired_forgotten` `:233`（`memory_forget_retention_days` `core/settings/memory.py:36` 默认 30 天，届满脸 + 级联删 `memory_links`） |
| 冲突处理 | 转正时 `on_promoted` 对同主题做 supersede / merge / contradicts，落 `memory_links` |
| 后台任务 | `apps/backend/app/services/memory/job_worker.py:71`（`run_job_tick`，由 `apps/backend/app/application/worker_loop.py:21` 驱动）；每日衰减入队幂等键 `:93-94`（`memory_decay:{YYYY-MM-DD}`）；认领 `:100`（`FOR UPDATE SKIP LOCKED`，`:111`）；处理器表 `_JOB_HANDLERS` `:31`（`memory_decay` / `embedding_backfill`）；扩展点 `register_job_type` `:41` / `register_tick_hook` `:46`；轮询 `job_poll_interval`（`core/settings/memory.py:52`） |
| 失败语义 | 指数退避重试至 `job_max_attempts=5` 转 failed；`job_running_timeout=600` 僵尸回收 |

#### 2.1.4 表结构（`apps/backend/app/core/db/memory.py`）

| 表 | 定义 | 关键点 |
|---|---|---|
| `memories` | `:19` | `type`（种 CHECK 9 值 `:61`）、`importance`、`confidence`、`status`、`superseded_by`，v2 列 `embedding(VectorType)` / `salience` / `last_reinforced_at` / `last_decayed_at` / `forgotten_at` / `merge_chain` / `source_ref` / `visibility`；索引 `:67-73` |
| `memory_candidates` | `:77` | `proposed_type` / `source` / `source_table` / `source_id` / `status` / `reason` / `visibility`；`UniqueConstraint("source_table","source_id")` `:104` |
| `memory_links` | `:109` | `relation` ∈ `supersedes/merges/contradicts`（CHECK `:120`）——**仅供冲突处理与冷却过滤使用，检索路径不做图遍历** |
| `background_jobs` | 记忆 job 基建 | 通用后台任务表 |

迁移：基线 `apps/backend/migrations/versions/0001_squashed_full_schema.py`（`background_jobs` `:114`、`memories` `:471`、`memory_candidates` `:506`、`memory_links` `:526`）；增量链现有 `0002`~`0009`（`0002_briefing_preferences` … `0009_app_release_artifacts`），**新增结构变更须从 `0010` 起**。

#### 2.1.5 产品侧出口

| 面 | 落点 | 能力 |
|---|---|---|
| REST | `apps/backend/app/api/v1/memory.py`：`GET /memory/items` `:51`、`PATCH /memory/items/{memory_id}` `:73`、`POST /memory/items/{memory_id}/forget` `:93` | 分组列表 + 用途回执 + 编辑 + 软遗忘 |
| 兼容读面 | `apps/backend/app/api/v1/history.py:79`（`list_memories`，`GET /history/memories`） | 历史遗留读接口 |
| 移动端 | `apps/mobile/lib/features/memory/presentation/memory_page.dart` | 四分组 + 来源追溯 + 逐条编辑 + 逐条遗忘 + 隐私承诺；分组/标签/来源中文名全部服务端下发 |
| Web 端 | `apps/frontend/src/components/debug/memory-panel.tsx` | **只读调试面板**（importance/confidence/status 徽章）；编辑/遗忘入口缺失 |
| 调试归因 | `apps/backend/app/api/v1/debug/attribution.py` | 记忆/候选归因查询 |

### 2.2 缺口清单（均为已核实结论）

| # | 缺口 | 证据 |
|---|---|---|
| G-M1 | **无情景/语义分层**：类型是扁平 9 值（`types.py:9` 起 `V2_MEMORY_TYPES`），无 episodic/semantic 通道概念 | `apps/backend/app/services/memory/types.py:9`、`apps/backend/app/core/db/memory.py:61` |
| G-M2 | **无记忆图谱/多跳检索**：`memory_links` 只有三种关系且不参与检索 | `apps/backend/app/core/db/memory.py:120`、`retriever.py:265`（单次单跳） |
| G-M3 | **无 LLM rerank / query 改写 / 多轮检索** | `retriever.py:265` 无 LLM 调用点 |
| G-M4 | **无聚类/主题聚合、无 learned importance** | 未找到证据（`importance` 为写入期给定值） |
| G-M5 | **无字段级/部分遗忘**：遗忘为整行置 `forgotten` | `lifecycle.py:358` |
| G-M6 | **无按记忆的 ACL/可见性分级**（除 `user_id` 归属与 `hypothetical` 标记） | 产品读面仅校验 `user_id` 与 `status`（`product_view.py`） |
| G-M7 | **无用户可见的搜索/筛选/时间过滤**：产品读面仅按 kind 分组 | `apps/backend/app/services/memory/product_view.py` |
| G-M8 | **Web 端无编辑/遗忘入口**（移动端已有） | `apps/frontend/src/components/debug/memory-panel.tsx` |
| G-M9 | **向量检索在非 PostgreSQL 或未配置 embedding 时无等价方案**：直接降级为纯结构化 | `retriever.py:30-32/282-294`；`core/settings/memory.py` 的 `embedding_model` 默认空串 |

### 2.3 下一步演进设计（规划，未实现）

体例：**最小改动方案**（零/低迁移、单包内演进）与**进阶方案**（需迁移或新子系统）。所有阶段均须复用既有 `memory_candidates`（幂等摄取）、`embeddings`（向量）、`retriever`（混合排序）作为底座。

#### 阶段 M1：检索质量（最小改动，零迁移）

| 子项 | 设计 | 落点 | 迁移 |
|---|---|---|---|
| M1.1 LLM 重排 | 检索候选（top-K，K ≤ `memory_vector_recall_k`）交 lite profile 做一次性重排打分；仅在候选数 > 阈值时触发，受预算位与兜底率护栏约束 | 新增 `apps/backend/app/chains/memory_rerank_chain.py`；挂接 `retriever.retrieve` 之后 | 无 |
| M1.2 Query 改写 | 用当轮用户消息生成 1~2 条检索 query（同义/口语化），并行检索后并集打分；失败即回落原始 query | `chains/` 新增改写链；`conversation/context.py:253` 调用处扩展 | 无 |
| M1.3 亲和词表扩容 | `TYPE_AFFINITY_KEYWORDS` 从 4 类扩到全 7 类 + 增加同义词 | `apps/backend/app/services/memory/types.py:30` | 无 |
| M1.4 召回可观测 | 在 `turn_meta.memory_refs` 之外补「重排前后名次/分数」调试字段，便于评估 | `apps/backend/app/services/memory/refs.py` + `debug/*` | 无 |
| M1.5 离线门槛 | 扩展 `offline_metrics.py` 的评估集，把重排纳入门槛 | `apps/backend/app/services/memory/offline_metrics.py` | 无 |

**收益**：直接提升回答相关性，且**同时惠及 §3 的澄清质量**（澄清上下文消费 `PlanContext._assemble_memory`，见 `apps/backend/app/services/planning/context.py:605`）。

#### 阶段 M2：显式分层（Episodic / Semantic，需迁移）

| 子项 | 设计 | 落点 | 迁移 |
|---|---|---|---|
| M2.1 分层标记 | 为 `memories` 增 `layer` 列（`episodic` / `semantic`，默认由 `type` 映射推导，写入期可覆盖） | `apps/backend/app/core/db/memory.py` | 迁移 `0010`（ADD COLUMN + 回填 + 索引） |
| M2.2 情景聚合 | 以 `(user_id, 时间窗, 主题)` 聚合会话/行动/世界事件，形成「情景条目」并落 `memories`（`layer=episodic`），保留 `source_ref` 指针 | 新增 `apps/backend/app/services/memory/episodic.py`（**注意**：`services/planning/` 有包模块白名单断言，见 §4.2 注；`services/memory/` 无此约束，但应同步登记白名单类测试） | 依赖 M2.1 |
| M2.3 语义抽象 | 由若干 `episodic` 条目经 LLM 抽象为 `semantic`（跨事件概念/偏好），经既有三段评估转正 | 新增 `apps/backend/app/services/memory/semantic.py`；复用 `evaluator` | 依赖 M2.2 |
| M2.4 检索分层配额 | `retriever` 在两类间分配配额（例如 3:5），避免情景条目挤占语义条目 | `apps/backend/app/services/memory/retriever.py` | 无（配置项新增） |
| M2.5 生命周期差异 | `episodic` 衰减 λ 更快、`semantic` 更慢（`memory_decay_lambda_json` 已按类型配置，扩展即可） | `apps/backend/app/core/settings/memory.py:39` | 无 |

**风险**：`layer` 与既有 `type` 语义重叠，须明确「`type` = 内容性质，`layer` = 记忆通道」的分工，避免双重真相。

#### 阶段 M3：结构化与产品面（进阶）

| 子项 | 设计 | 落点 | 迁移 |
|---|---|---|---|
| M3.1 记忆图谱 1-hop 扩展 | 扩展 `memory_links.relation` 值域（加 `caused_by` / `before` / `related`），`retriever` 增加 1-hop 扩展召回（扩展结果降权） | `apps/backend/app/core/db/memory.py:120`（CHECK 需改）+ `retriever.py` | 迁移 `0010+`（改 CHECK） |
| M3.2 因果/时序抽取 | 转正时用 LLM 判定新记忆与既有记忆的关系并落 link | `services/memory/evaluator.py` 延伸 | 依赖 M3.1 |
| M3.3 记忆搜索与筛选 | `GET /memory/items` 增 `q` / `type` / `layer` / 时间区间参数（服务端检索，复用 `retriever`） | `apps/backend/app/api/v1/memory.py:51` + `services/memory/product_view.py` | 无 |
| M3.4 主题聚类 | 周期性对同用户 `semantic` 记忆做聚类，产出「主题卡片」（只读派生，不新表） | `services/memory/product_view.py` + 后台 job | 无 |
| M3.5 Web 端补齐 | `memory-panel.tsx` 由只读升级为可编辑/可遗忘（复用移动端已验收的 API） | `apps/frontend/src/components/debug/memory-panel.tsx` | 无 |
| M3.6 字段级遗忘 | 支持「部分遗忘」（如仅清除金额/地点），实现方式为内容脱敏重写 + `merge_chain` 留痕 | `lifecycle.py` | 无 |

### 2.4 落点与影响面汇总

| 面 | 阶段 M1 | 阶段 M2 | 阶段 M3 |
|---|---|---|---|
| 迁移 | 无 | `0010`（`memories.layer`） | `0010+`（`memory_links` CHECK 扩展） |
| 配置 | 新增取值类配置（按领域命名，如 `memory_rerank_mode` / `memory_query_rewrite_mode` / `memory_rerank_top_k`；**禁止 `*_enabled` 形态**，见 V4.0.0 裁决 9） | 新增分层配额配置 `memory_layer_quota` | 新增搜索相关配置 |
| 服务包 | `services/memory/` 内新增 2 个模块 | `services/memory/` 新增 `episodic.py` / `semantic.py` | `retriever.py` / `product_view.py` 扩展 |
| 链 | 新增 2 条 chain（重排/改写） | 新增抽象链 | 新增关系判定链 |
| API | 无变化（仅调试字段） | 无变化 | `GET /memory/items` 增参（向后兼容） |
| 客户端 | 无 | 移动端分组/标签可能新增「情景/语义」维度（服务端下发，端上零映射） | Web 端功能补齐 + 移动端搜索框 |
| 评估 | `offline_metrics` 扩展评估集 | 新增分层评估规则 | 新增图谱命中率指标 |

### 2.5 风险与纪律

| # | 风险 | 缓解 |
|---|---|---|
| R-M1 | **prompt 预算膨胀**：重排/改写/分层都会增加注入量 | 注入总量受 `memory_retrieval_budget`（800 字符）与 `context_total_char_budget` 双重约束，新增内容必须在预算内竞争 |
| R-M2 | **LLM 成本**：重排/改写/抽象均为额外调用 | 全部走 lite profile + 门控（候选数阈值）+ 兜底率护栏；失败一律回落既有路径 |
| R-M3 | **分层引入双重真相** | `layer` 只作检索分通道依据，不做权限或来源真相；来源真相永远是 `source_ref` + `memory_candidates` |
| R-M4 | **降级纪律不可破** | 记忆域既有纪律是「异常只降级不阻断」，所有新链路必须沿用（异常 → 回落 + trace） |
| R-M5 | **迁移纪律** | 任何结构变更走 `0010+` 增量迁移，禁止折叠；`memories` 存量行 `layer` 回填必须幂等 |

---

## 3. 规划系统：交互式澄清（human-in-the-loop）

### 3.1 现状审核（已实现）

#### 3.1.1 规划全链路

| 环节 | 落点与证据 |
|---|---|
| 目标候选 | `apps/backend/app/services/goal/planning.py:98`（`collect_candidates`）、`:190`（`materialize`，落目标并 enqueue 规划 job） |
| **规划本体（生产主路径）** | `apps/backend/app/services/goal/planning.py:404`（`plan_goal`）：前置闸 → `propose_plan` `:350`（LLM 提案）→ 结构闸 → `activate_plan` `:391`；prompt 构造 `_build_messages` `:274`，LLM 调用 `_ask_llm_with_retry` `:329`（**一次性结构化输出，无循环追问**）；job 面 `run_planning_jobs` `:247`、`register_runtime` `:268` |
| 七闸引擎 | `apps/backend/app/services/planning/engine.py`：七闸说明 `:7-17`，理由码 `PLANNING_REASONS` `:87`；`PlanningEngine.plan` `:170`；`_pre_llm_gate` `:491`；`_reject` `:277` → `_create_rejection` `:375`（落 `rejected` + `rejection_reason`）；`_persist` `:292`（落 `validated`）；单例 `_ENGINE` `:392`。七闸 = `attempt_cap` / `subgoal_count_exceeded` / `invalid_sub_goal_shape` / `capability_unaligned` / `plan_tool_unresolvable` / `plan_tool_off_surface` / `llm_failed`（`:87-95` 与列举一致） |
| 上下文装配 | `apps/backend/app/services/planning/context.py:277`（`assemble`）→ `:297`（`_build_context`，字段收口 `:310-327`）；六源：Goal / World / Context / Memory（`_assemble_memory` `:605`，检索调用 `:608`）/ Reflection（`_assemble_reflection` `:626`）/ ToolSurface（`_assemble_tool_surface` `:329`） |
| 拆解与调度 | 拆解 `apps/backend/app/services/planning/decompose/decomposer.py`（PLAN-004，零 LLM）；调度 `apps/backend/app/services/planning/scheduler.py:127`（`PlanScheduler`）、`blocked_reason` `:193`（三值 `off_surface` `:74` / `cooldown` `:75` / `predecessor_failed` `:76`——**是调度阻塞，非等用户输入**） |
| 执行 | `apps/backend/app/services/planning/executor_bridge.py:173`（`PlanExecutorBridge`）、`execute_step` `:213`（**唯一执行入口**，单步串行） |
| 观测与结算 | `apps/backend/app/services/planning/observer.py:266`（`PlanObserver`）、`settle` `:346`（唯一改 `GoalStatus` 入口）、修订投影 `record_plan_revision` `:515` / `project_plan_revision` `:562` |
| 重规划 | `apps/backend/app/services/planning/revision.py:101`（`PlanRevisionPolicy`）、`should_replan` `:104`；`revision_listener.py:132`（`on_insight_created`） |
| 状态机 | `apps/backend/app/models/goal.py:29`（`GoalPlanStatus` = `draft/validated/active/rejected/superseded`，**无 `completed`**，完成由 `GoalStatus` 表达） |

**驱动方式是后台**：`apps/backend/app/application/life_loop.py:65`（`run_life_loop_worker`）→ `materialize` `:345` → `_route_planning_jobs` `:350`；步骤执行 `_execute_plan_step` `:418`；观测 `_observe_goals` `:467`。前台 `chat_pipeline` 只做单条 Action 规划与工具确认（`apps/backend/app/application/post_process.py`）。`autonomy_engine` 只**只读**消费计划事实。

#### 3.1.2 已有的两道「人机闸门」

| 闸门 | 层级 | 落点 |
|---|---|---|
| **计划审批闸门**（已落地，2026-10-10） | 计划级、一次性、**执行前** | 策略位 `plan_require_approval`（`apps/backend/app/core/settings/plan.py:29`，**默认 `False`**）；插入点 `services/goal/planning.py:497-498`；裁决服务 `services/goal/approval.py`（`list_pending` `:37` / `approve` `:42` / `reject` `:58` / 归属守卫 `:77`）；端点 `api/v1/plans.py`（`:51` / `:69` / `:75`，注册于 `api/v1/router.py:39`） |
| **工具级确认** | 工具级、逐次、**执行中** | `apps/backend/app/services/tool/confirmation.py`（`request` `:243` / `resolve` `:308` / `pending` `:363` / `expire_due` `:385`；kind 字面量 `CONFIRMATION_ROW_KIND="tool_confirmation"` `:50`）；阻塞映射 `executor_bridge.py:130`（`GATE_REASON_OUTCOMES`）→ `BLOCKED_STEP_STATUS` `:107`（步骤留 `in_progress` 等待）；检出器 `ConfirmationIntentDetector` `confirmation.py:642`；接线 `post_process.py:564`（`_run_confirmation_round`）；恢复 `action_engine.py:797`（`run_confirmation_round`）→ `_resume_confirmed_record` `:838` |

**关键区别**：工具级确认虽实现「提问 → 等答复 → 恢复」，但其语义是**授权（执行许可）**，用户答复**不进入规划上下文、不改变 `sub_goals`**。

#### 3.1.3 可复用范式：账本域「带选项澄清」

| 面 | 落点与证据 |
|---|---|
| 挂起载荷 | `apps/backend/app/services/ledger/pending.py:181`（`PendingItem`），含 `question` 字段 `:186` |
| 澄清文案（**含候选选项**） | `apps/backend/app/prompts/ledger_clarify.py:28`：形如「这笔记到哪一类？（餐饮、购物、交通）」 |
| 澄清 API | `apps/backend/app/api/v1/ledger.py`：`GET /ledger/pending` `:530`、`POST /ledger/pending/{pending_key}/confirm` `:548`、`/ignore` `:577` |
| 客户端 | `apps/mobile/lib/features/chat/presentation/chat_ledger_page.dart`、`ledger_auto_page.dart` |

**注（复核更正）**：账本澄清的候选**并非 A/B/C 编号**，而是「（餐饮、购物、交通）」式的顿号连接中文候选（`ledger_clarify.py:26-28`；候选标签见 `services/ledger/confirmation.py:108-116`）。全仓无 A/B/C 渲染。**本设计沿用「候选列表 + 自由文本」范式，不沿用编号。**

#### 3.1.4 关键否定结论（已逐项搜索确认）

| 能力 | 结论 | 证据 |
|---|---|---|
| `ask_user` / `await_user` / `human_in_the_loop` / `pending_question` / `subagent` | **0 命中** | 全 `apps/backend/app/` 搜索 |
| LangGraph 式 `interrupt` | **不存在**（仅 Python `KeyboardInterrupt` 等） | — |
| `clarification` / `clarify` | **仅账本域**，与 planning 无关 | `services/ledger/**`、`prompts/ledger_clarify.py` |
| `resume` | 存在但非规划澄清：`agent_runtime/session.py`（会话台账重建）、`action_engine._resume_confirmed_record:838`（工具确认恢复） | — |
| 规划 prompt 澄清槽位 | **无**：`goal/planning.py:274-318`（`_build_messages`）只有 system + goal/overlay/world_facts/evidence_refs | `services/goal/planning.py:274` |
| `PlanContext` 澄清字段 | **无**：字段集 `context.py:310-327` 不含「用户待答问题/用户答复」 | `services/planning/context.py:310-327` |
| 计划审批 UI | **前端与移动端均无** | `apps/frontend/src/features/` = json-viewer / ledger / token-demo / world-sim；`apps/mobile/lib/features/` = album / briefing / car / chat / home / ledger / life / memory / profile |
| 计划版本对比 UI | **无**（修订链只落 `decision_records`，供调试面只读） | `observer.py:515` / `:562` |
| 审批超时策略 | **未实现**（基点 §8.6 已登记为待决策项） | `docs/current-system-architecture-baseline.md:503` |

### 3.2 缺口清单

| # | 缺口 |
|---|---|
| G-P1 | 无「Agent 主动带选项提问 → 用户选择 → 作为规划输入继续」的挂起点 |
| G-P2 | 规划 prompt 与 `PlanContext` 无澄清问答槽位 |
| G-P3 | 无澄清挂起的持久化载体（无法跨请求/跨进程恢复） |
| G-P4 | 无澄清的客户端承载面（无 plans 页，移动端无卡片） |
| G-P5 | 审批闸门无客户端 UI、无超时策略，与澄清叠加后可能长期悬空 |
| G-P6 | 无澄清轮次审计（答复是否真正改变了计划，不可归因） |

### 3.3 演进设计（规划，未实现）

#### 3.3.1 闸门层级与定位（先定义，再实现）

新增的澄清闸门**必须**落在既有两道闸门之间，形成三层：

```
[计划生成] → L1 澄清闸（新）：Agent 带选项提问 → 用户答复 → 重新提案/继续
           → L2 审批闸（已有）：人批准/驳回整份计划
           → [执行] → L3 工具确认（已有）：逐次授权
```

理由：澄清是**信息补齐**（影响计划内容），审批是**许可裁决**（不影响计划内容），工具确认是**执行授权**。三者的「答什么」不同，不能合并。

#### 3.3.2 澄清挂起态建模（**零迁移优先**）

| 方案 | 做法 | 迁移 | 评价 |
|---|---|---|---|
| **A（推荐）** | 计划仍停在既有停靠态 `validated`（`list_active_plans` 只认 `active`，故「停住即不执行」是既有语义，与审批闸门复用同一机制）；澄清请求落 `trigger_registry`（复用工具确认的 kind 模式，新增 kind 字面量，如 `plan_clarification`） | **零迁移**（`trigger_registry` 已存在且工具确认复用中，见 `confirmation.py:50`） | 与审批闸门机制同构，风险最低；缺点是「澄清中」与「待审批」共用一个状态位，需靠 `trigger_registry` 行区分 |
| B | 新增 `GoalPlanStatus.clarifying` 值 | 迁移（改 `ck_goal_plans_status` CHECK）+ 触发大量状态机测试改写 | 语义最清晰，代价最高；仅在 A 被证明不足时启用 |
| C | 新增 `plan_clarifications` 专用表 | 迁移 `0010` | 审计最完整（天然满足 G-P6），但引入第二载体 |

**结论**：先做 A；G-P6（审计）可先复用 `decision_records` 的既有记录（不新增 kind，避免迁移），完整审计等 C。

#### 3.3.3 澄清生成（新闸）

在 `plan_goal()` 的 LLM 提案之后、`activate_plan` 之前插入**澄清判定**：

| 要素 | 设计 |
|---|---|
| 结构化输出 | 在既有提案输出中扩展 `/ 或新增一次判定调用`：`{need_clarification: bool, questions: [{id, question, options[], allow_free_text}]}` |
| 触发条件（闸） | ①`need_clarification=true`；②问题数 ≤ 上限；③选项数 ≥ 2 或 `allow_free_text=true`；④澄清预算未耗尽（**必须设澄清轮次上限，防无限追问**） |
| 落点 | `apps/backend/app/services/goal/planning.py`（与 `plan_goal` 同域；**注意** `services/planning/` 有包模块白名单断言，见 §4.2 注，故优先落 `services/goal/`） |
| 配置 | 按领域命名：`plan_require_clarification`（策略位，默认 `False` 保证零回归，**对齐既有 `plan_require_approval` 先例、非 `*_enabled` 形态**）、`plan_clarify_max_rounds`、`plan_clarify_max_questions`、`plan_clarify_timeout_hours` |

#### 3.3.4 上下文与 prompt 澄清槽位

| 改动 | 落点 |
|---|---|
| `PlanContext` 新增 `clarification` 字段（`questions[]` + `answers[]` + `round`） | `apps/backend/app/services/planning/context.py:310-327`（字段收口处） |
| `_build_messages` 注入「用户已澄清」段（仅在 `round ≥ 1` 的重新提案时注入） | `apps/backend/app/services/goal/planning.py:274` |
| 澄清轮次后走**重新提案**（同 `propose_plan` 路径，带答案）而非增量修补 | `services/goal/planning.py:350` |

#### 3.3.5 用户答复的恢复路径（三选一）

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **R1（推荐）前台对话轮次** | 用户直接在对话里回答，由 `post_process` 新增步骤检出（复用 `ConfirmationIntentDetector` 的零 LLM 词表/序号匹配范式，新增 `PlanClarificationIntentDetector`），命中即「取答复 → 触发重新提案」 | 复用移动端既有聊天面，**零客户端改动**；与工具确认同构 | 受自然语言歧义影响，需词表 + 守卫（可加「有 pending 时才检出」的前置条件降低误判） |
| R2 审批端点扩展 | `POST /plans/{plan_id}/clarify`，body 为结构化答案 | 语义精确、天然可审计 | 需新增移动端/Web 端 plans 页（G-P4，成本最高） |
| R3 后台 job 超时兜底 | `plan_clarify_timeout_hours` 到期后按「用默认假定继续」或「驳回」自动决策 | 避免长期悬空（解 G-P5 一半） | 需要读侧（默认假定）策略设计；建议**后置** |

**结论**：先 R1（最小路径、零客户端改动），R3 作为**必须同期交付的兜底**（否则引入新的长期悬空风险），R2 随客户端 plans 页一起做。

#### 3.3.6 与既有闸门的关系与纪律

| 纪律 | 说明 |
|---|---|
| 写面唯一 | 澄清答复的落库仍只经 `goal_repository` 计划面；**不新增写函数、不新增 `decision_records` kind**（新增 kind 需改 CHECK = 需迁移） |
| 零回归 | `plan_require_clarification` 默认 `False`；OFF 时 `plan_goal()` 行为逐字节不变 |
| 与审批闸门叠加 | 澄清发生在审批**之前**；澄清完成后若 `plan_require_approval=True` 则继续停在 `validated` 待批，两道闸门串联而非并行 |
| 停靠不误伤 | 澄清挂起期间**不撤下**旧 `active` 计划（沿用审批闸门既有语义，`docs/current-system-architecture-baseline.md:503`） |
| 降级 | 澄清链路任何异常 → 回落「不澄清直接按现状提案」，绝不阻断规划 |

### 3.4 落点与影响面汇总

| 面 | P1（澄清挂起 + 前台恢复） | P2（客户端 UI） | P3（超时 + 审计） |
|---|---|---|---|
| 迁移 | **无** | 无 | 可选（若做完整审计表则 `0010+`） |
| 配置 | `plan_require_clarification` / `plan_clarify_max_rounds` / `plan_clarify_max_questions` | 无 | `plan_clarify_timeout_hours` |
| 服务 | `services/goal/`（澄清判定 + 恢复）、`planning/context.py`（字段）、`planning/` 只读消费 | 无 | `services/goal/` |
| 应用层 | `application/post_process.py`（新增澄清检出步骤）、`application/life_loop.py`（超时检查挂 tick） | 无 | `life_loop` tick |
| API | 无（走既有对话） | `api/v1/plans.py` 增 clarify 端点 | 无 |
| 客户端 | **无改动** | 移动端新增「待澄清计划」卡片 + Web 端 plans 页 | 无 |
| 测试 | 新增澄清闸门阈值/上限/降级/零回归用例 | 端侧用例 | 超时用例 |

### 3.5 风险与纪律

| # | 风险 | 缓解 |
|---|---|---|
| R-P1 | **无限追问**（Agent 反复提问，用户疲劳） | 硬上限 `plan_clarify_max_rounds`；超限即「按最合理假定继续」并 trace |
| R-P2 | **误检出**（用户普通消息被当成澄清答复） | 检出前置条件「存在该用户的 pending 澄清行」+ 问句守卫（复用工具确认范式） |
| R-P3 | **长期悬空**（挂起后无人回答） | R3 超时兜底为同期必交项；策略（自动继续 / 自动驳回）需显式裁决 |
| R-P4 | **与审批闸门叠加导致双重悬空** | 明确串联顺序（先澄清后审批）；同一目标同时最多存在一条 pending 澄清 |
| R-P5 | **包模块白名单约束** | `services/planning/` 有包模块枚举断言（`apps/backend/tests/v25/test_plan002_static_scan.py:189-207`，逐条枚举 14 个模块路径）；澄清服务落 `services/goal/`，如需落 `planning/` 必须同步改该断言 |
| R-P6 | **零回归** | 策略位默认 `False`，并提供「澄清关、审批关」的基线行为钉测 |

---

## 4. subAgent 可行性评估（本稿不裁决）

> 本章为**评估**，不含实现建议的承诺。是否放开架构红线由项目负责人裁决。

### 4.1 现状（已实现）：原材料齐全，但无 Agent 身份与委派语义

| 原材料 | 落点与证据 | 可用性 |
|---|---|---|
| Run Profile 注册表 | `apps/backend/app/application/agent_runtime/profiles.py`：`ProfileSpec` `:17`（字段 `run_kind` `:25` / `budget_tier` `:26` / `stages` `:27` / `llm_capable` `:28` / `critical` `:29` / `optional_stages` `:30`）；`_PROFILE_TABLE` `:33`；现有三个 Profile：`foreground_chat` `:34` / `autonomous_tick` `:51` / `event_driven` `:70`；`get_profile` `:80` / `snapshot_profile` `:87` | 高：声明式阶段序列 + 预算档 |
| **缺失** | **无 `register_profile` 运行时注册 API**（全文仅上述两函数）；新增 Profile = 改源码 `_PROFILE_TABLE` | — |
| Agent 契约 | `apps/backend/app/application/agent_runtime/contracts.py:233`（`AgentRuntime` Protocol），唯一方法 `run(input, context) -> RunResult`（`:236-238`）；**无 `name` / `role` / `tools` 字段** | 中：是运行时内核接口，不是可多实例化的 `BaseAgent` |
| 编排 | `apps/backend/app/application/agent_runtime/loop.py`：`_run_stages` `:389`（**线性顺序驱动**）、`STAGE_RUNNERS` `:215`、`register_stage_runner` `:221`（静态注册、重复 fail-closed）、`resolve_stages` `:154` | 低：无 DAG / 嵌套 Run / 并行段 |
| Run 生命周期 | `apps/backend/app/application/agent_runtime/controller.py:38`（`open_run`，写 `loop_runs` 经 `loop_run_repository.create_run` `:57`） | 高 |
| 上下文装配/隔离 | `apps/backend/app/application/agent_runtime/context.py`：四段 `_build_user_segment` `:113` / `_build_memory_segment` `:138` / `_build_character_segment` `:156` / `_build_world_segment` `:188`；`assemble` `:230`；`frozen` `:238`/`:239`/`:285`/`:287`；`run.data["runtime_context"]` 读 `:240` / 写 `:288`；`_resolve_user_id` `:103` | 中：隔离只能靠**开新 Session/新 Run**（键 = user + session + character） |
| 模型分流 | `apps/backend/app/core/llm_factory.py:37`（`get_llm`）/ `:86`（`list_llm_profiles`）；`apps/backend/app/application/agent_runtime/llm_gateway.py`：`CAPABILITIES` `:64`、`acquire` `:89`、`resolve_answer_llm` `:138`、tier 仅 `main`/`light`（`_CAPABILITY_DEFAULTS` `:29-42`） | 中：可按调用方选模型/档位 |
| **缺失** | **无「主体 → 独立 system prompt / 身份」绑定**：Gateway 只裁决放行/模型/预算，prompt 由各 `chains/`、`prompts/` 自带 | — |
| 异步执行底座 | `apps/backend/app/application/worker_loop.py:21`（`run_worker_loop`）；`background_jobs` 表（`services/memory/job_worker.py`：`register_job_type` `:41`、`register_tick_hook` `:46`、SKIP LOCKED 认领 `:100`/`:111`）；组合根 `apps/backend/app/main.py`：job_worker `:78`、life_loop `:89`、retention `:128`、agent evolution `:131` | **高**：subAgent 异步派发的天然载体 |
| 可观测 | `apps/backend/app/application/agent_runtime/execution_history.py`（`ExecutionHistory` `:40`、`history_for_run` `:127`、`history_for_session` `:151`）；`debug_view.py`（`ReplayBundle` `:37`、`debug_view` `:68`、`replay_bundle` `:84`）；`api/v1/debug/observability.py`（trace 路由 `:32`/`:43`/`:51`） | 中：以**单 Run 为粒度，无父子/嵌套层级** |
| 并发 | `asyncio.gather` 全 `apps/backend/app/` **仅 4 处**：`services/briefing/compose.py:130`、`application/observability.py:290`、`:296`、`application/chat_pipeline.py:543` | 低：**无计划步骤级 / 多 Agent 级并发框架** |

**否定结论**：全库搜索 `subagent`、`ask_user`、`human_in_the_loop`、`await_user`、`pending_question` 均 **0 命中**；`delegate` 命中 `apps/backend/app/engines/decision.py:383`/`:392`/`:442`，均为字面量 `"delegated"`（Action 闸门的委托状态标记），**非 Agent 委派语义**。即：**无任何 subAgent / 多 Agent / 委派雏形**。

### 4.2 架构红线冲突清单（做 subAgent 必须先解）

**注（复核更正）**：原稿把「`profiles.py` 新增会触发冻结哈希测试」列为约束，复核结果为——`FROZEN_SOURCES` 定义在 `apps/backend/tests/v24/test_tool008_integration.py:43` 与 `test_tool007_integration.py:33`，`ZERO_DIFF_HASHES` 定义在 `tests/v24/test_tool010_e2e.py:72`，**`profiles.py` 均不在其中**（`tests/v24/test_tool012_bans.py:112` 反而显式断言其不在 `FROZEN_BLOB_SHA_BASELINE`）。故新增 Profile **不受冻结哈希约束**，但受下述红线与包白名单约束。

| # | 红线 | 原文位置 | 与 subAgent 的冲突 |
|---|---|---|---|
| RL-1 | **多 Agent / 多角色并行属 Non-Goal** | `docs/version/v3.0.0/architecture.md:53`（§0.3），条目 `:55` | 直接冲突：任务型子 Agent 即「多 Agent」 |
| RL-2 | **禁止引入外部 Agent 编排框架（LangGraph / CrewAI 等）** | `docs/version/v3.0.0/architecture.md:59` | 直接冲突：若走框架路线 |
| RL-3 | **不建第二套 Agent**（新能力走 Profile 阶段 / 段本体 / Update-handoff / 域唯一写面 / 既有 trigger 五种姿势） | `docs/version/v5.0.0/tasks.md:31`；`docs/version/v4.0.0/tasks.md:20` / `:35` | 强约束：subAgent 若被建模为「第二套 Agent Pipeline」即违规；按「新增 run_kind + 独立 Run」建模则在白名单内 |
| RL-4 | **Agent Runtime 单管线**（三种 Run Profile 唯一声明，禁止另开阶段序列） | `docs/current-system-architecture-baseline.md:545`（ADR-7） | 与 RL-3 同源：只能扩展 `_PROFILE_TABLE` |
| RL-5 | **基线 §8 Extension Points 与 §11 未含 subAgent / 多 Agent** | `docs/current-system-architecture-baseline.md:438`（§8 标题，8.1~8.6 无该条目）、`:569`（§11.1 只提「扩展新 run_kind」） | subAgent 属**基线未登记方向**，须先登记再开发 |

**唯一预留点**：`docs/version/v3.0.0/architecture.md:571-573`（§10.4「更远」）——`character_id` / `session_id` 贯穿使 Agent Runtime 可按角色实例化多份循环（每角色独立 Session/Context/State 版本），**本版本不设计**。这是「按角色多实例」，**不是「委派/协作」**。

**包约束**：`services/planning/` 有包模块枚举断言（`apps/backend/tests/v25/test_plan002_static_scan.py:189-207`，逐条枚举 14 个模块路径）；`services/planning/goal_contract.py:197`（`PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS`）为调用白名单。subAgent 相关服务**不应落 `services/planning/`**。

### 4.3 落点选项（评估，不裁决）

| 选项 | 形态 | 改动面 | 需迁移 | 需更新基线 | 冲突度 |
|---|---|---|---|---|---|
| **S-A 新 run_kind + 独立 Run（任务型子 Agent）** | 每个子 Agent = 一个新 Profile（独立阶段序列 + 预算档 + 独立 Session/Run）；由主 Run 通过 `background_jobs` 派发，结果经 Outbox/事件回投 | `profiles.py` 新增 Profile；新增「主体 → prompt/身份」映射层；新增派发器（复用 `worker_loop`）；`loop_runs` 增父子关联（可能需迁移） | 可能（父子 Run 关联列） | **必须**（解 RL-1/RL-3/RL-5） | 高 |
| **S-B 按 `character_id` 多实例（多角色）** | 沿 §10.4 预留点，按角色实例化多份循环，每角色独立 Session/Context/State | `profiles.py` 保持不变；`session.py` / `context.py` 的键已含 `character_id`，主要是装配与调度侧扩展 | 否 | 需登记（§10.4 从「更远」升为「规划中」） | **中（不改红线）** |
| **S-C Agent-as-Tool（能力化）** | 把「子 Agent」降格为一种 Tool（`ToolRegistry` 注册），主 Agent 通过 Function Calling 调用 | `services/tool/` 新增工具实现；Tool 执行器已是同步/异步封装 | 否 | 需登记（须说明为何不算「第二套 Agent」） | 低-中 |
| **S-D 引入外部编排框架** | LangGraph / CrewAI 等 | 全面重构 Agent Runtime | — | **必须**且需废除 RL-2 | **极高（明确不推荐）** |

**说明**：S-C 与 RL-3 张力最小（它明确「不建第二套 Agent」，只是加一个 Tool），但表达力最弱（无独立上下文/无长时异步/无委派链）；S-A 表达力最强但冲突最大；S-B 是**唯一不改红线**的路径，但只解决「多角色」而非「任务委派」。

### 4.4 缺口清单（做 subAgent 需要补的）

| # | 缺口 | 证据 |
|---|---|---|
| G-S1 | 无 Agent 身份/注册抽象（无 `BaseAgent`，无 `register_profile`） | `profiles.py:80` / `:87`；`contracts.py:233` |
| G-S2 | 无「主体 → 独立 system prompt / 身份」绑定机制 | `llm_gateway.py:89` 仅裁决模型/预算 |
| G-S3 | 无父子 / 嵌套 Run 概念，无委派链观测 | `controller.py:38`；`loop_runs` 为唯一递归单位 |
| G-S4 | 上下文隔离只能靠新 Session/Run，无同 Run 内多隔离上下文 | `context.py:103` / `:230` |
| G-S5 | 编排线性，无 DAG / 并行段 / 步骤级并发 | `loop.py:389`；`asyncio.gather` 仅 4 处且不可复用 |
| G-S6 | 无子 Agent 结果的回投/聚合机制（超时、失败、部分成功语义未定义） | 未找到证据 |
| G-S7 | 基线未登记 subAgent 方向（§8 / §11 均无） | `docs/current-system-architecture-baseline.md:438` / `:569` |

### 4.5 若要做，必须先做的三件事（前置）

1. **红线裁决与基线登记**：显式裁决 RL-1~RL-5（哪条放开、放开到什么程度），并同步更新 `docs/current-system-architecture-baseline.md`（§8 Extension Points 新增条目 + §11 演进方向改写 + ADR 追加）。**在此之前任何 subAgent 代码都判违规。**
2. **Agent 身份抽象**：定义 `BaseAgent`（名称/角色/system prompt 作用域/工具作用域/预算档）与**主体 → prompt/profile 绑定**机制；决定「注册是源码级还是运行时级」（S-A 需要运行时注册，涉及 `_PROFILE_TABLE` 与钉测改写）。
3. **Run 血缘与观测**：为 `loop_runs` 增父子/委派关联（`parent_run_id` + `delegation_kind`，需迁移 `0010+`），并让 `execution_history` / `debug_view` 支持「参与树」查看；同时定义子 Agent 的超时/失败/部分成功的收敛语义（G-S6）。

**落地建议顺序（不构成裁决）**：先在 S-C（Agent-as-Tool）上做一次**最小可行性验证**（不改红线、表达力受限但风险最低），验证「独立 prompt + 独立上下文 + 异步执行 + 结果回投」四要素是否够用，再决定是否升级到 S-A 并解红线。

---

## 5. 推进顺序与依赖

### 5.1 阶段划分

| 阶段 | 主题 | 关键交付 | 迁移 | 前置 |
|---|---|---|---|---|
| **M1** | 记忆检索质量 | LLM 重排 + query 改写 + 亲和词表扩容 + 离线门槛扩展 | 无 | 无 |
| **M2** | 记忆显式分层 | `memories.layer` + 情景聚合 + 语义抽象 + 检索配额 | `0010` | M1（复用重排） |
| **M3** | 记忆图谱与产品面 | 1-hop 图扩展 + 记忆搜索/筛选 + Web 端编辑 + 主题聚类 | `0010+`（CHECK 扩展） | M2 |
| **P1** | 计划级澄清（挂起 + 前台恢复） | 澄清闸 + `PlanContext` 槽位 + `post_process` 检出 + 超时兜底 | 无 | 无（与 M 并行） |
| **P2** | 澄清客户端面 | 移动端「待澄清计划」卡片 + Web plans 页 | 无 | P1 |
| **P3** | 澄清审计与审批 UI 合流 | 审批 UI + 澄清归因 + 超时策略产品化 | 可选 | P2 |
| **S0** | subAgent 红线裁决 | 基线登记 + ADR | — | **用户裁决** |
| **S1~** | subAgent 实现 | 身份抽象 + 血缘观测 + 派发器 | `0010+` | S0 |

### 5.2 依赖矩阵

| 依赖方 ↓ / 被依赖 → | M1 | M2 | M3 | P1 | P2 | P3 | S0 |
|---|---|---|---|---|---|---|---|
| M2 | 需要（复用重排） | — | — | — | — | — | — |
| M3 | — | 需要 | — | — | — | — | — |
| P1 | **受益（非阻塞）**：`PlanContext._assemble_memory` `context.py:605` 消费记忆检索，M1 提升澄清质量 | — | — | — | — | — | — |
| P2 | — | — | — | 需要 | — | — | — |
| P3 | — | — | — | — | 需要 | — | — |
| S1 | — | — | — | **需要 P1 的「挂起态 + 恢复」范式**（委派链本质是挂起/恢复编排） | — | — | 需要 |

### 5.3 基线同步建议（架构演进纪律）

本稿为**规划稿**，不产生代码。已核实的**三处文档漂移（§1.2 D1~D3）**属**现状描述错误**，已**同批**更新 `docs/current-system-architecture-baseline.md`（2026-10-14）：

| 修正项 | 动作 |
|---|---|
| D1 | §3.6（`:169`/`:170`）与 §8.2（`:453-456`）、§11.2（`:577`）中的 `services/memory_service.py` / `memory2/` 改为 `apps/backend/app/services/memory/`（单包，14 模块），并补 `engines/memory_policy.py` 的 v1 硬规则定位 |
| D2 | §3.4（`:135-148`）澄清「生产主路径 = `goal_planning.plan_goal`；七闸 `PlanningEngine` 当前仅可选段接入」，避免读者误判引擎已接管 |
| D3 | §3.4 注明 `draft` 为「已定义未使用」状态 |
| 新增 | §8.7 新增「Plan Clarification Gate（规划中，未实现）」扩展点 |
| 顺带更正 | §3.4 / §3.6 / §8.2 / §11.2 / §11.3 的路径与描述同步更正（含 `decompose/decomposer.py`、`services.memory.job_worker`）；§8.6 包模块断言归因更正为 `tests/v25/test_plan002_static_scan.py:189-207` |
| 任务注册 | 已生成 `docs/version/v6.0.0/tasks.md`（主干 `MEV-001~014` + `PLN-001~009`；`SAG-000~004` 未排期） |

按仓库纪律：**任何架构演进须先更新该基线，再进入开发**。基线同步与任务注册表生成**已完成**（2026-10-14，任务注册见 `docs/version/v6.0.0/tasks.md`）；后续进入开发时，应先按该注册表 §7 生成对应里程碑的 Task Detail，再动代码。

---

> **文档结束**。本文档为评审级规划稿，所有「现状」结论均附代码路径与行号，所有「规划」内容均显式标注未实现；不含任何代码改动。
