# memory 域双套（memory / memory2）合并审查与清理台账

> **审查对象**：`apps/backend/app/services/memory2/`（14 模块）与 `app/services/memory_service.py` 等 v1 模块并存的「两套记忆域」
> **审查范围**：仅 `apps/backend`；`docs/` 按约定不纳入改动面
> **本文数据**：均为**实测**（全仓 grep 调用点核对 + 真实 import 图 + `git worktree` 基线对照），非估算
> **权威依据**：`docs/version/v2.0.0/version-boundary.md` §1 L12 裁决 / §3 L38 禁止事项
> **审查与执行日期**：2026-09-29

---

## 一、执行摘要

### 1.1 结论

**这不是「两套平行系统需要合并」，而是一次已完成的 v1 → v2 替换，留下了未清理的 v1 尸体。**

读写主干**已 100% 在 v2**：

| 路径 | 入口 | 实际走向 |
|---|---|---|
| **读** | `services/context_builder.py:257` | `memory2_retriever.retrieve()` |
| **写** | `application/post_process.py::run_memory_extract` | `_run_memory_ingest_v2` + `_run_memory_evaluate_v2` |

v1 的 `memory_service.extract_and_save` / `retrieve` / `select_for_context` **生产零调用**（仅测试引用）。

`version-boundary.md` 早已预留清理窗口，本次只是执行它：

> `memories` 表 + `memory_service/memory_policy/memory_conflict` | **Extend + Replace(路径)** | v2 新 `memory2/` 服务为 Flag 内替换路径，**旧代码保留一个观察期后清理** —— §1 L12

> 任何 Task 不得删除 v1 代码路径（**清理统一在 v2 全量稳定一个版本后单独执行**）—— §3 L38

v2 已从 V2.0.0 全量推进至 V5.0.0，**观察期已过**。

### 1.2 v1 残留分三类，处理方式完全不同

| 类 | 内容 | 处置 |
|---|---|---|
| **① 死代码** | 生产零调用的函数、整文件、死导入、空转循环 | **删除** |
| **② 活的共享件** | 被 v2 反向复用的 v1 模块 | **保留 + 归位**（不可删） |
| **③ 写入侧双通道** | 绕过 v2 通道直写 `memories` 的旁路 | **需产品裁决**（真问题） |

---

## 二、实测边界

### 2.1 死代码（生产零调用）

| 位置 | 生产调用 | 测试引用 | 备注 |
|---|---|---|---|
| `memory_service.extract_and_save` | 无 | 有 | 写路径已被 v2 ingest/evaluate 取代 |
| `memory_service.retrieve` | 无 | 有 | 读路径已被 `memory2_retriever` 取代 |
| `memory_service.select_for_context` | 无 | 有 | 上下文装配已由 `context_builder._select_retrieval_segment` 承担 |
| `memory_service.reclaim_expired_memories` / `run_memory_reclaim_loop` | `main.py:54` 启动 | 有 | **恒空转**，见 §2.1.1 |
| `memory_conflict.resolve_batch` / `resolve_candidate` | 无 | 有 | 冲突处理已由 `memory2/lifecycle.on_promoted` 承担 |
| `relationship_memory.py` **整文件** | 无 | 14 个测试文件 | v1 关系记忆写路径 |
| ~~`planning/memory_policy.py` 写入路径~~ | **有（实测）** | 有 | ⚠️ **本行原判有误**：`planning/observer.py:101/422/637` 是活跃调用链（PLAN-009 计划终态记忆投递），**不可删**。详见 §3.3.1 |
| `post_process.py:21` 的 `memory_service` import | — | — | **死导入**（全文只出现 1 次 = import 行本身） |
| `context_builder.py:19` 的 `memory_service` import | — | — | **死导入**（同上） |

#### 2.1.1 空转循环的证据链

`reclaim_expired_memories` 按 `memories.expires_at` 过滤过期记忆，但全仓 `create_memory(...)` 的 **6 个调用点无一传 `expires_at`**：

```
services/action/capabilities/memory.py:49
services/action/memory_bridge.py:122,159
services/planning/memory_policy.py:362
services/relationship_memory.py:141
services/world/memory_bridge.py:66
```

且 v2 转正路径（`memory2/evaluator.py::_promote`）也不写该列 → **`expires_at` 恒为 NULL → 该循环每轮扫 0 行**，仅消耗一次调度。

### 2.2 活的共享件（不可删，需归位）

| 模块 | 谁在用 | 说明 |
|---|---|---|
| `memory_conflict.same_topic` / `_lcs_length` | `memory2/{retriever,lifecycle,commands,evaluator}` + `reflection/{evidence,lifecycle}` | 事实上**已是 v2 的底层依赖** |
| `memory_policy.apply_policy`（R1~R8） | `action/memory_bridge.py:112,154`、`action/capabilities/memory.py:41` | 行动/工具记忆的**投递闸**，活跃 |
| `models/memory.py::UserMemory` | `memory_repository._to_memory` 构造 → v2 retriever 的**返回类型** | 是 v2 的读模型，非 v1 遗留 |
| `models/memory.py::MemoryCandidate` / `MemoryExtraction` | `chains/extractor_chain` → `post_process` → `memory2/ingest` | v2 摄取的输入契约 |
| `memory_refs.build_memory_refs` | `chat_pipeline.py:704` | 吃 v2 检索结果、产出 `turn_meta.memory_refs` |

### 2.3 写入侧双通道（真问题，未处理）

`memories` 表存在**两个写入入口**，且**同时活跃**：

| 入口 | 调用链 | 幂等键 |
|---|---|---|
| **v2 正门** | `post_process` → `ingest_from_{world_event,action_record}` → 候选 → `evaluator._promote` | `memory_candidates.source_table + source_id` |
| **v1 旁路** | `world_engine.py:875,921` → `world/memory_bridge.materialize_event_memory` | `world_events.payload.memory_materialized` |
| **v1 旁路** | `action_engine.py:586` → `action/memory_bridge.deliver` | `effects.kind == "memory"` |

**两套幂等键互不可见**，而 v2 的摄取源（`world_events` / `action_records`）与旁路读的是**同一批行** → 同一个事件**可能落两条内容不同的记忆**（旁路写「用户在 X 月 X 日完成了 Y」，v2 写 `event.title`）。

> ⚠️ **尚未验证**：需要连库查询确认重复行是否真实存在（见 §六 待人工验证项）。

---

## 三、已执行批次

### 3.1 第 0 批：删死代码与空转循环

**改动 5 文件，+7 −11**

| 文件 | 改动 |
|---|---|
| `app/main.py` | 删 `_reclaim_task` 全局量、lifespan 内 `create_task(run_memory_reclaim_loop())`、清理 tuple 项与置 None；import 去掉 `memory_service` |
| `app/application/post_process.py` | 删 `memory_service` 死导入 |
| `app/services/context_builder.py` | 删 `memory_service` 死导入 |
| `tests/v24/test_tool011_security.py` | `EXPECTED_TASK_GLOBALS` 去 `_reclaim_task`；`EXPECTED_CREATE_TASK_COUNT` 5 → 4 |
| `tests/v24/test_tool010_e2e.py` | `ZERO_DIFF_HASHES[post_process.py]` 摘要 `c1702717…` → `2040a4df…`（附显式声明） |

**边界（刻意不做）**：`memory_service.py` 本体及仍引用它的 7 个测试文件未动，留待第 2 批随文件一起清。

### 3.2 第 1 批：模型归位与反向依赖消除

**改动 12 文件，+47 −31（含删 1 文件）**

| 文件 | 改动 |
|---|---|
| `app/models/memory.py` | ① `MemoryStatus` 补 `decayed` / `forgotten`（修潜伏 500 缺陷）；② 新增 `EvaluationVerdict`（归位） |
| `app/models/memory2.py` | **删除**（`find -delete`，非 `git rm`） |
| `app/services/memory2/types.py` | 新增 `TYPE_AFFINITY_KEYWORDS` **权威定义** |
| `app/services/memory_service.py` | 改为从 `memory2/types.py` 重导出（原定义删除） |
| `app/services/memory2/evaluator.py` | 改从 `types` 取常量；import 改指 `models.memory` |
| `app/services/memory2/migration.py` | 同上，并去掉 `import memory_service` |
| `app/services/memory2/product_view.py` | 修正两处因改动 ① 而过时的 docstring |
| `tests/eval/{test_development_growth_loop,test_memory_eval_gate}.py` | import 改指 `models.memory` |
| `tests/v2/{test_mem003_evaluator,test_mem008_attribution}.py` | 同上 |
| `tests/v24/test_tool008_integration.py` | `FROZEN_SOURCES[models/memory.py]` 摘要 `4371cd84…` → `3d9419eb…`（附显式声明） |

**本批核心收益**：`memory2/` 对 `memory_service` 的**反向依赖彻底消除** —— 现在 `grep memory_service app/services/memory2/` 唯一命中是 `types.py` 里的一句注释文字。

**关键确认**：`core/db.py::Memory.__table_args__` **只有 `type` 的 CheckConstraint，无 `status` 约束** → 改 Pydantic Literal **零迁移**，不需要 Alembic 变更。

#### 3.2.1 修正的潜伏缺陷

`MemoryStatus` 原只声明 `active` / `superseded` / `invalidated` 三态，而 `memory2/lifecycle.py` 会写 `decayed` / `forgotten` 两态 → `memory_repository._to_memory()` 读这两态时抛 `ValidationError`（**而非返回 None**），导致「按 id 读非 active 记忆」的路径 500。

### 3.3 第 2 批：去版本后缀与 v1 尸体清理（2026-09-29 执行）

**执行结果**：6 项中 5 项执行、**1 项判定不可执行**（见 §3.3.1）。

| # | 动作 | 结果 |
|---|---|---|
| 1 | `services/memory2/` → `services/memory/` | 已执行。**实测爆破半径** app/ 31 文件 71 处 + tests/ 40 文件 114 处 = 216 处（点号形态 95 处）。⚠️ **文档原写「~297 处测试 import」为高估** |
| 2 | `prompts/memory2_evaluator.py` → `prompts/memory_evaluator.py` | 已执行（**§5.1 未列出此文件**）。它同带版本后缀，漏改会致 `ModuleNotFoundError` |
| 3 | 删 `memory_service.py` 及其测试依赖 | 已执行（4 文件整删 / 2 文件部分编辑 / 1 处仅改字符串） |
| 4 | 删 `relationship_memory.py` | 已执行。⚠️ **文档原写「14 个测试文件」为高估**：实测真实依赖 3 个（`v26/test_acceptance.py:287` 只是测试函数名，非依赖） |
| 5 | ~~删 `planning/memory_policy.py` 写入路径~~ | ❌ **不可执行**，见 §3.3.1 |
| 6 | 归位 `memory_conflict` / `memory_policy` | 已执行（含死代码裁剪） |

#### 3.3.1 ❌ §5.1「删 `planning/memory_policy.py` 写入路径」前提错误，未执行

§2.1 该行记「生产调用：**无** / `planning/observer.py:58` 仅注释提及」。**实测该模块是活跃生产代码**：

- `planning/observer.py:101` `from app.services.planning import goal_contract, memory_policy as plan_memory_policy`
- `planning/observer.py:422` 调用 `deliver_goal_terminal_memory(settled, plan, target)`
- `planning/observer.py:637` → `plan_memory_policy.deliver_plan_memory(...)`
- 8 个 `tests/v25/test_plan009_*.py` 覆盖该链路

**处置**：本项从第 2 批**移除**，`planning/memory_policy.py` 保持不动——它是 PLAN-009「计划终态记忆投递」的唯一实现，删除会直接破坏计划域。

#### 3.3.2 🚨 附带发现：V7-010 `scheduled_followup` 已失效（**非本次引入**）

`trigger_evaluator.register_followup` 全仓**唯一调用点**是 `memory_service.py:113`（经 `_register_followups`，由 `extract_and_save` 在 `:96` 调用）。而 `extract_and_save` 生产零调用（v2 替换后）→ **该功能自 V2.0.0 记忆替换起即不可达**；v2 的 `memory/ingest` 路径**未承接** followup 登记。

- 影响：「用户说『明天有面试』→ 次日 18:00 主动跟进」不成立。
- 删除 `memory_service.py` 后该功能的**唯一实现随之消失**（可从 git 历史恢复）。
- 原测试 `tests/unit/test_trigger_followup.py::test_memory_pipeline_registers_followup` 直接调 v1 函数故**恒绿**，给出虚假信心；已随本次删除。
- **待裁决**：① 把 `_register_followups` 移植进 v2 ingest（恢复功能）；② 正式废弃并登记。

#### 3.3.3 归位与死代码裁剪（第 6 项）

| 动作 | 结果 |
|---|---|
| `services/memory_conflict.py` → `services/memory/conflict.py` | 已执行，并**裁掉死代码**：`resolve_batch` / `resolve_candidate` / `ConflictOutcome` / `_find_matches` / `_best_match` / 6 个 `ACTION_*` 常量（唯一消费者 `memory_service.py` 已删）。保留 `same_topic` / `_lcs_length`（被 `memory/*` 4 处 + `reflection/*` 3 处复用） |
| `services/memory_policy.py` → `services/memory/policy.py` | 已执行，**内容逐字节未变**（摘要 `416f27a9…` 不变，仅键路径更新） |
| 导入面改写 | 21 个文件（app 9 + tests 12） |

**踩坑（已修）**：批量替换未处理 `from app.services import memory_policy as <别名>` 形态 → 生成 `... import policy as memory_policy as <别名>` 语法错误，波及 7 个文件；已二次修复并以 `compileall` 全仓复核。

#### 3.3.4 冻结面与契约守卫更新（均按惯例显式声明 + 保留前值）

| 面 | 文件 | 旧 → 新 |
|---|---|---|
| `ZERO_DIFF_HASHES` | `app/application/post_process.py` | `2040a4df…` → `30125e6e…`（改名后 import 路径变更） |
| `ZERO_DIFF_HASHES` | `app/services/action/capabilities/memory.py` | `b8cedddd…` → `912619b5…`（memory_policy 导入路径变更） |
| `tool008 FROZEN_SOURCES` | 键 `app/services/memory_policy.py` → `app/services/memory/policy.py` | 摘要 `416f27a9…` **不变** |
| `v21 DOMAIN_MODULES` | `memory_service.py` / `memory_policy.py` / `memory_conflict.py` 三条 → `app/services/memory` 一条 | 顺带**强化**守卫（原三条未覆盖 memory2 包） |
| `v25 plan009 冻结契约` | `test_plan009_flags.py:190` 绝对路径改指 `memory/policy.py`；`test_plan009_step_criteria.py:260` 期望集加 `policy` | — |

#### 3.3.5 测试编辑（不整删，保留有效覆盖）

| 文件 | 处理 |
|---|---|
| `tests/integration/test_memory.py`（14 例） | 整删（纯 v1） |
| `tests/integration/test_memory_reclaim.py`（4 例） | 整删（纯 v1） |
| `tests/integration/test_memory_retrieval.py`（14 例） | 整删（纯 v1） |
| `tests/integration/test_memory_update_flow.py`（10 例） | 整删（纯 v1） |
| `tests/integration/test_memory_context.py`（11 例） | **部分编辑**：删 `TestSelectForContext`（4 例，测 `select_for_context` 死代码）；保留 `TestPromptMemorySection`（4）+ `TestContextBuilderIntegration`（3，测 v2 活链路） |
| `tests/unit/test_trigger_followup.py`（6 例） | **部分编辑**：删 `test_memory_pipeline_registers_followup`（1 例，死前提）；保留 5 例 `trigger_evaluator` 活测试 |
| `tests/unit/test_memory_conflict.py`（18 例） | **重写**：删 12 例测死代码者，保留 `TestSameTopic`（6 例） |
| `tests/v8.5/test_relationship_memory.py`（8 例） | 整删（纯 v1） |
| `tests/v2/test_rel001_truth_source.py` | **部分编辑**：`TestV1BypassGate` 由「运行时 monkeypatch 断言未被调用」改为**静态守卫**（断言 v1 模块不存在 + `state_service` 无引用） |

#### 3.3.6 验证

| 面 | 结果 |
|---|---|
| 语法面 | `compileall app tests` 退出码 0 |
| 目标套件 | `tests/v25`（plan009 五文件）**120 passed** |
| 全量 | `tests/v2 v8.5 v21 v24 v25 v26 v30 v40 v50 unit eval integration` → **17 failed / 6593 passed / 2 skipped** |
| 零回归判定 | 17 = **基线 14**（`v2` aut005/life002、`v21` agent008、`v24` tool009×6、`v25` prompt digest×3、`v26` migration head、`v30` maintenance steps）+ **3 项已知既存**（`unit/test_feishu_settings`×2 因本地 `.env` 有真实凭据；`integration/test_db_migration::test_http_lifecycle_on_postgres` 因 Redis 未起）。**失败集 ⊂ 基线 ∪ 已知既存 → 零新增** |
| 中途发现并修复 | 3 项 flaky（`v30/test_runtime_foreground_cutover`、`v21/test_agent001`、`v21/test_agent007`）隔离复跑 3/3 通过；2 项契约守卫（§3.3.4 末行） |

---

## 四、验证

### 4.1 零回归判据

**判据 = 失败集 diff，不是失败计数**（HEAD 基线本身不是绿的）。方法：`git worktree add <sha>` 建基线树 → 复制 gitignored 的 `.env` 与 `llm_profiles.json` → 用主仓库 venv 跑同一命令 → 逐条比对失败集 → `git worktree remove --force`。

### 4.2 结果

| 测试面 | 命令 | 结果 | 判定 |
|---|---|---|---|
| 目标测试 | `pytest tests/v24/test_tool008_integration.py tests/v2/test_mem003_evaluator.py tests/v2/test_mem008_attribution.py tests/v50/test_memory_product_view.py tests/v50/test_memory_api.py` | **128 passed** | ✓ |
| 离线评估 | `pytest tests/eval` | **11 passed** | ✓ |
| 版本面 | `pytest tests/v2 tests/v21 tests/v24 tests/v25 tests/v26 tests/v30 tests/v40 tests/v50` | 14 failed / 4553 passed / 2 skipped | **与基线 worktree（`fe335e6`）逐条一致 → 零回归** |
| 主链路 | `pytest tests/integration tests/unit tests/e2e` | 6 failed / 2186 passed | 4 条既存 + 2 条 flaky（见下） |
| 其余版本面 | `pytest tests/v9 tests/evaluation tests/v22 tests/v23 tests/v7.8 tests/v8 tests/v8.5` | 1 failed / **469 passed** | 既存 perf budget flaky |

**flaky 甄别**：`e2e/test_debug_state_history::test_state_reflects_turn_and_respects_limit` 与 `e2e/test_debug_evaluation::test_debug_evaluation_endpoints` 在 e2e 批量并发下失败、**隔离重复跑 2 次均通过** → flaky（两者都在 debug 端点、与 memory 域无关联）。

**既存失败（非本次引入）**：`v2/test_aut005`、`v2/test_life002::TestUserCycle`、`v21/test_agent008::TestLowEnergySuppression`、`v24/test_tool009_reflector`（6 条）、`v25/test_plan001|011|012`（三条 prompt digest）、`v26/test_acceptance::test_v25_migration_head_documented`、`v30/test_runtime_autonomous_loop::TestSchedulerUnchanged`、`integration/test_db_migration::test_http_lifecycle_on_postgres`（Redis 未起）、`unit/test_redis_client`、`e2e/test_scene_cases`（2 条）、`v8/test_world_performance`。

### 4.3 冻结面处理

本次触碰两处整文件哈希冻结面，均按仓库惯例**显式声明 + 同步摘要**（保留前值可追溯）：

| 冻结面 | 文件 | 旧摘要 | 新摘要 |
|---|---|---|---|
| `tests/v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` | `app/application/post_process.py` | `c1702717…` | `2040a4df…` |
| `tests/v24/test_tool008_integration.py::FROZEN_SOURCES` | `app/models/memory.py` | `4371cd84…` | `3d9419eb…` |

摘要算法：`read_bytes().replace(b"\r\n", b"\n")` 后 sha256（行尾归一，抵消 CRLF 检出差异）。

---

## 五、剩余批次

### 5.1 第 2 批：去版本后缀（中风险）—— **✅ 已执行（2026-09-29），见 §3.3**

> ⚠️ 下表为**执行前**的原始计划，其中第 4 行（删 `planning/memory_policy.py` 写入路径）经实测判定**前提错误、未执行**（§3.3.1）；改名爆破半径与 `relationship_memory` 测试引用数亦与实测有偏差（§3.3）。

| 动作 | 影响面 |
|---|---|
| `services/memory2/` → `services/memory/` | ~297 处测试 import |
| 删 `memory_service.py` 及其 7 个测试文件 | `integration/test_memory{,_context,_reclaim,_retrieval,_update_flow}.py`、`unit/test_trigger_followup.py`、`v21/test_agent008_review_fixes.py` |
| 删 `relationship_memory.py`（生产零引用） | 14 个测试文件 |
| 删 `planning/memory_policy.py` 写入路径 | — |
| 归位 `memory_conflict` / `memory_policy` | 受 `tool008 FROZEN_SOURCES` 约束，需显式声明 |

**必须同步**：`tests/conftest.py::_SERVICE_DB_MODULES`（8 项 memory2 登记）、`tests/v21/test_agent008_review_fixes.py::DOMAIN_MODULES`（硬编码 `app/services/memory_service.py` 路径）。

**有利条件**：`memory2/__init__.py` 是 **0 字节空文件**，无重导出 → 目录改名成本低于预期。

### 5.2 第 3 批：收敛写入双通道（高风险）

将 `world/memory_bridge.materialize_event_memory` 与 `action/memory_bridge.deliver` 的直写分支改为投 v2 候选。

**前置条件**：先连库确认重复记忆是否真实存在（§六）；动 `application/world_engine.py`（`tool007 FROZEN_SOURCES`）与 `application/action_engine.py`（`ZERO_DIFF_HASHES`）需显式声明。

**行为语义变化**：同一事件从「可能落 2 条」变为「落 1 条」，属产品可感知变更。

### 5.3 附带发现（待后续批次）

`memory2/retriever.py::QUERY_TYPE_KEYWORDS` 与 `memory2/types.py::TYPE_AFFINITY_KEYWORDS` 是**同一份类型亲和映射的新旧两版** —— 前者键为 v2 规范类型名（`experience` / `relationship_fact`），后者键为遗留名（`important_event` / `relationship_event`）。

本次**只做物理搬迁、未动内容**，因为合并键名会改变 `evaluator._type_affinity` 的评分行为（`candidate.proposed_type` 可能携带遗留名，见 `ingest_from_world_event` 的 `proposed_type="important_event"`）。统一需单独评估。

---

## 六、待人工验证项

1. **重复记忆查库**（第 3 批前置）：对同一 `world_events` / `action_records` 行，确认 `memories` 表中是否存在旁路与 v2 各写一条的重复行。
2. **真实模型人工回归**：`reclaim` 循环移除后，确认无「过期记忆未回收」的线上反馈（该循环恒空转，理论上零影响，但需观察）。
3. ~~**`memory2/` 目录改名**（第 2 批）：改名后需重跑全量测试并核对 `conftest` 的模块登记。~~ **✅ 已完成（2026-09-29）**：全量回归零新增失败，`conftest` 的 9 条 import 与 9 项模块登记已同步（§3.3.6）。
4. **`QUERY_TYPE_KEYWORDS` 与 `TYPE_AFFINITY_KEYWORDS` 统一**（§5.3）：需先确定 `proposed_type` 的遗留名归一化时机。
5. **🚨 V7-010 `scheduled_followup` 裁决**（§3.3.2，**新增**）：该功能自 V2.0.0 起已不可达，且其唯一实现随本次删除消失。需裁决：移植进 v2 ingest 恢复功能，还是正式废弃。
6. **`relationship_lexicon.MEMORY_TEMPLATES` 已无使用者**（§3.3 附带）：原唯一消费者 `relationship_memory.py` 已删，该字典成为新的孤儿常量，待后续批次裁决去留。
