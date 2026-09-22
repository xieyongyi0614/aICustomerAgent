# V4.0.0 Personal Life Agent Foundation Tasks

> **上游（架构依据，最优先）**：`docs/version/v4.0.0/architecture.md`（V4.0 唯一架构依据：主体与归属设计、账本域设计、运行时采用裁决、边界不变量 10 条）——**本注册表之外的任何能力均不得进入 Task Detail**。
> **上游（需求来源）**：`docs/version/v4.0.0/reviews/personal-life-agent-architecture-review.md`（个人生活智能体架构评审：五缺口 + 六维评分 + Phase A~F 演进路径）。
> **上游（运行时审计）**：`docs/version/v4.0.0/audits/v3.0.0-runtime-adoption-audit.md`（V3.0.0 Agent Runtime 完成度与采用审计；裁决见 architecture §2）。
> **上游（现状约束）**：`docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线）；`docs/version/v3.0.0/architecture.md` + `tasks.md` + `acceptance-report.md`（Agent Runtime 线，§7.3 Backlog 已预留 V3.1~V3.3）。
> **状态**：Task Registry（任务定义）+ **Task Detail 已就位**（`tasks/PLA-001.md` ~ `tasks/PLA-018.md`）；**PLA-001 / PLA-002 / PLA-018 已实现（2026-09-22）**；PLA-003 ~ PLA-017 未实现
> **主干**：PLA-001 ~ PLA-018（依赖顺序即文档顺序；PLA-018 为审计后**追加登记**，执行位置在 Phase 1，见 §4.1）
> **说明**：本文档做任务级拆分，冻结 **ID / 名称 / 类型 / 优先级 / 依赖 / 交付面**；各 Task 的可执行明细见 `docs/version/v4.0.0/tasks/PLA-XXX.md`（体例对齐 `docs/version/v3.0.0/tasks/RT-002.md`：Task Overview / Background / Scope / Tech Design / Implementation Plan / File Impact / Testing / Acceptance / Commit）。**本文档不含代码、不含 DDL 与迁移脚本。**
> **定位复述**：V4.0 = **个人生活智能体地基（Personal Life Agent Foundation）**。把当前「角色生命模拟器」的主体从**角色**翻转为**用户**，交付两块此前完全缺失的地基——**① 用户实体（谁是主人）** 与 **② 账本域（什么算事实）**——并以记账（Ledger）作为第一个纵切，跑通「自然语言 → 结构化事实 → 可查询 / 可对账 / 可纠正 → 主动服务」的完整闭环。**不重造任何既有器官，只补主体与事实底座。**
> **任务命名**：`PLA-001 ~ PLA-018`（PLA = Personal Life Agent）。任务按 **系统能力** 拆分，不按文件拆分。
> **版本号说明**：V3.1 / V3.2 / V3.3 已被 V3.0.0 注册表 §7.3 预留给 Memory 双通道 / 循环内嵌反思 / Self Improvement（Agent Runtime 线延续）。本版本是**新的产品轴**而非该线延续，故启用大版本 V4.0.0。

---

## 0. 关键前提裁决（先读）

> 本版本全部任务建立在以下九条前提之上；任一 Task 的 Detail 与实现不得绕过。**裁决 9（禁止新增功能开关）优先于本注册表任何提及开关的旧表述。**

### 0.1 裁决 1：补地基，不建第二套 Agent

V4.0 的落点是**既有资产之上新增两个领域面**（`users` 身份面 + `ledger` 账本面），而非新的运行时或第二套编排：

| 既有资产 | V4.0 处置 |
|---|---|
| `agent_runtime`（Run / Profile / 会话 / 事件 / 契约） | **Preserve + 消费**：账务节律与预警以注册新 Profile 阶段 / 维护步 / trigger 的方式接入，**禁止另开阶段序列** |
| `services/tool/`（注册 + 五段执行 + manifest） | **Extend**：记账以 `builtin.ledger.*` 工具 + `ledger` capability 接入治理链路 |
| `services/action/`（ActionEngine / 台账 / 六态状态机） | **Preserve + 消费**：记账是一次受治理的行动，落 `action_records` 台账 |
| `services/planning/` + Goal Stack（七道闸） | **Preserve + 消费**：预算表达为 goal，**不建预算表** |
| `services/reflection/` + `development/` | **Preserve + 消费**：消费洞察走既有 Insight 三闸 |
| `life_loop` + `proactive_delivery` + `channel_identities` | **Preserve + 消费**：日结 / 周报 / 预警经既有主动投递与通道出口 |
| `memory2`（7 类 + 生命周期 + 候选幂等） | **Preserve**：仅**借鉴其候选幂等范式**，账目**不落记忆**（裁决 2） |
| `relationship` 三件套（账本 + 当前态 + 快照） | **模式借鉴**：账本域照搬该已验证模式，但**不得复用其表或引擎** |

**禁止**：新增 `agents2/` / `life_runtime/` / 第二套 Pipeline；嫁接 LangGraph / CrewAI 等第三方编排引擎；绕过 Profile Registry 自建调度。

### 0.2 裁决 2：账本是一等结构化领域，**不塞进 memory**（本版最重要的单条裁决）

账目与记忆在机制上**逐条冲突**，因此账本必须是独立领域：

| 账目要求 | 记忆的机制（证据） | 结论 |
|---|---|---|
| 精确、不可篡改 | LLM 抽取，`content` 为自然语言 | 冲突 |
| **不可遗忘** | `salience · exp(-λ·Δdays)` 衰减 + `decayed`/`forgotten` 生命周期 | **冲突（会忘掉花过的钱）** |
| 无限增长 | 单用户 active **软上限 200**，超出 `capacity_drop` 丢弃（`privacy-governance.md` §2） | 冲突 |
| 可累加可对账 | 无 amount / currency / category 字段，无法 SQL 聚合 | 冲突 |
| 必须保存金额 | 目标策略 L2（含财务数据）「**不保存**」（`privacy-governance.md` §1.1） | **冲突（由裁决 6 重裁）** |
| 订正留痕 | 冲突消解走 `superseded`（取代），无冲正语义 | 冲突 |

**因此**：账本域自建三表、自带 append-only 纪律与冲正语义；**账本条目无衰减、无失效、无容量上限、无过期**（与记忆相反，这是设计意图，不是遗漏）。记忆域唯一允许承接的是**抽象模式**（如「高频外卖」），且**金额明细永不进记忆**。

### 0.3 裁决 3：Schema 扩展与迁移纪律

| 需求 | 迁移 | 归属 | 说明 |
|---|---|---|---|
| 用户实体 + 归属列 | `0053_life_user_identity.py`（`users` 表 + `worlds.owner_type` / `worlds.owner_id`） | PLA-001 / PLA-002 | 一次迁移承载身份与归属两面 |
| 账本三表 | `0054_life_ledger_domain.py`（`ledger_accounts` / `ledger_categories` / `ledger_entries`） | PLA-004 | 账本域一次性建齐 |
| 其余 | **零新迁移** | — | 预算 / 待确认 / 洞察全部复用既有表（裁决 0.1） |

- 迁移链：`0053`（`down_revision = "0052"`）→ `0054`（`down_revision = "0053"`）；当前链尾 `0052`（`0052_runtime_session_trace_links.py`，已核）。
- **表数变化**：`SCHEMA_TABLE_COUNT` **45 → 46 → 49**（+4 表：`users` + 账本三表）。
- ⚠️ **先还一笔债**：迁移链头钉测散落在 `v23/v24/v25/v26` 共 15 个测试文件（`MIGRATION_HEAD` 常量、`test_migration_chain_head_is_still_00NN` 用例名、`SCHEMA_TABLE_COUNT`、`SCHEMA_COLUMNS_DIGEST`）。FEISHU-010 加 `0050` 时实测 **22 个用例由绿转红**（baseline §9 P1 技术债）。本版本要加 **2 个迁移 4 张表**，是该体系升级成本最高的一次——**PLA-001 必须先于其他任务把这套钉测升级机制收拾到可复用状态**（详见 PLA-001 Scope 第 5 项）。
- 命名避歧：`ledger_*` 指**财务账本**，与既有审计语义 `services/domain_ledger.py` / `evolution.ledger()`（只读投影，无表）**严格区分**，实现时不得混用命名。

### 0.4 裁决 4：设置项——只许参数，不许开关

> ⚠️ **本裁决已被 §0.9 收紧**（2026-09-22）。原计划的 9 个功能开关字段**全部作废**，见 §0.9 与被移除清单。

- 新增设置落**两个新领域模块**（现有 21 个领域模块，见 `core/settings/`）：`core/settings/life.py`（个人生活域参数）与 `core/settings/ledger.py`（账务域参数）。**不扩 `pipeline.py`**（`default_user` 保持原位不动）。
- `vXX_` 版本前缀体系已删除（2026-09-19 收官），**不得引入 `v40_` 前缀**。
- env 名 = 字段名大写（无 alias 层）；改名须同批同步部署侧 `.env`。
- **只允许参数类字段**（阈值 / 取值 / 文案 / 周期），**禁止 `*_enabled` 形态的功能位**（§0.9）。
- 首批字段（**仅 4 个参数 + 1 组时刻参数**，实现期以 Task Detail 冻结）：

| 字段 | 类型 | 语义 | 默认 | 归属 |
|---|---|---|---|---|
| `ledger_extraction_min_confidence` | 阈值 | 抽取置信度阈值（低于则转澄清，**不猜**） | `0.70` | PLA-007 |
| `ledger_confirm_threshold_amount` | 阈值 | 超过此金额（元）需人工确认 | `100.0` | PLA-010 |
| `ledger_default_currency` | 取值 | 默认币种 | `"CNY"` | PLA-004 |
| `ledger_category_fallback` | 取值 | 未归类兜底类目名 | `"其他"` | PLA-008 |
| `ledger_digest_send_time` | 时刻 | 日结 / 周报发送时刻（如 `"21:30"` / `"SUN 20:00"`） | `""` | PLA-011 |

- **不设「关闭态」**：能力上线即生效，因此**不存在**「Flag 关闭时行为等价」这类必测项；每个 Task 的等价性要求改为**零回归 + 可回滚**（见 §6.2）。

### 0.5 裁决 5：Preserve 清单（零改动，git diff 可证）

Agent Runtime（V3.0.0）/ Memory V2 + V4（7 类封顶、R1~R8、衰减数学、200 条上限）/ World（V8 + V2.3，旁路纪律）/ Relationship（V8.5 六维数学）/ Planning（V2.5 七道闸）/ Action Execution（V2.6 六态状态机与检定）/ Tool System（V2.4 注册与五段）/ Reflection（V2.6.1 三闸）/ Development / Decision Pipeline / Goal Stack / Character（V2.2）/ Evaluation 全部 **Preserve**。

V4.0 只做**新增领域、注册、调用、读取**。明确不写：

- 不写 `memories` / `memory_candidates`（记忆唯候选摄取；且账目永不入记忆）；
- 不写 `world_*`（唯 `deferred_world_op → outbox → world_engine`）；
- 不写 `relationship_state` / `personality_state`（唯各自引擎）；
- 不写计划（唯 `goal_repository` 计划面）；
- 不写 `loop_runs`（唯 Agent Runtime）；
- **不写 `amount` / `currency` 之外的任何既有业务表**。

### 0.6 裁决 6：隐私与数据治理重裁（记账的前置合法性条件）

`privacy-governance.md` §1.1 现行目标策略把「财务数据」列为 **L2 → 不保存**——这与记账**直接冲突**，必须在本版本重裁：

| 项 | 现策略 | V4.0 重裁（落 PLA-003） |
|---|---|---|
| 财务数据分级 | L2 → 丢弃，trace 记 `privacy_drop` | **降为 L1 受控保存**：本地存储 + 用户可控 + 用户可导出/删除 |
| 是否进 Prompt | 未规定 | **硬规则：账目明细永不进 Prompt 上下文**，仅聚合结果（合计 / 分布）可进 |
| 溯源 | 未规定 | 每条账目带 `source` + `source_ref`（可回溯到原始消息 / 行动 / 手动录入） |
| 用户权利 | 无通道 | 导出（JSON/CSV）+ 删除（含级联与审计旁路清理） |

> 记忆域的 R1~R8 与敏感分级 R9 **不动**（Preserve）；本次重裁只作用于**新增的账本域**与治理服务，不反向修改 V4 记忆策略。

### 0.7 裁决 7：单用户 → 用户实体的兼容性

现状：`default_user = "default-user"` 硬编码（`core/settings/pipeline.py:30`），`user_id` 是贯穿全链的**裸字符串**（无 FK、无 users 表）。

| 项 | 裁决 |
|---|---|
| 兼容策略 | **加实体、不加约束**：`users` 表建立并幂等播种 `default_user` 行；既有 `user_id` 列语义与取值**零变更**，**不加强制 FK**（避免历史数据撕裂） |
| 隔离强度 | 生活域（账本 / 治理）读写**一律经 `user_id` 校验（直接生效，不设开关）**；既有域（会话 / 记忆 / 世界）保持现状行为 |
| 鉴权 | **本版本不做注册 / 登录 / 鉴权**。用户身份仍来自既有请求参数与 `channel_identities` 映射；API 面只保证「不能读写他人数据」，不解决「你是谁」 |
| 多用户 | 本版本只把**结构**准备好，不承诺多租户运营能力（配额 / 计费 / 隔离运维列 Backlog） |

> **兼容红利**：因 `user_id` 已是贯穿全链的裸字符串（而非散落的硬编码常量），补用户实体的改动面**远小于**从零引入多租户。这也是本版本敢把地基放在第一位的原因。

### 0.8 裁决 8：运行时采用——基于 Agent Runtime，不基于旧管线

> 来源：`docs/version/v4.0.0/audits/v3.0.0-runtime-adoption-audit.md` + `architecture.md` §2。审计结论：V3.0.0 **地基与契约完整、前台已默认收编，但后台仍走 legacy、六段为影子实现**（验收状态 `CONDITIONAL — NOT RELEASED`）。

| # | 裁决 | 理由 |
|---|---|---|
| **R1** | 新能力一律以 **Profile 阶段序列 + 段本体**接入（`profiles.py` 唯一声明处 + `AgentLoop.run()`） | 前台已默认此路径（`runtime_foreground_loop_enabled = True`）；V3.0 铁律「无第二套 Agent Pipeline」 |
| **R2** | **禁止**以 `chat_pipeline._drive_foreground_linear` 为开发基线 | 它是 **C-2 kill switch**（不建台账 / 不发事件 / 不冻上下文），仅用于一键回退 |
| **R3** | **禁止**依赖 `agent_runtime/stages/*` 六段影子实现 | `SHADOW_STAGE_IMPLEMENTATION = True`，未接入生产 `run()`，且已从生产导出面隔离 |
| **R4** | **后台必须收编**，独立立为 **PLA-018**（P0） | 否则形成「前台 Runtime + 后台 legacy + 六段影子」三套路径 |
| **R5** | 六段认知循环**本版不激活**，保持影子 | V4.0 的价值在数据正确性而非循环形态；方案 A 需先建 C-2 补充 e2e 安全网（列入 Backlog） |

**新功能接入四条合法姿势**（四条之外即为违规）：① 注册新 Profile 阶段或接入既有段本体；② 跨域副作用走 Update / handoff（复用 `post_process` 步骤注册）；③ 持久化走对应域唯一写面仓储；④ 定时 / 节律 / 预警挂既有维护步或 `trigger_registry`，**不新增常驻循环**。

**同时确认的 V3.0 三处遗留（本版知情、不修、不扩大）**：`debug_view` 未接 debug 端点（L1）；前台未传 `runtime_input` / `session_context` 致 Context 冻结分支生产恒不进入（L2）；`app/api/**` 反向依赖 `app/repositories` 26 处（L3，本版新增 API 必须零 `repositories` 依赖）。

### 0.9 裁决 9：禁止新增功能开关阀门（2026-09-22 追加）

> 来源：用户指令 + `architecture.md` §0.2 铁律 5 / §9 / §10 不变量 11。**本裁决优先于本注册表任何提及开关的旧表述。**

**V4.0 不新增任何功能门控 / 灰度总闸开关。** 能力**上线即生效**，没有「关闭态」需要维护。

**理由（三条）**：

1. **本项目已经为「开关太多」付过代价**——`vXX_` 版本门控体系整体删除（2026-09-19 收官，台账 `docs/refactor/flag-removal-audit.md`）。再压一批功能开关等于重走一遍。
2. **每个开关都是一条额外的待维护路径**。V3.0 的 `runtime_*` 系列是现成反例：**13 个开关里只有 2 个为 `True`**，其余 11 个以「关闭时与上一版逐字节一致」的测试承诺形式长期挂着。
3. **开关会把「没想清楚」推迟到配置层**，而设计层面的问题应当在上线前解决。

**替代方案——回滚靠什么**：

| 手段 | 落点 |
|---|---|
| 代码回滚 | 发布以代码为单位（本项目以 git 版本发布） |
| 迁移可逆 | `0053` / `0054` 必须可空跑、可回滚；新增列可空、默认兼容（G13） |
| append-only 天然安全 | 账本只增不改，新功能只会**多写**条目，不破坏既有账目 |
| 端点 / 页面隔离 | 新 API 为**新增端点**、前端为**新增视图**，不改既有契约、不动 Debug Console |
| 能力顺序 | 用交付顺序（§4.2）而非开关控制上线节奏 |

**被移除的功能开关清单（原 §0.4 计划，现全部作废）**：

| 原字段 | 处置 |
|---|---|
| `life_user_isolation_enabled` | 删除 → 用户隔离**直接生效** |
| `life_ownership_enforced` | 删除 → 归属校验**直接生效** |
| `life_data_export_enabled` / `life_data_delete_enabled` | 删除 → 导出 / 删除端点随 PLA-003 **直接提供** |
| `ledger_enabled` | 删除 → 账本域随 `0054` 迁移**直接可用** |
| `ledger_extraction_enabled` | 删除 → 抽取链随 PLA-007 **交付即生效** |
| `ledger_digest_daily_enabled` / `ledger_digest_weekly_enabled` | 删除 → 日结 / 周报随 PLA-011 **交付即生效** |
| `ledger_overspend_alert_enabled` | 删除 → 预警随 PLA-013 **交付即生效** |

**既有开关的处置（只许两种，不得新增）**：

1. **置为唯一有效值**——如 PLA-018 把后台统一到 Agent Runtime（`runtime_autonomous_cycle_enabled` 不再是「切换」，而是「统一」）。
2. **纳入 `flag-removal-audit.md` 台账**，按既有批次流程清理——V4.0 建议登记 `runtime_foreground_loop_enabled` / `runtime_autonomous_cycle_enabled` 两个已转常开的字段（**清理动作本身不入 V4.0 交付面**，只登记）。

**连带影响（本注册表内已同步）**：§4.2 由「灰度与开关开启顺序」改为「能力交付顺序」；§6.2 DoD 第 2 条由「Flag 关闭时逐字节一致」改为「零回归 + 可回滚」；Gate G12 口径同步；各 Task Scope / Expected Output 中的开关引用已移除。

---

## 1. V4.0.0 Task Overview

### 1.1 总览表

| ID | Task Name | Type | 能力域 | Priority | Dependencies | Phase |
|---|---|---|---|---|---|---|
| PLA-001 | User Identity & Ownership Contract | ARCH / DB | 主体地基 | P0 | 无 | Phase 1 主体与治理地基 |
| PLA-002 | Life Domain Ownership | ARCH | 主体地基 | P0 | PLA-001 | Phase 1 主体与治理地基 |
| PLA-003 | Privacy & Data Governance Re-adjudication | ARCH / BE | 治理 | P0 | PLA-001 | Phase 1 主体与治理地基 |
| PLA-004 | Ledger Domain Model & Migration | DB | 账本内核 | P0 | PLA-001 | Phase 2 账本域内核 |
| PLA-005 | Ledger Repository & Single Write Surface | BE | 账本内核 | P0 | PLA-004 | Phase 2 账本域内核 |
| PLA-006 | Ledger Query & Aggregation | BE | 账本内核 | P0 | PLA-004, PLA-005 | Phase 2 账本域内核 |
| PLA-007 | Ledger Extraction Chain | BE | 摄取 | P0 | PLA-004 | Phase 3 摄取与行动接入 |
| PLA-008 | Category Normalization | BE | 摄取 | P1 | PLA-004, PLA-007 | Phase 3 摄取与行动接入 |
| PLA-009 | Ledger Capability & Tool Integration | BE | 行动接入 | P0 | PLA-005, PLA-006, PLA-007 | Phase 3 摄取与行动接入 |
| PLA-010 | Confirmation, Correction & Reversal | BE | 行动接入 | P0 | PLA-009 | Phase 3 摄取与行动接入 |
| PLA-011 | Ledger Rhythm Delivery | BE | 主动服务 | P1 | PLA-006, PLA-009 | Phase 4 主动性与洞察 |
| PLA-012 | Budget Goal Integration | BE | 主动服务 | P1 | PLA-006 | Phase 4 主动性与洞察 |
| PLA-013 | Overspend Alert Triggering | BE | 主动服务 | P1 | PLA-011, PLA-012 | Phase 4 主动性与洞察 |
| PLA-014 | Spending Insight | BE | 洞察 | P2 | PLA-006, PLA-007 | Phase 4 主动性与洞察 |
| PLA-015 | Ledger Query API | API | 用户面 | P1 | PLA-006, PLA-010 | Phase 5 用户面 |
| PLA-016 | User-Facing Life View | FE | 用户面 | P2 | PLA-015 | Phase 5 用户面 |
| PLA-017 | Acceptance & Regression | TEST | 全能力域（验收） | P0 | PLA-001 ~ PLA-016 | Phase 6 验收 |
| PLA-018 | Agent Runtime Adoption & Background Cutover | ARCH / BE | 运行时采用（追加） | P0 | PLA-001（建议）, PLA-003 | Phase 1 主体与治理地基（**追加任务，执行不晚于 Phase 4**） |

**Priority 语义**：P0 = 版本发布阻断项（缺一不可上线）；P1 = 版本价值主体；P2 = 可延后至版本内末尾或下一版本。
**Priority ≠ 顺序**：PLA-017 为 P0 但必须最后执行（验收性质决定）；PLA-018 ID 靠后但**执行位置在 Phase 1**（审计后追加，按约定不重排既有编号）。
**Dependencies 记法**：只列**直接**前置；传递依赖不重复罗列。PLA-013 依赖 PLA-011 是**跨能力域直接前置**（预警须先有投递出口），非笔误。
**Priority 分布**：P0 ×11 / P1 ×5 / P2 ×2。

### 1.2 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| **Phase 1 主体与治理地基** | PLA-001 ~ PLA-003 + **PLA-018** | 用户成为一等实体；生活域归属明确；财务数据治理策略重裁并落地导出/删除；**后台自治收编到 Agent Runtime（消除三套路径）** |
| **Phase 2 账本域内核** | PLA-004 ~ PLA-006 | 账本三表落地；单一写面 + 幂等 + 冲正；「这个月花了多少」有权威且精确的答案来源 |
| **Phase 3 摄取与行动接入** | PLA-007 ~ PLA-010 | 自然语言稳定抽取为结构化候选；记账经 Tool 治理链路成为可审计行动；可确认、可订正、可撤销 |
| **Phase 4 主动性与洞察** | PLA-011 ~ PLA-014 | 日结 / 周报 / 预算 / 超支预警 / 消费洞察——复用既有主动投递与规划器官 |
| **Phase 5 用户面** | PLA-015, PLA-016 | 查询与订正的 API 面；前端从纯调试台升级为双模（保留 Debug） |
| **Phase 6 验收** | PLA-017 | 全部 Gate 全绿；**账目精确性人工核对零幻觉数字**；回归清单与验收报告就位 |

### 1.3 能力域覆盖矩阵（覆盖 review 的六维缺口）

| review 缺口维度 | 现状评分 | 承载任务 |
|---|---|---|
| ① 主体（Owner） | 2/10 | PLA-001（用户实体）/ PLA-002（归属）/ PLA-003（治理权利面） |
| ② 账本（Ledger） | 0/10 | PLA-004（模型）/ PLA-005（写面）/ PLA-006（聚合） |
| ③ 摄取（Ingest） | 3/10 | PLA-007（抽取链）/ PLA-008（类目归一）/ PLA-009（能力接入）/ PLA-010（确认订正） |
| ④ 主动性（Agency） | 8/10 | PLA-011（节律）/ PLA-012（预算）/ PLA-013（预警）/ PLA-014（洞察） |
| ⑤ 界面（Surface） | 1/10 | PLA-015（API）/ PLA-016（用户视图） |
| ⑥ 信任治理 | 2/10 | PLA-003（分级 / 导出 / 删除 / 溯源）+ PLA-017（精确性 Gate） |

---

## 2. Task Dependency Graph

### 2.1 依赖关系图

```text
Phase 1 主体与治理地基
─────────────────────────────────────────────────────────────────
PLA-001 User Identity & Ownership Contract（起点；含迁移钉测机制收拾）
    │
    ├──────────────────────┬──────────────────────┐
    ▼                      ▼                      ▼
PLA-002                PLA-003                PLA-004 Ledger Domain
Life Domain            Privacy &              Model & Migration（0054）
Ownership              Data Governance            │
（0053 同批 ownership 列）  （治理服务 + 权利面）        │
    │                      │                      │
    │                      ├──▶ PLA-018 Agent Runtime Adoption
    │                      │    & Background Cutover（追加；R4 后台收编）
    │                      │    └──▶ 为 PLA-011 / PLA-013 提供 Runtime 挂载面
    │                      │                      │
Phase 2 账本域内核                                  │
─────────────────────────────────────────────────────────────────
                       ┌──────────────────────────┘
                       ▼
                  PLA-005 Ledger Repository & Single Write Surface
                       │
                       ▼
                  PLA-006 Ledger Query & Aggregation

Phase 3 摄取与行动接入
─────────────────────────────────────────────────────────────────
PLA-007 Ledger Extraction Chain ──▶ PLA-008 Category Normalization
   │（另依赖 PLA-004）                  │
   └──────────────┬────────────────────┘
                  ▼
             PLA-009 Ledger Capability & Tool Integration（依赖 005 + 006 + 007）
                  │
                  ▼
             PLA-010 Confirmation, Correction & Reversal

Phase 4 主动性与洞察
─────────────────────────────────────────────────────────────────
PLA-006 ──▶ PLA-012 Budget Goal Integration ──┐
   │                                          │
   ├──▶ PLA-011 Ledger Rhythm Delivery ────────┼──▶ PLA-013 Overspend Alert
   │        （另依赖 PLA-009）                  │
   └──▶ PLA-014 Spending Insight（另依赖 PLA-007）

Phase 5 用户面
─────────────────────────────────────────────────────────────────
PLA-006 + PLA-010 ──▶ PLA-015 Ledger Query API ──▶ PLA-016 User-Facing Life View

Phase 6 验收
─────────────────────────────────────────────────────────────────
PLA-017 Acceptance & Regression
    ▲ 全量扇入：PLA-001 ~ PLA-016
```

### 2.2 关键路径

```text
PLA-001 → PLA-004 → PLA-005 → PLA-006 → PLA-007 → PLA-009 → PLA-010
        → PLA-015 → PLA-016 → PLA-017
```

（**10 个任务**，为本版本最长依赖链。）

并行支链长度对照：

| 支链 | 长度 |
|---|---|
| PLA-001 → PLA-002 | 2（在 PLA-017 前并入） |
| PLA-001 → PLA-003 | 2（治理面独立，可与 Phase 2 并行） |
| PLA-004 → PLA-007 → PLA-008 | 3（在 PLA-009 前并入） |
| PLA-006 → PLA-012 → PLA-013 | 3（在 PLA-017 前并入） |
| PLA-006 → PLA-011 → PLA-013 | 3（在 PLA-017 前并入） |
| PLA-006 → PLA-014 | 2（最闲支链，P2 可延后） |

### 2.3 并行建议

| 组 | 可并行任务 | 前提 |
|---|---|---|
| A | PLA-002 ‖ PLA-003 ‖ PLA-004 ‖ **PLA-018** | PLA-001 完成（归属 / 治理 / 账本模型 / 运行时收编四面互不依赖；PLA-018 建议先于 PLA-003 或与其同批） |
| B | PLA-005 → PLA-006 之间不并行（同链） | PLA-004 完成 |
| C | PLA-007 ‖ PLA-003 | PLA-004 完成（摄取链与治理面无交集） |
| D | PLA-008 可与 PLA-005 / PLA-006 并行 | PLA-007 完成（类目归一不依赖写面） |
| E | PLA-011 ‖ PLA-012 ‖ PLA-014 | PLA-006 完成（三条主动服务支链互不阻塞） |
| F | PLA-016 可与 PLA-017 的 Gate 准备并行 | PLA-015 完成 |

**关键风险点排序**（实现顺序上不可颠倒的五处）：

1. **PLA-001 必须先于一切**——它是 `user_id` 语义与迁移钉测机制的底座；账本表一旦带着"含糊的 owner 语义"落地，后续 9 个任务全部承压。
2. **PLA-003（治理重裁）必须先于 PLA-004（账本落表）在策略上完成**——因为现行隐私策略把财务数据列为「不保存」，**不先重裁就等于明知违规建表**。两者可在同一批次但治理裁决须先落。
3. **PLA-018（后台收编）不晚于 Phase 4**——否则节律与预警会挂在 legacy 链上，形成「同一能力两条链路」的第三套路径（架构不变量 1 违规）。
4. **PLA-005 单一写面必须先于 PLA-007 抽取链上线**——抽取先跑而无写面与幂等，会直接产出重复账目，用户信任一次就崩。
5. **PLA-010 确认与冲正必须先于 PLA-011 主动推送**——先推送一个"不能改"的账本，等于把错误固化给用户看。

---

## 3. Detailed Task List

> 字段约定：**Task ID / Task Name / Type / Priority / Goal / Scope（含 Out of Scope）/ Dependencies / Expected Output**。
> `Expected Output` = 交付物 + 可判定断言（Task Detail 阶段展开为正式 Acceptance Criteria 与测试用例清单）。
> 「交付面」给出落点以便实现，但**不得据此把 Task 再拆成按文件的任务**。

## PLA-001 User Identity & Ownership Contract

Type: ARCH / DB
Priority: P0

Goal: 把 `user_id` 从贯穿全链的**裸字符串**升格为一等实体，冻结「用户 → 数据分区键」契约与生活域隔离规则，使一切生活域数据有明确 owner（review 缺口 ①，Phase A）。

Scope:

- **交付面**：迁移 `0053_life_user_identity.py`（`users` 表：`id` / `display_name` / `status` / `is_default` / `created_at` / `updated_at`；唯一约束保证单一默认用户）+ `core/db.py::UserRow` + `repositories/user_repository.py` + `services/identity/user_service.py`（`ensure_default_user` 幂等播种 / `resolve_user` / `UserContext` 值对象）。
- **契约纪律**：`UserContext` 为 `frozen` 值对象，零 IO、零 LLM；`user_id` 缺失时不抛错而是回落 `default_user`（**与现状行为一致**，兼容红线见裁决 0.7）；**不加强制 FK**。
- **迁移钉测机制收拾（本任务必须先做，见裁决 0.3）**：把散落在 `v23/v24/v25/v26` 共 15 个测试文件的链头钉测**收敛为单一可复用断言入口**（链头常量 + 表数 + 列摘要集中于一处，其余文件改为引用），使本版本后续 `0054` 与将来迁移只升级一处。**这是本版本唯一允许触碰既有测试文件的任务**。
- **设置**：`core/settings/life.py`（新增领域模块，**仅参数类字段**，本任务当前无参数需求即为空模块骨架）；登记进测试支持模块。**不新增功能开关**（§0.9）。
- **Out of Scope**：不做注册 / 登录 / 鉴权（裁决 0.7）；不做多租户配额与运营能力；不建 `sessions` 表；不改 `channel_identity_service` 的身份派生结果；不改既有表 `user_id` 列语义与取值。

Dependencies: 无

Expected Output:

- `0053` 迁移（`down_revision = "0052"`，可空跑、可回滚）+ ORM + 仓储 + 服务；`MIGRATION_HEAD == "0053"`、`SCHEMA_TABLE_COUNT` **45 → 46**。
- **钉测收敛断言**：链头常量在全仓**只有一处**定义（静态断言）；`0053` 升级时改动文件数 ≤ 3（对照 FEISHU-010 的 22 用例转红）。
- **幂等播种断言**：`ensure_default_user()` 重复调用只产生 1 行；并发生成不产生重复（唯一约束兜底）。
- **兼容断言**：既有全部测试零修改通过（除钉测文件）；无 `user_id` 的调用路径行为逐字节不变。
- 测试：`tests/v40/test_life_user_identity.py` + 迁移用例。

---

## PLA-002 Life Domain Ownership

Type: ARCH
Priority: P0

Goal: 明确「世界与生活数据属于角色还是用户」，为用户的生活建立归属容器，解除主体错位（review 缺口 ①，Phase A 第 3 项）。

Scope:

- **交付面**：`worlds` 增 `owner_type`（`character` / `user`）+ `owner_id`（迁移并入 `0053`，均可空 + 默认兼容）；`services/life/ownership.py`（纯函数：`resolve_owner` / `assert_access` / `scope_filter`）；`application/world_engine` 归属解析接入点（只读）。
- **语义**：既有 `home` 世界保持 `owner_type = "character"`（默认值即兼容，**零数据迁移**）；用户生活容器以 `owner_type = "user"` 承载，**与角色世界严格分离，不混用**。
- **纪律**：归属校验为**纯函数**（无 IO、无 LLM，可直接单测）；异常按世界旁路纪律处理——校验失败只降级 / 拒绝，**不阻断聊天与主动链路**。
- **Out of Scope**：不做世界推演升级；不改 V8 / V2.3 的世界数学与状态机；不迁移既有世界数据；不做多世界并行运营；不实现用户生活容器的内容建模（后续版本按生活域逐个补）。

Dependencies: PLA-001

Expected Output:

- 归属列 + 解析器 + 世界引擎接入点（**归属校验直接生效，不设开关**；见 §0.9）。
- **零迁移断言**：既有世界数据无需数据迁移；`owner_type` 默认值路径行为逐字节不变。
- **分离断言**：角色世界与用户容器互不可见（跨 owner 读取被拒或只读降级，行为在 Detail 中冻结并测）。
- **纯函数断言**：`ownership.py` 零 IO / 零 LLM；越权用例全覆盖。
- 测试：`tests/v40/test_life_ownership.py`。

---

## PLA-003 Privacy & Data Governance Re-adjudication

Type: ARCH / BE
Priority: P0

Goal: 重裁财务类数据的隐私策略并落地用户数据权利面（导出 / 删除 / 溯源），使「记录金额」在治理上合法可行（review 缺口 ⑤ 与缺口 2 的冲突项）。

Scope:

- **交付面**：改写 `docs/version/v1.0.0/v4/privacy-governance.md` 中 L2 财务数据结论（改为 L1 受控保存，见裁决 0.6）并**同步登记至架构基线**；`services/governance/`（`export_user_data` / `delete_user_data` / `record_provenance`）；导出 / 删除端点**直接提供**（不设开关，§0.9）。
- **治理规则**：账目明细**永不进 Prompt 上下文**（仅聚合结果可进）；每条账目带 `source` + `source_ref` 可回溯；删除为用户自助操作，删除后零残留（含候选与审计旁路）。
- **纪律**：导出为**只读**操作；删除必须走既有 `repositories` 单一写面（不得直接 SQL 批量清表）；删除与导出均落审计。
- **Out of Scope**：不做密钥管理服务（沿用既有 env 机制）；不做合规认证 / 等保；**不改 V4 记忆的 R1~R8 与敏感分级 R9**（Preserve）；不做数据脱敏展示层（归 PLA-016）。

Dependencies: PLA-001

Expected Output:

- 分级文档更新（含基线回写登记）+ 治理服务 + 导出 / 删除通路（**端点直接提供，不设开关**）。
- **零泄漏断言**：金额数字不出现在任何 prompt 快照 / trace 明文中（静态扫描 + golden 快照断言）。
- **删除彻底性断言**：删除后该用户账本条目 / 账户 / 类目零残留，且无孤儿引用。
- **导出完备性断言**：导出内容与库内一致、可对账（条数与合计逐分相等）。
- **Preserve 断言**：记忆域策略与代码 diff 为空。
- 测试：`tests/v40/test_life_governance.py`。

---

## PLA-018 Agent Runtime Adoption & Background Cutover（追加任务）

> **ID 说明**：本任务为审计后**追加登记**，按 §7.2 约定不重排既有编号（新增任务追加为 `PLA-018+`），但**执行位置在 Phase 1**，不得晚于 Phase 4。来源：`audits/v3.0.0-runtime-adoption-audit.md` + `architecture.md` §2（裁决 R4）。

Type: ARCH / BE
Priority: P0

Goal: 把后台自治从 legacy 路径收编到 **Agent Runtime** 轨道，消除「前台 Runtime + 后台 legacy + 六段影子」三套路径并存，使 V4.0 的节律 / 预警有唯一合法的 Runtime 挂载面（架构不变量 1）。

Scope:

- **交付面**：把后台自治**统一到 Agent Runtime 轨道**——`runtime_autonomous_cycle_enabled` **置为唯一有效值**（不再作为「切换」，见 §0.9 / architecture 附 D C-2），`controller.py::run_autonomous_cycle` 的 legacy 分支（`_legacy_run_autonomous_cycle`）**降级为非默认回退位**；`application/life_loop.py` 的 tick 与维护步挂接确认（维护步清单零改动）；`autonomous_tick` Profile 段序列保持 `profiles.py` 唯一声明。
- **等价性证明**：统一前后，同一次 tick 的**段序列、段本体、预算三道闸、cooldown / idle / storm 判定**逐项等价（对照测试）；**空转 0 LLM / 0 Run** 语义不变。
- **开关台账登记**：把 `runtime_foreground_loop_enabled` 与 `runtime_autonomous_cycle_enabled` 两个**已转常开**的既有字段登记进 `docs/refactor/flag-removal-audit.md`，按既有批次流程待清理（**清理动作不在本任务交付面内**，只登记；见 §0.9）。
- **文档登记**：`docs/version/v3.0.0/acceptance-report.md` 中「边界不变量 8 PASS」的**口径澄清**（该 PASS 为开关开启的测试态；本任务把生产态补齐）——以勘误或 V4.0 验收报告交叉引用方式登记，不改写历史结论。
- **顺带勘误**：`acceptance-report.md` §影子矩阵表格遗漏 `runtime_foreground_loop_enabled` / `runtime_six_stage_loop_enabled` 两个字段（代码与 `tests/v30/runtime_support.py` 均为 13 个，登记完整；仅报告表格停留在 11 行）——在 V4.0 验收文档中登记该差异，不修改 V3.0 冻结报告。
- **Out of Scope**：**不激活六段认知循环**（裁决 R5，`runtime_six_stage_loop_enabled` 保持既有 `False`）；**不新增任何功能开关**（§0.9）；不删除 legacy 分支代码（只降级为非默认，删除留待 flag-removal 批次）；不修 `debug_view` 未接端点（L1）；不修前台 `runtime_input` / `session_context` 未传参（L2）；不新增常驻循环；不改 `profiles.py` 三 Profile 的段序列语义；不引入第三方编排框架。

Dependencies: PLA-001（建议）；PLA-003（同批，二者无耦合）

Expected Output:

- 后台统一经 Agent Runtime 轨道运行 + legacy 降级为非默认回退位 + 开关台账与文档登记。
- **等价断言**：统一前后同 tick 的段序列 / 段本体 / 预算闸 / 节流判定逐项一致（对照测试）。
- **空转断言**：无 due 工作时 0 LLM、0 Run（沿用既有断言）。
- **单一路径断言**：全仓零第二条自治编排路径（静态断言）；legacy 分支不可由配置触达，仅可被代码级回退调用。
- **零回归断言**：后台相关既有测试全绿；孤儿 Run 清扫（`sweep_orphan_runs`）行为不变。
- **零新增开关断言**：`core/settings/` 无新增 `*_enabled` 字段（静态断言）。
- **不激活断言**：`runtime_six_stage_loop_enabled` 仍为 `False`；`SHADOW_STAGE_IMPLEMENTATION` 仍为 `True`（静态断言）。
- 测试：`tests/v40/test_runtime_background_cutover.py`。

---

## PLA-004 Ledger Domain Model & Migration

Type: DB
Priority: P0

Goal: 建立账本三表，以 **append-only 账本**承载精确、可累加、不可遗忘的用户财务事实（review 缺口 ②，Phase B 核心）。

Scope:

- **交付面**：迁移 `0054_life_ledger_domain.py` —— `ledger_accounts`（`id` / `user_id` / `name` / `type` / `currency` / `status`）、`ledger_categories`（`id` / `user_id` / `parent_id` / `name` / `kind` / `aliases`(JSON)）、`ledger_entries`（`id` / `user_id` / `account_id` / `category_id` / `amount_minor` / `currency` / `direction` / `occurred_at` / `merchant` / `note` / `source` / `source_ref` / `idempotency_key` / `reversal_of` / `created_at`）+ `core/db.py` ORM + `models/ledger.py` 领域模型。
- **关键裁决**：
  - 金额以**整数最小单位（分）** 存 `amount_minor`，**禁用 float / 货币用 Decimal 出口**（精度是账本的生命线）；
  - `direction` ∈ `expense` / `income` / `transfer`；
  - **纠错用冲正**：`reversal_of` 指向被冲正条目，append-only，**永不 UPDATE 金额**；
  - `idempotency_key` 唯一约束保证幂等；
  - **无衰减、无失效、无容量上限、无过期**（与记忆相反，见裁决 0.2）。
- **单一写面**：`repositories/ledger_repository.py`（写路径唯一入口）。
- **Out of Scope**：不建预算表（预算走 Goal Stack，PLA-012）；不建汇率表（首版单币种）；不建账本快照表（PLA-006 实时聚合）；不做账目附件 / 票据图像。

Dependencies: PLA-001

Expected Output:

- `0054` 迁移（`down_revision = "0053"`，可空跑回滚）+ ORM + 领域模型；`MIGRATION_HEAD == "0054"`、`SCHEMA_TABLE_COUNT` **46 → 49**。
- **精度断言**：全仓账本路径零 `float`（静态扫描）；`amount_minor` 为整数类型；分-元换算往返无损。
- **不可遗忘断言**：账本表**无任何** TTL / 过期 / 状态衰减列（静态断言）。
- **幂等与冲正断言**：`idempotency_key` 唯一约束生效；冲正后原行逐字节未变、净额为 0。
- **命名避歧断言**：新表不与审计语义 `domain_ledger` / `evolution.ledger()` 命名混用（静态断言 + 文档登记）。
- 测试：`tests/v40/test_ledger_model.py` + 迁移用例。

---

## PLA-005 Ledger Repository & Single Write Surface

Type: BE
Priority: P0

Goal: 交付账本唯一写面，保证每一次记账**幂等、可追溯、可冲正**（review Phase B 写面纪律）。

Scope:

- **交付面**：`repositories/ledger_repository.py`（`create_entry` 幂等 / `reverse_entry` / `list_entries` / `get_account` / `ensure_default_account` / `ensure_seed_categories`）+ `services/ledger/service.py`（业务编排：校验 → 幂等 → 落账 → 审计）；`ensure_*` 幂等播种（对齐既有 `world_entities` 播种范式）。
- **规则**：一切写经此面，**业务层零直接 ORM**；写失败不产生半成品；`reverse_entry` 生成反向条目并标记 `reversal_of`，**原条目不删不改**；每笔写落审计可溯源。
- **Out of Scope**：不做聚合查询（PLA-006）；不做抽取（PLA-007）；不做确认交互（PLA-010）；不建定时 / 重试机制。

Dependencies: PLA-004

Expected Output:

- 仓储 + 服务 + 默认账户与种子类目幂等播种。
- **单一写面断言**：全仓零旁路写账本表（静态断言 + 打桩）。
- **幂等断言**：同 `idempotency_key` 重复写**仅 1 行**，第二次返回既有条目而非报错。
- **冲正断言**：冲正后净额归零、原行未变、两条记录均可在 `list_entries` 中查得。
- **失败原子性断言**：任一步失败不留半成品条目。
- 测试：`tests/v40/test_ledger_repository.py`。

---

## PLA-006 Ledger Query & Aggregation

Type: BE
Priority: P0

Goal: 为「这个月花了多少」提供**权威且精确**的答案来源——只从结构化字段聚合，不经 LLM 复述（review 缺口 ②的核心产出）。

Scope:

- **交付面**：`services/ledger/query.py`（`summary(period, group_by)` / `trend(periods)` / `top_categories(n)` / `list_entries(filters)`）+ `LedgerSummary` 值对象（合计 / 分方向 / 类目分布 / 账户分布 / 期间对比 / 条目数）；聚合下压 `repositories/ledger_repository.py`。
- **规则**：全部 SQL 聚合，**零 LLM**；只读；内部整数分，出口格式化为字符串 / `Decimal`；跨月 / 跨时区边界显式按本地时区与自然月定义；冲正条目参与净额计算（双向计入）。
- **Out of Scope**：不做可视化（PLA-016）；不做预测 / 预算推算（PLA-012）；不做 LLM 摘要（PLA-011 用模板渲染）；不做任意 SQL / 查询 DSL。

Dependencies: PLA-004, PLA-005

Expected Output:

- 聚合服务 + `LedgerSummary` 值对象 + 期间与分组的确定性定义。
- **精确性断言**：构造数据的手工计算合计与聚合结果**逐分一致**（含冲正、跨月、同日多笔）。
- **零 LLM 断言**：聚合路径不触碰 LLM Gateway / chains。
- **只读断言**：聚合对账本表零写入（静态 + 打桩）。
- **边界断言**：月末 / 年初 / 时区边界用例全覆盖。
- 测试：`tests/v40/test_ledger_query.py`。

---

## PLA-007 Ledger Extraction Chain

Type: BE
Priority: P0

Goal: 把「中午吃了20块快餐」这类自然语言稳定抽取为**结构化账目候选**（含置信度与缺失字段标记），补上缺失已久的「事实管道」（review 缺口 ③）。

Scope:

- **交付面**：`chains/ledger_extraction_chain.py`（**必须**走 `chains/structured.py::build_structured_chain`，主链 + 一层降级）+ `models/ledger.py::LedgerExtraction`（金额 / 方向 / 类目候选 / 商户 / 发生时间 / 账户 / 置信度 / 缺失字段集）+ prompt 模板落 `prompts/`（PromptBuilder，禁手工拼接）+ 挂接 post_process 步骤（**读取进链、写入出链**纪律）。
- **规则**：金额缺失或置信度 < `ledger_extraction_min_confidence` → 标记「待澄清」，**不直接入账**；相对时间（"中午" / "昨晚"）按世界时间与本地时区解析为绝对时间；抽取结果**只作候选**，入账必经 PLA-009 / PLA-010。
- **纪律**：LLM 实例必须来自 `core/llm_factory.get_llm()`；结构化输出禁自由解析；后处理失败不影响已产出回答。
- **Out of Scope**：不做类目归一算法（PLA-008）；不做入账写入；不接语音 / 票据 OCR / 图片识别；不改既有 `turn_analysis` / `extractor_chain`。

Dependencies: PLA-004

Expected Output:

- 抽取链 + `LedgerExtraction` schema + 降级路径 + prompt 模板。
- **契约断言**：FakeLLM 按 schema 结构化输出；金额非数字 / 负数 / 超界 → 拒绝并转澄清。
- **分流断言**：置信度阈值上下分流行为确定（≥ 阈值进确认流程；< 阈值转澄清）。
- **prompt 纪律断言**：模板化生成（golden 快照全绿）；零手工拼接。
- **零写库断言**：抽取链零 DB 写（静态 + 打桩）。
- **零幻觉前置断言**：抽取产出的金额必须来自原文片段（Detail 中冻结校验策略）。
- 测试：`tests/v40/test_ledger_extraction.py`。

---

## PLA-008 Category Normalization

Type: BE
Priority: P1

Goal: 把中文消费表述**稳定归一**到用户类目树，避免 LLM 随手分类造成的类目漂移（review 中已点名的真实难点）。

Scope:

- **交付面**：`character/<persona>/ledger_categories.py`（种子类目树 + 别名词表，按人设分子目录存放）+ `services/ledger/category.py`（归一：精确匹配 → 别名 → 规则 → 兜底 `ledger_category_fallback`）+ 用户自定义类目 / 别名落 `ledger_categories`。
- **规则**：**确定性优先**（词表 / 规则命中即止）；LLM 仅作最后兜底，且结果必须落到既有类目或标注「未归类」，**不得凭空新建类目**。
- **Out of Scope**：不做自动类目发现 / 聚类 / 重分类批处理；不做多语言；不做类目预算（归 PLA-012）。

Dependencies: PLA-004, PLA-007

Expected Output:

- 类目树 + 别名词表 + 归一服务 + 用户自定义通路。
- **命中率断言**：样本集（含「快餐 / 盖浇饭 / 外卖 / 烧烤 / 打车 / 话费」等）归一命中率达 Detail 冻结阈值。
- **不漂移断言**：归一过程零新建类目；兜底类目命中可统计。
- **确定性断言**：同输入重复归一结果一致（无随机、无 LLM 参与主路径）。
- 测试：`tests/v40/test_ledger_category.py`。

---

## PLA-009 Ledger Capability & Tool Integration

Type: BE
Priority: P0

Goal: 以既有 Capability / Tool 体系承载记账动作，使「记账」是一次**受治理、可审计的行动**，而非旁路写入（对齐 ADR-10「能力是手脚不是逻辑」）。

Scope:

- **交付面**：`services/action/capabilities/ledger.py`（`ledger.record` / `ledger.query` / `ledger.revise`）+ `services/tool/builtin.py`（或 manifest）注册 `builtin.ledger.*` + `character/asuna/action.py::ACTION_CAPABILITY_MAP` 增记账类动作映射 + `services/action/detector.py` 增记账意图词表（**保持既有纯词表 + 正则、零 LLM 风格**）。
- **规则**：写路径经 Tool **五段短路**（权限 → 确认 → 校验 → 归一 → 健康度）；`ledger.record` 的 payload **必须结构化**（金额 / 币种 / 方向 / 类目引用），**拒绝自由文本入参**；能力只执行不做决策，调度 / 重试 / 回复生成归引擎。
- **Out of Scope**：不改 Tool 五段与 `ToolRegistry` 注册机制（启动期代码注册，非热插拔）；不做用户自定义记账工具（后续版本）；不改 Action 六态状态机与检定；不绕过 `ActionManager` / `ActionEngine`。

Dependencies: PLA-005, PLA-006, PLA-007

Expected Output:

- 能力 + 工具注册 + 意图词表 + 动作映射。
- **可审计断言**：每次记账在 `action_records` 有对应台账行，状态机流转合法。
- **治理断言**：非法 payload 被拒；权限 / 确认 / 校验 / 健康度四段短路生效；熔断时不产生写。
- **零决策断言**：能力内零决策 / 零重试 / 零回复生成（静态断言）。
- **风格一致断言**：意图检测仍为零 LLM 词表（静态断言 + 用例）。
- 测试：`tests/v40/test_ledger_capability.py`。

---

## PLA-010 Confirmation, Correction & Reversal

Type: BE
Priority: P0

Goal: 让记账**可确认、可订正、可撤销**——这是账本区别于记忆的核心产品体验，也是用户信任的来源。

Scope:

- **交付面**：`services/ledger/confirmation.py`（澄清策略：缺金额 / 类目歧义 / 超 `ledger_confirm_threshold_amount` 需确认）+ 对话层挂接（post_process 步骤 + 待确认登记，**复用 `scene_state.pending_action` 与 `action_schedules`，零新表**）+ `services/ledger/correction.py`（修改 = 冲正 + 新增；删除 = 冲正）。
- **规则**：待确认项带超时与幂等（同 `source_ref` 不重复回问）；用户回话解析**复用 PLA-007 抽取链**（不另建解析）；确认 / 订正 / 冲正全落审计；超时未确认**不产生账目**。
- **Out of Scope**：不做图形化订正 UI（PLA-016）；不做批量导入与批量订正；不改 scene / pending 机制本体。

Dependencies: PLA-009

Expected Output:

- 确认 / 订正 / 冲正服务 + 待确认登记通路（零新表）+ `ledger_confirm_threshold_amount` 生效。
- **单次澄清断言**：模糊金额只产生**一次**澄清回问，重复同一句不重复回问。
- **订正正确性断言**：订正后净额正确、原条目逐字节未变、新旧两条均可查。
- **超时断言**：超时未确认不产生任何账目行。
- **零新表断言**：schema 无新增表（复用既有承载）。
- 测试：`tests/v40/test_ledger_confirmation.py`。

---

## PLA-011 Ledger Rhythm Delivery

Type: BE
Priority: P1

Goal: 日结 / 周报经**既有主动投递链路**送达用户——本版本投产比最高的一相（review 明确「器官全在」，Phase D）。

Scope:

- **交付面**：`services/ledger/digest.py`（模板化日结 / 周报：今日合计 / 类目分布 / 与昨日对比 / 条目明细摘要）+ 挂 `life_loop` 维护步或 `trigger_registry` 触发 + 经既有 Outbound / `proactive_delivery` 投递；参数 `ledger_digest_send_time`（发送时刻，**参数而非开关**，§0.4）。
- **规则**：文案由**模板渲染**，数字**只来自 PLA-006 聚合**（**严禁 LLM 生成金额**）；遵守既有 quiet hours / cooldown / 每日上限；同周期幂等不重复推送。
- **Out of Scope**：不做图表 / 富媒体卡片（纯文本）；不做多用户广播；不改投递幂等、免打扰与通道出口；不新增常驻循环（挂既有维护步）。

Dependencies: PLA-006, PLA-009

Expected Output:

- 节律任务 + 模板 + 投递接线（**交付即生效，不设开关**）。
- **零 LLM 数字断言**：模板渲染路径不调用 LLM 生成数字（静态断言 + 快照）。
- **免打扰断言**：静默窗口内零投递（既有判定零差异）。
- **幂等断言**：同周期（日 / 周）重复触发只投递一次。
- **数字一致断言**：推送数字与 PLA-006 聚合结果逐分一致。
- 测试：`tests/v40/test_ledger_digest.py`。

---

## PLA-012 Budget Goal Integration

Type: BE
Priority: P1

Goal: 把「本月餐饮预算 1500」表达为 **Goal Stack 目标**，复用 Planning 七道闸做预算检查，**不建预算表**。

Scope:

- **交付面**：`services/ledger/budget.py`（预算 = goal 的领域视图，复用 `character_goals` 的 `domain` / `layer` 字段承载，**零新表**）+ 预算检查以 plan step 承载（只读消费 `services/planning/scheduler.py`）+ `services/planning/goal_contract.py` 失败理由扩展（预算类理由）。
- **规则**：**不新增真相源**；预算写入只经 `goal_repository` 计划单一写面；前台只读（长期化写只在后台，铁律既有）。
- **Out of Scope**：不重写 Planning 引擎 / 七道闸 / 拆解 / 修订；不建预算表；不做预算推荐算法（自动建议额度）；不做跨用户预算。

Dependencies: PLA-006

Expected Output:

- 预算目标适配 + 检查步骤 + 失败理由契约扩展。
- **单一写面断言**：预算写入只经 `goal_repository`（静态断言）。
- **精确性断言**：超预算判定与 PLA-006 聚合逐分一致。
- **零改动断言**：`services/planning/*` 数学与状态机零差异（对照测试）；零新增表。
- 测试：`tests/v40/test_ledger_budget.py`。

---

## PLA-013 Overspend Alert Triggering

Type: BE
Priority: P1

Goal: 预算 / 类目超支时经既有触发与投递链路预警，形成完整的「主动服务」闭环。

Scope:

- **交付面**：`services/ledger/alert.py`（阈值判定：类目 / 总额 / 日 / 月）+ `trigger_registry` 触发注册 + 经 Outbound 投递（**交付即生效，不设开关**，§0.9）。
- **规则**：去重键 = 同预算 + 同周期（**只报一次**）；遵守 quiet hours；**数字只来自聚合，禁 LLM 生成**。
- **Out of Scope**：不改 trigger 评估数学与 `trigger_registry` 机制；不新增通知渠道；不做分级告警策略（首版单级）。

Dependencies: PLA-011, PLA-012

Expected Output:

- 预警判定 + 触发注册 + 投递（**交付即生效，不设开关**）。
- **幂等断言**：同预算同周期只告警一次（去重键命中即跳过）。
- **免打扰断言**：静默窗口内零投递。
- **数字来源断言**：告警金额来自聚合而非 LLM（静态 + 快照）。
- 测试：`tests/v40/test_ledger_alert.py`。

---

## PLA-014 Spending Insight

Type: BE
Priority: P2

Goal: 从账目流沉淀**消费模式洞察**，复用既有 Reflection / Development 上层——验证「记忆承接抽象、账本承接事实」的分工边界。

Scope:

- **交付面**：`services/ledger/insight.py`（聚合特征 → Insight 候选，走既有 `reflection` 证据窗与三闸）+ 经 `memory2` 摄取**仅** `behavior_pattern` 类候选。
- **规则**：**金额明细永不进记忆**（裁决 0.2 红线）；仅抽象模式（如「高频外卖」/「夜间消费占比高」）可成候选；候选受既有 200 条上限与衰减约束——**这是记忆该有的行为，不是缺陷**。
- **Out of Scope**：不改 Reflection 三闸与 Insight 生命周期；不改 Development 编译（唯 Evolution）；不做消费预测 / 财务建议（避免越界为投资顾问）；不做对外分享。

Dependencies: PLA-006, PLA-007

Expected Output:

- 洞察适配 + 候选投递通路。
- **零金额入记忆断言**：`memories` / `memory_candidates` 中零金额数字（静态 + 用例）。
- **零改动断言**：`services/reflection/*` 三闸零差异。
- **边界断言**：仅 `behavior_pattern` 类可入；其余类型被拒。
- 测试：`tests/v40/test_ledger_insight.py`。

---

## PLA-015 Ledger Query API

Type: API
Priority: P1

Goal: 为用户提供**查询与订正**的 HTTP 面；`api` 层只做表现，聚合下沉 `services`（遵守既有分层纪律）。

Scope:

- **交付面**：`api/v1/ledger.py`（`GET /ledger/summary`、`GET /ledger/entries`、`POST /ledger/entries`（手动记账）、`POST /ledger/entries/{id}/reverse`（订正 / 撤销）、`GET /ledger/categories`）+ `api/v1/schemas.py` 增 ledger schema + 注册进 `api/v1/router.py`。
- **规则**：用户身份只从既有身份机制解析，**不得由客户端任意指定他人 `user_id`**（越权红线）；金额出口统一格式化；`api` 层**禁依赖 `repositories` 与 langchain**。
- **Out of Scope**：不做鉴权体系（沿用既有身份机制）；不做高级查询 DSL / 任意 SQL；不做导出（归 PLA-003 治理面）；不改既有 API 路由与响应契约。

Dependencies: PLA-006, PLA-010

Expected Output:

- 路由 + schema + 越权防护。
- **分层断言**：`api/v1/ledger.py` 零 import `repositories` / langchain（静态断言）。
- **越权断言**：跨用户读取 / 订正请求被拒（用例覆盖）。
- **一致性断言**：API 返回与 PLA-006 聚合结果逐分一致。
- 测试：`tests/v40/test_ledger_api.py`。

---

## PLA-016 User-Facing Life View

Type: FE
Priority: P2

Goal: 前端从纯调试台升级为**双模**：保留既有 Debug Console，新增面向用户的账本视图（review 缺口 ④）。

Scope:

- **交付面**：`apps/frontend/src/features/ledger/`（月视图 / 类目分布 / 条目列表 / 订正入口 / 空态 / 加载态 / 错误态）+ 双模路由入口。
- **规则**：只消费 PLA-015 的 API，**不直连后端内部**；金额展示与后端格式化一致；**既有 `components/debug/*` 与 `workbench.tsx` 调试能力完整保留，不得删除**（调试台是本项目的独特资产）。
- **Out of Scope**：不做移动端专门适配；不做图表库替换 / 大改版；不删除 Debug 面板；不做主题改版。

Dependencies: PLA-015

Expected Output:

- 用户账本视图 + 双模入口 + 三态（空 / 加载 / 错误）。
- **回归断言**：Debug 面板功能与截图零变化（既有前端测试全绿）。
- **一致性断言**：月视图数字与 API 返回逐分一致。
- **隔离断言**：前端零后端内部依赖（只经 API）。
- 测试：前端组件测试 + 手工验收清单。

---

## PLA-017 Acceptance & Regression

Type: TEST
Priority: P0

Goal: 对 V4.0.0 全量能力做 **Gate 化验收**，并完成本版本存在的理由——**账目精确性人工核对**。

Scope:

- **验收面**：PLA-001 ~ PLA-016 全部 Expected Output 断言汇总执行；零回归（既有 unit / api / integration / e2e / golden 全绿）；治理面（导出 / 删除）人工验证。
- **交付文档**：`docs/version/v4.0.0/acceptance-report.md` + `docs/version/v4.0.0/regression-checklist.md`（真实模型人工回归：自然语言记账 / 澄清 / 订正 / 冲正 / 日结 / 周报 / 预算 / 超支 / 查询 / 导出删除）。
- **精确性人工核对（本版本核心 Gate）**：构造 ≥ 50 笔真实对话记账样本，人工核对金额与类目，**零幻觉数字**——直接对标 `docs/household-inventory-review.md` 记录的失败模式（库存 6 个鸡蛋被说成「没了」）。
- **基线回写**：按项目纪律「架构演进先更新基线」，V4.0 落地后回写 `docs/current-system-architecture-baseline.md`。
- **Out of Scope**：不新增功能；不修改任何 Preserve 模块；不做性能优化（仅记录基线）。

Dependencies: PLA-001 ~ PLA-016

Expected Output:

- 全量 Gate 结果 + 验收报告 + 回归清单（对齐 V2.6.0 / V3.0.0 验收文档体例）。
- **零回归断言**：`pytest -m "(unit or api) and not slow"`、`-m integration`、`-m e2e`、golden 快照全绿。
- **精确性断言**：50 笔样本核对零幻觉数字、零类目漂移超阈。
- **边界断言**：Preserve 模块 diff 为空；分层依赖零违规；核心层零 import 具体渠道实现。
- **迁移断言**：`MIGRATION_HEAD == "0054"`、`SCHEMA_TABLE_COUNT == 49`、列摘要钉测全绿、两个迁移均可空跑回滚。
- **影子断言**：Flag 全 off 时全量回归与 V3.0.0 逐字节一致。

---

## 4. Implementation Order Recommendation

### 4.1 推荐批次（Batch）

| 批次 | 任务 | 并行度 | 批次出口（可判定） |
|---|---|---|---|
| **B0 地基与债** | PLA-001 | 串行（门禁） | `0053` 落地；钉测收敛为单点（改动文件 ≤ 3）；默认用户幂等播种；既有测试零修改通过 |
| **B1 归属、治理与运行时** | PLA-002 ‖ PLA-003 ‖ PLA-004 ‖ **PLA-018** | 4 并行（治理裁决先行） | 归属列 + 治理策略重裁落地 + 导出删除通路；账本三表落地且钉测全绿；`SCHEMA_TABLE_COUNT == 49`；**后台收编到 Runtime 且等价性对照全绿** |
| **B2 账本写读面** | PLA-005 → PLA-006 | 串行 | 幂等 / 冲正断言全绿；聚合精确性逐分一致 |
| **B3 摄取与行动** | PLA-007 → PLA-008 ‖ PLA-009 → PLA-010 | 先并行后收口 | 抽取契约与分流全绿；类目命中率达标；记账经动作台账可审计；澄清单次且可订正冲正 |
| **B4 主动服务** | PLA-011 ‖ PLA-012 ‖ PLA-014 → PLA-013 | 3 并行后收口 | 日结 / 周报零 LLM 数字；预算零新表；超支幂等单次 |
| **B5 用户面** | PLA-015 → PLA-016 | 串行 | 越权被拒；分层零违规；Debug 面板零回归 |
| **B6 验收** | PLA-017 | 串行（末端） | Gate 全绿；50 笔样本零幻觉数字；验收报告 + 回归清单归档 |

### 4.2 能力交付顺序（部署侧，**无开关**）

> 本版本**不新增任何功能开关**（§0.9 / architecture 铁律 5）。因此上线节奏以**交付顺序**控制，而非以配置位控制——每一批交付即生效，没有「关闭态」。

| 序 | 交付物 | 交付即生效的能力 | 观察重点 |
|---|---|---|---|
| 1 | **PLA-018** 后台统一到 Agent Runtime ✅ **已实现（2026-09-22）** | 后台自治走 Runtime 轨道（legacy 降级为**代码级**回退位，不可由配置触达） | 一个完整 tick 周期：段序列 / 预算闸 / 节流判定等价。**建议先于账本上线**——先统一调度路径，再往上叠功能 |
| 2 | **PLA-001** 用户实体 + `0053` | `users` 表 + 默认用户播种 | 既有链路零行为变化（读路径不变） |
| 3 | **PLA-002 / PLA-003** 归属 + 治理 | 归属校验生效；导出 / 删除端点可用 | 角色世界与用户容器互不可见；导出可对账、删除零残留 |
| 4 | **PLA-004 / PLA-005 / PLA-006** 账本内核 + `0054` | 账本三表可写可查（**此时只能手动记账**） | 幂等 / 冲正 / 聚合精确性逐分一致 |
| 5 | **PLA-007 / PLA-008 / PLA-009 / PLA-010** 摄取与行动 | 自然语言记账可用（含澄清 / 订正 / 冲正） | **重复入账**与**幻觉数字**——本版本最大风险面 |
| 6 | **PLA-011 / PLA-012 / PLA-013** 主动服务 | 日结 / 周报 / 预算 / 超支预警开始推送 | 推送数字与聚合逐分一致；免打扰与幂等 |
| 7 | **PLA-014 / PLA-015 / PLA-016** 洞察与用户面 | 消费洞察候选；查询 API；前端账本视图 | 记忆里零金额明细；越权被拒；Debug 面板零回归 |

**保持不变（本版不动，均为既有开关）**：`runtime_six_stage_loop_enabled = False`、`runtime_context_freeze_enabled = False`、`runtime_session_tracking_enabled = False`、`runtime_state_versioning_enabled = False`、`runtime_event_bus_enabled = False`——裁决 R5 与 V3.0 遗留 L2 的显式登记。**注意：这是「不动既有开关」，不是「新增开关」。**

**回滚策略（无开关靠什么）**：

| 场景 | 回滚手段 |
|---|---|
| 功能行为异常 | **代码回滚**（发布以 git 版本为单位） |
| Schema 变更异常 | **迁移回滚**（`0053` / `0054` 可空跑、可回滚，G13） |
| 账本已有真实数据 | ⚠️ **迁移不可回退数据**（表可 drop，但一旦用户已记账，回滚即丢数据）。因此账本上线后**只做代码级回滚，不回退迁移**；上线前必须明确数据备份策略（PLA-017） |
| 推送 / 预警骚扰 | 通过**参数**调低频率或改发送时刻（参数类字段），而非开关关闭功能 |

### 4.3 人力与节奏建议（按单 Agent 串行实现视角）

| 阶段 | 建议投入 | 说明 |
|---|---|---|
| B0 ~ B1 | 版本 35% 工时 | 地基不牢则后续全部返工；PLA-001 的钉测收敛与 PLA-004 的精度裁决是质量分水岭 |
| B2 ~ B3 | 版本 35% 工时 | 账本写读面 + 抽取与行动接入；**PLA-007 抽取精度是本版本最大不确定性** |
| B4 | 版本 15% 工时 | 主动服务；器官全在，主要为接线与模板工作 |
| B5 ~ B6 | 版本 15% 工时 | 用户面与验收；PLA-017 的 50 笔人工核对不可省 |

---

## 5. Risk Analysis

### 5.1 风险清单

| # | 风险 | 影响 | 概率 | 缓解措施 | 归属 |
|---|---|---|---|---|---|
| R1 | **抽取精度不足**（金额 / 时间 / 方向识别错） | 账目错误，用户信任一次崩塌，且是账本类产品最致命的失败 | 高 | 置信度阈值分流 + 低置信转澄清（不猜）；抽取结果只作候选、入账必经确认；PLA-017 50 笔人工核对零幻觉 | PLA-007 / PLA-010 |
| R2 | **重复入账**（同一句话记两次） | 账目翻倍，破坏可对账性 | 中高 | `idempotency_key` 唯一约束 + 抽取层去重键（沿用 `source_ref`）+ 幂等断言 | PLA-005 / PLA-007 |
| R3 | 财务数据隐私策略未重裁即建表 | **明知违规建表**，且后续返工 | 中 | PLA-003 治理裁决**先于** PLA-004 落表（§2.3 风险点 2）；L2→L1 重裁须先评审通过 | PLA-003 |
| R4 | 迁移链头钉测升级成本（本版 +4 表 / 2 迁移） | 大面积用例转红，阻塞交付 | **高** | PLA-001 先把 15 文件钉测收敛为单点入口；本版为升级成本最高的一次，列为 PLA-001 硬验收项 | PLA-001 |
| R5 | 金额误用 float / 精度丢失 | 账目出现「0.1+0.2」类错误，账本失去可信度 | 中 | 整数分存储 + 全仓 float 静态扫描 + 分元往返无损用例 | PLA-004 |
| R6 | 类目漂移（LLM 随手分类） | 聚合结果失去意义，用户不认账 | 中高 | 确定性优先归一（词表 / 规则命中即止）+ 禁新建类目 + 兜底可统计 | PLA-008 |
| R7 | 账目被塞进记忆（衰减 / 上限 / 隐私丢弃） | 重演已证伪的失败模式；「忘掉花过的钱」 | 中 | 裁决 0.2 红线 + 零金额入记忆断言 + Preserve diff 为空作为 Gate | PLA-014 / PLA-017 |
| R8 | LLM 编造金额（Prompt 挡不住） | 与 `household-inventory-review.md` 记录的同型故障 | 中高 | 金额**只来自结构化字段**；聚合与推送零 LLM 数字生成（静态 + 快照断言）；账目明细永不进 Prompt | PLA-006 / PLA-011 / PLA-013 |
| R9 | 越权读写他人账目 | 隐私事故 | 中 | 隔离**直接生效**（不设开关）+ API 越权断言 + 不信任客户端传入的 `user_id` | PLA-001 / PLA-015 |
| R10 | 预算 / 待确认另建表，形成第二真相源 | 违反单一写面，预算与账目漂移 | 中 | 预算走 Goal Stack、待确认走 `pending_action`（零新表）；零新表断言 | PLA-010 / PLA-012 |
| R11 | 用户自定义记账工具诉求被过早实现 | 触 `ToolRegistry` 启动期注册限制（非热插拔、重启丢失），引入不稳定面 | 中低 | 本版**只做内置 `ledger.*` 能力**；自定义工具列入 Out of Scope 与 Backlog | PLA-009 |
| R12 | 多用户 / 鉴权被顺带实现（范围蔓延） | 版本发散，Non-Goal 失控 | 中 | 裁决 0.7 明确「只备结构、不做鉴权」；多租户运营列入 Backlog | 全部 |
| R13 | 新仓储 / 新服务未注册进 `tests/conftest.py` | 测试连真实 PG 挂起（已知坑） | 中 | 新增仓储 → `_REPO_MODULES`；模块级 `SessionLocal` 服务 → `_SERVICE_DB_MODULES`；列为每任务实现清单项 | 全部 |
| R14 | 账本回滚丢失真实数据 | 用户账目不可恢复 | 中低 | §4.2 明确「功能可关、迁移不可回退」；上线前明确数据备份策略 | PLA-017 |
| **R15** | **三套调度路径并存**（前台 Runtime + 后台 legacy + 六段影子） | 同一能力在不同链路行为不一致，违反架构不变量 1，排障困难 | **高** | PLA-018 后台收编（不晚于 Phase 4）；新能力一律走 Profile 阶段序列（裁决 R1）；R2/R3 两条禁令写进 DoD | PLA-018 + 全部 |
| **R16** | **PG 用例静默 skip 掩盖发布阻断缺陷**（V3.0 的 D-4 教训：`template1` 排序规则错配致整批 PG 用例 skip，使迁移在 PG 上不可执行竟长期未被发现） | V4.0 加 2 迁移 4 表，若 PG 未真实执行，可能带着「PG 上根本跑不通」的迁移发布 | **高** | PLA-017 新增前置检查：确认 `TEST_DATABASE_URL` 可用且 PG 用例**非全 skip**；`0053`/`0054` 必须真实 PG 双向空跑 | PLA-017 / PLA-001 |
| **R17** | **无开关带来的回滚粒度变粗**（C-1 的必然代价：出问题时只能整版代码回滚，无法单点关闭） | 故障影响面可能扩大；紧急止血手段变少 | 中 | 用**设计层隔离**对冲：账本 append-only（多写不破坏）、新增端点 / 页面不改既有契约、迁移可逆；**上线前必须有明确的数据备份与回滚演练**（PLA-017）；接受「回滚粒度粗」换「配置面干净」是本裁决的显式取舍 | PLA-017 + 全部 |

### 5.2 不可接受风险（触发即暂停实现并回到架构评审）

1. 任何 Task 把账目数据写入 `memories` / `memory_candidates`（违反裁决 0.2）。
2. 任何 Task 为账本另建第二套 Agent Pipeline / 绕过 Profile Registry。
3. 任何 Task 让金额由 LLM 复述或生成（而非来自结构化字段）。
4. 任何 Task 为账本条目引入衰减 / 失效 / 容量上限 / 过期语义。
5. 任何 Task 绕过 `ledger_repository` 直写账本表。
6. 任何 Task 修改 Preserve 清单（§0.5）中模块的语义或数学。
7. 任何 Task 在治理裁决（PLA-003）未通过前落地账本表迁移。
8. 任何 Task 以 `chat_pipeline._drive_foreground_linear`（C-2 kill switch）或 `agent_runtime/stages/*`（六段影子实现）为开发基线（裁决 R2 / R3）。
9. 任何 Task 激活六段认知循环（`runtime_six_stage_loop_enabled`）或引入第三方编排框架（裁决 R5）。
10. 任何 Task 新增功能开关 / 灰度门控（`*_enabled`）来「让上线更安全」（裁决 9）——安全应由设计层隔离与可回滚性提供，而非配置位。

---

## 6. Acceptance Criteria

### 6.1 版本级 Gate（缺一不可上线）

| Gate | 判据 | 验证方式 |
|---|---|---|
| **G1 用户实体就位** | `users` 表落地、默认用户幂等播种、既有调用零行为变化 | 迁移用例 + 兼容回归 |
| **G2 账目精确性（核心）** | ≥ 50 笔真实对话样本，金额与类目人工核对**零幻觉数字** | 人工核对记录 + PLA-017 报告 |
| **G3 不可遗忘** | 账本表无 TTL / 过期 / 衰减列；账目在任意时间点可查 | 静态断言 + 时间跨度用例 |
| **G4 幂等与冲正** | 同 `idempotency_key` 仅 1 行；冲正后净额归零且原行未变 | `tests/v40/test_ledger_repository.py` |
| **G5 金额精度** | 全仓账本路径零 `float`；分元换算无损 | 静态扫描 + 往返用例 |
| **G6 账目不入记忆** | `memories` / `memory_candidates` 零金额明细 | 静态 + 用例 |
| **G7 零 LLM 数字** | 聚合 / 日结 / 周报 / 预警路径无 LLM 生成数字 | 静态断言 + 快照 |
| **G8 治理合规** | 导出完整可对账；删除零残留；金额不进 Prompt 快照 | 治理用例 + 快照断言 |
| **G9 越权防护** | 跨用户读写被拒 | API 越权用例 |
| **G10 单一写面** | 账本写只经 `ledger_repository`；预算只经 `goal_repository` | 静态断言 |
| **G11 Preserve 零改动** | §0.5 清单模块 diff 为空 | git diff + 对照测试 |
| **G12 零回归（判定口径）** | 既有 unit / api / integration / e2e / golden **零回归成立**（当前失败集 ⊂ 基线失败集，沿用 V3.0 因既存 18 项失败形成的口径，见 `audits/v3.0.0-runtime-adoption-audit.md` §3.1）；**能力上线即生效**，无「关闭态」需验证 | Fast Test + integration + e2e + golden + 基线对照法 |
| **G12b 零新增功能开关** | `core/settings/` 无新增 `*_enabled` 功能位；新增字段全为参数类（阈值 / 取值 / 时刻） | 静态断言 + 字段清单核对（对照 §0.4 白名单） |
| **G13 迁移可空跑** | `0053` / `0054` 可空跑、可回滚；`MIGRATION_HEAD == "0054"`；`SCHEMA_TABLE_COUNT == 49` | 迁移测试（需 `TEST_DATABASE_URL`） |
| **G14 钉测收敛** | 链头钉测单点化；加迁移的改动文件数 ≤ 3 | 静态断言 + PLA-001 验收 |
| **G15 运行时单一路径** | 后台已收编 Agent Runtime；全仓零第二条自治编排路径；六段仍为影子（`SHADOW_STAGE_IMPLEMENTATION == True`） | 静态断言 + `test_runtime_background_cutover.py` |
| **G16 PG 真实执行** | PG 用例**非全 skip**（D-4 教训）；两个迁移在真实 PG 上正放 / 逆放通过 | `pytest tests/integration/test_db_migration.py` 输出核验 + `alembic upgrade head`/`downgrade` |

### 6.2 每个 Task 的 Definition of Done（统一要求）

1. Expected Output 中的**全部断言**有可执行用例（不允许「口头保证」）。
2. **零回归 + 可回滚**（替代原「Flag 关闭时逐字节一致」）：既有测试零回归（当前失败集 ⊂ 基线失败集）；本 Task 的改动在代码层可整体回滚；涉及 Schema 的 Task 迁移可空跑回滚。**不新增任何功能开关**（§0.9）——若实现中出现「需要一个开关才能安全上线」的想法，应回到架构评审而非加开关。
3. 分层依赖方向零违规；`api` 不依赖 `repositories` / langchain；核心层不 import 具体渠道实现。
4. 新增仓储 / 使用模块级 `SessionLocal` 的服务已注册进 `tests/conftest.py`。
5. 测试执行遵守 `docs/TESTING.md`：Focused → Module → 必要时 Fast；不默认跑全量。
6. 无临时文件残留（`git status` 干净）；提交信息符合 `feat:` / `fix:` / `refactor:` / `docs:` 约定（单行 ≤ 30 字）。
7. Task Detail 文档就位（`docs/version/v4.0.0/tasks/PLA-XXX.md`），实现与 Detail 的偏差已回写。
8. 阈值 / 魔法数字全部落 `core/settings/life.py` / `ledger.py`，零硬编码。

### 6.3 版本级验收产物

| 产物 | 位置 | 说明 |
|---|---|---|
| 验收报告 | `docs/version/v4.0.0/acceptance-report.md` | Gate 结果 + 证据（用例名 / 命令 / 输出摘要）+ 50 笔精确性核对记录 |
| 回归清单 | `docs/version/v4.0.0/regression-checklist.md` | 真实模型人工回归：记账 / 澄清 / 订正 / 冲正 / 日结 / 周报 / 预算 / 超支 / 查询 / 导出删除 |
| 架构基线更新 | `docs/current-system-architecture-baseline.md` | 回写用户实体、账本域、治理策略（含 L2→L1 重裁） |
| 治理策略文档 | `docs/version/v1.0.0/v4/privacy-governance.md` | L2 财务数据结论改写（**唯一允许修改的历史文档**，属策略重裁而非史实改写） |
| 文档链接同步 | `AGENTS.md` / `apps/backend/AGENTS.md` | 版本入口指向 V4.0.0；迁移链尾 `0052` → `0054`；settings 模块数 21 → 23 |
| 运行时口径勘误 | `docs/version/v4.0.0/acceptance-report.md`（登记项） | 登记 V3.0 影子矩阵表格漏 2 字段（11 vs 13）与「不变量 8 PASS 为测试态口径」两处差异；**不修改 V3.0 冻结报告** |

---

## 7. 附录

### 7.1 需求追溯矩阵（review 章节 → 任务）

| review 章节 | 承载任务 |
|---|---|
| §2 已有资产盘点（不该重造） | §0.1 裁决 + PLA-009（Tool）/ PLA-012（Goal+Planning）/ PLA-011（Autonomy+投递）/ PLA-014（Reflection+Development）/ PLA-004（账本三件套模式借鉴自 relationship） |
| §3 缺口 1 没有「主人」（主体错位） | PLA-001（用户实体）+ PLA-002（归属） |
| §3 缺口 2 没有「账本」（结构化底座缺失） | PLA-004 + PLA-005 + PLA-006 |
| §3 缺口 3 抽取是文本管道不是事实管道 | PLA-007 + PLA-008 |
| §3 缺口 4 没有面向用户的面 | PLA-015 + PLA-016 |
| §3 缺口 5 信任与治理未就绪 | PLA-003 + PLA-017（精确性 Gate） |
| §4 六维评分（主体 2 / 账本 0 / 抽取 3 / 界面 1 / 治理 2 / 主动性 8） | §1.3 能力域覆盖矩阵 |
| §5 Phase A 立用户 | PLA-001 + PLA-002 + PLA-003 |
| §5 Phase B Ledger 三件套 | PLA-004 + PLA-005 + PLA-006 |
| §5 Phase C 抽取与确认 | PLA-007 + PLA-008 + PLA-009 + PLA-010 |
| §5 Phase D 主动性与洞察 | PLA-011 + PLA-012 + PLA-013 + PLA-014 |
| §5 Phase E 用户面 | PLA-015 + PLA-016 |
| §5「最短路径 A → B → D」建议 | §4.1 批次 B0~B4（B3 抽取为 P0 但可与 B4 部分并行；Detail 中登记该收敛顺序） |
| §5 Phase C 难点：中文消费类目归一 | PLA-008 |
| §6 避坑清单第 1~5 条 | §5.2 不可接受风险 1~5 |
| §6 避坑清单第 6 条（加新表摩擦成本） | PLA-001（钉测收敛）+ G14 |
| §6 避坑清单「不要先做 UI」 | PLA-016 为 P2 且依赖 PLA-015；Phase 5 排在 Phase 2~4 之后 |
| `architecture.md` §2 运行时采用裁决（R1~R5） | §0.8 裁决 8 + **PLA-018**；禁令写入 §5.2 与 DoD |
| `architecture.md` §10 边界不变量 10 条 | §6.1 Gate + 各 Task 的 Out of Scope |
| `audits/v3.0.0-runtime-adoption-audit.md` §3.4 遗留 L1~L3 | L1/L2 列 Backlog；L3 由 PLA-015 的「不扩大」断言承担 |
| `audits/v3.0.0-runtime-adoption-audit.md` §3.2 / §3.3（D-1~D-4 / I-2 / I-7） | G12 零回归口径（I-2）+ G16 PG 真实执行（D-4）+ PLA-017 前置检查（I-7） |
| `architecture.md` 附 D C-1（禁止新增功能开关） | §0.9 裁决 9 + §0.4 收紧 + §4.2 改写 + G12b + 风险 R17 + 不可接受风险 10 |
| `architecture.md` 附 D C-2（后台统一到 Runtime） | PLA-018「统一而非切换」+ 开关台账登记 |

### 7.2 命名与文档约定

- **任务编号**：`PLA-001 ~ PLA-018`，冻结后不重排；新增任务追加为 `PLA-019+` 并登记依赖。**PLA-018 为审计后追加**（执行位置在 Phase 1），是「追加而非重排」规则的首次适用。
- **Task Detail**：`docs/version/v4.0.0/tasks/PLA-XXX.md`（**已生成，PLA-001 ~ PLA-018 全 18 份**），体例对齐 `docs/version/v3.0.0/tasks/RT-002.md`（Task Overview / Background / Scope / Technical Design Requirements / Implementation Plan / File Impact / Testing Requirements / Acceptance Criteria / Commit Requirement）。Detail 只能细化注册表，**不得扩权到 Out of Scope 之外的模块**；实现与 Detail 的偏差须回写 Detail。
- **本注册表的权威性**：Task 的 ID / 名称 / 类型 / 优先级 / 直接依赖 / 交付面以本文档为准；Detail 只能细化，不得扩权到 Out of Scope 之外的模块。
- **需求变更**：任何超出 `architecture.md` 的能力须**先更新 `docs/version/v4.0.0/architecture.md` 与 `docs/current-system-architecture-baseline.md`**，再回到本文档改任务（对齐项目纪律：架构演进先改基线再进开发）。
- **架构依据（已就位）**：本版本以 `docs/version/v4.0.0/architecture.md` 为唯一架构依据（含主体与归属设计、账本域设计、运行时采用裁决、边界不变量 12 条），需求侧由 `reviews/` 下评审文档支撑，运行时由 `audits/` 下审计报告支撑。**§0 九条裁决为架构级前提，不得绕过；其中裁决 9（禁止新增功能开关）与裁决 8（运行时采用）优先于本注册表任何旧表述**。
- **文档目录（本版本归拢约定）**：`docs/version/v4.0.0/` 下——`architecture.md`（架构）/ `tasks.md`（注册表）/ `tasks/`（明细，后续生成）/ `reviews/`（需求评审）/ `audits/`（前置审计）/ 验收产物（`acceptance-report.md` / `regression-checklist.md`，实现后生成）。
- **表命名**：`ledger_accounts` / `ledger_categories` / `ledger_entries` 指**财务账本**；与审计语义 `services/domain_ledger.py`（无表，只读投影）严格区分。

### 7.3 本版不做的显式登记（Backlog）

| 项 | 归属版本 | 依据 |
|---|---|---|
| 注册 / 登录 / 鉴权体系 | 未排期 | 裁决 0.7（本版只备结构） |
| 多租户运营能力（配额 / 计费 / 隔离运维） | 未排期 | 裁决 0.7 |
| 用户自定义记账工具（DSL 注册） | 未排期 | PLA-009 Out of Scope（`ToolRegistry` 启动期注册限制） |
| 票据 OCR / 语音记账 / 图片识别 | 未排期 | PLA-007 Out of Scope |
| 多币种与汇率 | 未排期 | PLA-004 Out of Scope（首版单币种） |
| 自动类目发现 / 聚类 / 重分类批处理 | 未排期 | PLA-008 Out of Scope |
| 消费预测 / 财务建议 / 投资类内容 | 未排期 | PLA-014 Out of Scope（避免越界） |
| 批量导入与批量订正（账单对账） | 未排期 | PLA-010 Out of Scope |
| 外部账单源接入（支付平台 / 银行） | 未排期 | 依赖 `tool/ext_api.py` manifest + 用户授权体系（未建） |
| 移动端专门适配 | 未排期 | PLA-016 Out of Scope |
| **六段认知循环真收编（方案 A）** | 未排期 | 裁决 R5；前置：C-2 补充 e2e 安全网 + 六段与 Profile 段序列等价性证明 |
| `debug_view` 接入 debug 端点（V3.0 遗留 L1） | 未排期 | 审计 §3.4；PLA-018 Out of Scope |
| 前台传参启用 Context 冻结（V3.0 遗留 L2） | 未排期 | 审计 §3.4；`runtime_context_freeze_enabled` 本版保持 `False` |
| `app/api/**` 反向依赖 `app/repositories` 治理（V3.0 遗留 L3） | 未排期 | 审计 §3.4；本版只承诺「不扩大」 |
| **既有 `runtime_*` 已转常开开关的清理**（`runtime_foreground_loop_enabled` / `runtime_autonomous_cycle_enabled`） | 未排期（flag-removal 批次） | §0.9；V4.0 只**登记**进 `flag-removal-audit.md`，**清理动作不入本版交付面** |
| Episodic / Semantic 记忆双通道 | V3.1（**已预留，勿占用**） | v3.0.0 tasks.md §7.3 |
| 循环内嵌持续反思 | V3.2（**已预留**） | v3.0.0 tasks.md §7.3 |
| Self Improvement 闭环深化 | V3.3（**已预留**） | v3.0.0 tasks.md §7.3 |

---

> **文档结束**。本文档为 V4.0.0 的唯一任务注册表；实现顺序、依赖与验收以本文档 + review 文档 §0 裁决为准。
