# 架构评审：本系统距「Personal Life Agent」还有多远

> **文档位置**：`docs/version/v4.0.0/reviews/`（V4.0.0 需求侧评审文档；**已于 2026-09-22 归入 V4.0.0 版本目录**，原位于 `docs/` 根目录）
> **文档角色**：V4.0.0 的**需求来源**。架构侧依据见 `../architecture.md`，运行时采用裁决见 `../audits/v3.0.0-runtime-adoption-audit.md`，任务拆分见 `../tasks.md`。
> **评审对象**：`F:\aICustomerAgent`（角色对话 Agent / 亚丝娜）
> **评审基准**：`docs/current-system-architecture-baseline.md`（2026-09-20）+ V3.0.0 Agent Runtime（2026-09-22）+ 当前代码实测
> **评审性质**：系统级架构评审，**不涉及代码修改**。结论基于代码与迁移链的实证核查，非文档转述。
> **评审日期**：2026-09-22

---

## 0. 结论摘要

**一句话结论**：
> 这个系统已经有了一副完整的「大脑」和一套讲究的「骨架」，但**没有「主人」，也没有「账本」**——而个人生活 Agent 恰恰是建立在这两样东西之上的。

用一句话概括差距：**当前系统的主体是「角色」，个人生活 Agent 的主体必须是「用户」。这不是加功能，是翻转主体。**

| 判断 | 结论 |
|---|---|
| 能否直接演进为个人生活 Agent？ | **可以，且起点很高**——但必须先补两块地基，否则后面全是沙上建塔 |
| 已有的最大资产 | Agent Runtime（Profile 注册表）+ Tool System（执行五段）+ Action/Goal/Memory/Reflection 全套器官 |
| 最致命的缺口 | ① 无用户实体（单用户硬编码）② 无用户结构化领域数据底座（无账本） |
| 「记账」这个需求能不能做？ | 能做，而且**同构问题项目里已经解过一次**（World 家居库存），但当前**必须先建 Ledger 域**，绝不能塞进 memory |
| 预估工作量 | 地基（Phase A/B）约占 60%——功能层（C/D/E）反而简单，因为器官都在 |
| 最大风险 | 用「记忆 + Prompt」冒充「账本」，重演 `household-inventory-review.md` 里已经证伪过的错误 |

---

## 1. 评审基准：什么才算一个「个人生活 Agent」

先把标准立清楚，否则「像不像管家」会变成感觉之争。一个真正的个人生活 Agent 需要五层能力：

| 层 | 含义 | 记账场景对应 |
|---|---|---|
| **① 主体（Owner）** | 系统知道"这是谁的生活"，数据属于谁、如何隔离 | 这是**我**的账本，不是亚丝娜的 |
| **② 账本（Ledger）** | 面向用户的结构化领域事实，精确、可累加、可对账 | 交易：金额/币种/类别/商户/时间 |
| **③ 抽取（Ingest）** | 自然语言 → 结构化事实，含置信度与澄清 | "中午20块快餐" → 一条 entry |
| **④ 主动性（Agency）** | 会主动：提醒、汇总、洞察、预警 | 日结/周报/超支预警 |
| **⑤ 界面（Surface）** | 用户能查、能改、能看趋势 | "这个月餐饮花了多少" |

另外还有一条贯穿性的**⑥ 信任与治理**：隐私分级、可纠错、可溯源、LLM 不得凭空生成数字。

下面按这六条逐一对照。

---

## 2. 已有资产盘点（不该重造的东西）

这是本次评审最想强调的部分。**大量个人生活 Agent 需要的能力，这个项目已经建成了**，且工程质量与纪律在同类项目中属于上乘。

| 资产 | 位置 | 为什么这对个人生活 Agent 至关重要 |
|---|---|---|
| **Agent Runtime / Profile 注册表** | `application/agent_runtime/profiles.py`（阶段序列唯一声明处） | 新增「记账」等能力**不需要第二套管线**，注册新阶段/新 Profile 即可。这条铁律（`architecture.md` ADR-7）是整个项目最值钱的架构约束 |
| **Tool System 执行五段** | `services/tool/executor.py`（权限→确认→校验→归一→健康度） | 「确认」段天生适配记账（金额不确定时回问用户）；「健康度+熔断」适配外部支付网关的不稳定 |
| **External API 声明式清单** | `services/tool/ext_api.py:962 ToolManifestLoader`，配置 `core/settings/tool.py:29 tool_ext_manifest_path` | 这是**接入账单类外部数据源的现成插槽**：写一个 YAML manifest 就能生成 `ext.api.*` 工具，含域名白名单（`:30`）与八项校验（`:148`） |
| **Action Engine + 行动台账** | `application/action_engine.py`、`action_records` 表（状态机 + 幂等键） | 每一次「记账」都是一条可审计的行动记录，天然满足财务数据的可追溯要求 |
| **Goal Stack + Planning 七道闸** | `services/planning/engine.py`、`character_goals`/`goal_plans` | 「本月餐饮预算 1500」就是一个 goal，「每日检查」就是一个 plan。**预算管理的能力骨架已经存在** |
| **World 对象状态机** | `models/world.py::WorldObject` + `OBJECT_STATE_MACHINES`（含 consume 挪移/扣减） | 家居库存的扣减，与「账户余额的扣减」是**同构问题**——项目已经解过一次 |
| **Memory2 四源摄取 + 幂等候选** | `services/memory2/ingest.py:115`（`memory_candidates` 唯一约束幂等） | 抽取管道的**工程范式**（候选→评估→转正）可直接复刻为"记账候选→确认→入账" |
| **Reflection → Development** | `services/reflection/`、`services/development/`、`memory2/types.py:9` 中已有 `behavior_pattern` | 「消费习惯洞察」正是 Insight → pattern 的自然应用场景，**不需要新概念** |
| **Autonomy + 主动投递 + 通道** | `proactive_actions`、`trigger_registry`、Feishu `delivery.py`、quiet hours/cooldown | 日结、周报、超支预警的**投递链路已通到真实用户**（飞书已真实链路验证） |
| **审计与可回放** | `decision_records`、`loop_runs`、`runtime_traces`、relationship 的「账本+状态+快照」三件套 | **关系域的三件套模式可直接照搬给账本域**——这是被验证过的最佳实践 |

> **评审意见**：以上资产的存在意味着，个人生活 Agent 的**「手脚」和「作息」几乎不用新建**。这是这个项目最大的红利，也是它比从零开始的团队快得多的原因。

---

## 3. 五个结构性缺口

### 缺口 1（P0）：没有「主人」——主体错位

**证据：**

| 事实 | 位置 |
|---|---|
| 单用户硬编码 | `core/settings/pipeline.py:30` → `default_user: str = "default-user"` |
| user_id 是**外部传入的裸字符串** | `api/v1/world.py:79` `return user_id or get_settings().default_user`；`state.py:55`、`proactive.py:18`、`history.py:50` 同款 `Query(default=...)` |
| `user_id` **无外键、无 users 表** | `core/db.py:35` `Conversation.user_id: Mapped[str]` |
| 唯一的多用户线索 | `core/db.py:1302` `channel_identities`（channel + external_id → internal_user_id）——仅为飞书身份映射 |

**更深的错位：世界建模的是「角色的生活」，不是「用户的生活」。**

| 事实 | 位置 |
|---|---|
| 作息模板是**亚丝娜的** | `character/asuna/routine.py:12` `ROUTINE_TEMPLATES`（做早餐/工作学习/下午茶） |
| 日计划由角色作息驱动 | `services/world/daily_plan.py:125` `build_daily_plan`（asuna routine + 用户影响） |
| 世界的定义 | `character/asuna/world.py:12` `"description": "你和亚丝娜的家"` |
| 用户的处境只是**角色视角下的扁平标签** | `services/world/user_situation.py:3` 「处境是世界域事实（**角色视角下用户属于世界**）」；`:43-79` `SITUATION_PATTERNS` 仅 health/work/travel/emotional 五维，**无消费/账目维度** |

**影响：**
- 无法多用户，无法数据隔离——个人生活 Agent 的第一性要求不满足；
- 更根本的是：现在问「用户今天过得怎么样」，系统答的是「亚丝娜今天做了什么」。**主体是角色。**
- 记账场景下，这一点会立刻暴露：账目的 owner 必须是用户，而当前世界里没有「用户的生活」这个容器。

**好消息**：`user_id` 已经是贯穿全链的裸字符串（而非硬编码常量），这意味着补用户实体主要是**加约束与隔离规则**，而不是大规模重构。

---

### 缺口 2（P0）：没有「账本」——用户结构化领域数据底座缺失

**证据：**

| 事实 | 位置 |
|---|---|
| 全部 ORM 44 表**无任何**财务/交易/资产/账单表 | `core/db.py`（Conversation/Memory/World/Relationship/Goal/Action/Run/Observability 各域）；迁移链 `0001~0052` 无对应迁移 |
| 唯一的 "ledger" 是审计语义 | `services/domain_ledger.py:1` 「多域审计账本」——与金钱无关 |
| 记忆类型是扁平 7 类，且**无任何金额/数量字段** | `services/memory2/types.py:9` `V2_MEMORY_TYPES`；`core/db.py:144` `memories.type` |
| 用户信息只落文本记忆 | `memories` / `memory_candidates`（content 为纯文本，≤50 字） |

**为什么「记忆不能当账本」——这是本次评审最关键的技术判断：**

| 账目必须满足 | 当前记忆的机制 | 是否兼容 |
|---|---|---|
| 精确，不可篡改 | LLM 抽取，content 是自然语言 | ❌ |
| 不可遗忘 | `salience · exp(-λ·Δdays)` 衰减 + `decayed`/`forgotten` 生命周期 | ❌ **会忘掉你花过的钱** |
| 可累加、可对账 | 无 amount/currency/category 字段，无法做 SQL 聚合 | ❌ |
| 无限增长 | 单用户 active **软上限 200 条**，超出走 `capacity_drop` 丢弃 | ❌ |
| 必须保存金额 | `privacy-governance.md:13` 明确 **L2 敏感（含财务数据）→「不保存」** | ❌ **策略直接冲突** |
| 可被取代 | LCS 同题检测冲突消解 → `superseded` | ❌ 被取代的账目不叫账目 |

**结论**：记账必须是**一等的结构化领域（Ledger Domain）**，不是记忆的一种类型。这条判断如果不守住，后面所有努力都会返工。

**项目自己已经给出了反例证据**：`docs/household-inventory-review.md` 记录了一次真实对话——库存里有 6 个鸡蛋，角色却说「没了，刚才那枚刚好用完」；凭空出现了不存在的番茄汤。结论原文：

> 「毛病不是 LLM 演技问题，而是系统级『世界事实账目』与『角色叙事』脱节导致的。」
> 「即使给了『以清单为准』的引导语，LLM 仍编造。说明需要**系统侧强制**，而非只依赖提示。」

**把「鸡蛋」换成「钱」，这就是记账功能上线后必然出现的故障。** 这个报告等于提前替我们做完了记账功能的失败预演。

---

### 缺口 3（P0）：抽取是「文本管道」，不是「事实管道」

**证据：**

| 事实 | 位置 |
|---|---|
| 行动意图检测是**纯词表 + 正则、零 LLM** | `services/action/detector.py:1`；调用点 `application/chat_pipeline.py:682` |
| action_type 枚举**无任何记账类** | `character/asuna/action.py:22`（create_reminder / move_object / use_object …） |
| 记忆抽取输出是**纯文本 + 类型** | `chains/extractor_chain.py:7` `build_extraction_chain` → `models/memory.py:69 MemoryExtraction`（仅 content 字符串 + type） |
| 唯一带结构化输出的是用户处境 | `services/world/user_situation.py:218 llm_assist_detect`（输出仍是 dimension/summary/intensity） |

**实际后果（以你的例子说明）：**

> 用户说：「中午吃了 20 块快餐」

这句话走完今天的所有链路后，系统里的产物是：**一条 content ≈「用户中午吃了快餐」的文本记忆候选**。

**数字 20 在整个系统里没有任何位置可以落。** 没有 amount 字段，没有币种，没有类别，没有可聚合的数值。这不是配置问题，是**数据结构层面无处安放**。

**缺的是四样东西：**
1. **Schema-first 的抽取链**：为每个生活域定义结构化 Schema（账目/待办/健康），走既有 `chains/structured.py::build_structured_chain`；
2. **置信度 + 澄清回问**：金额/类别模糊时主动确认（可复用 Tool 五段的「确认」段）；
3. **幂等去重**：同一笔消费不能被记两次（可复刻 `memory_candidates` 的唯一约束幂等范式）；
4. **用户可纠正**：记错了必须能改——账本需要「冲正」语义，而非记忆的 `superseded`。

**好消息**：这个机制的**同构实现已经在项目里**——`services/world/interpreter.py` 做的就是「用户消息 → 世界状态迁移解释」。把它平移成「用户消息 → 账目条目」在架构上是同一件事。

---

### 缺口 4（P1）：没有面向用户的「面」

**证据：**

| 事实 | 位置 |
|---|---|
| API 路由几乎全是调试端点 | `api/v1/router.py` → chat / **debug** / feishu / action / state / history / llm / proactive / world；`debug.py` 下有 `/debug/tools`、`/debug/memories`、`/debug/decisions` 等 |
| 仅有的读接口是只读调试视图 | `history.py:48` `GET /memories`；`state.py:53` `GET /state` |
| **无任何聚合/报表服务** | `services/development/aggregate.py` 是角色成长聚合；`services/observability/metrics_aggregator.py` 是系统指标——均非用户数据 |
| 前端是**开发者调试台** | `apps/frontend/src/components/debug/*`（overview/state/memory/trace panel）；`components/shell/workbench.tsx:5` 挂 `DebugPane`；`App.tsx:27` 主路由即 `<Workbench/>` |

**影响**：记账功能如果用户不能查、不能改、不能看趋势，它就是个黑盒，用户不会用第二次。**个人管家类产品的竞争力一半在「面」上**，而这部分目前是零。

**但注意顺序**：先有数据和正确的账本，再有面。反过来做会得到一堆假数据的漂亮界面。

---

### 缺口 5（P1）：信任与治理还未就绪

| 缺口 | 证据/现状 |
|---|---|
| 隐私分级**未实现**，且策略与记账冲突 | `privacy-governance.md` §1：L2（含财务数据）目标策略为「不保存」，标注"未实现"；L3 需显式指令 |
| 无数据导出/删除（被遗忘权） | 全库无相应 API；`privacy.md` 提到「不自动删除用户记忆」原则，但无用户自助通道 |
| **LLM 幻觉无系统侧强制约束** | `household-inventory-review.md` §2①：仅靠 prompt 约束，LLM 仍编造库存事实 |

**记账场景的映射**：LLM 编造「鸡蛋没了」= LLM 编造「你这个月花了 3000」（实际 2000）。**财务数据上，这类错误是不可接受的**，而项目已经用真实对话证明了"Prompt 挡不住"。

**结论**：账本类数据的读写必须**绕过 LLM 生成、走结构化查询**——金额只能来自结构化字段，不能来自模型复述。

---

## 4. 距离量化：六维评分

| 维度 | 现状 | 距离个人生活 Agent | 说明 |
|---|---|---|---|
| ① 主体（Owner） | ██░░░░░░░░ 2/10 | **最远** | 单用户硬编码；世界归属是角色 |
| ② 账本（Ledger） | ░░░░░░░░░░ 0/10 | **完全空白** | 无任何用户结构化领域表 |
| ③ 抽取（Ingest） | ███░░░░░░░ 3/10 | 管道在，Schema 缺 | 有意图检测/抽取管道，无结构化事实 Schema |
| ④ 主动性（Agency） | ████████░░ 8/10 | **接近可用** | Autonomy/Goal/Planning/主动投递/安静时段齐全 |
| ⑤ 界面（Surface） | █░░░░░░░░░ 1/10 | 近乎空白 | 仅调试控制台 |
| ⑥ 信任治理 | ██░░░░░░░░ 2/10 | 有文档无实现 | 分级未实现，且与记账冲突 |
| **（参考）运行时内核** | █████████░ 9/10 | **世界级** | Agent Runtime / Profile / Tool / Action / Memory 全套 |

> **读法**：这个系统是「双腿发达、大脑发达，但没有躯干」。④ 和运行时内核已经超出大多数同类项目，而 ①② 是空的。

---

## 5. 演进路径建议

**总原则**：不新建第二套 Agent，不违反既有铁律（分层单向依赖、单一写面、写入出链、Profile 唯一声明）。

### Phase A — 地基：把「主人」立起来（P0，必须最先做）

1. **引入 `users` 表**，把 `user_id` 从裸字符串升格为带外键的一等实体（当前全链已贯穿 `user_id`，改动面可控）。
2. **重新裁决财务数据的隐私策略**：`privacy-governance.md` 中 L2「不保存财务数据」必须改写——记账要存金额。建议改为「**本地存储 + 用户可控 + 加密 + 不注入 Prompt**」，而非丢弃。
3. **明确世界归属**：让世界支持 `owner_type`（角色 / 用户），或为用户的「生活」新建独立容器。**这一步决定后续所有生活域的归属，不能拖。**

### Phase B — Ledger 域：把「账本」立起来（P0）

**照搬 Relationship 域已经验证过的三件套模式**（这是项目内最佳实践，不要另创）：

| Relationship 的做法 | Ledger 的对应 |
|---|---|
| `relationship_events`（append-only 账本，时序权威） | `ledger_entries`（append-only，**幂等键**，含 amount/currency/category/merchant/occurred_at/account_id/source） |
| `relationship_state`（当前态，强一致 upsert，version 乐观锁） | `ledger_accounts`（余额、预算），可选 |
| `relationship_snapshots`（版本化快照，逐字节可重放） | 月度快照，支持对账与重放 |

**纪律照旧**：`repositories/` 唯一写面；账本只增不改，**纠错走冲正（reversal）而非修改**。

**另外需要**：`ledger_categories`（类目体系）。注意这里有个真实难点——**中文消费表述的类目归一**（"快餐"/"盖浇饭"/"外卖"→餐饮），这是需要产品化打磨的地方，不能只靠 LLM 随手分类。

### Phase C — 抽取与确认（P1）

1. 新增 `ledger_extraction_chain`（走 `chains/structured.py`，禁止自由解析）。
2. 新增 capability `ledger.record`（走 Capability/Tool 五段执行，复用「确认」段做金额澄清）。
3. 抽取结果落「候选 → 确认 → 入账」，复刻 `memory_candidates` 的幂等范式。
4. **支持撤销与修改**：这是账本区别于记忆的核心产品体验。

### Phase D — 主动性与洞察（P1，收益最快）

器官全在，**这是投产比最高的一相**：
- **日结/周报**：复用 `proactive_actions` + Feishu `delivery`；
- **超支预警**：复用 `trigger_registry` + quiet hours/cooldown；
- **预算目标**：复用 Goal Stack + Planning 七道闸（"本月餐饮 1500"）；
- **消费习惯洞察**：复用 `reflection` Insight → `development` 的 `behavior_pattern`。

### Phase E — 用户面（P2）

- 新增**聚合查询 API**（聚合逻辑落 `services/`，`api/v1` 只做表现——遵守既有分层），如 `GET /ledger/summary?period=month`；
- 前端从「调试控制台」升级为**双模**：保留 Debug 面板（这是项目的独特资产，别删）+ 新增用户视图。

### Phase F — 横向扩展其他生活域（按需）

| 生活域 | 可复用 |
|---|---|
| 待办/日程 | `action_schedules` + `reminder` 能力（已存在） |
| 物品/采购 | `world_entities` + 对象状态机（已存在，注意归属翻转） |
| 健康/作息 | `user_situations` 已有 health 维度 |
| 订阅/账单到期 | External API manifest（已存在插槽） |

---

## 6. 建议不要做的事（避坑清单）

1. **不要把账目塞进 memory**——它会衰减、会被取代、会被 200 条上限丢弃、会被隐私策略拒收。
2. **不要为记账另开第二套 Agent Pipeline**——违反 ADR-7（Profile 唯一声明）与「无第二套 Agent」铁律。
3. **不要试图用 Prompt 解决准确性**——`household-inventory-review.md` 已经用真实对话证伪。金额必须来自结构化字段。
4. **不要先做 UI 再做数据**——会得到漂亮的假数据界面。
5. **不要急着做「用户自定义记账工具」**——`services/tool/registry.py:3-9` 是**启动期代码注册、运行期不增删**，`services/tool/user_defined.py:17` 的自定义工具是**进程内存态、重启丢失**。先做内置 `ledger` capability 更稳。
6. **注意加新表的摩擦成本**：`docs/current-system-architecture-baseline.md` §9 P1 技术债——**迁移链头钉测散落在 15 个测试文件**（FEISHU-010 加 `0050` 时实测 22 个用例由绿转红）。账本域要加多张表，**建议先还这笔债**，否则每加一张表都疼。

### 附：需要留意的两个架构现状

- **V3.0.0 的六段认知循环目前是「影子实现」**：`docs/version/v3.0.0/architecture.md` 附登记 D-1 明确——默认在跑的是 `profiles.py` 的 **Profile 阶段序列**，六段方法（observe/reason/plan/act/reflect/update）**未接入生产 `run()`**，受 `runtime_six_stage_loop_enabled` 门控。**这对个人生活 Agent 影响不大**（Agent 的「聪明」来自数据正确性而非循环形态），但评审时不应把六段循环当作已具备的能力。文档在这点上诚实，值得肯定。
- **`services/agent_service.py` 是兼容壳**（P2 技术债）：编排已迁 `chat_pipeline`，壳仍保留供 api/测试依赖。新同学易误入旧路径，接入新域时注意别顺着壳走。

---

## 7. 最终判断

> 这是一个**架构纪律远高于同类项目**的系统：有唯一架构基线、有 ADR、有单一写面纪律、有 Profile 唯一声明、有真实链路验证、有意义明确的代码审查报告。这些是「能做大事」的信号。

> 但它目前是一台**精密的「角色生命模拟器」**，而个人生活 Agent 是**「用户生活操作系统」**。两者共享大量基础设施（这正是红利），却有两个根本不同的前提：**谁的生活**（主体），和**什么算事实**（账本）。

> **好消息是：这两块地基都不是技术难题，而是决策难题。** 尤其是隐私策略的重新裁决和世界归属的定义——它们需要的是一次明确的产品判断，而不是几个月的工程量。做完 Phase A/B，剩下的 C/D/E 因为器官俱全，反而会推得很快。

> **给你的具体建议**：如果目标是「记账」这个 MVP，最短路径是 **Phase A（users + 隐私重裁）→ Phase B（ledger 三件套）→ Phase D（日结/周报，投递链路现成）**，先不做界面（用飞书对话 + 日结推送），跑通后再补 Phase C 的抽取精度和 Phase E 的界面。这样大约用最小工程量，就能得到一个**真实可用**的记账管家——而且它天然带着一个别人没有的东西：**它会用亚丝娜的口吻跟你说话**。「管钱」+「有人味」的组合，是这个项目真正的差异化优势。

---

> **文档结束**。本评审为只读架构评审，未修改任何代码、迁移或既有文档。
