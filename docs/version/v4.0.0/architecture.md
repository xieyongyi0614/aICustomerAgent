# V4.0 Personal Life Agent Architecture

> **状态**：Architecture（架构设计稿；**仅设计，未实现**，不含代码实现）
> **前置**：V3.0.0 Agent Runtime（Implemented — CONDITIONAL，见 §2 审计）、V2.0.0 Memory V2 / Reflection / Development / Life Loop、V2.1.0 Goal Stack / Decision Pipeline、V2.3.0 World Simulation、V2.4.0 Tool System、V2.5.0 Planning System、V2.6.0/2.6.1 Action Execution + Reflection
> **需求来源**：`docs/version/v4.0.0/reviews/personal-life-agent-architecture-review.md`（个人生活智能体架构评审：五缺口 + 六维评分 + Phase A~F 路径）
> **现状约束**：`docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线）
> **定位**：V4.0 = **Personal Life Agent Foundation（个人生活智能体地基）**。把系统主体从**角色**翻转为**用户**，补上此前完全缺失的两块地基——**① 用户实体（谁是主人）** 与 **② 账本域（什么算事实）**——并以**记账**作为第一个纵切，跑通「自然语言 → 结构化事实 → 可查询 / 可对账 / 可纠正 → 主动服务」的完整闭环。
> **铁律**：本文档只做架构裁决，不含 Task、不含代码实现（仅关键契约与字段裁决）、不改任何既有模块；基于 Current System Architecture Baseline 演进，明确 Runtime 与业务模块边界。

---

## 0. 版本定位与设计原则

### 0.1 核心判断

V1~V3 已经把「器官」和「运行时骨架」全部建齐（记忆 / 反思 / 成长 / 关系 / 目标 / 决策 / 规划 / 行动 / 工具 / 世界 / 人格 / 运行时内核）。

| 能力 | 承载 | 状态 | V4.0 处置 |
|---|---|---|---|
| 长期记忆（7 类 + 生命周期 + 混合检索） | V4 + Memory 2.0 | 已实现 | **Preserve**（账目**不**入记忆） |
| 经历 → 认知 → 行为演化 | Reflection + Development | 已实现 | **消费**（消费洞察） |
| 关系成长 | V8.5 六维引擎 | 已实现 | **模式借鉴**（账本三件套） |
| 目标 / 规划 / 预算承载 | Goal Stack + V2.5 七道闸 | 已实现 | **消费**（预算 = goal） |
| 行动执行与治理 | V2.6 Action + V2.4 Tool | 已实现 | **消费**（记账是一次行动） |
| 世界模拟 | V8 + V2.3 | 已实现 | **Preserve** + 归属扩展 |
| 主动性与投递 | V7 + life_loop + 通道 | 已实现 | **消费**（节律 / 预警） |
| Agent Runtime 内核 | V3.0.0 | Implemented（CONDITIONAL） | **采用为唯一开发基线**（§2） |
| **用户实体** | — | **完全缺失** | **V4.0 新建** |
| **账本域** | — | **完全缺失** | **V4.0 新建** |

**核心判断**：当前系统是一个精密的**「角色生命模拟器」**，而个人生活 Agent 是**「用户生活操作系统」**。二者共享大量基础设施（这是红利），却有两个根本不同的前提——**谁的生活**（主体）与**什么算事实**（账本）。

> **主体错位是首要问题**：现状问「用户今天过得怎么样」，系统答的是「亚丝娜今天做了什么」——世界描述为「你和亚丝娜的家」（`character/asuna/world.py:12`），作息模板是亚丝娜的（`character/asuna/routine.py:12`），用户处境只是角色视角下的 5 个扁平标签（`services/world/user_situation.py:3`、`:43-79`，且**无消费维度**）。

**V4.0 只做两件事**：立主体、立账本。其余全部复用。

### 0.2 五条铁律（对所有后续 Task 生效）

1. **只补地基，不建第二套 Agent**：新能力一律以「注册 Profile 阶段 / 维护步 / 工具能力」接入，禁止新增编排引擎、第二套 Pipeline 或第三方 Agent 框架（延续 V3.0 ADR-7）。
2. **事实与叙事分离（本版本最重要的一条）**：**账目是事实，记忆是叙事**。账目进账本域，**永不进记忆**；金融数字**永不由 LLM 生成或复述**，只能来自结构化字段。
3. **单一写面 + append-only**：账本写只经 `ledger_repository`；账本**只增不改**，纠错走**冲正**（reversal）而非修改；预算只经 `goal_repository`。
4. **先立主体，再谈功能**：Phase 1（用户实体 / 归属 / 治理）是全部后续能力的门禁；治理裁决（财务数据分级重裁）**必须先于**账本表落地。
5. **禁止新增功能开关阀门**（2026-09-22 追加）：V4.0 **不引入任何新的功能门控 / 灰度总闸开关**。理由与替代方案见 §9——开关是**技术债的另一种形态**（配置面膨胀、双路径并存、每个开关都要维护「关闭时等价」的测试承诺），而本项目已有的 `flag-removal-audit.md` 正是拆除上一代开关体系的台账。能力**上线即生效**；回滚改由「代码回滚 + 迁移可逆 + append-only 不破坏既有语义」承担。**仅允许新增参数类字段**（阈值 / 币种 / 类目文案 / 周期），不得新增 `*_enabled` 形态的功能位。

### 0.3 Non-Goals（本版本明确不做）

- **不做注册 / 登录 / 鉴权体系**：用户身份仍来自既有请求参数与 `channel_identities` 映射；本版只保证「不能读写他人数据」，不解决「你是谁」。
- **不做多租户运营能力**：配额 / 计费 / 隔离运维列 Backlog。
- **不新增任何功能开关 / 灰度门控 / 版本开关**（见 §0.2 铁律 5、§9）。
- **不做票据 OCR / 语音记账 / 图片识别**。
- **不做多币种与汇率**（首版单币种 CNY）。
- **不做消费预测 / 投资建议 / 理财内容**（避免越界为投资顾问）。
- **不做外部账单源接入**（依赖尚未建立的用户授权体系）。
- **不激活六段认知循环**：`agent_runtime/stages/*` 保持影子实现（§2.5）。
- **不重造任何既有器官**：Memory / World / Relationship / Planning / Action / Tool / Reflection / Development / Decision / Goal / Agent Runtime 的数学与状态机零改动。

---

## 1. Problem Definition

基于架构评审（`reviews/personal-life-agent-architecture-review.md` §3）审计，识别五类结构性问题。

### 1.1 主体错位（P0）

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| O1 | 单用户硬编码 | `core/settings/pipeline.py:30` `default_user: str = "default-user"` | 无用户实体，无法隔离 |
| O2 | `user_id` 是裸字符串 | `core/db.py:35` `Conversation.user_id`（无 FK、无 users 表）；`api/v1/world.py:79` 等 4 处 `Query(default=...)` | 无归属权威 |
| O3 | 世界属于角色 | `character/asuna/world.py:12`「你和亚丝娜的家」；`services/world/daily_plan.py:125` 由角色作息驱动 | 生活域归属未定义 |
| O4 | 用户仅是「角色视角下的标签」 | `services/world/user_situation.py:3`、`:43-79`（5 维，无消费） | 用户生活无容器 |

> **兼容红利**：`user_id` 已是贯穿全链的**裸字符串**（而非散落的硬编码常量），补用户实体的改动面远小于从零引入多租户。

### 1.2 事实底座缺失（P0）

| # | 问题 | 证据 |
|---|---|---|
| F1 | 无任何面向用户的结构化领域表 | 全库 45 表（`SCHEMA_TABLE_COUNT = 45`，`tests/v24/tool012_support.py:81`）无财务 / 交易 / 资产 / 待办表 |
| F2 | 唯一的 "ledger" 是审计语义 | `services/domain_ledger.py`（多域审计账本，与金钱无关） |
| F3 | 用户信息只落文本记忆 | `memories` / `memory_candidates`，`content` 为 ≤50 字纯文本，**无金额字段**（`services/memory2/types.py:9` 扁平 7 类） |

**后果（以「中午吃了 20 块快餐」为例）**：这句话走完今天全部链路的产物是**一条 content ≈「用户中午吃了快餐」的文本记忆候选**——**数字 20 在整个系统里没有任何位置可以落**。这不是配置问题，是数据结构层面无处安放。

### 1.3 摄取是文本管道，不是事实管道（P0）

| # | 问题 | 证据 |
|---|---|---|
| I1 | 行动意图检测为纯词表 + 正则、零 LLM | `services/action/detector.py`；调用点 `application/chat_pipeline.py:682` |
| I2 | `action_type` 枚举无记账类 | `character/asuna/action.py:22` |
| I3 | 记忆抽取输出为「文本 + 类型」 | `chains/extractor_chain.py:7`；`models/memory.py:69 MemoryExtraction` |

**缺四样东西**：Schema-first 的结构化抽取链、置信度 + 澄清回问、幂等去重、用户可纠正（冲正语义）。
**同构实现已在项目内**：`services/world/interpreter.py` 做的是「用户消息 → 世界状态迁移解释」，与「用户消息 → 账目条目」是同一件事。

### 1.4 治理与信任未就绪（P0）

| # | 问题 | 证据 |
|---|---|---|
| G1 | 财务数据策略与记账**直接冲突** | `docs/version/v1.0.0/v4/privacy-governance.md` §1.1：L2（含财务数据）目标策略「**不保存**」 |
| G2 | 无数据导出 / 删除（被遗忘权） | 全库无相应 API |
| G3 | LLM 幻觉无系统侧强制 | `docs/household-inventory-review.md`：库存 6 个鸡蛋被说成「没了」，凭空出现番茄汤；结论「即使给了『以清单为准』引导语 LLM 仍编造，需要**系统侧强制**」 |

> **把「鸡蛋」换成「钱」，这就是记账功能上线后的故障模式。** 该报告等于提前完成了本功能的失败预演，V4.0 的 §4.6「零幻觉」设计直接源于此。

### 1.5 无面向用户的面（P1）

| # | 问题 | 证据 |
|---|---|---|
| S1 | API 几乎全为调试端点 | `api/v1/router.py` → chat / **debug** / feishu / action / state / history / llm / proactive / world |
| S2 | 仅有的读接口是只读调试视图 | `api/v1/history.py:48` `GET /memories`；`api/v1/state.py:53` `GET /state` |
| S3 | 前端是开发者调试台 | `apps/frontend/src/components/debug/*`；`App.tsx:27` 主路由即 `<Workbench/>` |

---

## 2. 运行时采用裁决（Agent Runtime vs 旧管线）

> 本节回答「后续开发用 Agent Runtime 还是旧管线」，基于对本仓库的**只读代码审计**（完整证据见 `docs/version/v4.0.0/audits/v3.0.0-runtime-adoption-audit.md`）。

### 2.1 审计结论：V3.0.0 完成了什么、没完成什么

**V3.0.0 判定：结构完整、地基落地、但循环未激活 → `CONDITIONAL — NOT RELEASED`。**

| 面 | 事实 | 证据 |
|---|---|---|
| 交付物 | RT-001~RT-019 **全部存在**：`contracts.py`（RuntimeInput/SessionContext/RunResult/RuntimeEvent/RuntimeFailure/AgentRuntime）、`session.py`、`context.py`、`state.py`、`events.py`、`inbound.py`、`outbound.py`、`recovery.py`、`execution_history.py`、`debug_view.py` | `application/agent_runtime/**` |
| Schema | 迁移 `0052` 已落地；`loop_runs.session_id`、`runtime_traces.correlation_id` 已在 ORM（可空 + 索引） | `core/db.py:1213` / `:873`；`0052_runtime_session_trace_links.py` |
| **前台路径** | **已默认走 Agent Runtime**：`runtime_foreground_loop_enabled = True` → `AgentLoop.run()` + `profiles.py` 前台段序列 | `core/settings/agent_runtime.py:41`；`chat_pipeline.py:401`、`:880-893` |
| **后台路径** | **仍走 legacy**：`runtime_autonomous_cycle_enabled = False` → `_legacy_run_autonomous_cycle` | `core/settings/agent_runtime.py:40`；`controller.py:319-336`、`:255-316` |
| **六段循环** | **未激活（影子实现）**：`runtime_six_stage_loop_enabled = False`；段本体**刻意不导出**生产面 | `settings/agent_runtime.py:42`；`loop.py:659-662`；`stages/__init__.py:25 SHADOW_STAGE_IMPLEMENTATION = True`；`agent_runtime/__init__.py:168-169` |
| 回退开关 | `_drive_foreground_linear` 作为 **C-2 kill switch** 保留（不建台账、不发事件） | `chat_pipeline.py:356`、`:369`、`:895` |
| 验收 | G1~G6、G8~G12 **PASS**；**G7 FAIL**（既存 18 项失败，非 V3.0 引入，零回归成立）；人工回归待执行 | `docs/version/v3.0.0/acceptance-report.md` |

**关键辨析（必须说清，否则会误用）**：`acceptance-report.md` 的「边界不变量 8：前后台共用同一认知循环 = PASS」是在**开关开启的测试态**下成立的；**默认生产配置下，后台仍是 legacy、六段仍是影子**。引用 V3.0 成果时不可把「测试态全绿」等同于「生产态已收编」。

**V3.0.0 三处遗留（未阻断，但 V4.0 必须知情）**：

| # | 遗留 | 证据 | V4.0 处置 |
|---|---|---|---|
| L1 | `debug_view` 未接任何 debug 端点 | 无 API 路由引用 | 不在本版修（Backlog）；本版只要求**不依赖**它 |
| L2 | 前台未传 `runtime_input/session_context` → Context 冻结分支**生产恒不进入** | `agent_service.stream_chat` 调用点未传参；`chat_pipeline.py:410-419` | 不在本版修；`runtime_context_freeze_enabled` 保持 `False` |
| L3 | `app/api/**` 反向依赖 `app/repositories`（5 文件 26 处） | acceptance-report 遗留登记 I-3 | 本版**不扩大**该违规：新增 `api/v1/ledger.py` 必须零 `repositories` 依赖（写进 PLA-015 断言） |

### 2.2 采用裁决（R1~R5）

| # | 裁决 | 理由 |
|---|---|---|
| **R1** | **后续开发基线 = Agent Runtime 的「Profile 阶段序列」**（`profiles.py` 唯一声明处 + `AgentLoop.run()`） | 前台已默认此路径；V3.0 铁律 ADR-7「无第二套 Agent Pipeline」；段本体与既有业务函数同一套，收编成本已付 |
| **R2** | **禁止**以 `chat_pipeline._drive_foreground_linear` 为开发基线 | 它是 **C-2 kill switch**（不建台账、不发事件、不冻上下文），仅用于「一键回退」，不是能力扩展面 |
| **R3** | **禁止**依赖 `agent_runtime/stages/*` 六段影子实现 | 未接入生产 `run()`，`SHADOW_STAGE_IMPLEMENTATION = True`；依赖它等于依赖未启用代码 |
| **R4** | **后台必须收编**：V4.0 将后台自治切到 Agent Runtime 轨道并纳入验收 | 否则会出现「前台 Runtime + 后台 legacy + 六段影子」**三套路径**，比 V3.0 之前更乱；且节律 / 预警需挂 Runtime 维护步 |
| **R5** | **六段认知循环本版不激活**，保持影子；登记为「方案 A 真收编」的立项前置 | 六段的价值在于循环形态，而 V4.0 的价值在**数据正确性**；先激活循环会把风险叠加到地基之上。方案 A 需先建 C-2 补充 e2e 安全网（V3.0 architecture 附裁决登记 D-1 已定） |

### 2.3 新功能接入方式（唯一合法姿势）

V4.0 及后续一切新能力，按以下方式接入，**四条之外即为违规**：

1. **新增能力 = 注册新 Profile 阶段或接入既有阶段的段本体**（段序列只在 `profiles.py` 声明）。
2. **跨域副作用 = 走 Update / handoff**（复用 `application/post_process` 既有步骤注册，独立容错），不得新增第二轮询。
3. **持久化 = 走对应域的唯一写面仓储**；Run 台账只写 `loop_runs`。
4. **定时 / 节律 / 预警 = 挂既有维护步或 `trigger_registry`**，不新增常驻循环。

> **对 V4.0 的具体落点**：账务节律与超支预警（PLA-011 / PLA-013）挂 `life_loop` 维护步 + `trigger_registry`；记账动作（PLA-009）经 Action Engine → Tool Registry 既有治理链；消费洞察（PLA-014）走 Reflection 既有证据窗。**不新增任何编排引擎。**

### 2.4 后台收编的独立任务

后台从 legacy 切到 Agent Runtime 是**跨域结构性改动**（涉及 `controller.py` / `life_loop.py` / 维护步），不属任何账本任务，故独立立为 **PLA-018（Agent Runtime Adoption & Background Cutover，P0）**，作为 Phase 4 的前置。其交付面与验收见 `tasks.md`。

### 2.5 六段循环的处置登记

```
现状：run() 分叉（loop.py:659-662）
  runtime_six_stage_loop_enabled = False（默认）
     → _run_stages(profile.stages)        ← 生产唯一实际路径（Profile 段序列）
  runtime_six_stage_loop_enabled = True
     → _run_six_stage_loop()              ← 六段分组；自治 tick 才调真六段

V4.0 裁决：保持 False，不改。
方案 A（真收编）前置：① 建 C-2 补充 e2e 安全网；② 六段与 Profile 段序列等价性证明；
                    ③ 独立立项评审（不在 V4.0 范围）。
```

---

## 3. 主体与归属设计（User Domain）

### 3.1 用户实体

**目标**：把 `user_id` 从裸字符串升格为一等实体，冻结「用户 → 数据分区键」契约。

| 项 | 设计 |
|---|---|
| 表 | `users`（`id` / `display_name` / `status` / `is_default` / `created_at` / `updated_at`） |
| 默认用户 | 幂等播种 `default_user` 行（对齐既有 `world_entities` 播种范式）；唯一约束保证单一默认用户 |
| 键约束 | **不加强制 FK**（既有表 `user_id` 列语义与取值**零变更**，避免历史数据撕裂） |
| 契约 | `UserContext` 值对象（`frozen`、零 IO、零 LLM） |
| 兜底 | `user_id` 缺失 → 回落 `default_user`（与现状行为**逐字节一致**） |

### 3.2 归属模型

| 项 | 设计 |
|---|---|
| 世界归属 | `worlds` 增 `owner_type`（`character` / `user`）+ `owner_id` |
| 既有数据 | `home` 世界保持 `owner_type = "character"`（**默认值即兼容，零数据迁移**） |
| 用户生活容器 | `owner_type = "user"` 承载，**与角色世界严格分离，不混用** |
| 解析 | `services/life/ownership.py` 纯函数（`resolve_owner` / `assert_access` / `scope_filter`），无 IO、无 LLM |
| 降级纪律 | 校验失败只降级 / 拒绝，**不阻断聊天与主动链路**（沿世界旁路纪律） |

### 3.3 隔离与权限

- **生活域**（账本 / 治理）读写一律经 `user_id` 校验——**直接生效，不设开关**（§9 铁律 5）。
- **既有域（会话 / 记忆 / 世界 / 关系）保持现状行为**——本版不改变它们的隔离强度。
- 用户身份**只从既有身份机制解析**，绝不信任客户端传入的 `user_id`。

---

## 4. 账本域设计（Ledger Domain）

> 本版本的核心。**账本是一等结构化领域，不是记忆的一种类型。**

### 4.1 裁决依据：为什么账本不能是记忆

| 账目要求 | 记忆的机制（证据） | 结论 |
|---|---|---|
| 精确、不可篡改 | LLM 抽取，`content` 为自然语言 | 冲突 |
| **不可遗忘** | `salience · exp(-λ·Δdays)` 衰减 + `decayed` / `forgotten` 生命周期 | **冲突（会忘掉花过的钱）** |
| 无限增长 | 单用户 active **软上限 200**，超出 `capacity_drop` 丢弃（`privacy-governance.md` §2） | 冲突 |
| 可累加可对账 | 无 amount / currency / category 字段，无法 SQL 聚合 | 冲突 |
| 必须保存金额 | 目标策略 L2（含财务）「**不保存**」（`privacy-governance.md` §1.1） | **冲突（须重裁，§4.7）** |
| 订正留痕 | 冲突消解走 `superseded`（取代），无冲正语义 | 冲突 |

**因此**：账本域自建表、自带 append-only 纪律与冲正语义；账本条目**无衰减、无失效、无容量上限、无过期**——**与记忆相反，这是设计意图，不是遗漏**。

**记忆域唯一允许承接的**：抽象模式（如「高频外卖」），且**金额明细永不进记忆**（§6.4）。

### 4.2 三表模型

| 表 | 职责 | 关键字段 |
|---|---|---|
| `ledger_accounts` | 账户（现金 / 银行卡 / 电子钱包） | `id` / `user_id` / `name` / `type` / `currency` / `status` |
| `ledger_categories` | 类目树（含用户自定义与别名） | `id` / `user_id` / `parent_id` / `name` / `kind` / `aliases`(JSON) |
| `ledger_entries` | **账本条目（append-only）** | `id` / `user_id` / `account_id` / `category_id` / `amount_minor` / `currency` / `direction` / `occurred_at` / `merchant` / `note` / `source` / `source_ref` / `idempotency_key` / `reversal_of` / `created_at` |

> **命名避歧**：`ledger_*` 指**财务账本**，与审计语义 `services/domain_ledger.py` / `evolution.ledger()`（只读投影，无表）**严格区分**，实现时不得混用。

### 4.3 字段裁决

| 字段 | 裁决 | 理由 |
|---|---|---|
| `amount_minor` | **整数最小单位（分）**，禁用 float | 精度是账本的生命线；`0.1+0.2` 类错误会让账本失去可信度 |
| 货币出口 | `Decimal` / 格式化字符串 | 只在展现层转元 |
| `direction` | `expense` / `income` / `transfer` | 支持转账（不计入消费净额） |
| `occurred_at` | 绝对时间（相对时间由摄取层解析） | 「中午」→ 具体时点 |
| `source` / `source_ref` | 必填，可回溯原始消息 / 行动 / 手动录入 | 治理与审计（§4.7） |
| `idempotency_key` | **唯一约束** | 同一句话不能被记两次 |
| `reversal_of` | 冲正指向 | 纠错留痕（§4.4） |
| **禁止字段** | 任何 TTL / `expires_at` / 衰减 / 状态软化列 | 不可遗忘（§4.1） |

### 4.4 幂等与冲正

```
记账：create_entry(payload, idempotency_key)
   → 命中 idempotency_key → 返回既有条目（不报错、不重复写）
   → 未命中             → 落一条 append-only 条目

纠错：reverse_entry(entry_id, reason)
   → 生成一条反向条目（amount 取负 / direction 反向）+ reversal_of = 原条目 id
   → 原条目【不删、不改】——逐字节保留

净额：聚合时原条目与冲正条目双向计入 → 自然归零
```

**为什么不用 UPDATE**：账本是可对账的历史，不是可变状态。冲正保留「曾经记错」这一事实，符合财务语义与审计要求。

### 4.5 生命周期（与记忆对照）

| 维度 | 记忆（Memory 2.0） | 账本（Ledger） |
|---|---|---|
| 读时衰减 | 有（`exp(-λ·Δdays)`） | **无** |
| 容量上限 | 200 条 / 用户 | **无** |
| 状态机 | active / superseded / invalidated / decayed / forgotten | **无状态机**（append-only） |
| 删除 | 软删 → 物理删 | **仅冲正**；用户主动删除（治理面）才物理删 |
| 冲突 | LCS 同题检测 → supersede | **不复用**：靠 `idempotency_key` 去重 + 冲正纠错 |
| 进 Prompt | 注入 content + type | **永不进 Prompt**（仅聚合结果可进） |

### 4.6 零幻觉设计（直接源自 §1.4 的失败预演）

| 层 | 约束 |
|---|---|
| 抽取 | 金额必须可回溯到原文片段；缺失或低置信 → **转澄清，不猜** |
| 入账 | 写面只接受**结构化字段**，拒绝自由文本 |
| 聚合 | **纯 SQL 聚合，零 LLM** |
| 推送 | 日结 / 周报 / 预警**模板渲染**，数字只来自聚合（**严禁 LLM 生成数字**） |
| 展示 | 明细不注入 Prompt 上下文 |

### 4.7 治理重裁（记账的前置合法性条件）

`privacy-governance.md` §1.1 现行目标策略把财务数据列为 **L2 → 不保存**，与记账**直接冲突**，必须重裁：

| 项 | 现策略 | V4.0 重裁 |
|---|---|---|
| 财务数据分级 | L2 → 丢弃（trace 记 `privacy_drop`） | **降为 L1 受控保存**：本地存储 + 用户可控 + 可导出 / 删除 |
| 是否进 Prompt | 未规定 | **硬规则：明细永不进 Prompt**，仅聚合结果可进 |
| 溯源 | 未规定 | 每条带 `source` + `source_ref` |
| 用户权利 | 无通道 | 导出（JSON/CSV）+ 删除（含级联与审计旁路清理） |

> **作用域限定**：本次重裁**只作用于新增的账本域**与治理服务；记忆域 R1~R8 与敏感分级 R9 **不动**（Preserve）。该重裁属「策略结论更新」而非「史实改写」，是本版本**唯一允许修改历史文档**的例外，须在基线同步登记。

---

## 5. 摄取与行动接入（Ingest & Action）

### 5.1 抽取链

| 项 | 设计 |
|---|---|
| 落点 | `chains/ledger_extraction_chain.py`，**必须**走 `chains/structured.py::build_structured_chain`（主链 + 一层降级） |
| Schema | `models/ledger.py::LedgerExtraction`（金额 / 方向 / 类目候选 / 商户 / 发生时间 / 账户 / 置信度 / 缺失字段集） |
| Prompt | 落 `prompts/`（PromptBuilder），禁手工拼接 |
| 挂接 | post_process 步骤（**读取进链、写入出链**纪律；后处理失败不影响已产出回答） |
| 分流 | 置信度 < `ledger_extraction_min_confidence` 或金额缺失 → 标记「待澄清」，**不直接入账** |
| 时间 | 相对时间（"中午" / "昨晚"）按世界时间与本地时区解析为绝对时间 |
| 定位 | **只产候选**，入账必经能力层与确认层（§5.3 / §5.4） |

### 5.2 类目归一

| 项 | 设计 |
|---|---|
| 落点 | `character/<persona>/ledger_categories.py`（种子类目树 + 别名词表）+ `services/ledger/category.py`（归一服务） |
| 顺序 | **确定性优先**：精确匹配 → 别名 → 规则 → 兜底 `ledger_category_fallback` |
| LLM 角色 | **仅最后兜底**，且必须落到既有类目或标注「未归类」，**不得凭空新建类目** |
| 用户自定义 | 落 `ledger_categories`（可增类目与别名） |
| 难点登记 | 中文消费表述归一（"快餐 / 盖浇饭 / 外卖 / 烧烤" → 餐饮）是本版本最大不确定性，需样本集量化验收 |

### 5.3 能力与工具接入

| 项 | 设计 |
|---|---|
| 能力 | `services/action/capabilities/ledger.py`：`ledger.record` / `ledger.query` / `ledger.revise` |
| 工具注册 | `builtin.ledger.*`（走既有 `services/tool/` 注册，**启动期代码注册，非热插拔**） |
| 意图 | `services/action/detector.py` 增记账词表（**保持纯词表 + 正则、零 LLM 风格**） |
| 治理 | 写路径经 Tool **五段短路**（权限 → 确认 → 校验 → 归一 → 健康度） |
| 入参 | payload **必须结构化**（金额 / 币种 / 方向 / 类目引用），**拒绝自由文本** |
| 分界 | 能力**只执行不决策**；调度 / 重试 / 回复生成归引擎（ADR-10） |
| 可审计 | 每次记账在 `action_records` 有台账行 |

### 5.4 确认、订正与冲正

| 项 | 设计 |
|---|---|
| 需确认条件 | 缺金额 / 类目歧义 / 金额 > `ledger_confirm_threshold_amount` |
| 澄清 | 单次澄清（同 `source_ref` 不重复回问）；用户回话**复用 §5.1 抽取链**解析 |
| 待确认登记 | **复用 `scene_state.pending_action` + `action_schedules`，零新表** |
| 订正 | 修改 = 冲正 + 新增；删除 = 冲正 |
| 超时 | 超时未确认**不产生账目** |
| 审计 | 确认 / 订正 / 冲正全落审计 |

---

## 6. 主动性与洞察（Agency & Insight）

### 6.1 节律投递

- 落点：`services/ledger/digest.py`（模板化日结 / 周报）+ 挂 `life_loop` 维护步或 `trigger_registry` + 经既有 Outbound / `proactive_delivery` 投递。
- **数字只来自 §4.2 聚合**；遵守既有 quiet hours / cooldown / 每日上限；同周期幂等不重复推送。
- 参数：日结 / 周报的**发送时刻**（参数类，**非开关**；能力交付即生效，见 §9）。

### 6.2 预算

- 预算 = **Goal Stack 的领域视图**（复用 `character_goals` 的 `domain` / `layer`），**不建预算表**。
- 检查以 plan step 承载（只读消费 `services/planning/scheduler.py`）；`goal_contract.py` 扩展预算类失败理由。
- 写只经 `goal_repository` 计划单一写面；前台只读（长期化写只在后台，铁律既有）。

### 6.3 超支预警

- `services/ledger/alert.py` 阈值判定（类目 / 总额 / 日 / 月）+ `trigger_registry` 注册 + 经 Outbound 投递。
- 去重键 = 同预算 + 同周期（**只报一次**）；遵守 quiet hours；**数字来自聚合**。
- **顺序约束**：预警**必须晚于**节律稳定（先有可靠投递与聚合，再报警）。

### 6.4 洞察与记忆边界

| 允许进记忆 | 禁止进记忆 |
|---|---|
| 抽象模式（`behavior_pattern` 类，如「高频外卖」「夜间消费占比高」） | **任何金额明细** |
| 经 Reflection 既有证据窗与三闸 | 绕过三闸直达 `memories` |

- 候选受既有 200 条上限与衰减约束——**这是记忆该有的行为，不是缺陷**。
- Development 编译仍**唯 Evolution**（本版不动）。

---

## 7. 用户面（Surface）

### 7.1 API

| 端点 | 语义 |
|---|---|
| `GET /ledger/summary` | 周期聚合（月 / 周 / 自定义） |
| `GET /ledger/entries` | 条目查询（分页 / 过滤） |
| `POST /ledger/entries` | 手动记账 |
| `POST /ledger/entries/{id}/reverse` | 订正 / 撤销 |
| `GET /ledger/categories` | 类目树 |

- **分层纪律**：`api/v1/ledger.py` **零 import `repositories` / langchain**（聚合落 `services`）——这是对 V3.0 遗留 L3 的**不扩大**承诺。
- 越权红线：不得信任客户端传入的 `user_id`。

### 7.2 前端双模

- `apps/frontend/src/features/ledger/`（月视图 / 类目分布 / 条目列表 / 订正入口 / 空 / 加载 / 错误三态）。
- **既有 Debug Console 完整保留**（`components/debug/*`、`workbench.tsx`）——调试台是本项目独特资产，不因新增用户视图而删。

---

## 8. 数据架构

### 8.1 新增表与迁移

| 迁移 | 内容 | 表数 |
|---|---|---|
| `0053_life_user_identity.py` | `users` + `worlds.owner_type` / `worlds.owner_id` | `SCHEMA_TABLE_COUNT` 45 → 46 |
| `0054_life_ledger_domain.py` | `ledger_accounts` / `ledger_categories` / `ledger_entries` | 46 → **49** |

- 链尾：`0052` → `0054`；`down_revision` 严格单链。
- ⚠️ **迁移链头钉测**：`MIGRATION_HEAD` 常量散落在 **≥12 个测试文件**（实测：`tests/v25/` 11 个 + `tests/v24/tool012_support.py`），`SCHEMA_TABLE_COUNT = 45` 位于 `tests/v24/tool012_support.py:81`。FEISHU-010 加 `0050` 时 **22 个用例转红**（baseline §9 P1 债）。V4.0 要加 2 迁移 4 表，**必须先把这套钉测收敛为单点入口**（见 `tasks.md` PLA-001）。
- **口径提示**：`acceptance-report.md` G6 记「46 表」含 `alembic_version`；G5 记「45 表」为业务表口径。V4.0 统一按 **`SCHEMA_TABLE_COUNT` 业务表口径**（45 → 49）。

### 8.2 Source of Truth

| 真相源 | 承载 | 说明 |
|---|---|---|
| 用户 | `users` | 一等实体；`user_id` 的分区键权威 |
| 账目 | `ledger_entries` | **append-only 账本**，净额由聚合推导 |
| 账户 / 类目 | `ledger_accounts` / `ledger_categories` | 状态型（可 upsert） |
| 预算 | `character_goals`（经 `goal_repository`） | **不自建表** |
| 归属 | `worlds.owner_type` / `owner_id` | 世界与生活容器归属 |
| 待确认 | `scene_state.pending_action` / `action_schedules` | **不自建表** |

### 8.3 生命周期纪律

- **账本表**：append-only，只增不改（冲正补充新行）；**无 TTL / 无衰减 / 无上限**。
- **用户 / 账户 / 类目**：状态型，可 upsert，带 `updated_at`。
- **删除**：仅经治理服务（用户主动），且必须清理关联引用与审计旁路。

---

## 9. 配置架构（只许参数，不许开关）

### 9.1 核心裁决：V4.0 零新增功能开关

> **2026-09-22 追加裁决**：本版本**不新增任何功能门控 / 灰度总闸开关**。

**为什么**：

| 问题 | 说明 |
|---|---|
| 配置面膨胀 | 本项目已为「开关太多」付过一次代价：`vXX_` 版本门控体系整体删除（2026-09-19 收官），台账见 `docs/refactor/flag-removal-audit.md`。再加一批等于重走一遍。 |
| 双路径并存 | 每个功能开关都隐含「开」与「关」两条路径，两者都要维护正确性。V3.0 的 `runtime_*` 11+ 开关就是现成例子——**13 个里只有 2 个为 `True`**，其余 11 个的「关闭时等价」承诺成为长期测试负担。 |
| 测试承诺成本 | 本项目既有规范要求「Flag 关闭时行为与上一版逐字节一致」，这是一个**每开关 × 每任务**的断言矩阵，成本随组合增长。 |
| 掩盖而非解决风险 | 开关让「没想清楚能不能上」的问题被推迟到配置层，而不是在设计层解决。 |

**替代方案（回滚靠什么）**：

| 手段 | 说明 |
|---|---|
| **代码回滚** | 版本发布与回滚以代码为单位（本项目发布即 git 版本）。 |
| **迁移可逆** | `0053` / `0054` 必须可空跑、可回滚（G13）；新增列可空、默认兼容，回退不丢既有数据。 |
| **append-only 天然安全** | 账本只增不改——新功能上线只会**多写**条目，不会破坏既有账目语义。 |
| **端点隔离** | 新 API 为**新增端点**，不改既有响应契约；前端为**新增视图**，不动 Debug Console。 |
| **按阶段交付** | 用「能力顺序」而非「开关」控制上线节奏（见 `tasks.md` §4.2）。 |

### 9.2 允许新增的字段类型（白名单）

| 允许 | 例 |
|---|---|
| 阈值类 | `ledger_extraction_min_confidence`、`ledger_confirm_threshold_amount` |
| 取值 / 文案类 | `ledger_default_currency`、`ledger_category_fallback` |
| 周期 / 区间类 | 日结 / 周报的发送时刻 |
| 与既有模块一致的纯参数 | 预算区间、类目别名补充 |

### 9.3 禁止新增的字段形态（黑名单）

- 任何 `*_enabled` 形态的**功能位 / 灰度位**（如 `ledger_enabled`、`ledger_extraction_enabled`、`life_user_isolation_enabled`）。
- 任何以「版本号前缀」命名的字段（`vXX_`，既有禁令延续）。
- 任何用于「切换新旧两条路径」的开关。

### 9.4 领域模块与命名

| 项 | 设计 |
|---|---|
| 新增模块 | `core/settings/life.py`（个人生活域参数）+ `core/settings/ledger.py`（账务域参数）——领域模块数 **21 → 23** |
| 不改 | `pipeline.py`（`default_user` 保持原位） |
| 命名 | 无版本前缀；env 名 = 字段名大写；无 alias 层 |
| 改动既有开关 | **只允许两种情况**：① 把既有开关**置为唯一有效值**（如 PLA-018 把后台统一到 Agent Runtime）；② 把已转常开的开关**纳入 `flag-removal-audit.md` 台账**按既有批次流程清理。**不得新增**。 |
| 上线即生效 | 能力上线即生效，无「关闭态」需要维护——**DoD 以「零回归」替代「关闭时逐字节一致」**（见 `tasks.md` §6.2）。 |

---

## 10. 边界与不变量（铁律清单）

后续任何 Task 与实现必须逐条成立；违反任一条即回到架构评审。

1. **Runtime 只调度**：V4.0 不改 Agent Runtime 的循环语义、契约与状态机；新能力以 Profile 阶段 / 维护步 / 工具接入（§2.3）。
2. **账目不入记忆**：`ledger_entries` 与 `memories` / `memory_candidates` 之间**零数据流**（明细方向）。
3. **金额零 LLM**：金融数字只在抽取层「读取」，在聚合 / 推送 / 展示层**只来自结构化字段**。
4. **账本只增不改**：账本表零 `UPDATE`（纠错走冲正）。
5. **单一写面**：账本写只经 `ledger_repository`；预算只经 `goal_repository`；Run 只写 `loop_runs`。
6. **归属不混用**：角色世界与用户生活容器严格分离。
7. **治理先行**：财务数据分级重裁（§4.7）未通过评审前，不得落地账本表迁移。
8. **零新表承诺**：除 §8.1 的 4 张表外，**不新增任何表**（预算 / 待确认 / 洞察 / 快照全部复用既有承载）。
9. **不扩大既有违规**：新增 `api/v1/ledger.py` 必须零 `repositories` / langchain 依赖（V3.0 遗留 L3）。
10. **Preserve 零改动**：Memory / World / Relationship / Planning / Action / Tool / Reflection / Development / Decision / Goal / Agent Runtime 的语义与数学零差异（git diff 可证）。
11. **零新增功能开关**：V4.0 不新增任何功能门控 / 灰度开关（§0.2 铁律 5、§9）；能力上线即生效，回滚靠代码与迁移可逆性；既有开关只允许「置唯一有效值」或「按 `flag-removal-audit.md` 流程清理」，不得新增。
12. **零平行路径**：V4.0 落地后，前台与后台**共用同一调度轨道**（Agent Runtime Profile 阶段序列）；六段循环保持影子（裁决 R5），不得出现第三种编排路径。

---

## 11. 未来演进（非本版本）

| 方向 | 版本 | 说明 |
|---|---|---|
| 更多生活域（待办 / 日程 / 健康 / 物品） | V4.x | 复用节律 / 目标 / 抽取底座，逐域纵切 |
| 外部账单源接入（支付平台 / 银行） | V4.x | 依赖 `tool/ext_api.py` manifest + **用户授权体系**（未建，前置） |
| 语音 / 票据 OCR 记账 | V4.x | 补充摄取入口 |
| 多币种与汇率 | V4.x | 账本已单币种建模，扩展方向明确 |
| 用户自定义记账工具（DSL） | V4.x | 受 `ToolRegistry` 启动期注册限制，需先解决热插拔 |
| 多租户运营（配额 / 计费） | 未排期 | 依赖鉴权体系 |
| 六段认知循环真收编（方案 A） | 未排期 | 前置：C-2 e2e 安全网 + 等价性证明（§2.5） |
| Episodic / Semantic 记忆双通道 | **V3.1（已预留）** | v3.0.0 tasks.md §7.3 |
| 循环内嵌持续反思 | **V3.2（已预留）** | 同上 |
| Self Improvement 闭环深化 | **V3.3（已预留）** | 同上 |

---

## 附 A：实现期裁决登记

> 实现过程中若出现与本文档不符的裁决，须登记在此，并同步更新 §10 边界不变量。

| # | 裁决 | 涉及面 | 理由 | 登记日期 |
|---|---|---|---|---|
| I-1 | **PLA-018 §7.3「`tests/v30` 零修改通过」不可满足**：`tests/v30/test_runtime_autonomous_loop.py` 的 `test_flag_defaults_off` 断言「开关默认 `False`」、`test_flag_off_uses_legacy_path` 断言「关闭走 legacy」——二者断言的正是本任务**废止的语义**，与交付面逻辑互斥。**裁决：做语义同步的 3 处最小修改**，而非保留失效用例或放宽 AC 口径 | `tests/v30/test_runtime_autonomous_loop.py` | 断言对象已被架构裁决（R4 后台收编）废止，保留会变成「绿灯但无意义」的用例。修改属**语义同步**而非为通过而放宽：新断言更强（验证「不可由配置触达」，原用例无此保证） | 2026-09-22 |
| I-2 | **legacy 回退位保留但零模块级调用点**：收敛后 `_legacy_run_autonomous_cycle` / `legacy_cycle_runnable` 无任何模块级调用者，仅 `tests/v30/test_runtime_lifecycle.py` 显式直调 | `controller.py` | 任务 D3 要求「给紧急回滚留手工手段，同时不让它成为可配置的第三条路径」。代价：留下一个**有意保留的无调用点函数**，靠 docstring + 文档登记防止被后续误当死代码清理 | 2026-09-22 |
| I-3 | **任务书笔误登记**：`PLA-018.md` §7.3 回归命令写作 `tests/v21 tests/v7 tests/v22`，实际不存在 `tests/v7`（正确为 `tests/v7.8`） | 本任务文档 | 执行期实测发现；不回溯改任务书正文，在此登记 | 2026-09-22 |

## 附 B：与需求评审文档的差异登记

| # | 评审文档原意见 | 本文档裁决 | 理由 |
|---|---|---|---|
| D-1 | Phase C（抽取）排在 Phase D（主动服务）之前 | **保持不变，但允许 D 的节律任务与 C 部分并行** | 评审建议的最短路径为 A→B→D；节律只依赖聚合（B），不依赖抽取（C），故 D 可提前 |
| D-2 | 「Phase A 第 3 项：明确世界归属」 | 提升为**独立任务 PLA-002**，且与 PLA-004 并行 | 归属是架构级裁决，不宜混在身份任务里 |
| D-3 | 评审未涉及运行时选型 | **新增 §2 运行时采用裁决 + PLA-018** | 审计发现 V3.0「测试态已收编、生产态未收编」，若不裁决会出现三套路径 |
| D-4 | 评审建议先不做界面（MVP 用飞书） | 采纳：PLA-016 为 P2 且依赖 PLA-015 | 避免「先做漂亮界面的假数据」 |

## 附 D：决策变更登记（架构裁决追加）

> 记录本文档定稿后追加的架构级决策及其影响面。每一项都须回写 `tasks.md` 与 §10 边界不变量。

| # | 决策 | 日期 | 来源 | 影响面 |
|---|---|---|---|---|
| **C-1** | **禁止新增功能开关阀门**：V4.0 零新增功能门控 / 灰度开关；仅允许参数类字段（阈值 / 取值 / 周期）；既有开关只允许「置唯一有效值」或按 `flag-removal-audit.md` 流程清理 | 2026-09-22 | 用户指令 | ① §0.2 铁律 4 条 → **5 条**（新增铁律 5）；② §0.3 Non-Goals 增列；③ **§9 配置架构整节重写**（原「13 个灰度位 / 策略位字段」全部作废，改为白名单 + 黑名单 + 替代回滚方案）；④ §10 不变量 10 条 → **12 条**（新增 11 零新增功能开关、12 零平行路径）；⑤ `tasks.md` §0.4 设置项裁决重写、新增 §0.9 裁决 9、§4.2 灰度顺序改为「能力交付顺序」、§6.2 DoD 第 2 条改写、各 Task Scope 中 9 个功能开关字段移除、Gate G12 口径调整 |
| **C-2** | 后台自治统一到 Agent Runtime：`runtime_autonomous_cycle_enabled` **置为唯一有效值（True）**，legacy 分支降级为非默认；**不新增开关**；该字段与 `runtime_foreground_loop_enabled` 一并登记进 `flag-removal-audit.md` 待后续清理 | 2026-09-22 | 审计 §5 + C-1 连带 | `tasks.md` PLA-018 重写为「统一而非切换」；`runtime_six_stage_loop_enabled` 保持既有 `False`（六段继续影子） |

### C-1 被移除的功能开关清单（原 `tasks.md` §0.4）

以下 9 个原计划的 `*_enabled` 字段**全部作废**，对应能力改为直接交付：

| 原字段 | 处置 |
|---|---|
| `life_user_isolation_enabled` | 删除 → 用户隔离**直接生效** |
| `life_ownership_enforced` | 删除 → 归属校验**直接生效** |
| `life_data_export_enabled` | 删除 → 导出端点直接提供 |
| `life_data_delete_enabled` | 删除 → 删除端点直接提供 |
| `ledger_enabled` | 删除 → 账本域随迁移直接可用 |
| `ledger_extraction_enabled` | 删除 → 抽取链随 PLA-007 交付即生效 |
| `ledger_digest_daily_enabled` | 删除 → 日结随 PLA-011 交付即生效 |
| `ledger_digest_weekly_enabled` | 删除 → 周报随 PLA-011 交付即生效 |
| `ledger_overspend_alert_enabled` | 删除 → 预警随 PLA-013 交付即生效 |

**保留的参数类字段（4 个，非开关）**：`ledger_extraction_min_confidence`、`ledger_confirm_threshold_amount`、`ledger_default_currency`、`ledger_category_fallback`（外加日结 / 周报的**发送时刻**参数）。

## 附 C：非目标与红线复述

- 不引入 MQ / Redis / Event Sourcing / 分布式锁。
- 不引入 LangGraph / CrewAI / AutoGen 等第三方编排框架。
- 不新增常驻循环。
- 不改 ChannelAdapter 契约。
- **不新增功能开关 / 灰度门控 / 版本开关**（铁律 5、§9、不变量 11）。

---

> **文档结束**。本文档为 V4.0 的架构依据；任何超出本文档的变更须**先更新本文档与 `docs/current-system-architecture-baseline.md`**，再进入任务与实现（对齐项目纪律：架构演进先改基线）。
