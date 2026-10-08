# 后端测试规范与 AI Coding 测试执行规则

> 位置：`apps/backend/tests/`，pytest 配置：`apps/backend/pyproject.toml [tool.pytest.ini_options]`。
> 原则：**测试可靠性 > 覆盖数量 > 执行数量**。AI 修改代码后禁止默认执行全量测试。

## 1. 测试分类

| 类型 | 特征 | 位置 | marker |
|---|---|---|---|
| Unit | 纯函数 / Chain / Domain 逻辑；无 DB、无 HTTP、无网络；允许 FakeLLM | `tests/unit/` | `unit` |
| API | FastAPI Router + httpx `ASGITransport`；参数校验 / Status / Response Model / Dependency Override；FakeLLM + 内存 SQLite | `tests/e2e/`（端点类）、unit 内少量编排测试 | `api` |
| Integration | DB 读写 / Alembic 迁移 / 多模块协作；内存 SQLite（每测试独立建表） | `tests/integration/`、`tests/v8.5/`、`tests/evaluation/` | `integration` |
| E2E | HTTP 全链路业务流程（含本地 SSE server 线程） | `tests/e2e/` | `api + e2e` |
| Golden | prompt 快照回归（`UPDATE_GOLDEN=1` 重新生成） | `tests/golden/` 快照 + `tests/unit/test_prompt_golden.py` | `golden + unit` |
| Slow | 慢测试（server 线程、轮询等待），可与任意类型叠加 | 见 `conftest.py SLOW_TEST_FILES` | `slow` |
| Legacy | 历史版本套件（被测模块仍在跑，但不参与日常回归） | `tests/v2/`、`tests/v8.5/`、`tests/v22/`~`tests/v26/` | `legacy`（默认不收集，`--run-legacy` 启用） |

Marker 不互斥，一个测试可同时是 `integration + slow`。

### 打标方式（重要）

Marker 由 `tests/conftest.py::pytest_collection_modifyitems` **自动打标**，不需要手写：

- 测试使用 `db_session_factory` fixture → `integration`
- 测试使用 `ASGITransport` 或位于 `tests/e2e/` → `api`（位于 `tests/e2e/` 额外 `e2e`）
- 其余按目录兜底：`tests/unit/` → `unit`，其他 → `integration`
- `test_prompt_golden.py` → `golden + unit`；`SLOW_TEST_FILES` 中的文件 → `slow`

新增慢测试时把文件名加入 `SLOW_TEST_FILES`，或直接 `@pytest.mark.slow`。

## 2. 外部依赖现状

- **无 Redis / Celery / MQ**（项目刻意未引入）；队列用 DB 表实现。
- **禁止真实 LLM 调用**：统一用 `tests/conftest.py::FakeLLM`（`fake_llm` fixture），结构化输出按 schema 类名分发；通过 `core/llm_factory.set_llm` / `get_chat_llm` dependency override 注入。
- DB：测试全部使用内存 SQLite（StaticPool，每测试独立建表），不依赖外部实例。
- 唯一例外：`tests/integration/test_db_migration.py`、`test_relationship_migration.py` 需要真实 PostgreSQL（`TEST_DATABASE_URL`），**无实例时自动 skip**。
- 无 CI（暂无 `.github/workflows`）。

## 3. 测试命令（在 `apps/backend/` 下执行）

| 级别 | 命令 | 说明 |
|---|---|---|
| Focused | `pytest tests/unit/test_state_engine.py::test_xxx` | 改完代码第一优先级 |
| Module | `pytest tests/unit/`、`pytest tests/e2e/` | 当前模块相关测试 |
| Fast | `pytest -m "(unit or api) and not slow"` | 日常开发最大范围，无真实外部依赖 |
| Integration | `pytest -m integration` | 改 DB / 迁移 / 跨模块时 |
| E2E | `pytest -m e2e` | 全链路回归 |
| Full | `pytest` | **禁止作为日常默认动作**，仅阶段完成 / PR / 发布 / CI |

> ⚠️ **层级命令一律按 marker，不要按目录切片。** 版本目录中 `v30 / v40 / v50 / v51` 保留在默认集，
> `v2 / v8.5 / v22~v26` 为历史版本套件（`legacy` marker），由 `tests/conftest.py::pytest_ignore_collect`
> **默认不收集**。按 `pytest_collection_modifyitems` 的自动打标规则，非 `unit` / `e2e` 目录且无
> `db_session_factory` / `asgi_transport` 的用例会落到 **`integration` marker** —— 因此：
>
> - ✅ `pytest` —— 日常全量（管家主线 + 全部分层测试）
> - ✅ `pytest --run-legacy` —— 含历史套件的完整全量，阶段收口 / PR / 发布时用
> - ✅ `pytest -m integration` —— 改 DB / 迁移 / 跨模块时的层级命令
> - ❌ `pytest tests/unit tests/integration tests/e2e` —— 只覆盖分层目录，会漏掉 `tests/v30|v40|v50|v51`
>   等版本目录（2026-10-03 雪花 ID 改造即因此漏掉 4 个回归）
> - ⚠️ 聚焦 legacy 域（tool / planning 等）时须带开关：`pytest --run-legacy tests/v24/test_tool009_reflector.py`

> Fast Test 即 `-m "(unit or api) and not slow"`。**多个 `-m` 连用只有最后一个生效**（如 `-m "unit or api" -m "not slow"` 实际等价于只写 `-m "not slow"`，会放进全部 integration），必须写进单个表达式。
> 全量默认已启用 `pytest-xdist`（`-n auto --dist loadgroup`，见 pyproject addopts），并行安全：每测试独立内存 SQLite、无共享外部状态、无 Redis；需要真实 PostgreSQL 的迁移测试文件用 `xdist_group("migration")` 钉入同一 worker 顺序执行，避免并发升降级同一 `asuna_test` 库互踩。

## 4. AI Coding 测试执行规则（必须遵守）

AI 修改代码后**不允许直接执行 `pytest`（Full Test）**。默认流程：

```text
代码修改 → 分析修改文件 → 识别影响范围 → 找到对应测试
→ Focused Test → 通过 → Module Test → 必要时 Fast Test → 继续开发
```

### 变更影响范围规则

| 修改内容 | 最低测试范围 |
|---|---|
| 纯 Unit / Utility / Chain | 相关 Unit Test |
| Router（`app/api/`） | 相关 API Test（`-m api` 中对应文件） |
| Service（`app/services/`、`app/application/`） | 相关 Unit Test，视依赖加相关 API Test |
| 公共 Service / Domain | 相关 Unit + API Test；跨模块依赖时 Integration |
| DB Model / Repository（`app/models/`、`app/repositories/`） | API + Integration（`-m integration`） |
| LangGraph / Agent（`app/chains/`、`app/agents/`） | 相关 Unit / Mock 测试；必要时 Integration |
| 基础设施（`app/core/`：db、settings、deps、llm_factory、middleware） | Fast Test；必要时 Full Test |

### settings 字段改动的验证规则

改动 / 删除 `app/core/settings/` 字段时必须按**三种引用形态**全量检索，缺一即误判：

| 形态 | 示例 | 检索要点 |
|---|---|---|
| ① 静态属性访问 | `if not settings.action_detector_enabled: return None` | 蛇形字段名 |
| ② **大写 env 名** | `monkeypatch.setenv("EVALUATION_BEHAVIOR_ENABLED", "false")`、`os.environ.setdefault(...)` | 字段名**大写形式**（测试侧常用） |
| ③ **动态 f-string（最易漏）** | `bool(getattr(settings, f"evaluation_{dimension}_enabled", True))` | 按字段名 grep **无法命中**，须搜 `getattr(settings, f"` / `f"[a-z_]*_enabled"` |

形态 ③ 的 `getattr(..., True)` 兜底会让**字段缺失时静默退化为「永远开启」**——不报错、行为不变、能力消失。因此**删字段后必须以测试为最终裁判**（`pytest -m "(unit or api) and not slow"`），并对失败项做基线对照。误判实例与复现命令见基线 §9 技术债表。

### Full Test 使用时机

仅限：一个完整开发阶段结束、PR、发布前、CI、用户明确要求。执行前如预计耗时较长，先汇报测试规模。
日常全量为 `pytest`（自动排除 `legacy` 历史套件）；阶段收口 / 发布 / 需回归历史域时用 `pytest --run-legacy`。

## 5. LLM / Agent 测试规则

架构：`Application → LLM Interface（llm_factory / get_chat_llm）→ Real LLM（生产）/ FakeLLM（测试）`。

- 一律复用 `tests/conftest.py::FakeLLM`，不要另造 mock 体系。
- 禁止测试中发起真实 LLM / 外网调用（FakeLLM 的 base_url 指向 `example.invalid` 兜底）。
- Chain 测试通过 `llm=` 参数直接注入 FakeLLM；Router/E2E 通过 dependency override 注入。

## 6. Slow Test 与稳定性

- 慢测试不删除，只隔离：日常开发用 `-m "not slow"` 排除。
- 已知慢测试（server 线程 + 轮询等待）：`tests/e2e/test_chat_http_integration.py`、`tests/e2e/test_turn_meta_stream.py`、`tests/integration/test_goal_e2e.py`。
- **TestClient/lifespan 说明**：`with TestClient(app)` 触发的全应用 E2E 较慢（首个用例即拉起完整 lifespan），默认标记 `slow` 隔离。早前观察到的「lifespan 挂起」实为世界维护循环 `run_world_maintenance_loop`（循环体首轮同步访问 DB）连接真实 PostgreSQL(`.env`) 而无实例所致，**非 fastapi 版本问题**；已由 conftest autouse `_offline_repos`（world_repository 等全部落内存 SQLite）从根源修复，无需再关闭 world。
- **根因B（已修复）**：`PromptBuilder.build(..., analysis=...)` 隐含访问 `relationship_milestone_repository.SessionLocal`，导致 `test_answer_chain` / `test_v5_matrix` 等“纯单测”连真实 PG 而挂起；已由 conftest autouse `_offline_repos`（默认把所有 repo `SessionLocal` 指向内存 SQLite）修复。需真实 PG 的迁移测试设 `TEST_USE_POSTGRES=1`。
- 后台任务等待统一用 `conftest.wait_until`（有 deadline 的谓词轮询），禁止新增裸 `sleep(5)` 掩盖竞态。
- 时间冻结用注入 TimeProvider（不 monkeypatch `datetime.now`）。
- 迁移类测试依赖本机 PostgreSQL 时自动 skip，属预期行为，不算失败。
- **超时兜底**：pytest-timeout 全局启用（`timeout = 120`、thread 方法，见 `pyproject.toml`），任何用例卡死 120s 后被强制失败并 dump 全线程栈，不再无限等待；等待一律用 `conftest.wait_until` 等有界机制，禁止无界轮询。
- **新模块接入 offline 保护**：services / application 层新增模块级 `SessionLocal`（`from app.core.db import SessionLocal`）的模块，必须同步加入 `tests/conftest.py::_SERVICE_DB_MODULES`（autouse `_offline_repos` 默认只覆盖 `repositories/*`），否则测试会连真实 PostgreSQL（`.env`）挂起——根因B 模式，MEM-003 评估器/摄取模块曾复发。

## 7. CI 策略

当前无 CI。推荐：

```text
Developer / AI：Focused → Module → Fast → commit
CI（未来接入）：Fast Test → Integration → E2E → Full Test
```

CI 上注意：`TEST_DATABASE_URL` 提供 PostgreSQL service container，否则迁移测试 skip。

## 8. 已知问题 / 待办

- `tests/unit/` 中有 5 个文件实际使用内存 DB（`test_chat_pipeline_split.py`、`test_orchestration_v2.py`、`test_relationship_models.py`、`test_scene_updater.py`、`test_trigger_followup.py`），自动打标会归入 `integration`，不影响正确性；后续可迁至 `tests/integration/`。
- `tests/v8.5/`、`evaluation/` 为按版本组织的套件，保持现状不迁移，统一按 fixture 打标为 `integration`。

## 9. 历史套件归档登记（2026-10-08）

`pytest` 默认只跑管家主线 + 分层测试（约 3170 项）；`pytest --run-legacy` 追加下表 legacy 套件。

| 套件 | 状态 | 覆盖承接方 |
|---|---|---|
| `tests/v2/` `v8.5/` `v22/` `v23/` `v24/` `v25/` `v26/` | 保留（`legacy`，默认不收集） | — |
| `tests/v7.8/` | **已删除** | v30 Runtime + `integration/test_observability_llm_turn_capture.py` 等 |
| `tests/v8/` | **已删除** | `tests/v23/`（世界模拟） |
| `tests/v9/` | **已删除** | `tests/v26/`（动作执行 + step-result 契约） |
| `tests/v21/` | **已删除** | `tests/v30/`（agent_runtime） |

被删除文件明细（同批）：`v24/` 的 `test_tool001_settings.py`、`test_tool006_params.py`、`test_tool_acceptance.py`；`v25/` 的 `test_plan002_settings.py`、`test_plan004_flags.py`、`test_plan009_flags.py`、`test_plan011_regression.py`、`test_plan012_flag_matrix.py`、`test_plan012_gates_and_invariants.py`；另删除两条冻结断言：`v25/test_plan001_flag_regression.py::test_planning_prompt_bytes_are_unchanged`、`v30/test_runtime_autonomous_loop.py::TestSchedulerUnchanged::test_maintenance_steps_unchanged`（v40 `test_runtime_background_cutover.py` 已覆盖新口径）。

删除判据：版本契约 / 开关快照 / 逐字节摘要类用例在每轮合法演进中持续假红（如 `ACTION_TYPES` 白名单扩项即改 prompt 字节），维护成本高于检出价值；行为覆盖均留在承接套件。

引用提示：`docs/version/v1.0.0/v9/regression-checklist.md`、`docs/version/v2.5.0/planning-system/regression-checklist.md` 已就地加注；其余历史设计文档（各版本 `tasks/`、`testing.md`）保留原文，视为当时的记录。
