# memory 迁移脚本与版本号命名审查

> 审查日期：2026-10-15 ｜ 分支：`feat/feishu_bot` ｜ 性质：**只审查，未改代码**
> 触发：`app/services/memory/migration.py` 作用不明 + 发现 `V2_MEMORY_TYPES` 一类版本号命名
> 范围：`apps/backend/app`（含 `scripts/`、`tests/` 交叉引用核对）
> 依据：`docs/version/v2.0.0/phases/phase-4-relationship/task-details/REL-001.md`、`docs/current-system-architecture-baseline.md`

---

## 一、结论速览

| # | 问题 | 定性 | 严重度 | 建议 |
|---|---|---|---|---|
| 1 | `memory/migration.py` 有实现、**无任何生产入口** | 悬空能力（REL-001 承诺的 ops 脚本从未创建） | 中高 | 补 `scripts/migrate_relationship_memory_types.py`（推荐），或删库 |
| 2 | `V9_ERROR_TEXT` | **死代码**（全仓含 docs 零引用） | 低 | 删除 |
| 3 | `V4_EXTRACTOR_PROMPT` | 名称带版本 **+ 正文口径过期** | 中 | 改名 + 复核正文 4 类口径 |
| 4 | 关系维度常量三份副本 + `_V85` 后缀 | 重复定义 + 版本后缀 | 中 | 收敛为一处，去后缀 |
| 5 | `V2_MEMORY_TYPES` / `V1_STATUS_TARGETS` | 名称带版本号 | 低 | 择机改名（成本见 §4） |
| 6 | 测试符号名 `V30_ENABLED_FLAGS` 出现在生产 docstring | 跨层泄露 | 低 | 改 docstring 措辞 |

**判定依据（规则基线）**：`AGENTS.md` 只禁止 **settings 字段 / env 键**带版本前缀（`vXX_` 体系 2026-09-19 已删）。上述符号均为**常量 / 字符串**，不属规则违规，属**命名卫生**问题——但与已清理的 `vXX_` 是同一类味道（历史版本号泄漏进稳定标识符）。

---

## 二、`migration.py` 的作用与问题

### 2.1 它做什么

REL-001（V2.0.0 Phase 4 关系域）交付的「v1 遗留 `relationship_event` 记忆 → `relationship_fact`」**一次性存量迁移逻辑**，共 3 个函数：

- `collect_report()` — dry-run 报告（待迁移行数 / per-user 分布 / 创建时间分布 / 无 `source_ref` 行数 / replay 影响预估）；
- `apply_migration(batch_size=500)` — 分批 `UPDATE memories SET type=...`，条件命中、重跑零行（幂等）；**只动 type 列**；
- `_verify()` — 迁移后自检（剩余行数 + 别名映射 + 亲和归一）。

语义背景：v1 时代 `relationship_event` 与 v2 `relationship_fact` 是**同一叙事事实的双真相源**；迁移把存量行归一到 v2 类型，检索语义由 `LEGACY_TYPE_ALIASES`（`types.py:21`）保证不变。

### 2.2 为什么"看不出作用"——它没有入口

全仓引用**只有两处，都在测试侧**：

| 引用点 | 用途 |
|---|---|
| `tests/conftest.py:45` + `:195` | import 为 `memory_migration`，登记进 `_SERVICE_DB_MODULES`（把其模块级 `SessionLocal` 重定向到内存 SQLite） |
| `tests/v2/test_rel001_truth_source.py::TestLegacyMigration` | 唯一真实调用 `collect_report()` / `apply_migration()` 的地方（3 个用例） |

**没有** `if __name__ == "__main__"`、没有 argparse、没有 CLI、没有 debug 路由、没有 `scripts/` 包装。而 REL-001 Task Detail §3 明确要求新增 `scripts/migrate_relationship_memory_types.py`（默认 dry-run、`--apply`、分批 500、双读校验窗口）——**该脚本不存在**（`scripts/` 下无此文件，仅 `migrate_owner_id_to_email.py` 等同族脚本）。

→ 结论：这是**「有实现、无 runner」的悬空能力**。生产库要真跑，只能手写
`python -c "from app.services.memory.migration import apply_migration; ..."`。

**附带缺口**：设计 §3 要求的**双读校验**（`memory_service.retrieve` vs `memory2.retriever.retrieve` 同 query 命中集合对比）**未实现**——`_verify()` 只做剩余行数 + 别名映射 + 亲和归一三项。且设计里作为对比对象的 `memory_service` 已随 T-33 退役，`memory2/` 包也已并入 `services/memory/`，**该验收项已无法按原文执行**，须重新指定对比对象。

### 2.3 迁移前提是否仍成立

- v1 直写旁路（`relationship_memory.py` / `state_service.py`）已于 2026-09-29 删除（`TestV1BypassGate` 钉住文件不存在）。
- 但**不能断言存量已冻结**：`MemoryType` Literal 与 DB check 仍含 `relationship_event`，且 `memory_repository.create_memory()` 的两个直调点未在写入口归一——
  - `services/action/capabilities/memory.py:49`：`memory_type = params.get("memory_type", "user_fact")`（值来自动作参数，schema 仅文档串，无枚举校验）；
  - `services/planning/memory_policy.py:362`：`memory_type=chosen.type`（来自上游候选/计划）。
  即理论上仍可能有新行以遗留类型落库，迁移集合非严格收敛。
- 已确认**非** memory 类型的 `relationship_event` 同名物（勿混淆）：`conversation/state.py:245/253`、`observability/collector.py:32/80` 是 **trace 步骤名**；`relationship/shared.py:52` 是叙事条目 `kind`。

### 2.4 执行迁移的隐性影响（须告知评审）

`conversation/state.py::_replay_relationship_memories`（L453-464）仍按 `memory.type == "relationship_event"` 筛选 `state.memories`，而 `memory_repository._to_memory`（L14-30）**直传原始 `row.type`、未归一**。因此迁移后该回放路径命中 0 行 → `memory_replay` 事件归零、`rel_replay_discount` 补记停止。这正是 `migration.py` docstring 声明的「叙事/数值解耦的预期结果」，非缺陷——但它是**行为变更**，dry-run 报告已有 `replay_source_rows` 字段承载，须显式出示。

### 2.5 建议（按推荐排序）

| 选项 | 动作 | 适用前提 |
|---|---|---|
| **A（推荐）** | 新增 `scripts/migrate_relationship_memory_types.py`：argparse 默认 dry-run 打印 `collect_report()`，`--apply` 调 `apply_migration()`，`--batch-size`；补双读校验（对象改为现存检索入口） | 存量行数 > 0 |
| B | 删 `migration.py` + 3 个用例，REL-001 台账标注「存量窗口已关闭」 | 存量行数 = 0 |
| C | 保留现状，但文件头 docstring 与 REL-001 文档标注「仅库、无入口，需手写 runner」 | 暂不决策 |

**前置动作**：先对生产库跑
`SELECT count(*) FROM memories WHERE type='relationship_event'`（以及 `important_event`），
用真实数字决定 A/B，勿凭推测。

---

## 三、版本号命名盘点

### 3.1 需处理（7 处）

| 符号 | 位置 | 语义 | 引用数 | 定性 | 建议名 |
|---|---|---|---|---|---|
| `V2_MEMORY_TYPES` | `services/memory/types.py:9` | 7 类**规范**记忆类型（数据词表，非版本门控） | 49 | 无 V3 类型集，「V2」永远指不到东西；语义实为「权威/规范」 | `CANONICAL_MEMORY_TYPES` |
| `V1_STATUS_TARGETS` | `models/goal.py:179` | 扁平（`layer=NULL`）目标状态机出口集 | 14 | 「V1」实指「legacy 行」，非版本门控 | `LEGACY_STATUS_TARGETS` |
| `RELATIONSHIP_DIMENSIONS_V85` | `core/constants.py:9` | 6 维关系维度 | 36 | 「V85」= V8.5 加维历史 | `RELATIONSHIP_DIMENSIONS`（6 维），旧 4 维降为 `LEGACY_…` |
| `V4_EXTRACTOR_PROMPT` | `prompts/extractor.py:1` | 记忆提取 prompt | 6 | 名称带 V4；**正文仍写「仅以下 4 类」且含 2 个 v1 遗留类型** | `MEMORY_EXTRACTOR_PROMPT` |
| `V9_ERROR_TEXT` | `capabilities/search.py:38`、`capabilities/notification.py:33` | 无任何引用（全仓含 docs） | 0 | **死代码**（两文件各定义一份同值常量，无人消费） | 删除 |
| `V30_ENABLED_FLAGS` | `tests/v40/support.py:21` | V3.0.0 冻结开关基线（测试侧） | 测试侧 3 处 | 测试侧可接受；但 `core/settings/evaluation.py:35` 的生产 docstring 引用了它 | 生产 docstring 改述为「由 V4.0 测试基线冻结」 |
| `"v9_execution_chain"` | `engines/decision.py:392` | 决策 `reason` 字符串值 | 1 | 可观测数据里带版本号 | 语义化（如 `delegated_to_execution_chain`） |

### 3.2 `V4_EXTRACTOR_PROMPT` 的正文问题（比命名更值得看）

`prompts/extractor.py:4` 写「记忆类型（**仅以下 4 类**，不要创造其他类型）」，列的是
`user_preference / user_fact / important_event / relationship_event`——**2 个是 v1 遗留类型**，
而存储词表是 9 值（7 规范 + 2 遗留）。后果：经此 prompt 的 LLM **永远产不出**
`commitment` / `milestone_event` / `behavior_pattern` 三类（它们只能由规则/其他通道产生）。
该 prompt 仍在使用（`application/post_process.py:186` → `chains/extractor_chain.py`）。
→ 须确认这是**有意保守**还是**漏更新**；若是后者，属**语义缺口**而非命名问题。

### 3.3 关系维度常量的三份副本

| 位置 | 内容 | 状态 |
|---|---|---|
| `core/constants.py:7` `RELATIONSHIP_DIMENSIONS` | 4 维 | **死常量**（无任何 import 者） |
| `services/conversation/state.py:37` `RELATIONSHIP_DIMENSIONS` | 4 维（本地副本，遮蔽同名） | 仅 `_replay_relationship_memories` 用（v1 回放路径） |
| `services/evaluation/context/collectors.py:281` `_RELATIONSHIP_DIMENSIONS` | 6 维（与 `_V85` 同值不同名） | 评估上下文用 |
| `core/constants.py:9` `RELATIONSHIP_DIMENSIONS_V85` | 6 维 | 6 处 import，事实上的当前真源 |

即「4 维死常量 + 4 维本地副本 + 6 维副本 + 6 维 `_V85`」四份，收敛后可只留一份 6 维 + 必要的历史注释。

### 3.4 不算问题（正当版本号）

`app/api/v1/`（API 版本，正当）、`docs/version/vX.Y.Z/`（文档按版本归档）、`migrations/versions/0001_*`（Alembic）、`tests/v2|v22|v25|v30|v40|v50|v60|v8.5`（测试按版本归档）。

---

## 四、改名成本提示（防误伤）

- `V2_MEMORY_TYPES`（49 处）与 `RELATIONSHIP_DIMENSIONS_V85`（36 处）均被**测试硬编码钉住**：
  - `tests/v60/test_memory_type_vocabulary.py`（断言 `LEGACY_MEMORY_TYPES` 值、`LEGACY_TYPE_ALIASES` 表）、`tests/v2/test_rel001_truth_source.py`、`tests/v2/test_mem012_types.py`；
  - 关系维度面：`tests/unit/test_relationship_model.py` 等。
- 改名须**同批**改：`app/` 源码 + 上述测试 + 3 个 `.md`（含 `prompts/builder.py:52` 的 docstring 引用）。
- 若涉及冻结摘要面（`FROZEN_SOURCES` / `ZERO_DIFF_HASHES`），先 `grep` 确认目标文件是否在冻结清单内再动手。

---

## 五、建议动作优先级

| 优先级 | 动作 | 风险 |
|---|---|---|
| **P0** | 查存量行数 → 决策 `migration.py` 去留（§2.5 A/B/C） | 需连生产库只读查询 |
| **P1** | 删 `V9_ERROR_TEXT` 死代码（2 文件 2 行） | 极低 |
| **P1** | 复核 `V4_EXTRACTOR_PROMPT` 正文 4 类口径（潜在语义缺口） | 需产品口径确认 |
| **P2** | 关系维度常量收敛 + 去 `_V85` 后缀（顺带删 `constants.py:7` 死常量） | 中（36 处 + 测试钉） |
| **P2** | 重命名 `V1_STATUS_TARGETS` / `V2_MEMORY_TYPES` | 中（14 / 49 处 + 测试钉） |
| **P3** | 清 docstring 里的 `V30_ENABLED_FLAGS` 引用、`"v9_execution_chain"` 字符串 | 低 |

---

## 六、未改动声明

本次为**只读审查**，未修改任何源码、配置或测试。以上所有结论均基于当前工作区实际文件内容与引用统计。

---

## 七、执行记录（2026-10-15 回填）

> 决策前提：**数据库可删除重建** → 无存量行可迁，`migration.py` 采 §2.5 **选项 B**（删除）；
> §3.1 六项版本号命名按「全仓同批改名」执行。本节为事后回填，前六节保留审查时原样。

### 7.1 migration.py（§2.5 B）

| 动作 | 落点 |
|---|---|
| 删除模块 | `app/services/memory/migration.py`（83 行） |
| 删除用例 | `tests/v2/test_rel001_truth_source.py::TestLegacyMigration`（3 用例）+ 文件头注 |
| 移除测试登记 | `tests/conftest.py`（`memory_migration` import + `_SERVICE_DB_MODULES` 项） |
| 台账更正 | `docs/version/v2.0.0/phases/phase-4-relationship/task-details/REL-001.md` 与同目录 `tasks.md` 就地加注「存量窗口关闭」 |

**未做（理由）**：§2.4 的 `_replay_relationship_memories` 回放源影响面已随「无存量行」消失，
不另补 runner / 双读校验；`MemoryType` Literal 与 DB check 的遗留 2 值保持（写入口仍可能产生遗留类型行，
归一化在 `normalize_type`，属另一议题）。

### 7.2 命名改名（§3.1 七项全清）

| 旧名 | 新名 | 备注 |
|---|---|---|
| `V2_MEMORY_TYPES` | `CANONICAL_MEMORY_TYPES` | `services/memory/types.py` 及其全部引用面 |
| `V1_STATUS_TARGETS` | `LEGACY_STATUS_TARGETS` | `models/goal.py` |
| `RELATIONSHIP_DIMENSIONS_V85` | `RELATIONSHIP_DIMENSIONS`（6 维） | `core/constants.py` 成为唯一真源 |
| （旧 4 维）`core/constants.py::RELATIONSHIP_DIMENSIONS` 死常量 | 删除 | 无 import 者（§3.3） |
| （旧 4 维）`services/conversation/state.py` 本地副本 | `LEGACY_RELATIONSHIP_DIMENSIONS` | 仅 v1 回放路径消费，语义不变 |
| （旧 6 维）`collectors.py::_RELATIONSHIP_DIMENSIONS` 副本 | 删除，改 import 真源 | §3.3 四点收敛为一份 |
| `V4_EXTRACTOR_PROMPT` | `MEMORY_EXTRACTOR_PROMPT` | **正文未动**（见 7.5） |
| `V9_ERROR_TEXT` | 删除 | 两文件各一行死代码（§3.1） |
| `V30_ENABLED_FLAGS`（测试侧） | `BASELINE_ENABLED_FLAGS` | 比建议更进一步：测试符号一并改名，生产 docstring 同步 |
| `"v9_execution_chain"`（`decision.reason`） | `"delegated_to_execution_chain"` | 仅影响新落库观测值；旧值随库重建消失 |

**钉测同步**：`tests/v60/test_memory_type_vocabulary.py::PRESERVED_FUNCTION_DIGESTS["normalize_type"]`
摘要随函数体内改名刷新（`4917df56b1930afc` → `4231c001f40ea05e`，已加声明注释，逻辑不变）。

**文档同步**：`docs/version/v6.0.0/tasks/MEV-003.md` / `MEV-005.md` 改用新名（当前版本、MEV-005 未开工，
其 Preserve 断言按新名生效）；§3.4 所列正当版本号未动；历史版本文档（`v2.5.0/PLAN-001`、`v4.0.0/PLA-014`
`/PLA-018`、`v4.0.0/reviews/*`、`docs/backend-test-audit-2026-10-09.md`）按 `docs/TESTING.md` §9 惯例
**保留旧名，视为当时的记录**。

### 7.3 写入口归一（T2a，2026-10-15 追加）

针对 §2.3「两处 `create_memory()` 直调点未在写入口归一」——库可重建只消除了存量负担，
不堵写入口则仍会产生新的遗留类型行。本轮两处均已收口：

| 落点 | 动作 |
|---|---|
| `app/services/action/capabilities/memory.py` | `parameters["memory_type"]` 先经 `normalize_type` 归一（遗留名不落库）；表外取值 fail-closed 返回 `permanent` 失败，不再放行到仓储 `ValueError` |
| `app/services/planning/memory_policy.py::_persist` | 落库前 `normalize_type(chosen.type)`；非法类型记 warning 并 `return None`（与「政策闸丢弃」同语义，不回滚计划终态） |
| 契约面 | 边界表 / 候选 / 决策结构**零改动**（工具侧 `BOUNDARY_TABLE`、计划侧 `PLAN_MEMORY_BOUNDARY_TABLE` 仍写遗留名，冻结钉测照旧通过）；只有**落库行**变为规范类型（`important_event → experience`） |

**同步的测试**：`tests/v25/test_plan009_gate.py`（落库类型断言改为 `experience`）、
`tests/v25/test_plan009_step_criteria.py`（跨域导入面清单 +`types`，附声明）、
`tests/v24/test_tool010_e2e.py`（`capabilities/memory.py` 冻结摘要 + 声明）、
新增 `tests/unit/test_capabilities.py::test_memory_save_normalizes_legacy_type` /
`::test_memory_save_unknown_type_fails_closed`。

> 未覆盖（有意）：ingest 通道的 `proposed_type="important_event"/"relationship_event"`
> （`services/memory/ingest.py:248/283`）**已经**在 evaluator 转正时归一（`_final_type`），
> 属既有正确面，未动。

### 7.4 既存失败清账（T3，2026-10-15 追加）

前一轮验证记录的失败经 HEAD 干净副本对照后逐条定性并**全部清除**（共 25 条）：

| 组 | 条数 | 性质 | 处置 |
|---|---|---|---|
| `tests/v25/test_plan011_debug_api.py` | 19 | 测试过期：调试面自 v5.0.0 身份收口起经 `require_user`，而本模块源码不含 `app.main` 字面量，命中不了 `conftest::_mark_app_based` 的自动鉴权 override | 模块内新增 autouse `_auth_override` 显式安装 override |
| `tests/v25/test_plan_approval_gate.py::test_plans_endpoints_require_token` | 1 | 测试过期：断言真实 401，但 conftest 已装默认 override | 用例内自清 override（同 `tests/v50/test_identity_cutover.py::real_auth` 口径） |
| `tests/v51/test_car_api.py::test_car_profile_derives_age_and_paid_ratio` | 1 | **日历腐烂**：写死 `2024-06-15` → 断言「2 年 3 个月」，过 9 月即变 4 个月 | 购买日期改为「今天 − 27 个月」锚定（正午规避时区跨日） |
| `tests/v24/test_tool010_e2e.py`（冻结摘要） | 3 | 2 条旧账（`chat_pipeline.py` / `builder.py` 改文件时漏同步摘要，HEAD 即红）+ 1 条本次改名/归一改脏（`decision.py` / `capabilities/memory.py`，合计 4 条目） | 逐条同步 `ZERO_DIFF_HASHES` 并附声明注释（原值保留） |
| `tests/v24/test_tool012_bans.py::test_session_tables_zero_structural_change` | 1 | 旧账：表集随 `0002~0009` 增量迁移合法增长，本摘要漏同步 | 同步 `tool012_support.SCHEMA_TABLE_SET_DIGEST`（核对现表集 57 张与 `schema_pins.SCHEMA_TABLE_COUNT` 一致后） |

定性方法沿用 `docs/TESTING.md` §10.1：在 `git archive HEAD` 干净副本上跑同一批用例取基线失败集，
`A - B` 为空者判既存，非本次改动引起。

### 7.5 遗留决策项（未执行）

| 项 | 状态 | 阻塞点 |
|---|---|---|
| §3.2 `MEMORY_EXTRACTOR_PROMPT` 正文「仅以下 4 类」且含 2 个遗留类型 | **未改** | ① 属语义口径（LLM 产不出 `commitment` / `milestone_event` / `behavior_pattern`）非命名问题；② 正文受 `tests/unit/test_prompt_golden.py` 快照钉住，改动须同批更新 golden；③ 需确认「有意保守」还是「漏更新」 |
| 遗留 2 类型的**完整退役** | **未改** | §7.3 只堵了写入口（新行不再落遗留类型）；退役还牵动 `MemoryType` Literal、`ck_memories_type`（需新迁移，**取号须排 `MEV-005` 的 `0010` 之后**）、别名表 / 标签表、读侧归一与 v1 回放路径（`conversation/state.py::_replay_relationship_memories`），属独立任务 |

### 7.6 验证（终态）

| 范围 | 命令 | 结果 |
|---|---|---|
| 聚焦 | `pytest tests/v60/test_memory_type_vocabulary.py tests/v40 tests/unit/test_relationship_model.py tests/unit/test_prompt_golden.py` | 首次 360 passed + 1 failed（`normalize_type` 摘要）→ 同步后该文件 31 passed 全绿 |
| 写入口归一（聚焦） | `pytest tests/unit/test_capabilities.py --run-legacy tests/v25/test_plan009_step_criteria.py tests/v25/test_plan009_gate.py tests/v25/test_plan009_candidate.py` | **69 passed** |
| Fast | `pytest -m "(unit or api) and not slow"` | **2300 passed**（中间一轮的 2 条 setup `ERROR` 隔离重跑 2/2 通过 → §10.2 环境噪声） |
| Integration | `pytest -m "integration and not slow"` | **1220 passed / 5 skipped**（含清账后的 v51 车辆域） |
| 历史套件（全部受影响域） | `pytest --run-legacy tests/v2 tests/v8.5 tests/v24 tests/v25 tests/v26` | **3560 passed / 7 skipped / 0 failed** |

**失败集对照（TESTING.md §10.1）**：本次改动引入的失败只有两类——改名触发的 2 处钉测摘要
（`PRESERVED_FUNCTION_DIGESTS["normalize_type"]`、`ZERO_DIFF_HASHES[decision.py / capabilities/memory.py]`）
与 1 条静态导入面清单（v25 plan009），全部按 §11.3 同步并附声明；其余 25 条经 HEAD 副本对照判为既存，
已按 §7.4 逐条清除。
