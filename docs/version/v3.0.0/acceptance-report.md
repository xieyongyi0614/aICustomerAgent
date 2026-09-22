# V3.0.0 Agent Runtime Acceptance Report

> 验收日期：2026-09-22
> 验收范围：tasks.md §6.1 十二个版本级 Gate（G1~G12）+ 边界不变量 9 条 + 影子矩阵 + 性能基线
> 上游：`docs/version/v3.0.0/tasks.md`（§6 Acceptance Criteria）· `docs/version/v3.0.0/tasks/RT-020.md`
> 实现基线：RT-001 ~ RT-019 全部提交，`HEAD = 2d093ab`
> 验收环境：Windows / Python 3.13.5 / 内存 SQLite（`TEST_DATABASE_URL` **未配置**）
> 执行方式：RT-020「零代码改动」——本报告只产出证据，不修改任何生产 / 测试代码
> 提交信息：采用 `docs: RT-020 验收报告与回归清单`（RT-020 §9 允许二选一）。本任务产物为**纯文档**，按 `AGENTS.md` 提交约定应使用 `docs:` 而非 `feat:`；AC9 中的 `feat(runtime): RT-020 ...` 为备选形式，此处按项目约定择 `docs:` 并在本报告注明。

---

## Status

**CONDITIONAL — 不得发布**（G6 无法执行、G7 不满足「全绿」；详见「未过项」）

- V3.0 自身引入的回归：**0**（零回归成立，见「零回归判定」）
- 阻断发布的项：**2**（G6 缺真实 PG；G7 既存失败未清零）
- 待人工执行的项：**1**（真实模型人工回归，见 `regression-checklist.md`）

> 判定依据（RT-020 §7.3）：「任一测试红 → 记录到 acceptance-report『未过项』，**版本不得发布**；回对应 Task 修复。」
> 本次红灯全部为**既存失败**（干净基线同样失败，已逐项实测对照），不属 RT-001~RT-019 引入，故不构成「回对应 Task 修复」的对象，而属版本发布前置条件。

---

## 执行摘要（Gate 结果总表）

| Gate | 判据 | 结果 | 证据 |
|---|---|---|---|
| **G1 契约冻结** | 四类契约字段与语义冻结，后续零私改 | **PASS** | `tests/v30/test_runtime_contracts.py` **15 passed** |
| **G2 单一循环** | 前后台共用同一六段循环；段序列只来自 `profiles.py` | **PASS** | `test_stage_order_only_from_profiles` / `test_single_loop_path` / `test_run_preserves_declared_stage_order` / `test_act_module_has_no_second_orchestrator` / `test_reason_module_has_no_second_decision_implementation`（`test_agent_loop_core.py` **38 passed**） |
| **G3 边界不变量** | 9 条逐条成立 | **PASS** | 见「边界不变量 9 条逐条复检」 |
| **G4 Preserve 零改动** | §0.5 清单模块 diff 为空 | **PASS** | `git diff 7461c3c..HEAD --stat -- <Preserve 清单>` **输出为空** |
| **G5 零新表** | 无新增表；仅 `0052` 两列 | **PASS** | `SCHEMA_TABLE_COUNT = 45 == 实际 45`；`MIGRATION_HEAD = 0052`（prev `0051`）；`test_zero_migration_model_structure_unchanged` **passed** |
| **G6 迁移可逆** | `0052` 可空跑、可回滚 | **BLOCKED** | `TEST_DATABASE_URL` 未配置，无真实 PG 实例；内存 SQLite 仅覆盖 `tests/v30/test_runtime_migration_0052.py` **6 passed**（单链 / down_revision 静态校验） |
| **G7 零回归** | 既有 unit / api / integration / e2e / golden 全绿 | **FAIL（非 V3.0 引入）** | 零回归**成立**（当前失败集 ⊂ 基线失败集）；但「全绿」不成立：既存 17 项失败 |
| **G8 降级语义** | degraded / aborted 判定一致；行动失败 ≠ Run 失败 | **PASS** | `test_critical_failure_aborts` / `test_done_event_unchanged` / 契约 recoverable 矩阵（`test_agent_loop_core.py` **38 passed**） |
| **G9 预算纪律** | LLM 调用经 Gateway 记账；0 LLM 段零调用；超预算降级不抛错 | **PASS** | `test_idle_short_circuit_zero_llm_zero_runs` / `test_silence_winner_has_no_llm` / `test_context_module_performs_no_writes_and_no_llm` / `test_reason_does_not_call_gateway_directly` / `test_budget_exhausted_skips_without_raise` / `test_gateway_denied_falls_back_without_llm` |
| **G10 全链可观测** | 前台 / 后台各一次 Run 可由 `run_id` 还原六段顺序、耗时、降级与错误 | **PASS** | `tests/v30/test_runtime_observability.py` **15 passed**（含 `TestFullChain` 前台 / 后台两例） |
| **G11 恢复语义** | 孤儿 Run 收敛幂等；重启零自动重放 | **PASS** | `tests/v30/test_runtime_recovery.py` **11 passed**（含 `test_sweep_converges_timed_out_running_run` / `test_sweep_is_idempotent` / `test_no_replay_on_restart`） |
| **G12 多渠道可扩展** | 新渠道 = 实现 Adapter + 注册，不改 Runtime；核心层零 import 具体渠道 | **PASS** | `test_runtime_inbound_gateway.py` **22 passed** + `test_runtime_outbound_gateway.py` **10 passed**；AST 扫描（见 G3-⑥）**0 命中** |

**统计：PASS 10 / FAIL 1 / BLOCKED 1**

---

## 全量测试结果（RT-020 §7.1 六组）

| # | 组 | 命令 | 结果 |
|---|---|---|---|
| 1 | Fast Test | `pytest -m "(unit or api) and not slow" -q` | **1838 passed**（43.67s） |
| 2 | V3.0 新增 | `pytest tests/v30 -q` | **357 passed**（20.98s） |
| 3 | Integration | `pytest -m integration -q` | **17 failed / 4915 passed / 22 skipped**（95.84s） |
| 4 | E2E | `pytest -m e2e -q` | **1 failed / 157 passed**（30.35s） |
| 5 | Golden | `pytest -m golden -q` | **9 passed**（31.33s） |
| 6 | 既有版本目录 | `pytest tests/v2 tests/v21 … tests/v9 -q` | **17 failed / 4183 passed / 12 skipped**（79.73s）；复跑 **15 failed / 4185 passed**（78.46s） |

> **命令修正登记**：§7.1 第 5 组写作 `pytest tests/golden -q`，实测 **collected 0**——`tests/golden/` 目录只含 4 个 prompt 快照 `.txt`，无测试模块（用例为 `tests/unit/test_prompt_golden.py` 等并以 `@pytest.mark.golden` 标记）。**正确命令为 `pytest -m golden -q`**。本报告采用后者。

---

## 零回归判定（基线对照法）

方法：把工作区改动文件备份 → `git checkout` 还原到干净基线 → 跑**同一命令** → 恢复改动。判据 = **当前失败集 ⊂ 基线失败集**。
（本机 `git stash` 不可信，故采用文件级备份 / 还原。）

| 选择 | 改动后（HEAD = RT-019） | 干净基线（RT-018 = `6237556`） | 判定 |
|---|---|---|---|
| `-m integration --ignore=tests/v30` | 17 failed / 4768 passed | **19 failed / 4766 passed** | 当前失败集 **⊂** 基线 → 零回归 |
| 既有版本目录组（G6 组） | 17 failed（首跑）/ **15 failed**（复跑）/ 4183~4185 passed | **16 failed / 4184 passed** | 三跑成员在 15~17 间浮动，均为基线失败集成员 → 零回归 |
| `tests/e2e tests/golden` | 2 failed → **1 failed**（连跑 2 次） | 2 failed → **3 failed**（连跑 2 次） | 失败成员同码连跑互换 → 既存 flaky |
| `-m "(unit or api) and not slow"` | **1838 passed**（0 failed） | 同 | 零回归 |
| `tests/v30 tests/unit` | **1857 passed**（0 failed） | — | V3.0 新增面全绿 |

**关键对照（防止把 flaky 误判为回归）**：`tests/v7.8/test_performance.py::test_observability_overhead_within_budget` 在 G6 组首跑失败、复跑通过、单跑通过，且在**干净基线的 `-m integration` 跑中同样失败**——属时序敏感 flaky（40 轮对照，阈值 50ms/轮），与 RT-019 无关。

**已实测确认的既存失败**（干净基线同样失败）：
- `tests/v2/test_aut005_goal_evaluation.py::TestRules::test_clean_slice_passes_all`（单独在基线上复现）
- `tests/v24` 簇：`test_tool012_bans::test_ban_no_second_agent_profiles_frozen`、`test_tool_acceptance::test_g_compat_agent_runtime_profiles_semantics_replacing_blob_freeze`、`test_tool009_reflector` × 6、`test_tool010_e2e` × 3、`test_tool008_integration`、`test_tool006_integration`
- `tests/v21/test_agent008_review_fixes.py::TestLowEnergySuppression::test_low_energy_suppresses_short_term`
- `tests/v8/test_world_performance.py::test_world_assembly_overhead_within_budget`
- `tests/e2e/test_memory_e2e.py::test_extractor_failure_does_not_break_sse`

---

## 影子矩阵核对（AC5）

`core/settings/agent_runtime.py` 全部 11 个 `runtime_*` 字段（`Settings.model_fields` 实测）：

| 字段 | 默认值 | tasks.md §0.4 期望 | 一致 |
|---|---|---|---|
| `runtime_session_tracking_enabled` | `False` | `False` | ✅ |
| `runtime_state_versioning_enabled` | `False` | `False` | ✅ |
| `runtime_context_freeze_enabled` | `False` | `False` | ✅ |
| `runtime_event_bus_enabled` | `False` | `False` | ✅ |
| `runtime_loop_optional_stages` | `""` | `""` | ✅ |
| `runtime_reflect_in_loop_enabled` | `False` | `False` | ✅ |
| `runtime_inbound_gateway_channels` | `""` | `""` | ✅ |
| `runtime_outbound_gateway_channels` | `""` | —（RT-014 冻结时新增，已登记） | ✅ |
| `runtime_autonomous_cycle_enabled` | `False` | `False` | ✅ |
| `runtime_orphan_run_timeout_minutes` | `30` | `30` | ✅ |
| `runtime_orphan_run_sweep_enabled` | `True` | `True`（RT-018 定义的例外） | ✅ |

- **AC6 零版本前缀**：`grep -rn "v30_" apps/backend/app apps/backend/tests` → **0 命中**（仅 `docs/version/v3.0.0/tasks*.md` 在描述「不得复用 `v30_`」的规则文本中出现）。`grep -rn "V30_" apps/backend/app` → **0 命中**。
- **env 名 = 字段名大写**：`DOMAIN_MODEL_CONFIG = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")` —— **无 `env_prefix` / 无 alias 层**。11 个字段的 env 名即 `RUNTIME_*_ENABLED` 等。
- **登记完整性**：`tests/v30/runtime_support.py::V30_RUNTIME_FIELDS` 已登记全部 11 个字段，`test_runtime_contracts.py::test_settings_runtime_fields_are_registered` **passed**。
- **Flag 全 off 影子路径**：各 Task 的「Flag 关闭时行为与 V2.6.1 逐字节一致」用例均在 `tests/v30` 内（如 `test_empty_flag_matches_profile_stages` / `test_activate_noop_when_flag_off` / `test_event_silent_when_flag_off` / `test_adapter_outcome_unchanged_when_disabled` / `test_flags_off_means_legacy_context_assembly` / `test_persist_disabled_matches_v75_behavior`），**357 例全绿**。

---

## Preserve 清单 diff 证据（AC3）

```bash
git diff 7461c3c..HEAD --stat -- \
  apps/backend/app/services/decision_pipeline.py \
  apps/backend/app/services/intention_policy.py \
  apps/backend/app/services/goal_stack.py \
  apps/backend/app/services/planning \
  apps/backend/app/services/action \
  apps/backend/app/models/action.py \
  apps/backend/app/services/tool \
  apps/backend/app/application/world_engine.py \
  apps/backend/app/services/memory2 \
  apps/backend/app/services/memory_policy.py \
  apps/backend/app/services/reflection \
  apps/backend/app/services/development \
  apps/backend/app/services/agent_evaluation.py \
  apps/backend/app/evaluation_rules \
  apps/backend/app/channels/base.py \
  apps/backend/app/channels/feishu/delivery.py
```

**输出：空**（0 文件 0 行）。V3.0 全量改动共 **104 个文件**，全部落在允许面内：
`application/agent_runtime/**`（新增运行时子面）、`application/{observability,chat_pipeline,life_loop,autonomy_bridge}.py`、`channels/feishu/adapter.py`、`core/{db,settings/agent_runtime}.py`、`models/observability.py`、`repositories/*`（只读面扩参 / 新增读方法）、`services/observability/**`、`services/proactive_executor.py`、`migrations/versions/0052_*`、`tests/**`、`docs/version/v3.0.0/**`。

> 注：`channels/feishu/adapter.py` 与 `services/proactive_executor.py` **不在** §0.5 Preserve 清单内（清单只列 `channels/base.py` 与 `channels/feishu/delivery.py`），其改动属 RT-013 / RT-017 的显式交付面。

---

## 边界不变量 9 条逐条复检（G3）

| # | 不变量（architecture 附） | 结果 | 证据 |
|---|---|---|---|
| 1 | Runtime Core 只调度 / 路由 / 装配 / 记账；Reason/Plan/Act/Reflect/Update 业务语义归各域，零改动 | **PASS** | Preserve diff 为空；段级零写入断言：`test_observe_module_performs_no_writes` / `test_reason_module_performs_no_writes` / `test_act_performs_no_direct_writes` / `test_plan_module_performs_no_direct_writes` / `test_state_module_performs_no_writes` / `test_no_direct_domain_writes` |
| 2 | Context / Snapshot / RuntimeEvent 只读投影，不落真相源 | **PASS** | `test_context_module_performs_no_writes_and_no_llm` / `test_bus_does_not_write_any_table` / `test_events_module_performs_no_db_writes` / `test_state_module_performs_no_writes` |
| 3 | 一切长期变化可经 Execution History 指认来源并回放 | **PASS** | `test_history_aggregates_all_layers`（RT-018）+ `test_replay_bundle_is_read_only_and_complete` / `test_by_correlation_links_layers`（RT-019） |
| 4 | 循环内 LLM 调用四问只在 LLM Gateway 裁决 | **PASS** | `test_reason_does_not_call_gateway_directly` / `test_gateway_does_not_touch_execution_entry` / `test_state_machine_untouched_by_gateway` / `test_proactive_executor_uses_gateway` |
| 5 | 跨域可靠投递仍走 Outbox；Event System 只做进程内同步通信，不引入 Event Sourcing | **PASS** | `test_bus_does_not_write_any_table`（events 对 `outbox_events` / `world_events` 零写）+ RT-012 `Outbox 零改动断言`；`pyproject.toml` 无 MQ / Redis 依赖 |
| 6 | ChannelAdapter 契约零改动；新增渠道 = 实现 Adapter + 注册 | **PASS** | `channels/base.py` diff 为空（Preserve 证据）；`test_adapter_outcome_unchanged_when_disabled` / `test_deliver_dispatches_to_registered_adapter` / `test_channel_registry_has_no_discord` |
| 7 | Tool 治理零改动；Runtime 不干预工具选择语义 | **PASS** | `services/tool/**` diff 为空；`test_act_does_not_decide` / `test_act_uses_single_engine_entry` / `test_act_records_legal_transition_and_single_entry` |
| 8 | 前后台共用同一认知循环；不得再出现平行编排路径 | **PASS** | `test_stage_order_only_from_profiles` / `test_single_loop_path` / `test_all_stage_methods_are_delegated` / `test_cycle_equivalence_with_baseline`；`test_entry_convergence_doc_is_present`（RT-015 入口收敛登记） |
| 9 | 无第二套 Agent / Pipeline / 无新 Agent 框架嫁接 | **PASS** | `test_act_module_has_no_second_orchestrator` / `test_reason_module_has_no_second_decision_implementation`；`grep -in "langgraph\|crewai\|autogen\|semantic-kernel" pyproject.toml` → **0 命中**；Preserve diff 为空 |

### 静态扫描（AST 口径，避开 docstring 假红）

裸文本 grep 会命中 docstring 里的**声明式否定**（如 `outbound.py` 注释「不 import `app.channels.feishu`」、`delivery.py` 注释「不得 import `app.repositories`」），故改用 AST 取 `Import` / `ImportFrom` 标识符：

| # | 扫描 | 结果 |
|---|---|---|
| ① | `app/application/**` + `app/services/**` import `app.channels.feishu` | **0 命中** |
| ② | `app/channels/**` import `app.repositories` | **0 命中** |
| ③ | `app/core/**` import `app.channels.*` / `app.repositories` | **0 命中** |
| ④ | `app/api/**` import `app.repositories` / `langchain*` | **26 命中（5 文件）**——见「遗留问题登记 I-3」 |

---

## 性能基线（AC7，只记录不优化）

### Run 级开销

| 项 | 实测 | 口径 |
|---|---|---|
| 前台全链 Run 墙钟（9 段桩实现，含 Run open / close + 台账 IO） | **0.20s** | `TestFullChain::test_full_observability_chain_foreground` |
| 后台全链 Run 墙钟（11 段桩实现，同上） | **0.22s** | `TestFullChain::test_full_observability_chain_background` |

### 段级耗时留痕面

- 权威口径：`loop_runs.steps[].duration_ms`（`controller.append_step` / `AgentLoop._run_stage` 逐段落账，`round(perf_counter 差 * 1000, 2)`）。
- RT-019 新增**只读消费面**：`RunDebugView.stages`（`app.services.observability.trace_query.by_run_id`），`by_session` 可对比同一 Session 内多次 Run 的段耗时分布。
- 后台 Run 额外受 `AgentLoop._lifecycle` 的 `get_user_write_lock` 串行化约束（前台不加锁，裁决 D4）——这是既有语义，非本版本引入。

### 套件墙钟（本机，`-n auto`）

| 组 | 墙钟 |
|---|---|
| Fast `(unit or api) and not slow`（1838 例） | 43.67s |
| `tests/v30`（357 例） | 20.98s |
| `-m integration`（4932 例） | 95.84s |
| `-m e2e`（158 例） | 30.35s |
| `-m golden`（9 例） | 31.33s |
| 既有版本目录（4200 例） | 79.73s |
| `tests/v30` 最慢单例 | 0.57s（`test_turn_meta_keys_and_order_unchanged`） |

### 观测开销预算（既有守门，沿用 V7.8 阈值）

| 守门用例 | 阈值 | 备注 |
|---|---|---|
| `tests/v7.8/test_performance.py::test_observability_overhead_within_budget` | 观测 on/off 每轮差 < **50ms**（各 20 轮对照） | **时序敏感 flaky**：本机单跑通过；干净基线在 `-m integration` 组跑中同样失败 |
| `tests/v7.8/test_performance.py::test_hot_path_has_no_direct_io` | 热路径零同步写库（打桩写方法全爆） | PASS |
| `tests/v8/test_world_performance.py::test_world_assembly_overhead_within_budget` | 世界装配开销预算 | 既存失败（基线同） |

### 0 LLM 段零调用断言（G9 证据）

`test_idle_short_circuit_zero_llm_zero_runs`（空转 0 LLM + 0 Run）、`test_silence_winner_has_no_llm`、`test_context_module_performs_no_writes_and_no_llm`、`test_reason_does_not_call_gateway_directly`、`test_reason_module_has_no_second_decision_implementation`。

---

## 未过项（阻断发布）

| # | 项 | 类型 | 说明 | 收口动作 |
|---|---|---|---|---|
| **I-1** | **G6 迁移可逆未验证** | 环境阻断 | `TEST_DATABASE_URL` 未配置，无真实 PG 实例；仅内存 SQLite 覆盖静态链校验（`tests/v30/test_runtime_migration_0052.py` 6 passed）。**未执行** `alembic upgrade head` / `downgrade -1` 空跑回滚 | 配好 `TEST_DATABASE_URL` 后执行 `0052` 双向空跑，回填本报告 G6 行 |
| **I-2** | **G7 零回归「全绿」不成立** | 既存失败 | 既存 17 项失败（v24 簇 13 + v2 aut005 1 + v21 agent008 1 + v8 性能 1 + e2e 1）。**零回归（相对基线）成立**，但 §6.1 G7 判据要求「全绿」 | 作为独立缺陷簇跟踪（不挂 V3.0 发布门）或先清零再复跑 |

> **未过项不属 RT-001~RT-019 引入**：上表两项均已用基线对照法排除 V3.0 归因（I-1 为环境缺失；I-2 为既有技术债）。RT-020 §7.3 的「回对应 Task 修复」不适用——无对应 Task 可回。

---

## 遗留问题登记（不阻断）

| # | 项 | 说明 |
|---|---|---|
| I-3 | `app/api/**` 反向依赖 `app/repositories` | 5 个文件 26 处（`action.py` / `action_execution.py` / `debug.py` / `proactive.py` / `world.py`）。**V3.0 未触碰 `app/api/**`（`git diff 7461c3c..HEAD --name-only` 中 0 命中）**，属既存形态；`app/api/` 在渠道依赖 allowlist 中**刻意豁免**（与 `app/main.py` 同）。tasks.md §6.2 第 3 条「`api` 不依赖 `repositories`」与既存实现存在口径差，建议作为独立技术债（baseline §9 P2 同类）登记，不在本版本处置 |
| I-4 | §7.1 第 5 组命令笔误 | `pytest tests/golden -q` 实际 collected 0（目录只含快照），应为 `-m golden`。已在本文档登记，Task Detail 属冻结文档不回填 |
| I-5 | 时序敏感 flaky 簇 | `test_observability_overhead_within_budget`、`test_world_assembly_overhead_within_budget`、`tests/v2/test_life002_controller.py::TestMaintenanceAndIdle` 两例、`tests/v24/test_tool012_scenarios.py::test_s4_...`（`await_until` 3s 轮询）。同码连跑成员互换，与改动无关 |
| I-6 | `app/api/v1/debug.py` 未暴露 `correlation_id` | RT-019 刻意不扩 `RuntimeTrace.api_dict()`，保持 `/api/v1/debug` 响应逐字段不变（前端零改动）。前端可视消费（循环回放 UI）属 Backlog（未排期） |

---

## 待回写项（需用户确认，**不在本任务内**）

RT-020 §6.3 明确：以下两项属「验收之后」的独立动作，本任务只登记、不执行。

| # | 文件 | 待回写内容 |
|---|---|---|
| W-1 | `docs/current-system-architecture-baseline.md` | 回写 V3.0 已实现形态：Agent Runtime 六段循环、四组件（Context / Loop / State / Event）、Session 生命周期、Run/Trace/Execution History 三层、通道归一（Inbound / Outbound Gateway）、孤儿回收与观测查询面；迁移链尾 `0051` → `0052` |
| W-2 | `AGENTS.md` / `apps/backend/AGENTS.md` | 版本入口指向 `docs/version/v3.0.0/`；**迁移链尾由 `0050` 更新为 `0052`**（`AGENTS.md` 当前仍写 `0050`，已落后两个迁移） |

---

## Release Decision

**不得发布**（NOT RELEASED），条件：

1. **G6 必须先执行**：配置 `TEST_DATABASE_URL`，验证 `0052` 可空跑、可回滚（I-1）。
2. **G7 需澄清口径**：既存 17 项失败须「清零」或「显式豁免并登记」（I-2）。零回归已证（当前失败集 ⊂ 基线失败集）。
3. **真实模型人工回归必须先执行**：`regression-checklist.md` §2 A~F 六类场景（前台多轮 / 后台 tick / 主动投递 / 渠道切换 / 孤儿恢复 / 回放取材）。

### 发布门摘要

| Gate | 结果 |
|---|---|
| G1 契约冻结 | PASS |
| G2 单一循环 | PASS |
| G3 边界不变量（9 条） | PASS |
| G4 Preserve 零改动 | PASS（diff 为空） |
| G5 零新表 | PASS（45 表 / 头 `0052`） |
| G6 迁移可逆 | **BLOCKED**（无真实 PG） |
| G7 零回归 | **FAIL**（零回归成立；全绿不成立） |
| G8 降级语义 | PASS |
| G9 预算纪律 | PASS |
| G10 全链可观测 | PASS |
| G11 恢复语义 | PASS |
| G12 多渠道可扩展 | PASS |
| 影子矩阵 / 零版本前缀 | PASS |
| Preserve 清单 diff | PASS（为空） |

---

## Sign-off

- 自动化验收（可执行部分）：**PASS**（G1~G5、G8~G12 全绿；`tests/v30` 357 例全绿）
- 零回归判定：**PASS**（基线对照法，当前失败集 ⊂ 基线失败集）
- 边界不变量 9 条：**PASS**
- 迁移可逆（G6）：**未执行**（缺 `TEST_DATABASE_URL`）
- 零回归全绿（G7）：**不满足**（既存 17 项失败）
- 真实模型人工回归：**待执行**（`regression-checklist.md`）
- 架构基线与 AGENTS.md 回写：**待用户确认**（W-1 / W-2）
- 最终裁决：**CONDITIONAL — NOT RELEASED**（V3.0 自身零回归，但发布门前置未齐）
