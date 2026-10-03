# 全项目审查与下一步建议（2026-09-29）

> **性质**：全项目只读审查（不产码、不改架构）。对象 = 后端 `apps/backend/`（V1~V4.0.0）+ 移动端 `apps/mobile/`（V5.0.0）+ 文档台账（`docs/`）。
> **方法**：文档台账交叉核对（`docs/version/*`、`docs/refactor/*`、`docs/integrations/*`）+ 代码实测取证（全仓 grep / import 图 / 钉测常量），全部结论带 `file:line`。
> **依据**：`docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线）、各版本 `acceptance-report.md` / `regression-checklist.md`、`docs/version/v5.0.0/reviews/progress-audit-2026-09-29.md`。
> **基线**：分支 `feat/feishu_bot`；迁移链尾 `0002`（`tests/support/schema_pins.py:13`）；表数 `51`（同文件 `:15`）。
> **本文不含代码、不含 DDL、不含 UI 稿。**

---

## 0. 结论先行

1. **后端内核是「真材实料」，问题集中在三处**：① 两个版本悬空的发布门；② memory 域的历史残留与写入双通道；③ 移动端尚未收口的产品表面层。
2. **V3.0.0 与 V4.0.0 两份验收报告均为 `CONDITIONAL — NOT RELEASED`**。卡住的不是代码，而是三项「未执行的事」（真实模型人工回归、真实 PG 迁移空跑、基线失败口径澄清）。这是当前最大的隐性风险。
3. **发现 1 处 P0 级真缺陷**：`memories` 表存在两个同时活跃的写入入口，幂等键互不可见 → 同一事件可能落两条内容不同的记忆（**尚未连库验证**）。
4. **移动端存在 1 处硬阻塞**：本机 Flutter/Dart 工具链故障（子进程管道创建失败），`pub get` / `analyze` / `test` 全部不可用 → 任何需变更 Flutter 依赖的修复无法在本机完成。
5. **建议顺序**：先还清悬空账（阶段 A）→ 修工具链并收移动端尾巴（阶段 B）→ 清架构债（阶段 C）→ 最后才评估新功能（阶段 D）。

---

## 1. 项目现状

### 1.1 版本矩阵

| 线 | 版本 | 状态 | 说明 |
|---|---|---|---|
| 对话与角色基座 | V1 ~ V9 | 已实现 | 会话/流式、角色状态、场景连续性、长期记忆、情绪与关系、目标与意图、行为精修、自主行为、角色评估、运行时智能、世界状态、关系演化、行动能力 |
| 深化 | V2.0.0 ~ V2.6.1 | 已实现 | Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced；Character；World Simulation；Tool System；Planning System；Action Execution + Reflection |
| Agent 运行时 | **V3.0.0** | **CONDITIONAL — NOT RELEASED** | Agent Runtime（Run 台账 / Profile 注册表 / Trigger Router / LLM Gateway）。发布门剩 G7 口径（`docs/version/v3.0.0/acceptance-report.md` §未过项 I-2 / I-7） |
| 生活智能体 | **V4.0.0** | **CONDITIONAL — NOT RELEASED** | 用户实体 + 账本域（PLA-001~018）。发布门剩 A-1（真实模型 ≥50 笔核对）/ A-2（真实 PG 迁移空跑）/ A-3（CHECK 迁移补齐），见 `docs/version/v4.0.0/acceptance-report.md` §7 |
| 通道 | 飞书 | 已实现并真实链路验证 | `apps/backend/app/channels/feishu/`；多实例三项硬前置仅 1/3（见 §2.1-3） |
| 横切 | 邮箱验证码登录 / 身份收口 | 已实现 | Redis 验证码 + SMTP 发件；IDENT-001~009 默认用户概念整体退役 |
| 移动端 | **V5.0.0** | **进行中（约 39%）** | Flutter `apps/mobile/`，41 任务中真实现约 16 个；M4 健康段在 `PLT-001` 门控后未开工 |

### 1.2 三处悬空状态

| # | 悬空项 | 事实 | 后果 |
|---|---|---|---|
| 1 | V3.0.0 未发布 | G7「零回归全绿」不成立（既存 18 项失败）；零回归（相对基线）成立 | 版本停在「条件通过」，既存失败噪声长期污染回归判定 |
| 2 | V4.0.0 未发布 | G2 账目精确性人工核对未执行；G16 真实 PG 迁移未跑；A-3 CHECK 迁移未补 | 账本域（V5.0.0 记账页/首页的数据源）未经真实验证 |
| 3 | V5.0.0 无验收台账 | 41 个 Task Detail 状态行**全部为「未开工」**（2026-09-23 生成后未回写）；`tasks.md` 旧迁移号（0055~0058）未回写折叠事实；无验收报告 | 三个信息源（Detail 状态行 / `reviews/v5.0.0-code-review.md` 09-24 时点 / git log 实际进展）互相矛盾 |

### 1.3 V5.0.0 交付物实况

真实现合计 **16 / 41**（`docs/version/v5.0.0/reviews/progress-audit-2026-09-29.md` §1）：

| 里程碑 | 真实现 | 半成品 | 纯架子 / 门控 |
|---|---|---|---|
| M0 地基（8） | APP-001/002/003/006/007/008 | APP-004（drift 未接线）、APP-005（外部深链未配） | — |
| M1 对话（7） | API-001/002/003、APP-010/011 | APP-009（会话列表缺）、APP-012（mode 不上云） | API-001 配对码已退役（替代链路为真） |
| M2 生活域（9） | API-005/006、APP-017、APP-022 | API-004、API-007、APP-014、APP-016 | APP-015 |
| M3 主动（6） | APP-018 | API-008、APP-019/020/021 | — |
| M4 健康（5） | — | — | APP-024/025 + `health.py` stub；API-009/010、APP-023 按 D1 刻意留空 |
| PLT（6） | — | PLT-002/004/005 | PLT-003、PLT-006；PLT-001 探针就绪但结论未出，**门控仍关闭** |

---

## 2. 架构问题清单

### 2.1 P0 — 真问题，建议尽快处理

#### ① memory 域存在「写入双通道」（未验证的重复写入风险）

`memories` 表有**两个同时活跃**的写入入口：

| 入口 | 调用链 | 幂等键 |
|---|---|---|
| **v2 正门** | `app/application/post_process.py:148` `run_memory_extract` → `:168` `_run_memory_ingest_v2` → `:227` `_run_memory_evaluate_v2` → `memory2/evaluator._promote` | `memory_candidates.source_table + source_id` |
| **v1 旁路（世界）** | `app/application/world_engine.py:55` import → `:875` / `:921` `materialize_event_memory(...)`（实现于 `app/services/world/memory_bridge.py:58`） | `world_events.payload.memory_materialized` |
| **v1 旁路（行动）** | `app/application/action_engine.py:586` `memory_bridge.deliver(...)` | `effects.kind == "memory"` |

**两套幂等键互不可见**，而 v2 的摄取源（`world_events` / `action_records`）与旁路读的是**同一批行** → 同一个事件**可能落两条内容不同的记忆**（旁路写「用户在 X 月 X 日完成了 Y」，v2 写 `event.title`）。

- 台账：`docs/refactor/memory-domain-consolidation.md` §2.3（第 3 批，未执行）。
- **前置未做**：需连库查询确认重复行是否真实存在（同文件 §六 待人工验证项 1）。
- 动 `application/world_engine.py`（`tool007 FROZEN_SOURCES`）与 `application/action_engine.py`（`ZERO_DIFF_HASHES`）需显式声明 + 同步摘要。

#### ② Agent Runtime 名下存在「两套循环概念」

- **生产实际跑的**是 `app/application/agent_runtime/profiles.py:33` `_PROFILE_TABLE` 声明的 **Profile 阶段序列**（三个 run_kind：`foreground_chat` 9 段 / `autonomous_tick` 11 段 / `event_driven` 1 段）。
- **六段认知循环**（`observe` / `reason` / `plan` / `act` / `reflect` / `update`，实现于 `app/application/agent_runtime/stages/*.py`，方法在 `loop.py:414/427/457/473/492/506`）**未接入生产 `run()`**，仅在 `runtime_six_stage_loop_enabled=True` 时经 `loop.py:528` `_six_stage_enabled()` / `:531` `_run_six_stage_loop()` 触达（`loop.py:659-662` 为唯一分派点）。该开关默认 `False`（`app/core/settings/agent_runtime.py:42`）。

**性质**：这是 V3.0.0 的**显式裁决**（H-1 裁决 B，见 `docs/version/v3.0.0/architecture.md` 附「实现期裁决登记 D-1」），不是隐藏缺陷。但架构铁律「前后台共用同一认知循环、不得再出现平行编排路径」在事实层面是打折的——**两套循环概念长期并存是认知负担**，且六段实现会持续腐化（无生产流量覆盖）。

#### ③ 飞书多实例三项硬前置仅完成 1/3

| 前置 | 状态 |
|---|---|
| 入站去重落库 | ✅ 已实现（FEISHU-010，`feishu_dedupe_ledger` 表，`FEISHU_DEDUPE_PERSISTENT_ENABLED` 默认关闭） |
| **会话串行（跨进程）** | ❌ 仍为进程内 `asyncio.Lock`（`channels/feishu/adapter.py`） |
| **出站幂等落库** | ❌ 仍为进程内状态 |

**结论：三项不齐不得开多 worker**，即当前无法水平扩容。决策文档：`docs/integrations/feishu/multi-instance-options.md`。

### 2.2 P1 — 结构债，影响效率与可验证性

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| ④ | **`api → repositories` 反向依赖 7 处 / 6 文件** | `api/v1/action.py:12`、`action_execution.py:7`、`briefing.py:18`、`debug.py:47`、`debug.py:85`、`proactive.py:11`、`world.py:20` | 破坏「`api` 禁依赖 `repositories`」分层约定；V3.0.0 记录为 26 处，已清掉一部分 |
| ⑤ | **移动端本地存储层整体是死代码** | `core/storage/local_stores.dart:9` 的 `LocalStores` 在 `lib/` 内**零引用**（唯一提及是 `features/briefing/data/briefing_cache.dart:8` 的注释）；`AppCacheDb` 仅以 `NativeDatabase.memory()` 出现（`local_stores.dart:22` `openInMemory` + 测试） | 启动时无人打开**文件级** drift 库 → 离线缓存、导出落地、隐私页本地清空**全部卡住**。drift 7 表 / 3 仓储 / 重试队列全部未接进运行时 |
| ⑥ | **HEAD 基线测试不是绿的**（约 21~27 failed，集中 `tests/v24`） | `docs/version/v3.0.0/acceptance-report.md` §未过项 I-2；`docs/version/v5.0.0/reviews/progress-audit-2026-09-29.md` §9 | 「零回归」靠失败集 diff 对照成立，但每次改动都要做基线对照，成本高且易把 flaky 误判为回归 |
| ⑦ | **「过程卡」所需数据不存在** | `tool_step` 事件仅出现于 `api/v1/chat.py:18/19/59/115`（sink 绑定与下发）；`app/repositories/` 与 `app/core/db.py` 内**零命中** → 不落库、无读面 | 设计稿核心差异化体验（对话/记账过程卡）无法真实实现，历史会话过程无法复原 |
| ⑧ | **memory2 命名与类型亲和映射双版** | `memory2/retriever.py::QUERY_TYPE_KEYWORDS`（键为 v2 规范名）vs `memory2/types.py::TYPE_AFFINITY_KEYWORDS`（键为遗留名） | 同一份映射的新旧两版；合并会改变 `evaluator._type_affinity` 评分行为，需单独评估 |
| ⑨ | **v1 记忆尸体未清** | `services/memory_service.py` 生产**零引用**（仅 `memory2/types.py:38` 与 `planning/memory_policy.py:113/437` 的 docstring 提及）；`relationship_memory.py`、`planning/memory_policy.py` 写入路径同为死代码 | 目录语义混淆，新人易误入旧路径 |

### 2.3 P2 — 已知登记，不急

| # | 问题 | 说明 |
|---|---|---|
| ⑩ | ORM 集中 `core/db.py`（44 表）+ `app/models/` Pydantic 领域模型 | 边界靠约定无显式约束，新增表需人工判断落位 |
| ⑪ | settings 扁平命名空间（423 字段） | 局部可读性下降（未采纳的建议） |
| ⑫ | `ActionExecutor.execute_external` 返回 `external_adapter_reserved` 占位 | `app/services/action/executor.py:169`；外部 API 实际经 Tool 路径实现，`external` ExecutionKind 是保留桩 |
| ⑬ | 调试面无多用户隔离 | `/debug/*`、`/state` 可任意指定 `user_id` 查看他人数据（产品面已隔离） |
| ⑭ | 文档 1589 处 `vXX_` 引用未改写 | 历史文档不改写是约定（原「旧名→新名」对照表已于 2026-10-03 删除） |
| ⑮ | 测试侧版本标记残留 188 处 | fixture / 函数名如 `v24_tool_env`、`v21_on` |

---

## 3. 下一步推进建议

### 阶段 A · 收口两个悬空版本（最高优先，不写新代码）

| 动作 | 出处 | 判据 |
|---|---|---|
| V4.0.0 发布门 ①：真实模型 ≥50 笔账目精确性人工核对 | `acceptance-report.md` §7 A-1 / `regression-checklist.md` §2 | 零幻觉数字，样本表填毕 |
| V4.0.0 发布门 ②：真实 PostgreSQL `alembic upgrade head` 双向空跑 | 同 §7 A-2 / G16 | PG 用例非全 skip |
| V4.0.0 发布门 ③：补生产库 `ck_loop_runs_kind` / `ck_character_goals_domain` CHECK 迁移 | 同 §7 A-3 | 或回滚 ORM CHECK 与生产一致 |
| V3.0.0 G7 口径澄清：既存 18 项失败「清零」或「显式豁免并登记」 | `v3.0.0/acceptance-report.md` §未过项 I-2 | 口径定稿后改判 RELEASABLE |
| 回写 v5.0.0 的 41 个 Task Detail 状态行 + 修正迁移号描述 + 补验收台账 | `progress-audit-2026-09-29.md` §3 | 三个信息源不再互相矛盾 |

### 阶段 B · 修工具链，收移动端 M2/M3 尾巴

| 动作 | 说明 |
|---|---|
| **修复本机 Flutter/Dart 子进程管道故障** | 根因已定位：flutter_tools 在 `generateCommands` 阶段执行 `where.EXE aapt` 时子进程创建失败（`process_win.cc:744`）。疑 EDR hook，或在另一台可用机器上执行依赖变更 + 全量 `flutter test`。**这是当前移动端唯一硬阻塞** |
| drift 运行时接线 | 打开文件级 `AppCacheDb`（需把已在 lock 的 `path_provider` 提为直接依赖）→ 解锁离线缓存 / 导出落地 / 隐私页本地清空（问题 ⑤） |
| 简报契约重写 | 按 `tasks/API-008.md` 冻结规格：补 `period_key`、11 字段契约、`date` 参数、冻结逐字文案（当前契约差距很大，属整套重写） |
| `tool_step` 持久化 + 按 conversation 读面 | 解锁过程卡（问题 ⑦），同时影响对话页与记账页 |
| 产品裁决：首页「今日预算 ¥200」 | 设计稿写日预算，但 `services/ledger/budget.py::BudgetSpec.period` **只有 `month` / `week` 无 `day` 档** → 需裁决：改本月口径 / 新增日预算概念 / 明确 200 为配置默认值。**裁决前不应臆造日额度** |
| ResultCard / `sessions` 收口 | `ResultCard` 零使用（`design_system/components/proc_card.dart:274` 仅定义）；会话列表 `sessions` 从未写入 |

### 阶段 C · 架构债清偿

| 动作 | 说明 |
|---|---|
| memory 域第 2 批：`services/memory2/` → `services/memory/` 改名 + 删 v1 尸体 | 影响 ~297 处测试 import；必须同步 `tests/conftest.py::_SERVICE_DB_MODULES`（8 项 memory2 登记）与 `v21/test_agent008_review_fixes.py::DOMAIN_MODULES`。有利条件：`memory2/__init__.py` 是 0 字节空文件 |
| memory 域第 3 批：写入双通道收敛（问题 ①） | **前置**：先连库验证重复行；行为语义变化（同事件从「可能落 2 条」变「落 1 条」），属产品可感知变更 |
| 飞书多实例硬化（问题 ③） | 会话串行改 PG advisory lock；出站幂等落库。**若多实例在路线图则必须做，否则不做** |
| 基线失败清零或正式豁免登记（问题 ⑥） | 与阶段 A 的 V3.0.0 G7 口径同源，一并处置 |
| `api → repositories` 反向依赖清理（问题 ④） | 7 处 / 6 文件，V4.0.0 §7 A-4 记为 Backlog |
| Agent Runtime 双循环收编（问题 ②） | 二选一：①「方案 A 真收编」——把六段接入生产并删 Profile 分支（前置条件见 `v3.0.0/architecture.md` 附 D-1）；② 反向收口——承认 Profile 阶段序列为唯一循环，删除或明确隔离六段影子实现 |

### 阶段 D · 新功能（需产品裁决后立项）

全部为「扩展点已声明、代码未落地」，非新增构想。

---

## 4. 新功能候选

| 候选 | 为什么值得做 | 现状 / 出处 |
|---|---|---|
| **服务端推送（FCM / APNs）** | 目前「主动关怀」只有本地通知 + 飞书两条腿，系统级触达缺失；设计稿 08:00 早间简报即推送语义 | 决策 D4 明确列 V1.1，**未立项**（`requirements-analysis.md` §6） |
| **Episodic / Semantic 记忆双通道** | 产品差异化核心是「有长期记忆的 AI」。当前是扁平 7 类型 + 反思/成长上层 | 底座已具备（`memory_candidates` 四源摄取、embeddings、混合检索）；上层未建。基线 §8.2 / §11.2 |
| **Self Improvement 闭环** | `agent_metric_snapshots` + `agent_evolution_worker` 已有指标快照与人格编译骨架 | 骨架就位，闭环未合。基线 §11.1 |
| **关系等级产品读接口** | 移动端「我的」页要显示关系等级，现仅 `/debug/relationship/*`，`APP-020` 只能用占位文案 | N2 缺口，已登记 **V5.1** |
| **多通道（Discord / Telegram / 微信）** | `channels/base.py` 契约 + 身份派生 + 出站端口均已为多通道预留，新增通道只需实现 adapter | 微信已有可行性调研（`docs/integrations/wechat/feasibility-review.md`） |
| **评估闭环统一** | 规则 + LLM Judge 双路评估骨架已存在，离线/在线评估未统一 | 基线 §11.3 |
| 语音输入 / 票据 OCR / 多币种 | 移动端输入栏已留语音入口（P2）；账本域单币种 | 全部在 Backlog（`v4.0.0/tasks.md` §Out of Scope） |

---

## 5. 待人工验证项（本文结论依赖，但未执行）

| # | 事项 | 为什么必须人工做 |
|---|---|---|
| 1 | **重复记忆查库**：对同一 `world_events` / `action_records` 行，确认 `memories` 表是否存在旁路与 v2 各写一条的重复行 | 问题 ① 第 3 批的前置；静态读码无法判定运行时是否真发生 |
| 2 | V4.0.0 真实模型 ≥50 笔账目核对 | 发布硬条件（A-1） |
| 3 | 真实 PG `alembic upgrade head` 双向空跑 | 发布硬条件（A-2）；本地无可用 `TEST_DATABASE_URL` 时会静默 skip |
| 4 | `PLT-001` 手环实机验证 | 结论直接决定 M4 排期与首页三宫格形态；探针已就绪（`apps/mobile/docs/plt001-probe.md`） |
| 5 | 移动端 `flutter analyze` / `flutter test` | 本机工具链故障，现有移动端结论**全部为静态读码**，类型与签名问题抓不到 |

---

## 6. 附录：证据与复现命令

### 6.1 关键取证命令

```bash
# api → repositories 反向依赖（应为空）
grep -rn "from app.repositories" apps/backend/app/api/

# tool_step 是否有落库 / 读面（repositories 与 db.py 内应为空）
grep -rn "tool_step" apps/backend/app/repositories/ apps/backend/app/core/db.py

# memory 双通道调用点
grep -n "materialize_event_memory" apps/backend/app/application/world_engine.py
grep -n "memory_bridge.deliver" apps/backend/app/application/action_engine.py

# v1 记忆尸体（生产零引用，应仅剩 docstring）
grep -rn "memory_service" apps/backend/app/ --include=*.py

# 移动端本地存储层死代码（lib/ 内应无 LocalStores 引用）
grep -rn "LocalStores" apps/mobile/lib/

# 六段循环开关默认值
grep -rn "runtime_six_stage_loop_enabled" apps/backend/app/

# 钉测常量（迁移链尾 / 表数）
grep -n "MIGRATION_HEAD\|SCHEMA_TABLE_COUNT" apps/backend/tests/support/schema_pins.py
```

### 6.2 取证快照（2026-09-29）

| 项 | 实测值 |
|---|---|
| 迁移链尾 | `0002`（`tests/support/schema_pins.py:13`） |
| 表数 | `51`（同文件 `:15`） |
| 迁移文件数 | 3（`0001_squashed_full_schema.py` / `0002_briefing_preferences.py` / `__pycache__`） |
| `api → repositories` 反向依赖 | 7 处 / 6 文件 |
| `tool_step` 落库点 | 0 |
| `memory_service` 生产引用 | 0（仅 docstring） |
| `runtime_six_stage_loop_enabled` 默认 | `False`（`app/core/settings/agent_runtime.py:42`） |
| 未提交改动 | 1 个（`apps/mobile/dart_defines/dev.json`） |

### 6.3 相关文档索引

| 主题 | 文档 |
|---|---|
| 当前系统架构唯一基线 | `docs/current-system-architecture-baseline.md` |
| V3.0.0 验收与未过项 | `docs/version/v3.0.0/acceptance-report.md` |
| V4.0.0 验收与缺陷 | `docs/version/v4.0.0/acceptance-report.md` |
| V5.0.0 实现度审查 | `docs/version/v5.0.0/reviews/progress-audit-2026-09-29.md` |
| V5.0.0 代码质量审查 | `docs/version/v5.0.0/reviews/v5.0.0-code-review.md` |
| memory 域合并审查台账 | `docs/refactor/memory-domain-consolidation.md` |
| 剩余开关阀门审查 | `docs/refactor/remaining-flag-audit.md` |
| 飞书多实例方案 | `docs/integrations/feishu/multi-instance-options.md` |
| 微信通道可行性 | `docs/integrations/wechat/feasibility-review.md` |
| 测试规范 | `docs/TESTING.md` |

---

> **文档结束**。本文为一次性全项目审查产物，不替代各版本 `acceptance-report.md` / `regression-checklist.md`；架构演进的唯一依据仍为 `docs/current-system-architecture-baseline.md`。
