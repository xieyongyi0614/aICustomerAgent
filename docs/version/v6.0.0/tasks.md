# V6.0.0 Agent Evolution Tasks（记忆演进 + 计划澄清）

> **上游（唯一依据，最优先）**：`docs/agent-evolution-plan-2026-10.md`（三方审核结论 + 分层演进设计：记忆 §2 / 交互式澄清 §3 / subAgent 可行性 §4；推进顺序 §5）——**本注册表之外的任何能力均不得进入 Task Detail**。
> **上游（现状约束）**：`docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线；本版本依赖的 §3.4 / §3.6 已于 2026-10-14 同步更正，§8.7 已登记 Plan Clarification Gate 扩展点）。
> **上游（体例与工程纪律）**：`docs/version/v5.0.0/tasks.md` §0（七条前提，尤其 §0.3 迁移纪律与 §0.4 测试与验证纪律）、`docs/version/v4.0.0/tasks.md` §0（九条前提裁决，尤其裁决 9「禁止新增功能开关」）。
> **状态**：Task Registry（任务定义）+ **Task Detail 全部生成（28/28）**：`MEV-001~014`（14）+ `PLN-001~009`（9）+ `SAG-000~004`（5）均已就位（2026-10-14，位于 `docs/version/v6.0.0/tasks/`，体例见 `tasks/README.md`）。**注**：`SAG-*` 仍**未排期且阻塞于 `SAG-000`**（§0.6 裁决 6），Task Detail 就位不等于可开工。
> **主干**：28 个任务 / 3 条任务线（`MEV-` 记忆演进 / `PLN-` 计划澄清 / `SAG-` 子 Agent **未排期**）+ 6 个里程碑。
> **版本定位**：V6.0.0 = **Agent Evolution**（后端能力演进轴），与客户端轴 V5.x 并行不冲突；**不含** subAgent 实现（未裁决，仅登记候选）。
> **本文档不含代码、不含 DDL、不含 UI 稿。**

---

## 0. 关键前提裁决（先读）

> 本版本全部任务建立在以下七条前提之上；任一 Task 的 Detail 与实现不得绕过。

### 0.1 裁决 1：只做演进，不改既有域行为

| 既有资产 | V6.0.0 处置 |
|---|---|
| `services/memory/`（单包 14 模块） | **Extend**：检索链与生命周期参数扩展；`ingest` / `evaluator` / `candidates` 幂等契约**逐字节不变** |
| `services/goal/`（`planning.py` / `approval.py`） | **Extend**：新增澄清闸与恢复路径；`plan_goal()` 在策略位关闭时行为**逐字节不变** |
| `services/planning/`（七闸引擎 / scheduler / observer / executor_bridge） | **Preserve + 消费**：只读消费；**新增模块一律不得落该包**（见裁决 5） |
| `services/tool/confirmation.py` | **Preserve + 范式借鉴**：只借鉴 `ConfirmationIntentDetector` 的零 LLM 词表范式，**不复用其 kind** |
| `agent_runtime`（Run / Profile / 阶段） | **Preserve**：不新增 Profile、不改阶段序列（裁决 4） |
| `trigger_registry` | **Extend**：新增 kind 字面量（澄清挂起载体），零迁移 |
| 账本域 / 关系域 / 世界域 / Reflection / Development | **Preserve**：零改动 |

**禁止**：新增 `agents2/` / `memory3/` / 第二套 Pipeline；嫁接 LangGraph / CrewAI 等第三方编排（`docs/version/v3.0.0/architecture.md:53-59`）。

### 0.2 裁决 2：迁移纪律

| 项 | 内容 |
|---|---|
| 链尾现状 | `apps/backend/migrations/versions/0009_app_release_artifacts.py`（增量链 `0002`~`0009` 已存在） |
| 本版本新增 | **`0010`**（`ck_memories_type` 收窄为 7 值，服务 `MEV-015`，2026-10-16 入链）；**`0011`**（`ck_relationship_events_source` 收窄为两值，回放补记退役清账，2026-10-16 入链）；**`0012`**（`memories.layer`，服务 `MEV-005`）；**`0013`**（`memory_links.relation` CHECK 扩展，服务 `MEV-009`）；`SAG-002` 若开工再顺延取号 |
| 串行纪律 | 同一批迁移必须**串行入链**，不得并行改链尾；一个迁移承载一个域面 |
| 已知陷阱 | 加一条迁移会打破跨版本钉测（`MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`，单点 `tests/support/schema_pins.py`）→ 执行前先取干净基线测 blast radius（继承 `docs/version/v5.0.0/tasks.md` §0.3） |
| 禁止 | 再次折叠迁移链；`create_all` 路径（测试内存 SQLite 属豁免） |

### 0.3 裁决 3：零迁移优先 + 零回归优先

- **零迁移优先**：计划澄清闸（`PLN-001`~`PLN-005`）必须优先用「复用 `validated` 停靠态 + `trigger_registry` 新 kind」实现；**新增状态值或专用表**仅在零迁移方案被证伪时才提（届时单独裁决）。
- **零回归优先**：所有新增策略位/取值位默认 **off**；off 时既有行为逐字节不变，并提供基线行为钉测。
- **降级纪律**：记忆域与规划域既有纪律均为「异常只降级不阻断」；新增链路必须沿用（异常 → 回落既有路径 + 落 trace）。

### 0.4 裁决 4：设置项——只许参数与策略位，不许功能开关

> 继承 V4.0.0 裁决 9（**禁止 `*_enabled` 形态的功能位**）与基线「`vXX_` 前缀已删除」纪律。

| 允许形态 | 命名 | 语义 | 默认 | 归属 |
|---|---|---|---|---|
| 取值类 | `memory_rerank_mode` | 重排模式（`off` / `lite`） | `"off"` | MEV-001 |
| 取值类 | `memory_query_rewrite_mode` | 查询改写模式（`off` / `lite`） | `"off"` | MEV-002 |
| 阈值类 | `memory_rerank_top_k` | 参与重排的候选数上限 | 待 Task Detail 冻结 | MEV-001 |
| 取值类 | `memory_layer_quota` | 分层检索配额（如 `"3:5"`） | 待定 | MEV-008 |
| 策略位 | `plan_require_clarification` | 是否在提案后要求澄清（对齐既有 `plan_require_approval` 先例，**非 `*_enabled` 形态**） | `False` | PLN-001 |
| 参数类 | `plan_clarify_max_rounds` / `plan_clarify_max_questions` | 澄清轮次与问题数硬上限 | `1` / `3` | PLN-001 |
| 参数类 | `plan_clarify_timeout_hours` | 澄清挂起超时（`0` = 不启用超时兜底） | `0` | PLN-005 |

- 新设置落**既有领域模块**（`core/settings/memory.py` / `core/settings/plan.py`），不新建模块、不扩 `pipeline.py`。
- env 名 = 字段名大写（无 alias 层）；改名须同批同步部署侧 `.env`；`extra="ignore"` 是静默陷阱。

### 0.5 裁决 5：包白名单与落点纪律

| 包 | 约束 | 影响 |
|---|---|---|
| `services/planning/` | 有**包模块枚举**负向断言（`tests/v25/test_plan002_static_scan.py:189-207`）与 `PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS` 白名单（`services/planning/goal_contract.py:197`） | 澄清服务**必须落 `services/goal/`**；`PLN-*` 不得向 `services/planning/` 加模块 |
| `services/memory/` | 无模块枚举断言，但既有单包结构应保持；新增模块须同步登记相关静态扫描（如有） | `MEV-*` 新增文件优先落 `services/memory/` 单包内 |
| 写面 | 计划写面只经 `goal_repository` 计划面；记忆写面只经 `memory_repository`（候选唯一入口 `create_candidate`） | 不得新增写函数、不得新增 `decision_records` kind（新增 kind 需改 CHECK = 需迁移） |

### 0.6 裁决 6：subAgent 未裁决，本版本不开工

- `SAG-*` 任务（§6）**仅为候选登记，不计入主干，不排期**。
- 开工前置 = 用户对架构红线（`docs/agent-evolution-plan-2026-10.md` §4.2 RL-1~RL-5）的显式裁决 + 基线登记。**裁决前任何 `SAG-*` 代码均判违规。**

### 0.7 裁决 7：测试与验证纪律

- 继承 `docs/version/v5.0.0/tasks.md` §0.4 全部条目（基线对照法判零回归、`--basetemp` 换名、PG 用例前置 `DROP SCHEMA`、EOL 约定、**绝不执行 `git rm`**、commit 后复核 `rev-parse HEAD`）。
- 本版本特有：**策略位/取值位 off = 基线钉测**（`plan_require_clarification=False` 时 `plan_goal()` 行为不变；`memory_rerank_mode="off"` 时 `retriever.retrieve` 打分逐字节不变）。
- 记忆域评估：`MEV-004` 必须扩 `services/memory/offline_metrics.py` 的评估集并跑门槛。

---

## 1. 任务总览

| 里程碑 | 主题 | 任务 | 数量 |
|---|---|---|---|
| **M0** | 记忆词表收窄（迁移 `0010`） | `MEV-015` | 1 |
| **M1** | 记忆检索质量（零迁移） | `MEV-001 ~ MEV-004` | 4 |
| **M2** | 记忆显式分层（迁移 `0012`） | `MEV-005 ~ MEV-008` | 4 |
| **M3** | 记忆图谱与产品面（迁移 `0013`） | `MEV-009 ~ MEV-014` | 6 |
| **P1** | 计划澄清地基（零迁移） | `PLN-001 ~ PLN-005` | 5 |
| **P2** | 计划澄清产品面 | `PLN-006 ~ PLN-009` | 4 |
| **S** | 子 Agent（**未排期**，阻塞于 SAG-000 裁决） | `SAG-000 ~ SAG-004` | 5 |
| | | **主干合计（M0~M3 + P1~P2）** | **24** |
| | | **含未排期候选合计** | **29** |

**依赖总览**：**M0 → M1 → M2 → M3**（串行；M0 先入链以腾出类型词表的确定状态，M2 的 `layer` 回填映射因此只需覆盖 7 规范类型）；P1 → P2（串行）；**M 与 P 可并行**，但 P 的澄清上下文消费 `PlanContext._assemble_memory`（`apps/backend/app/services/planning/context.py:605`），故 M1 交付会直接改善澄清质量。**S 依赖 P1 的「挂起态 + 恢复」范式**。

### 1.1 M0 · 记忆词表收窄（`MEV-015`，迁移 `0010`，**2026-10-16 已实施**）

> **目标**：把记忆类型**存储词表**由 9 值（7 规范 + 2 遗留）收窄为 7 规范值，遗留类型
> `important_event` / `relationship_event` 退役；遗留名只保留在**入站归一**（LLM 输出 / 旧数据）。
> 触发：`docs/refactor/memory-migration-and-version-naming-audit-2026-10-15.md` §2.3 / §7.3
> （库可重建，存量迁移随之作废；写入口未归一仍会产遗留行）。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| MEV-015 | 遗留记忆类型退役 | 数据/契约 | P1 | — | 迁移 `0010`：`ck_memories_type` 收窄 + 存量遗留行就地归一；`models/memory.py`（`MemoryType` 7 值 + `CandidateMemoryType` 入站域）；`services/memory/types.py`（删 `STORAGE_MEMORY_TYPES`/`storage_type`，`LEGACY_TYPE_ALIASES` 降为入站归一表）；入站产出四处改规范名；标签表 / 分组表收窄；回放路径（`state.py::_replay_relationship_memories`）随之删除 |

**交付判据**：① 新库 / 重建库 `upgrade head` 到 `0010` 后 `memories.type` 仅接受 7 值；
② 遗留名从任一入口（LLM 提取、动作参数、世界/关系摄取、计划终态）进入后**落库即规范值**；
③ 回放补记路径与其 settings 字段一并删除，`memory_replay` 事件源不再产生新行；
④ `schema_pins` 四钉同步（HEAD/PARENT 推进，表数与列摘要不变）且全仓钉测绿。

---

## 2. M1 · 记忆检索质量（`MEV-001 ~ MEV-004`，零迁移）

> **目标**：在不改 schema 的前提下，把「召回 → 打分」这条链从「纯 cosine + 结构化」升级为「可选 lite LLM 重排 + 多 query 检索 + 完整类型亲和」，并补齐可观测与离线门槛。**默认全 off，off 时行为逐字节不变。**

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| MEV-001 | LLM 重排（lite rerank） | 能力 | P1 | — | 新增 `apps/backend/app/chains/memory_rerank_chain.py`；挂接 `apps/backend/app/services/memory/retriever.py::retrieve`（`score` 重排）；候选数阈值 + `memory_llm_fallback_rate_cap` 类护栏 + 失败回落既有排序；配置 `memory_rerank_mode` / `memory_rerank_top_k` |
| MEV-002 | Query 改写与多路检索 | 能力 | P1 | — | 新增改写链（lite profile）；`services/conversation/context.py`（`retrieve` 调用处 `:253`）扩展为「原 query ∪ 改写 query」并集打分；失败回落单 query；配置 `memory_query_rewrite_mode` |
| MEV-003 | 类型亲和词表扩容 | 质量 | P2 | — | `apps/backend/app/services/memory/types.py::TYPE_AFFINITY_KEYWORDS`（`:30`）由 4 类扩至全 7 类 + 同义词表；附单测覆盖每类命中 |
| MEV-004 | 召回可观测与离线门槛扩展 | 观测/评估 | P1 | MEV-001, MEV-002 | `services/memory/refs.py`（`turn_meta.memory_refs`）补「重排前后名次/分数」；`services/memory/offline_metrics.py` 评估集纳入重排维度；调试面只读展示 |

**M1 验收口径**：`memory_rerank_mode="off"` 且 `memory_query_rewrite_mode="off"` 时，`retriever.retrieve` 输出的分数序列与基线**逐字节一致**（钉测）；全 on 时离线评估集指标不低于基线且无 P95 延迟爆炸（预算内）；任一 LLM 调用失败时回落既有排序并落 trace。

---

## 3. M2 · 记忆显式分层（`MEV-005 ~ MEV-008`，迁移 `0012`）

> **目标**：在既有扁平 7 类型之上引入显式 **Episodic / Semantic** 通道，检索按通道分配配额，生命周期按通道差异化衰减。**`layer` 只作检索分通道依据，不做权限或来源真相。**

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| MEV-005 | `memories.layer` 迁移与回填 | 数据 | P0 | M0, M1 | 迁移 `0012`：ADD COLUMN `layer`（`episodic` / `semantic`）+ **幂等回填**（由既有 `type` 映射推导）+ 索引；改 `apps/backend/app/core/db/memory.py`；bump `tests/support/schema_pins.py` 钉测 |
| MEV-006 | 情景聚合（Episodic） | 能力 | P0 | MEV-005 | 新增 `apps/backend/app/services/memory/episodic.py`：按 `(user_id, 时间窗, 主题)` 聚合会话/行动/世界事件为情景条目，保留 `source_ref` 指针；经既有三段评估转正；后台 job 注册（复用 `register_job_type`） |
| MEV-007 | 语义抽象（Semantic） | 能力 | P1 | MEV-006 | 新增 `apps/backend/app/services/memory/semantic.py`：由若干 `episodic` 条目经 LLM 抽象为跨事件概念/偏好，复用 `evaluator` 三段评估与冲突消解 |
| MEV-008 | 分层检索配额与衰减差异化 | 调优 | P1 | MEV-006 | `retriever.py` 按 `layer` 分配召回配额（配置 `memory_layer_quota`）；`core/settings/memory.py::memory_decay_lambda_json` 扩展为按 `layer` 差异化（episodic 快、semantic 慢） |

**M2 验收口径**：`0001`+`0010` 全链可 `upgrade head` 且回填幂等（重复执行结果不变）；`layer` 与 `type` 语义不重叠（文档 + 单测断言映射关系）；关闭分层配额时检索结果与 M1 一致。

---

## 4. M3 · 记忆图谱与产品面（`MEV-009 ~ MEV-014`，迁移 `0013`）

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| MEV-009 | `memory_links` 关系扩展与 1-hop 检索 | 数据/能力 | P2 | M2 | 迁移 `0013` 改 `relation` CHECK（新增 `caused_by` / `before` / `related`）；`retriever.py` 增 1-hop 扩展召回（扩展结果降权）；bump 钉测 |
| MEV-010 | 记忆关系抽取 | 能力 | P2 | MEV-009 | 转正链路延伸 `services/memory/evaluator.py`：LLM 判定新记忆与既有记忆的关系并落 `memory_links`；失败静默跳过（不阻断转正） |
| MEV-011 | 记忆搜索与筛选端点 | API | P2 | M1 | `GET /memory/items`（`apps/backend/app/api/v1/memory.py:51`）增 `q` / `type` / `layer` / 时间区间参数，服务端检索复用 `retriever`；**向后兼容**（无参时行为不变） |
| MEV-012 | 主题聚类卡片 | 产品 | P3 | MEV-007 | `services/memory/product_view.py` 增只读派生「主题卡片」；后台 job 周期计算；**不新表** |
| MEV-013 | Web 端记忆面板可编辑化 | 前端 | P2 | MEV-011 | `apps/frontend/src/components/debug/memory-panel.tsx` 由只读升级为可编辑/可遗忘（复用移动端已验收 API）；补搜索框 |
| MEV-014 | 字段级 / 部分遗忘 | 能力 | P3 | M2 | `services/memory/lifecycle.py` 增「部分遗忘」（内容脱敏重写 + `merge_chain` 留痕），产品读面与 API 同步；不改整行遗忘既有语义 |

**M3 验收口径**：`GET /memory/items` 无参行为与基线一致；1-hop 扩展在无 link 数据时零影响；Web 端编辑/遗忘端到端可用；部分遗忘留痕可溯源。

---

## 5. P1 / P2 · 计划澄清（`PLN-001 ~ PLN-009`）

> **目标**：落地 **L1 澄清闸**（Agent 带多选项提问 → 用户选择 → 重新提案），与 L2 审批闸（§8.6）、L3 工具确认构成三层。**P1 阶段强制零迁移。**

### 5.1 P1 · 计划澄清地基（零迁移）

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| PLN-001 | 澄清判定闸（生成 + 阈值 + 上限 + 降级） | 能力 | P0 | — | `apps/backend/app/services/goal/planning.py`：在 `plan_goal()` 的提案后、`activate_plan()` 前插入澄清判定（结构化输出 `need_clarification` + `questions[]` + `options[]` + `allow_free_text`）；硬上限（轮次/问题数）；异常降级为「不澄清直接提案」；配置 `plan_require_clarification` / `plan_clarify_max_rounds` / `plan_clarify_max_questions` |
| PLN-002 | `PlanContext` 澄清槽位与重新提案 | 能力 | P0 | PLN-001 | `apps/backend/app/services/planning/context.py::_build_context`（`:297`）增 `clarification` 字段（questions/answers/round）；`services/goal/planning.py::_build_messages`（`:274`）在 `round ≥ 1` 注入「用户已澄清」段；重走 `propose_plan`（`:350`）而非增量修补 |
| PLN-003 | 澄清挂起载体（零迁移） | 数据 | P0 | PLN-001 | 复用 `trigger_registry` 新增 kind 字面量（如 `plan_clarification`），载荷含 `plan_id` + `questions[]` + `round`；计划仍停既有 `validated` 停靠态；**不新增状态值、不新增表、不新增 `decision_records` kind** |
| PLN-004 | 前台恢复（对话轮次） | 能力 | P0 | PLN-003 | 新增零 LLM 检出器（词表 + 问句守卫，范式对齐 `apps/backend/app/services/tool/confirmation.py::ConfirmationIntentDetector`（`:642`）），前置条件 = 存在该用户 pending 澄清行；接线 `apps/backend/app/application/post_process.py`（对齐 `_run_confirmation_round` `:564` 的位置）；命中即「取答复 → 触发重新提案」 |
| PLN-005 | 澄清超时兜底 | 能力 | P0 | PLN-003 | 挂 `apps/backend/app/application/life_loop.py` tick：`plan_clarify_timeout_hours` 到期按显式策略（自动继续 / 自动驳回）收敛；配置默认 `0`（关闭） |

**P1 验收口径**：`plan_require_clarification=False` 时 `plan_goal()` 行为**逐字节不变**（钉测）；ON 且触发澄清时计划停在 `validated` 且**不撤下**旧 `active` 计划；答复检出误判率可控（无非 pending 时的误触发）；澄清轮次不超上限；超时兜底可用；链路异常一律降级不阻断。

### 5.2 P2 · 计划澄清产品面

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| PLN-006 | 移动端「待澄清计划」卡片 | 客户端 | P1 | PLN-004 | `apps/mobile/lib/features/` 新增计划澄清入口（回答问题 + 提交）；选项文案服务端下发，端上零映射 |
| PLN-007 | 结构化澄清端点 + Web plans 页 | API/前端 | P2 | PLN-003 | `apps/backend/app/api/v1/plans.py` 增 `POST /plans/{plan_id}/clarify`（状态与归属守卫 fail-closed，对齐既有 `:69` / `:75` 风格）；`apps/frontend/src/features/` 新增 plans 页 |
| PLN-008 | 澄清审计归因 | 观测 | P2 | PLN-001 | 澄清轮次与答复对计划的**实际影响**可归因；**优先复用既有 `decision_records` 记录（不新增 kind）**，完整审计表留待后续裁决 |
| PLN-009 | 审批 UI（移动端 plans 页） | 客户端 | P2 | PLN-007 | 兑现基线 §8.6「当前未实现：前端 plans 页面」，与澄清卡片同页承载 |

**P2 验收口径**：移动端可完成「看到澄清 → 回答 → 计划继续推进」闭环；审批 UI 可批准/驳回；端上无中文标签映射表。

---

## 6. S · 子 Agent（`SAG-000 ~ SAG-004`，**未排期，阻塞于裁决**）

> **前置**：§0.6 裁决 6。开工前必须先完成 `SAG-000`（红线裁决 + 基线登记）。任务定义**仅为候选登记**，不构成承诺。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| SAG-000 | 架构红线裁决与基线登记 | 裁决 | **P0（阻塞项）** | 用户决策 | 逐条裁决 `docs/agent-evolution-plan-2026-10.md` §4.2 RL-1~RL-5；同步 `docs/current-system-architecture-baseline.md`（§8 新增条目 + §11 改写 + ADR 追加） |
| SAG-001 | Agent 身份抽象 | 基建 | P2 | SAG-000 | 定义 `BaseAgent`（名称 / 角色 / system prompt 作用域 / 工具作用域 / 预算档）+ 主体 → prompt/profile 绑定机制（当前 `llm_gateway` 只裁决模型档位） |
| SAG-002 | Run 血缘与观测 | 基建 | P2 | SAG-000, SAG-001 | `loop_runs` 增 `parent_run_id` / `delegation_kind`（迁移，取号顺延）；`execution_history` / `debug_view` 支持「参与树」只读查看 |
| SAG-003 | 派发器与结果回投 + 最小可行性验证 | 能力 | P3 | SAG-002 | 复用 `background_jobs` + `worker_loop` 异步派发；定义子 Agent 超时/失败/部分成功收敛语义（当前未找到证据）；**先在 S-C（Agent-as-Tool）形态做验证**（不改红线、风险最低） |
| SAG-004 | subAgent 架构文档 | 文档 | P3 | SAG-003 | 独立架构文档（含红线裁决结论、身份契约、委派语义、观测口径），作为该域唯一依据 |

---

## 7. Task Detail 生成状态与后续

| 项 | 状态 |
|---|---|
| Task Detail | **已生成（28/28）**（2026-10-14）。**M0**：`MEV-015`（遗留记忆类型退役，迁移 `0010`）——2026-10-16 由审查驱动直接实施，**未生成 Task Detail**（同批清账：`0011` 关系事件源枚举收窄）。**M1**：`MEV-001`（lite 重排）/ `MEV-002`（query 改写与多路召回）/ `MEV-003`（词表与标签覆盖）/ `MEV-004`（可观测与离线门槛）。**M2**：`MEV-005`（`layer` 列与迁移 `0012`）/ `MEV-006`（情景聚合）/ `MEV-007`（语义抽象）/ `MEV-008`（分层配额与衰减调制）。**M3**：`MEV-009`（`memory_links` 值域与 1-hop，迁移 `0013`）/ `MEV-010`（关系抽取）/ `MEV-011`（记忆搜索与筛选 API）/ `MEV-012`（主题卡片，只读派生）/ `MEV-013`（客户端记忆面：Web 可编辑 + 移动端搜索）/ `MEV-014`（部分遗忘）。**P1**：`PLN-001`（澄清判定闸）/ `PLN-002`（上下文与 prompt 槽位）/ `PLN-003`（挂起载体，零迁移）/ `PLN-004`（前台恢复）/ `PLN-005`（超时兜底）。**P2**：`PLN-006`（移动端澄清卡片）/ `PLN-007`（结构化端点 + Web plans 视图）/ `PLN-008`（审计与归因）/ `PLN-009`（移动端审批 UI）。**S（未排期）**：`SAG-000`（红线裁决，阻塞项）/ `SAG-001`（身份抽象）/ `SAG-002`（Run 血缘，迁移 `0012`）/ `SAG-003`（派发与收敛 + S-C 最小验证）/ `SAG-004`（域架构文档）。体例见 `tasks/README.md`（10 节）。**已登记的依赖/落点修正**：`PLN-006` 依赖改为 `PLN-007`（客户端需结构化端点）；`MEV-014` 留痕由 `merge_chain` 改为 `source_ref.partial_forget_history`（避免虚增 `source_count`）；`MEV-012` 与注册表「后台 job 周期计算」的显式偏差（改为读时派生）；`MEV-002` 落点由「`services/conversation/context.py` 调用处扩展为并集打分」改为「`services/memory/retriever.py` 内部多 query 召回 + 归并」（`conversation/context.py` 零改动，签名冻结） |
| 迁移编号占用 | `0010` = MEV-015（已入链）；`0011` = 关系事件源枚举收窄（已入链，回放补记退役清账）；`0012` = MEV-005；`0013` = MEV-009；`SAG-002` 顺延待取号（不得并行改链尾） |
| 待决策项 | ① 澄清超时策略（自动继续 / 自动驳回 / 永久等待）；② 是否为新 memory 模块补静态扫描；③ `MEV-008` 配额取值；④ subAgent 红线（SAG-000） |
| 未登记项 | V6.0.0 **不覆盖**：审批触达（飞书推送）、审批审计归因表、Self Improvement 闭环、多通道（Discord / Telegram）——属其他方向，须另立注册表 |
| 基线同步 | 已完成（2026-10-14）：§3.4 D2/D3、§3.6 D1、§8.2 / §11.2 / §11.3 路径更正、§8.7 新增 Plan Clarification Gate 扩展点 |

---

> **文档结束**。本注册表冻结 ID / 名称 / 类型 / 优先级 / 依赖 / 交付面；不含代码、不含 DDL、不含 UI 稿。任何超出 `docs/agent-evolution-plan-2026-10.md` 的能力不得进入 Task Detail。
