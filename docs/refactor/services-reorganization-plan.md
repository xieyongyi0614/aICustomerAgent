# services 目录归类规划（顶层散落模块归位 + 引擎收口 + 三类架构债）

> **审查对象**：`apps/backend/app/services/`（217 个 `.py` / 47108 行）—— 重点为 49 个顶层散落单文件模块、7 个单文件子包、`governance/` 整包
> **审查范围**：仅 `apps/backend/app/`；`docs/` 按约定不纳入改动面
> **本文数据**：均为**实测**（`ls` / `wc -l` / 全仓 `grep` 调用点核对 / 逐文件 Read 头部 + import 段 / Tarjan 强连通分量检测），非估算；口径已在各表标注
> **权威依据**：`docs/current-system-architecture-baseline.md` §2.2（分层职责与依赖方向）、`docs/version/v1.0.0/backend-refactor/target-architecture.md` §2/§3（`engines/` 目标态与 engines 依赖规则）、`apps/backend/AGENTS.md` §架构约束
> **状态**：**规划文档，不含任何代码改动**。执行前置 = 更新架构基线（`AGENTS.md` 硬规定：「任何架构演进须先更新该基线再进入开发」）
> **已裁决**：组织轴 = 领域优先 + 引擎收口；命名 = 统一去后缀；本次交付 = 只出文档
> **编写日期**：2026-09-30

---

## 一、执行摘要

### 1.1 结论

`services/` 的问题**不是「缺目录」，而是「有目录但一半文件没进去」**：

- 已经存在 **20 个领域子包**（`memory/` `world/` `action/` `planning/` `reflection/` `tool/` …），方向是对的；
- 但**同时有 49 个顶层散落单文件模块**，其中大量是「本领域已有子包、文件却留在顶层」——`relationship_*` 9 个、`goal_*` 7 个、评估族 5 个最为典型；
- 命名后缀混用 6 种以上（`_service` / `_engine` / `_policy` / `_bridge` / `_manager` / 裸名），而兄弟目录 `chains/*_chain.py`、`repositories/*_repository.py`、`models/<domain>.py` 是**单一后缀 + 扁平**，风格高度统一；
- `services/__init__.py` 是 **0 字节空文件**（无门面），导致外部 **1333 处** `app.services.*` import 全部走深层路径，任一文件移动都会逐个断链。

**因此本次不做「推倒重来」，只做两件事**：把散落的同域文件**收进已有/新建的领域包**；把无 IO 的纯函数模块**收口到 `engines/`**（兑现 `target-architecture.md` 里画了但从未落地的目标态）。

### 1.2 现状实测

| 指标 | 数值 | 口径 |
|---|---|---|
| `.py` 文件总数 | **217** / 47108 行 | `services/**/*.py` |
| 子包（有 `__init__.py`） | **20** | — |
| **顶层散落单文件模块** | **49** | `ls -1 *.py` 得 50，含空 `__init__.py` |
| 无 `__init__.py` 的命名空间目录 | **3** | `analytics/`、`tasks/`、`tool/manifests/` |
| `services/__init__.py` | **0 字节** | 无门面、无重导出 |
| 外部 `app.services.*` import | **1333 处** | 其中 **496 处** 为 ≥3 段深路径 |
| `services → application` 反向依赖 | **35 处 / 26 文件**（文件级 grep 命中 28） | 与文档单向依赖链冲突 |
| 导入期循环依赖 | **0** | Tarjan SCC 无 >1 分量；3 组双向依赖靠函数内延迟 import 化解 |

### 1.3 四个核心病灶

| # | 病灶 | 证据 |
|---|---|---|
| 1 | **同域文件既进子包又散顶层** | relationship 9 个、goal 7 个、evaluation 5 个全在顶层 |
| 2 | **命名后缀混用 6 种以上** | `_service`(13) / `_engine`(3) / `_policy`(6) / `_bridge`(5) / `_manager`(1) / 裸名；对照 `chains/` `repositories/` 单一后缀 |
| 3 | **单文件子包 / 超碎包** | `analytics/`(1) `tasks/`(1) `life/`(1) `insights/`(1) `briefing/`(1) `email/`(1) `grounding/`(1)；`governance/` 6 文件全部 25–42 行 |
| 4 | **无门面 → 移动成本高** | `services/__init__.py` 为空，1333 处外部 import 全为深层路径 |

**文档层面**：**没有任何成文规定**要求 services 如何组织（`target-architecture.md:22` 只说「保持现有文件」）。唯一成文的拆分指示是 §2:25 的 `engines/`（点名 `state_engine` / `memory_policy` / `memory_conflict`）与 §3:41 的 engines 依赖规则（允许 `models` / `core.settings` / `core.constants`，禁止 `repositories` / `chains` / `IO`）——**该目录从未创建**。

---

## 二、归类原则

1. **领域优先**：以业务领域为包边界（`goal/` `relationship/` `conversation/` `evaluation/` …）。一个域内的读写、策略、编排、桥接全部收进同一包，不再散在顶层。
2. **引擎收口**：无 IO / 无 LLM / 无 DB 的纯函数模块统一收进 `engines/`，与领域包解耦，可零 fixture 单测。
3. **包名即领域，文件名即职责**：新归位文件一律**去掉 `_service` / `_engine` 等后缀**（`goal_service.py` → `goal/service.py`）。**已有子包内的文件不改名**（降低爆炸半径，避免无谓 churn）。

---

## 三、目标目录树

```text
app/services/
├── __init__.py                 # 新增门面（PEP 562 惰性导出，最后一批落）
├── agent_service.py            # 兼容壳，保留原位（被 3 处守卫钉死）
│
├── engines/                    # ★ 纯函数引擎（无 IO / 无 LLM / 无 DB）
│   ├── state.py  autonomy.py  decision.py  behavior.py  mode.py
│   ├── habit.py  goal_alignment.py  character.py
│   ├── memory_policy.py  memory_conflict.py
│   └── relationship_evolution.py  relationship_signal.py  relationship_conflict.py
│
├── goal/                       # ★ Goal 域（7 个顶层文件收编）
│   └── service.py  stack.py  arbitration.py  execution.py
│       observation.py  planning.py  intention.py
│
├── relationship/               # 关系域（纯引擎移 engines/）
│   └── audit.py  milestone.py  narrative.py  patterns.py  shared.py  evaluation.py
│
├── conversation/               # ★ 会话 / 状态编排域
│   └── service.py  history.py  summary.py  context.py  scene.py  state.py
│
├── evaluation/                 # ★ 跨域评估框架
│   ├── context.py  engine.py  agent.py  offline.py
│   └── rules/                  # ← evaluation_rules/ 整体并入（__init__ 门面原样保留）
│
├── autonomy/                   # 自治域（纯引擎移 engines/）
│   └── trigger.py  executor.py
│
├── delivery/                   # ★ 通道投递域（刻意避开 channel/ 命名，见 §五⑥）
│   └── dedupe.py  ledger.py  outbound.py  outbox.py
│
├── life/          # 已有 + ownership.py + budget.py  gate.py  tasks.py
├── identity/      # 已有 + channel.py（← channel_identity_service）
├── observability/ # 已有 + collector.py（← trace_collector）+ analytics.py（← analytics/events）
├── development/   # 已有 + evolution.py
├── ledger/        # 已有 + domain.py（← domain_ledger）
├── memory/        # 已有 + refs.py（← memory_refs）；policy / conflict 移出至 engines/
├── briefing/      # 已有 + weather.py（← weather.py，现实天气源）
├── governance/    # 6 → 2：core.py（合并 5 文件）+ prompt_guard.py
│
├── action/        # 不动（含哈希冻结的 capabilities/ + planner.py + executor.py）
├── world/         # 不动（weather.py 是设定天气，与现实源区分）
├── planning/      # 不动（11 文件有精确清单守卫）
└── reflection/  tool/  character_action/  experience/  grounding/  email/  insights/
```

---

## 四、逐文件去向映射表（49 个顶层散落模块）

> 风险口径：**低** = 叶子模块（不 import 任何 services 内部模块）/ 无守卫 / 外部引用 ≤1；**中** = 有守卫或中等引用；**高** = 哈希冻结 / 路径硬编码守卫 / 高频引用。

| # | 原路径 | 真实职责 | 目标路径 | 判定依据 | 风险 |
|---|---|---|---|---|---|
| 1 | `agent_evaluation.py` | Agent 级六指标 + 周期快照（AGENT-006） | `evaluation/agent.py` | 有仓储 IO，属跨域评估 | 低 |
| 2 | `agent_service.py` | 兼容壳（编排已迁 `application/chat_pipeline`，只留 `stream_chat`） | **保留原位** | 被 feishu allowlist / conftest / `entry-convergence.md` 三处钉死 | 中 |
| 3 | `autonomy_policy.py` | 纯函数八步自治裁决（零仓储零 IO） | `engines/autonomy.py` | `test_plan007` 已证纯；target-architecture 同族 | **高** |
| 4 | `behavior_engine.py` | 纯函数 intention→strategy→budget | `engines/behavior.py` | docstring「纯函数：无 IO、无 LLM」 | 中 |
| 5 | `channel_identity_service.py` | 通道 ↔ 内部身份双向翻译 | `identity/channel.py` | 有仓储 IO，属身份域（非投递） | **高** |
| 6 | `character_assets.py` | 人设资产只读解析（`importlib` + `lru_cache`，零 IO） | `engines/character.py` | 纯访问器。**待裁决 D** | 中 |
| 7 | `context_builder.py` | ConversationState 装配（检索 / insight / 共同经历段） | `conversation/context.py` | 多服务编排，非纯 | 中 |
| 8 | `conversation_service.py` | 会话读写（ensure / load_window / save_turn） | `conversation/service.py` | 有仓储 IO | 中 |
| 9 | `decision_pipeline.py` | 统一决策管线五段（纯规则） | `engines/decision.py` | 纯；但**被 `ZERO_DIFF_HASHES` 冻结** | **高** |
| 10 | `domain_ledger.py` | 多域审计账本只读门面 | `ledger/domain.py` | 纯直通仓储，零业务判断 | 低 |
| 11 | `evaluation_context.py` | V7.5 评估上下文收集器（832 行） | `evaluation/context.py` | import 13 个仓储，评估域核心 | 中 |
| 12 | `evaluation_engine.py` | V7.5 两阶段评估引擎 | `evaluation/engine.py` | 链 + 仓储 IO | 中 |
| 13 | `evolution.py` | Evolution Engine 唯一写入点 | `development/evolution.py` | 有 DB 写；conftest 别名 `evolution_service` | 中 |
| 14 | `feishu_dedupe_service.py` | 飞书入站去重持久化路径 | `delivery/dedupe.py` | 有仓储 IO | 中 |
| 15 | `feishu_delivery_ledger_service.py` | 飞书出站投递幂等持久化 | `delivery/ledger.py` | 有仓储 IO | 中 |
| 16 | `goal_alignment.py` | Goal Alignment 纯打分 | `engines/goal_alignment.py` | 纯函数接口契约 | 低 |
| 17 | `goal_arbitration.py` | AUT-004 仲裁器 | `goal/arbitration.py` | 有仓储 IO；plan001 断言 `compute_priority` 唯一处 + plan008 | **高** |
| 18 | `goal_execution.py` | AUT-003 Sub-Goal 执行 | `goal/execution.py` | 有仓储 IO | 中 |
| 19 | `goal_observation.py` | AUT-003 判据求值 / 推进 | `goal/observation.py` | 有仓储 IO；plan008 读该文件 | **高** |
| 20 | `goal_planning.py` | AUT-002 规划执行器（唯一 LLM 面） | `goal/planning.py` | **不并入 `planning/`**，见 §五① | 中 |
| 21 | `goal_service.py` | V6 Goal 生命周期 + 每轮选择 | `goal/service.py` | 有仓储 IO | 中 |
| 22 | `goal_stack.py` | 四层目标栈激活裁决 | `goal/stack.py` | 有仓储 IO | 中 |
| 23 | `habit_runtime.py` | 动态 Habit 机制 | `engines/habit.py` | 仅读 settings / character 资产 | 中 |
| 24 | `history_service.py` | 读路径查询门面 | `conversation/history.py` | 有仓储 IO | 低 |
| 25 | `intention_policy.py` | V6 意图纯代码校验 | `goal/intention.py` | 纯但依赖 `goal_service.SelectedGoal` → **不进 engines** | 中 |
| 26 | `life_loop_budget.py` | 全局日 LLM 配额检查 | `life/budget.py` | 有仓储 IO，属 LIFE 域 | 低 |
| 27 | `llm_budget_gate.py` | LLM 预算闸门面 | `life/gate.py` | 间接 IO，预算域 | 低 |
| 28 | `memory_refs.py` | `turn_meta.memory_refs` 装配 | `memory/refs.py` | 领域格式化器，**不进 engines** | 低 |
| 29 | `mode_service.py` | Mode 迟滞稳定器（表驱动） | `engines/mode.py` | docstring「纯函数，R1~R5 表驱动」 | 低 |
| 30 | `offline_evaluator.py` | V7.5 离线批量评估编排 | `evaluation/offline.py` | 仓储 + 链 IO | 中 |
| 31 | `outbox_service.py` | Outbox 只读门面 | `delivery/outbox.py` | 只读门面 | 低 |
| 32 | `proactive_delivery.py` | 主动出站端口（依赖倒置注册表） | `delivery/outbound.py` | 无 IO，但属端口非引擎 | 中 |
| 33 | `proactive_executor.py` | V7 主动执行器（含 5 处 application 反向依赖） | `autonomy/executor.py` | 链 + 仓储 IO，自治域 | 中 |
| 34 | `relationship_audit.py` | REL-004 关系账本重放对账 | `relationship/audit.py` | 4 个关系仓储 | 中 |
| 35 | `relationship_conflict.py` | V8.5 M5 冲突状态机（纯） | `engines/relationship_conflict.py` | docstring「全部迁移为纯函数」 | 中 |
| 36 | `relationship_evaluation.py` | REL-004 关系域离线评估 | `relationship/evaluation.py` | 有 DB / IO，**留本域** | 中 |
| 37 | `relationship_evolution.py` | V8.5 M1/M3 演化引擎（纯，可重放） | `engines/relationship_evolution.py` | docstring「全部纯函数」 | 中 |
| 38 | `relationship_milestone.py` | V8.5 M4 里程碑 | `relationship/milestone.py` | 有仓储 IO；**agent008 `DOMAIN_MODULES`** | **高** |
| 39 | `relationship_narrative.py` | 叙事里程碑 job | `relationship/narrative.py` | 有 DB IO；**plan010 static_scan** | **高** |
| 40 | `relationship_patterns.py` | 关系模式只读消费 | `relationship/patterns.py` | 有 DB IO | 中 |
| 41 | `relationship_shared.py` | 共同经历只读投影 | `relationship/shared.py` | 3 个仓储 | 中 |
| 42 | `relationship_signal.py` | V8.5 M2 交互分析（纯，不落库） | `engines/relationship_signal.py` | docstring「信号不落库」 | **高** |
| 43 | `scene_service.py` | 场景 resolve / load | `conversation/scene.py` | 链 + 仓储 IO | 中 |
| 44 | `state_engine.py` | 情绪 / 关系纯计算 | `engines/state.py` | **target-architecture §2:25 点名** | 中 |
| 45 | `state_service.py` | V2 状态更新编排（533 行） | `conversation/state.py` | 链 + 4 仓储 + 5 服务；rel001 读该文件。**待裁决 E** | 中 |
| 46 | `summary_service.py` | 会话摘要 | `conversation/summary.py` | 链 + 仓储 IO | 低 |
| 47 | `trace_collector.py` | 内存 Trace 采集 | `observability/collector.py` | 无 IO，观测域；feishu allowlist | **高** |
| 48 | `trigger_evaluator.py` | V7 自治触发器求值 | `autonomy/trigger.py` | 有仓储 IO；plan007 `AUTONOMY_MODULES` | **高** |
| 49 | `weather.py` | **现实**天气源（Open-Meteo，`urllib` 网络） | `briefing/weather.py` | 有网络 IO；见 §五② | 中 |

---

## 五、争议裁决

### ① `goal_planning.py` → `goal/planning.py`（**不并入 `planning/`**）

**实测证据**：`planning/goal_contract.py:34-35` 明文 ——

> **不在写回面**：`expire_goal` / `cancel_goal` / `create_hierarchical_goal` / `create_goal` / `seed_goals` —— **Planning 不得调用**；计划被拒（`GoalPlanStatus.rejected`）**不改变** `GoalStatus`。

且白名单 `PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS` 从 12 → 16 → 19 项演进中，**始终不含**上述写面（`:115-116`、`:138-139` 两次重申「仍不在白名单」）。

而 `goal_planning.py` 是 AUT-002 执行器，直接 `create_goal` / `update_plan_progress`。二者是「Goal 说想要什么」vs「Planning 说怎么分步」两套系统，并入即违反该包白名单与 `test_plan001_static_scan` 的多条断言。**必须分域。**

### ② `weather.py` vs `world/weather.py`

- `services/weather.py` = **现实天气**（Open-Meteo，`urllib`，docstring 明示与设定天气相对，fail-open）。
- `services/world/weather.py` = **设定天气**（世界模拟，种子确定性演化）。

处置：现实源归 `briefing/weather.py`（唯一消费者是 `briefing/compose.py`，它是简报卡的数据后端）；设定天气保持 `world/weather.py` **不动**。**不新建 `services/weather/`**（会与 `world/weather.py` 形成两处同名包，反而更乱）。**待裁决 C**。

### ③ 评估族 9 处收敛

**实测证据**：`evaluation_rules/` 全部 11 个文件（含 `__init__.py:19`）均 `import app.services.evaluation_context`；`evaluation_engine.py:31` 与 `offline_evaluator.py:25` 均 `import app.services.evaluation_rules` → 强耦合，收进同一 `evaluation/` 包成立。

| 位置 | 处置 | 理由 |
|---|---|---|
| `evaluation_context.py` → `evaluation/context.py` | 收编 | 跨域评估框架：上下文收集器 |
| `evaluation_engine.py` → `evaluation/engine.py` | 收编 | 跨域评估框架：两阶段引擎 |
| `agent_evaluation.py` → `evaluation/agent.py` | 收编 | Agent 级指标，属跨域评估 |
| `offline_evaluator.py` → `evaluation/offline.py` | 收编 | 跨域批量评估编排器 |
| `evaluation_rules/` → `evaluation/rules/` | **整体并入** | 同一 V7.5 系统的规则引擎；`__init__` 的 `RULES` 门面原样保留 |
| `trigger_evaluator.py` → `autonomy/trigger.py` | 移出 | 求值对象是**自治触发器**（trigger），名同实异 |
| `development/evaluation.py` | **留** | 域专属离线报告 |
| `reflection/evaluation.py` | **留** | 域专属离线报告 |
| `relationship_evaluation.py` → `relationship/evaluation.py` | 留本域 | 域专属离线报告（REL-004） |

即：`evaluation/` 只收**跨域框架**；三个域专属 `evaluation.py` 留在各自领域，避免 `evaluation/` 反向依赖 4 个领域。

### ④ 会话 / 状态编排族 → 新建 `conversation/`

`service.py`(←conversation_service) / `history.py` / `summary.py` / `context.py`(←context_builder) / `scene.py`(←scene_service) / `state.py`(←state_service)。三个纯函数（`state_engine` / `mode_service` / `behavior_engine`）进 `engines/`。**待裁决 E**（`state_service` 是否单建 `state/`）。

### ⑤ 自治族

`autonomy_policy`→`engines/autonomy`；`decision_pipeline`→`engines/decision`；`habit_runtime`→`engines/habit`；`trigger_evaluator`→`autonomy/trigger`；`proactive_executor`→`autonomy/executor`；`intention_policy`→`goal/intention`（依赖 services 类型，不进 engines）。

### ⑥ 通道 / 投递族 → 新建 `delivery/`

**刻意不用 `channel/` 命名**，避免与 `app/channels/feishu/` 混淆：`dedupe.py` / `ledger.py` / `outbound.py` / `outbox.py`。`channel_identity_service` 归 `identity/channel.py`（身份域，非投递）；`proactive_executor` 归 `autonomy/`（非通道）。

---

## 六、引擎收口：判定标准与清单

### 6.1 判定标准（全部满足才算引擎）

1. 不 import `app.repositories` / `app.chains` / `app.core.db` / `app.application`；
2. 不 import 任何非 engines 的 `app.services.<业务模块>`；
3. 不 import 网络库（`httpx` / `requests` / `urllib` / `aiohttp` / `socket`）或 LLM 库（`openai` / `langchain` / `core.llm_factory`）；
4. 允许：`app.models.*` / `app.core.settings` / `app.core.constants` / `app.character.<id>.*`（纯数据资产）/ 标准库 / `pydantic`；
5. 无模块级 `SessionLocal`，可零 DB / 网络 fixture 单测。

### 6.2 清单（12 项）

`target-architecture.md` 点名 3 项：`state`(←state_engine) / `memory_policy`(←memory/policy) / `memory_conflict`(←memory/conflict)。

按上述标准扩大 9 项：`autonomy` / `decision` / `behavior` / `mode` / `habit` / `goal_alignment` / `character` / `relationship_evolution` / `relationship_signal` / `relationship_conflict`。

### 6.3 刻意排除（避免 engines 变杂货铺）

| 模块 | 理由 |
|---|---|
| `memory_refs.py` | 领域格式化器 → `memory/refs.py` |
| `proactive_delivery.py` | 端口注册表 → `delivery/outbound.py` |
| `intention_policy.py` | 依赖 services 类型（`goal_service.SelectedGoal`）→ `goal/intention.py` |

### 6.4 位置（**待裁决 A**）

| 选项 | 依据 | 优劣 |
|---|---|---|
| **A1 `app/engines/`** | `target-architecture.md` §2:25 画在 `app/` 下，与 `services/` **平级**，§3:41 作为独立层给出依赖规则 | 贴合文档的独立分层；但 `test_feishu_boundary.py` 等按 `services/**` 扫描的守卫**不会自动覆盖** |
| **A2 `app/services/engines/`** | 现状 `state_engine` 等就在 services 内，外部已有 `app.services.state_engine` 引用 | 守卫自动覆盖；但把「独立层」塞进 services 内，语义上弱化了分层 |

两者 import churn 基本相同（路径都要改）。**倾向 A1**（贴合文档），待用户拍板。

---

## 七、子包调整

| 现路径 | 处置 | 理由 |
|---|---|---|
| `analytics/`（1 文件，**无 `__init__.py`**） | 并入 `observability/analytics.py` | 同属横切遥测；且缺 `__init__.py` 是命名空间包隐患 |
| `tasks/`（1 文件，**无 `__init__.py`**） | 并入 `life/tasks.py` | 任务即 life 域；`life/` 已有 `ownership.py` |
| `life/`(1) | **保留为子包** | 归入 `budget` / `gate` / `tasks` 后成为真实领域包 |
| `insights/`(1) | **保留为子包**（补空 `__init__.py`） | 独立产品读面 |
| `briefing/`(1) | **保留为子包** | 收编现实 `weather.py` 后 2 文件 |
| `email/`(1) | **保留为子包** | 独立外部适配器域 |
| `grounding/`(1) | **保留为子包** | 独立领域且体量大（768 行） |
| `governance/`（6 文件，全部 25–42 行） | **6 → 2**：`core.py`（合并 `models` + `registry` + `provenance` + `delete` + `export`）+ `prompt_guard.py`（独立、零耦合，单独留便于测试） | 强内聚、过碎。**不**坍缩为单文件（会破坏 `governance/*.py` 的 AST 扫描守卫） |
| `tool/manifests/`（非 `.py`） | **原位保留** | 工具声明式数据目录（`README.md` + `weather_current.yaml` + `webhook_notify.yaml`） |

---

## 八、迁移批次（风险从低到高）

| 批次 | 内容 | 为什么排这里 |
|---|---|---|
| **0 建骨架** | 新建各领域包空 `__init__.py` + `engines/` | 零行为变化 |
| **1 叶子搬迁** | `memory_refs` / `domain_ledger` / `llm_budget_gate` / `life_loop_budget` / `evolution` / `outbox_service` / `proactive_delivery` / `feishu_dedupe_service` / `feishu_delivery_ledger_service` / `analytics/events` / `tasks/task_service` | 不被硬编码守卫引用，外部引用 ≤1，无哈希冻结 |
| **2 引擎收口** | `state_engine` / `mode_service` / `habit_runtime` / `goal_alignment` / `behavior_engine` / `relationship_{evolution,signal,conflict}` / `character_assets` | 纯模块、无哈希冻结 |
| **3 领域包搬迁** | `goal/*` / `relationship/*` / `conversation/*` / `evaluation/*`（含 `evaluation_rules→evaluation/rules`）/ `autonomy/*` / `identity/channel` / `observability/collector` / `briefing/weather` / `governance` 6→2 | 守卫多但语义清晰，改动可枚举（见 §九） |
| **4 哈希冻结模块** | `decision_pipeline` / `memory/policy` / `autonomy_policy` / `trigger_evaluator` | 最高风险，单独成批；每步同步冻结键 + 留痕。`action/*` **一律不动** |
| **5 门面收敛** | 落 `services/__init__.py` | 最后做，避免迁移期双重解析 |

---

## 九、守卫同步清单

| 守卫 | 受影响 | 同步动作 |
|---|---|---|
| `v21/test_agent008_review_fixes.py::DOMAIN_MODULES` | `relationship_signal/milestone/evolution.py` | 改路径（signal/evolution → `engines/`） |
| `v25/test_plan001_static_scan.py` | 断言 `def compute_priority` 唯一在 `goal_arbitration.py` | → `goal/arbitration.py` |
| `v25/test_plan001_scope_markers.py` | `planning/` 精确清单（11 项）+ L389 `from app.services import autonomy_policy` | `planning/` 不动；改 autonomy_policy 导入 |
| `v25/test_plan007_boundary.py` | `AUTONOMY_MODULES` + L27 模块导入 | 三路径改写（`engines.autonomy` / `engines.decision` / `autonomy.trigger`） |
| `v25/test_plan008_broadcast.py` | 读 `goal_observation.py` / `goal_arbitration.py` | → `goal/observation.py` / `goal/arbitration.py` |
| `v25/test_plan010_static_scan.py:50` | `relationship_narrative.py` | → `relationship/narrative.py` |
| `v2/test_rel001_truth_source.py` | 读 `state_service.py` | → `conversation/state.py`（负向断言「`relationship_memory.py` 不存在」仍成立） |
| `v50/test_tool_step_events.py` | `app/services/tool/step_events.py` | **不动**（`tool/` 未改） |
| `v40/test_life_governance.py` | glob `governance/*.py` + 硬读 `delete.py` | 合并后改读 `governance/core.py` |
| `v24/test_tool008_integration.py::FROZEN_SOURCES` | 键 `app/services/memory/policy.py` | 键 → `engines/memory_policy.py` + 留痕（内容哈希不变） |
| `v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` | 键 `app/services/decision_pipeline.py` | 键 → `engines/decision.py` + 留痕（**勿动 `action/*` 键**） |
| `v24/test_tool003_action_engine.py` | `action/executor.py` 类源码哈希 | **不动** |
| `tests/conftest.py::_SERVICE_DB_MODULES` | 别名 `evolution_service` / `insights_query` / `relationship_*_service` | 随批次改别名导入路径（**须指向真实子模块，不能指向门面别名**，否则打桩静默失效） |
| `v30/test_runtime_foreground_cutover.py` | rglob 匹配 `agent_service.stream_chat(` | `agent_service` 保留原位 → **无需改** |
| `unit/test_feishu_boundary.py` | allowlist 含 `channel_identity_service` / `trace_collector` / `agent_service` | 改前两者路径（AST 扫描 `services/**` 的规则本身不变） |

---

## 十、三类架构债规划要点

### ① `services → application` 反向依赖（35 处 / 26 文件）

**函数内延迟 import（较易，改 import 位置即可）**
- `action/{integration,manager}`、`goal_execution` → `action_engine`；
- `world/{catch_up,daily_plan,day_cycle,movement,user_situation,weather}` → `world_engine`（6 处，均缩进在函数体内）；
- `services/observability/{llm_capture,prompt_capture}` → `observability`（4 处）。

**模块级（较难，需依赖倒置）**

| 违规源 | 处数 | 整改思路 |
|---|---|---|
| `world_engine` | 14 | 在 `services/world/` 增只读端口（如 `get_world_engine()`），由 `app/main.py` lifespan 注册实现 —— **完全复刻现有 `proactive_delivery.register_proactive_outbound` 模式**。⚠️ `action/capabilities/{reminder,world_action,environment_query}.py` 是**哈希冻结**文件 |
| `observability` | 8 | 把 `on_decision` / `mark_decision_outcome` / `current_trace` 的**最小协议**下沉 `core/`（或 `services/observability/port.py`），`application/observability` 作为实现注册 |
| `reflection/reflector → logical_clock` | 2 | **直接下沉 `core/clock.py`**（纯时钟工具，最易） |
| `proactive_executor → get_user_write_lock / active_generations` | 3 | 共享锁与状态注册表**下沉 `core/`**；`autonomy_bridge` 两个函数用注册口倒置 |
| `memory/job_worker → worker_loop` | 1 | 改为 job handler 注册表（services 侧定义注册口，application 启动时注册） |

### ② 巨型文件拆分（>800 行 5 个）

| 文件 | 行数 | 拆分维度 |
|---|---|---|
| `reflection/evidence.py` | 1856 | → `evidence/{windows,collectors,persistence}.py`（证据窗构造 / 聚合采集 / 落库） |
| `tool/ext_api.py` | 1507 | → `ext_api/{schema,handlers,registry}.py`（按 API 面） |
| `planning/decompose.py` | 963 | → `decompose/{decomposer,validator}.py`（**须同步 `test_plan001_scope_markers` 精确清单**） |
| `planning/observer.py` | 861 | → `observer/{settlement,projection,broadcast}.py`（PLAN-008/011 广播接口须留在守卫可 import 的位置） |
| `evaluation_context.py` | 832 | → `evaluation/{context_slices,collectors,digest}.py`（按切片 vs 采集） |

次一级（700–800）：`tool/confirmation.py`(771) / `grounding/inventory_guard.py`(768) / `planning/context.py`(742) / `development/evaluation.py`(708)。

### ③ 门面收敛（`services/__init__.py`）

- **PEP 562 惰性 `__getattr__`**：把**旧顶层模块名**映射到新位置（`state_service`→`conversation.state`、`evaluation_rules`→`evaluation.rules`、`autonomy_policy`→`engines.autonomy` …），保住大量 `from app.services import X` 浅层调用点（242 处）。
- **深路径无法被门面拦截**：496 处 `from app.services.X import` / `import app.services.X` 由导入系统直接解析，`__getattr__` 不生效 → **必须一次性 codemod 改写**。
- **不破坏既有门面**：`evaluation/rules/__init__.py`（`RULES` 汇编，143 行）、`governance/__init__.py`（33 行）、`planning/__init__.py`（29 行）原样保留。
- **风险**：
  1. 门面必须**纯惰性**（急切 import 会拉起 repositories / LLM，拖慢包导入）；
  2. `tests/conftest.py::_SERVICE_DB_MODULES` 靠**真实子模块路径**打桩 `SessionLocal`，别名须指向真实模块，否则打桩**静默失效**；
  3. 迁移期建议「门面 + 旧路径 shim 并存」，批次 5 收尾。

---

## 十一、待裁决项

| # | 议题 | 选项 | 倾向 |
|---|---|---|---|
| A | `engines/` 位置 | A1 `app/engines/`（贴合 target-architecture 独立分层）vs A2 `app/services/engines/`（守卫自动覆盖） | **A1** |
| B | relationship 三引擎是否外迁 `engines/` | 外迁更纯粹 vs 留 `relationship/`（领域语义强） | 外迁 |
| C | 现实天气源归属 | 归 `briefing/weather.py` vs 新建 `integrations/` | 归 `briefing/` |
| D | `character_assets` 是否入 engines | 入（纯访问器）vs 留顶层 | 入 |
| E | `state_service` 归属 | `conversation/state.py` vs 单建 `state/service.py`（后者成单文件子包） | `conversation/state.py` |
| F | `governance` 合并粒度 | 6→2 vs 6→1 | 6→2 |

---

## 十二、风险

1. **哈希冻结是硬约束**：`decision_pipeline.py` / `memory/policy.py` / `action/capabilities/*` / `action/planner.py` / `action/executor.py`。前三者可移动（同步改键 + 留痕），`action/*` **建议完全不移动**。
2. **`test_plan007_boundary` 同时有「路径硬编码」与「模块导入」两种断言**，`autonomy_policy` / `decision_pipeline` 的引擎化是全局最高风险点。
3. **`planning/` 有精确文件清单守卫**（`test_plan001_scope_markers.py:490-506`，11 项），对该包的任何结构调整（含 §十② 的拆分）都须同步该断言。
4. **`conftest.py::_SERVICE_DB_MODULES` 静默陷阱**：新增带模块级 `SessionLocal` 的 services 模块必须登记；门面别名不可用于打桩目标。
5. **口径差待复核**：反向依赖「35 处 / 26 文件」为 grep 文件级命中（实测命中 28 文件），未逐符号核对；1333 处 / 496 处深路径未逐条复算（仅抽查热点）。
6. **未覆盖范围**：`world/` / `action/` / `tool/` / `reflection/` / `planning/` 等既有子包的**内部**重组不在本次方案内（仅处理顶层散落模块、单文件子包、`governance/`）。

---

## 十三、后续执行约定

- 每批次**独立提交**，提交信息：`refactor: services 按领域归位 - 批次 N`。
- 每批次跑全量 `pytest tests -q --basetemp=<每次换名的新目录> -rf`，**判据 = 失败集 diff，不是计数**（基线本身非全绿）。
- 动哈希冻结模块时，同步更新 `tests/support/schema_pins.py` 之外的钉测键，并在文件内写「归位至 …」留痕注释（沿用 `memory/conflict.py` 既有体例）。
- 批次 0~5 全部完成后，回写本台账的「实际执行结果」章节（含实测失败集 diff）。

---

## 十四、实际执行结果（2026-09-30 收官）

**批次 0~5 全部完成**，逐批独立提交：`455ad7f`（docs 规划 + 基线 ADR-15）→ `616c7d7`（批次 0 骨架）→ `b4c86d5`（批次 1）→ `d4d652f`（批次 2）→ `8969b42`（批次 3）→ `1b39d14`（批次 4）→ `b6c68ca`（批次 5 门面）。

### 14.1 判据与结果

- 基线全量：**20 failed / 7160 passed / 2 skipped**；收官全量：**19 failed / 7161 passed / 2 skipped**——失败集为基线的**严格子集**（唯一差异 = 基线中抖动的 `v7.8::test_observability_overhead_within_budget` 本次通过），**零真实回归**。
- 每批次均以「基线失败集 ∪ 已知抖动名单」为期望集做 diff；过程中暴露的真实回归（tool007/tool010 零差异哈希、feishu_boundary direction2、plan_stage 懒加载断言、plan009 两守卫）全部当场修复并复验。
- 已知抖动名单（12 项，非本次引入）：e2e debug 家族 5 例、`test_world_chat` 2 例、`test_scene_cases::test_case4_topic_switch`、`test_chat_http_integration::test_http_summary_trigger`、v7.8/v8 performance 预算 2 例、`test_runtime_background_cutover::test_maintenance_steps_unchanged`。
- **观察项**：`tests/e2e/test_memory_e2e.py::test_memory_roundtrip_across_turns` 全量偶发（召回轮 prompt 缺失刚存记忆，后台记忆管线竞态；单跑连过 3 轮）——本次仅改 import 路径不改运行时逻辑，判定为既有抖动，上线后例行观察。

### 14.2 实际搬迁面

- 批次 1：11 个叶子模块（memory_refs / domain_ledger / llm_budget_gate / life_loop_budget / evolution / outbox / outbound / dedupe / delivery ledger / analytics.events / tasks.task_service）+ 消灭 `analytics/` `tasks/` 命名空间包 + 补 `insights/__init__.py`。
- 批次 2：10 个纯函数模块收口 `app/engines/`（state / mode / habit / goal_alignment / behavior / relationship_{evolution,signal,conflict} / character / **memory_conflict**——§6.2 清单内、未排批次的补齐）。
- 批次 3：28 个顶层模块归位 goal/ relationship/ conversation/ evaluation/ autonomy/ identity/ observability/ briefing 八域 + `evaluation_rules/`→`evaluation/rules/`（12 文件整体并入）+ governance 6→2（core.py 合并五文件，prompt_guard 独立）。
- 批次 4：`decision_pipeline`→`engines/decision.py`、`memory/policy`→`engines/memory_policy.py`、`autonomy_policy`→`engines/autonomy.py`——**内容逐字节未变（摘要不变），仅键路径更新**（沿用 tool008 memory/policy 先例；§十三的「文件内留痕」改为钉测字典留痕，与既有体例一致）。
- 批次 5：`services/__init__.py` 落 PEP 562 惰性门面（54 个旧名映射，`importlib.import_module` 按需解析并缓存）；深路径改写未依赖门面，已在批次 1~4 由 codemod 全量完成（批次 1~4 分别改写 50 / 49 / 214 / 52 个文件）。

### 14.3 与规划的偏差

1. 待裁决 A~F 按文档倾向执行（A1 = `app/engines/` 独立层）。
2. `trigger_evaluator` 归入批次 3（§八批次 3/4 重复列名；plan007 路径断言同批同步）。
3. 零差异冻结面**再冻结 8 处**（§九未预见）：tool007 `world_engine`；tool010 `chat_pipeline`×2、`post_process`×2、`channels/feishu/delivery`、`prompts/builder`、`action/capabilities/memory`——均为 import 路径改写所致，钉测字典内按既有「非 TOOL-010/007 改脏」声明体例留痕。
4. §九之外的守卫同步：`test_feishu_boundary` direction2（identity/channel 路径 + 过滤串）、`test_runtime_plan_stage` 懒加载断言（`{"app.services.goal","app.services.planning"} <= nested`，原 `from app.services import goal_planning` 包形式经归位后字面失配）、`test_plan009_flags`（engines/memory_policy 读取路径）、`test_plan009_step_criteria`（导入面期望字典去 `policy`）、`test_life_governance`（改读 `governance/core.py` + reset 入口）。
5. 未动范围兑现：`action/*` / `world/` / `tool/` / `reflection/` / `planning/` 内部结构未触碰，`agent_service.py` 兼容壳原位保留。

### 14.4 遗留

§十 债①（`services → application` 反向依赖 35 处，含 world_engine 14 处端口化）与债②（巨型文件拆分 5 个）不在批次 0~5 范围，**保持未动**，沿用本台账 §十 规划要点另行排期。

---

## 十五、三类架构债执行结果（2026-09-30 第二批）

### 15.1 债① `services → application` 反向依赖清零 ✅

逐符号复核（§十二.5 口径差已闭合）：**26 文件 / 36 处代码引用**（另 1 处为 docstring）。逐组提交：

| 提交 | 内容 |
|---|---|
| `a36c594` | `logical_clock` → `core/clock.py`（纯时钟下沉，reflector 2 处 + application 3 处 + 3 个测试文件同步）；`action_engine.py` 因 import 变更再冻结 |
| `569f1d3` | action / observability 端口落地 + 8 处函数内懒调用改端口（`action/{integration,manager}`、`goal/execution` → action 端口；`observability/{llm,prompt}_capture` 4 处 → observability 端口） |
| `5488a56` | world_engine 端口化：12 个消费文件（含 3 个哈希冻结的 `action/capabilities/*`，均再冻结留痕）+ `character_action/validator` 调用点改写 |
| `2d64308` | `core/runtime_state.py` 下沉（`get_user_write_lock` / `active_generations` / `memory_digest_var`，post_process 与 chat_pipeline 再冻结）；executor 经 `services/autonomy/port` 访问 `autonomy_bridge`；`memory/job_worker` 改 worker_loop 注册表；observability 模块级消费 4 文件改端口 |

端口模式：**服务侧端口模块 + PEP 562 `__getattr__` 代理**（消费点只改 import 行、绑定名不变，属性调用期解析）；组合根 = `main.py` lifespan + `tests/conftest.py` 顶部。豁免：`agent_service.py`（兼容壳本体，随壳退役消失）、`observability/trace_query.py`（docstring 陈述规则，非代码引用）。

⚠️ **坑位记录（后续拆分必读）**：端口 `__getattr__` 与 monkeypatch 组合存在「快照残留」陷阱——`monkeypatch.setattr(端口模块, "attr", fake)` 会在 undo 时把真实函数**永久写入端口模块字典**，遮蔽 `__getattr__`，导致后续对实现模块的补丁全部失效（`test_character_action_mutator` 污染 `test_character_action_validator` 即此因）。**测试打桩一律打实现模块（`app.application.world_engine.X`），端口读穿天然生效。**

### 15.2 债② 巨型文件拆分：2/5 ✅

- ✅ **`evaluation/context.py`（834）→ `evaluation/context/` 包**（`639f3b0`）：`slices.py`（切片数据类 + 常量 + `_clip`）/ `collectors.py`（收集器）/ `digest.py`（digest 组装与截断），`__init__` 全量再导出，全部消费面（`from ...context import X` 形态）零改动。拆分前审计确认：无任何 monkeypatch 依赖 `context.<X>` 包属性 → 再导出安全。
- ✅ **`reflection/evidence.py`（1856）→ `reflection/evidence/` 包**（`75e0d22`，首轮回滚后带守卫适配重做）：`windows.py`（882 行，纯窗构造 + 门槛数学，零 IO）/ `collectors.py`（911 行，DB 采集 + trace 记录 + 聚合编排）；AST 调用图做纯/IO 精确分类（引用 SessionLocal/仓储/trace 助手的符号传递闭包 → collectors，其余 → windows，含 8 个 AnnAssign 常量），`__init__` 显式全量再导出 153 个名字（含私有名与仓储模块引用）。**首轮回滚的原因（plan010/011 分节级源码语义守卫族 10+ 断言）本轮逐守卫完成语义适配**：分节标记源码扫描改为 `plan010_support.plan_section_source()` AST 按符号抽段（44 个 PLAN-010 符号跨 windows/collectors 两文件拼接，语义等价「计划通道源码段」）；`__file__` 整文件读取改包内 `*.py` glob 拼接（plan011/ledger_insight/tool009 三处）；conftest 与 growth_loop 自建打桩清单的 `reflection_evidence` 绑定改指 `collectors`（唯一 DB 触点，防 §十三 打桩静默失效）；`_human_messages_after` / `_aggregate` 两处补丁目标改指子模块。
- ⏸ **`planning/observer.py`（863）：审计完成后判定不拆**（2026-09-30 第二批）。补丁缝审计结论：模块属性补丁仅 4 处、零 SessionLocal、零源码路径串——耦合面本身干净；**真正障碍是 v25 的 planning 包「扁平文件清单纪律」**：`planning_modules()` / `PLANNING_PACKAGE_MODULES` / `rglob("*.py") + path.name` 精确清单断言分布在 **14 个测试文件**（plan001/002/004/005/006/007/008/009/010 的 static_scan、scope_markers、boundary 等），observer 包化会引入 `observer/__init__.py`、`observer/core.py`、`observer/broadcast.py` 三个新条目与重名 `__init__.py`，需把全部清单从「文件名」升级为「相对包路径」语义。适配 churn（14 文件）超过拆分收益（863 行 → 两块），且 AST 闭包分析证实 PlanObserver.settle 与广播函数双向调用（core ↔ broadcast 无法单向切分，PlanObserver 须与广播同侧，语义别扭）。**可维护性替代**：文件内已有 `# ---` 分节注释体例，后续维护靠分节导航。
- ⏸ **`tool/ext_api.py`(1507) / `planning/decompose.py`(963) 待排期**：与 observer 同属 planning/tool 守卫体系（decompose 在 plan001_scope_markers 的 11 项清单 + plan004 清单；ext_api 有 tool 域钉测面）。**前置条件 = 先做「v25 清单守卫体系升级」专项**（14 文件的清单语义从文件名改为相对包路径，一次性解除全部 planning 子包化的守卫障碍），之后 decompose 可复用 evidence 全套方法论；ext_api 另需 tool 域钉测审计。

⚠️ **端口快照残留第二形态（本轮新发现，比 §15.1 第一形态更隐蔽）**：经**模块属性链**打到端口对象的补丁（如 `monkeypatch.setattr(plan_context.world_engine, "build_context", fake)`，其中 `plan_context.world_engine` 已是端口）——undo 时 monkeypatch 把「getattr 的快照」（即真实函数）**永久写进端口字典**，此后端口 `__getattr__` 被字典短路：①后续对实现模块的补丁全部失效（跨测试污染，`test_plan008_context` 文件内 TestWorldBriefBudget 污染 TestNineWorldFacts / TestAssemblyZeroWrite 即此因）；②形式上看不出「打的是端口」，审计极易漏。**修法与铁律同前**：补丁目标一律改打实现模块（`app.application.world_engine.X`），端口读穿天然生效。

---

## 附录：上线前人工回归移交（D1，2026-09-30 登记）

**执行前提**：代码改动冻结（含本台账全部批次与三类架构债工作）后执行，避免返工。

**清单总册**（26 份，均需真实模型人工执行）：
- V1.x 主线：`docs/version/v1.0.0/v{3,4,5,6.5,7,7.5,7.8,8,8.5,9}/regression-checklist.md`
- V2.0.0 六 Phase：`docs/version/v2.0.0/phases/phase-{1..6}-*/regression-checklist.md`
- V2.1.0 ~ V2.6.1：`docs/version/v2.{1.0,2.0,3.0,4.0,5.0/planning-system,6.0}/regression-checklist.md`
- V3.0.0 / V4.0.0：`docs/version/v{3,4}.0.0/regression-checklist.md`（V3.0.0 验收报告为 CONDITIONAL — NOT RELEASED，含 G7 既存失败，执行前先确认是否已被后续版本消化）
- 横切：`docs/integrations/feishu/regression-checklist.md`

**自动化回归基线**（人工回归前的机械门槛）：全量 `pytest tests -q`，判据 = 失败集与基线一致（当前基线 18 failed，均为既存失败 + 3 例已知抖动性能测试，见 §15.2 与提交 `b461c4c`）。

**上线后例行观察**：无「过期记忆未回收」类反馈（记忆老化由 v2 decay 状态机承接）；`test_memory_e2e` 召回竞态已根修（等待谓词改为检索可见），若再现按真 bug 处理。
