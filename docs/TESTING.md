# 后端测试规范与 AI Coding 测试执行规则

> 位置：`apps/backend/tests/`，pytest 配置：`apps/backend/pyproject.toml [tool.pytest.ini_options]`。
> 原则：**测试可靠性 > 覆盖数量 > 执行数量**。AI 修改代码后禁止默认执行全量测试。

## 1. 测试分类

| 类型 | 特征 | 位置 | marker |
|---|---|---|---|
| Unit | 纯函数 / Chain / Domain 逻辑；无 DB、无 HTTP、无网络；允许 FakeLLM | `tests/unit/` | `unit` |
| API | FastAPI Router + httpx `ASGITransport`；参数校验 / Status / Response Model / Dependency Override；FakeLLM + 离线 SQLite | `tests/e2e/`（端点类）、unit 内少量编排测试 | `api` |
| Integration | DB 读写 / Alembic 迁移 / 多模块协作；离线 SQLite（worker 级文件库，每测试重建表） | `tests/integration/`、`tests/v8.5/`、`tests/evaluation/` | `integration` |
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
- DB：测试使用 worker 级文件库 SQLite（`apps/backend/.tmp/offline-db/`，WAL + 每 Session 独立连接，每测试 `drop_all + create_all` 重建表），不依赖外部实例；`TEST_USE_POSTGRES=1` 时改用真实 PostgreSQL。
- 唯一例外：`tests/integration/test_db_migration.py`、`test_relationship_migration.py` 需要真实 PostgreSQL（`TEST_DATABASE_URL`），**无实例时自动 skip**。
- CI：`.github/workflows/ci.yml`（`mobile` / `backend` / `backend-full` 三个 job，见 §7）。

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
> 全量默认已启用 `pytest-xdist`（`-n auto --dist loadgroup`，见 pyproject addopts），并行安全：worker 级文件库 + 每 Session 独立连接、无共享外部状态、无 Redis；需要真实 PostgreSQL 的迁移测试文件用 `xdist_group("migration")` 钉入同一 worker 顺序执行，避免并发升降级同一 `asuna_test` 库互踩。

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

`.github/workflows/ci.yml`（触发：push 到 `main`、tag `v*`、PR 到 `main`、手动）：

| job | 内容 |
|---|---|
| `mobile` | `flutter pub get` + `flutter analyze` + `build_runner build` 产物零 diff + `flutter test` |
| `backend` | `uv sync` → `pytest tests -q -m "not slow"`（日常全量 − slow；无 PG，迁移类自动 skip） |
| `backend-full` | `needs: backend`；带 `postgres:16` service（`TEST_DATABASE_URL`）→ `pytest --run-legacy -q`（含 slow、legacy 历史套件与 PG 迁移用例） |

本地节奏不变：

```text
Developer / AI：Focused → Module → Fast → commit
CI：Fast（每次触发）→ Full（同一流水线内串行，含 PG）
```

CI 上注意：`backend-full` 的 `TEST_DATABASE_URL` 指向 service container；缺 PG 时迁移类用例自动 skip（`backend` job 即此路径）。

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

## 10. 回归判据与已知失败基线（T-25，2026-10-09 重采）

### 10.1 判据：**失败集 diff，不是失败计数**（铁律）

> **判「本次改动是否引入回归」的唯一判据**：把改动前后两次全量的**失败用例集合**做 diff。
> **禁止**用「失败数从 N 变成 M」来判断——本机存在非确定性环境噪声（见 10.2），
> 计数天然抖动（实测两次默认全量：21 failed vs 7 failed，同一份代码、未改一行）。

正确流程：

```text
① 改动前跑一次全量 → 存失败集 A（用例 id 列表，排序去重）
② 改动后再跑一次   → 存失败集 B
③ A - B 与 B - A 均应为空（或差异项能逐个解释）
④ 对差异项做隔离重跑（-n 0）判定真伪
```

### 10.2 本机既有环境噪声：`safe-delete` 外部守卫（**不在仓库内**）

- **机制（2026-10-16 查实）**：本机 CLI 经 `sitecustomize.py`
  （`<WorkBuddyAI>/resources/app.asar.unpacked/cli/vendor/shim/`）包装
  `shutil.rmtree` / `os.remove` / `os.unlink`：
  - 目标路径**在 `tempfile.gettempdir()`（即 `%TEMP%`）之下 → 走原生删除（旁路）**；
  - **否则 → 移入 Windows 回收站**（`genie-trash`），且**单棵目录 >50 文件时
    `_check_bulk_delete_guard` 直接 `raise SystemExit(1)`**（阈值与状态见 `CODEBUDDY_SAFE_DELETE_BULK_*`）。
- **现象**：pytest 清理 `tmp_path` 时撞上守卫 → 用例以 **teardown `ERROR: SystemExit: 1`** 出现，
  同一 worker 后续用例级联报 `AssertionError: previous item was not torn down properly`；
  被删文件同时堆进回收站（C 盘配额 25.79GB，堆满即 C 盘爆满）。
- **特征**：**非确定性**——命中集合与数量随 worker 负载变化；
  隔离重跑（`-n 0`、单独文件/目录）**稳定通过**。
- **判定方法**：差异项隔离重跑 3 次，3/3 通过即判**噪声**，不是回归。
  报错栈里出现 `sitecustomize.py` / `_check_bulk_delete_guard` / `SystemExit: 1` 即为本条，与本仓库代码无关。
- **规避（2026-10-16 修正，原建议有误）**：
  - ✅ **不要传 `--basetemp`** → 默认落在 `%TEMP%\pytest-of-<user>\pytest-<N>`，删除自动旁路、零回收站流量；
  - ✅ 若需自定义命名，**必须放在 `%TEMP%` 之下**（如 `--basetemp="$TEMP/t_xxx"`）；
  - 🚫 **不要指向 `C:\tmp` 或别的盘**——路径一旦离开 `%TEMP%`，回收站与 50 文件守卫**都会**命中；
  - 📌 实测对照：`--basetemp=C:/tmp/...` → `3507 passed / 18 errors`；默认 basetemp →
    **`3516 passed / 7 skipped / 0 failed / 0 errors`**，且回收站零增长；
  - 📌 清理大量临时目录：先 `Move-Item` 到 `%TEMP%` 再删（移动不是删除，不进回收站）；
  - 📌 `_OFFLINE_DB_DIR`（`apps/backend/.tmp/offline-db`）**不受 basetemp 影响**、也不在 `%TEMP%` 下
    → 每轮约 20MB `gw*.db` 的删除仍会进回收站；要归零需把它也移到 `%TEMP%` 下，或关闭 C 盘回收站。
- **输出重定向**：**必须写 `apps/backend/.tmp/`**（禁写仓库根）。

### 10.3 当前已知失败基线（2026-10-09 实测）

> **当前真实已知失败集：空（0 条）。**

采证过程（本机，PG 在跑 + `.env` 已加载，HEAD `ea32bbf9`）：

| 运行 | 命令 | 结果 |
|---|---|---|
| 默认全量 #1 | `pytest -q` | **21 failed / 3283 passed / 7 skipped / 25 errors** |
| 默认全量 #2 | `pytest -q` | **7 failed / 3298 passed / 7 skipped / 24 errors** |
| 两次失败集交集 | — | **仅 1 条**（`v50/test_memory_product_view.py::test_total_matches_group_sum`） |
| `tests/v50` 隔离 | `pytest tests/v50 -n 0` | **284 passed**（0 失败） |
| `tests/v51` 隔离 | `pytest tests/v51 -n 0` | **97 passed**（0 失败） |
| 交集那条隔离 | `pytest tests/v50/test_memory_product_view.py tests/v51/test_ledger_stats_api.py -n 0` | **47 passed** |

**结论**：两次默认全量的失败集**几乎不重叠**（21 vs 7，交集仅 1 条），且交集那条隔离通过
→ **全部为 10.2 所述环境噪声，真实回归为零。**

> ⚠️ **旧的「26 failed 基线」清单已作废**（2026-10-09 实测其中多条隔离重跑通过）。
> 该清单不再作为判据；**以「改动前后失败集 diff」为准**。

分层基线参考（`-n auto`，`tests/unit + integration + e2e`）：**2201 passed + 7 skipped**。

### 10.4 2026-10-15/16 清账记录（已归零）

历史套件（`--run-legacy`）此前累积 **25 条既存失败**，已按 §10.1 手法逐条定性并全部清除：

| 组 | 条数 | 性质 | 处置 |
|---|---|---|---|
| `v25/test_plan011_debug_api.py` | 19 | 调试面身份收口后需 token，而该模块命中不了 conftest 的自动鉴权 override | 模块内显式安装 override |
| `v25/test_plan_approval_gate.py` | 1 | 断言真实 401，但 conftest 已装默认 override | 用例内自清 override |
| `v51/test_car_api.py` | 1 | **日历腐烂**（写死购买日期 + 精确车龄断言） | 断言锚定「今天 − N 个月」 |
| `v24` 冻结摘要 / 表集摘要 | 4 | 2 条旧账（漏同步）+ 2 条本次改脏 | 按 §11.3 同步并附声明 |

**当前状态**：默认全量与 `--run-legacy` 全量失败集均为空；新增失败一律按 §10.1 与本次改动做 diff。

## 11. 冻结面 / 钉测处置流程（T-23）

固定整文件摘要的钉测（`ZERO_DIFF_HASHES` / `FROZEN_SOURCES`）在涉事文件被改动时会红，
这是**设计意图**（防止无意改动关键路径）。处置步骤：

### 11.1 先判「是我改坏的」还是「常量旧账」

**步骤 1 — 拿到 actual 摘要。** 自 T-24 起，失配断言会直接打印 expected 与 actual
（见 11.2），无需手工计算。若需手工复算：

```bash
# 在 apps/backend/ 下
python -c "import hashlib,pathlib; p=pathlib.Path('app/application/world_engine.py'); print(hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest())"
```

**步骤 2 — 对照本次改动范围。**
- 本次**确实**改了这个文件 → 属预期，走 11.1 的同步流程。
- 本次**没碰**这个文件 → 常量**早已 stale**（旧账）：查该文件最近一次改动 commit
  当时是否漏同步摘要。**不要**把它当成自己的回归。

> 🚨 真实踩过的坑：2026-09-28 实测 `world_engine.py` 在**动手改动之前**就是红的
> （上一次演进漏同步）。这正是 T-24 把「先打印 actual」做进断言的原因。

### 11.2 T-24：诊断工具 `tests/support/frozen_surface.py`

所有整文件冻结比对统一走该模块（失败信息含 expected / actual / 可直接粘贴的同步行）：

```python
from tests.support.frozen_surface import assert_frozen, file_digest

assert_frozen(relative, expected=FROZEN_SOURCES[relative], actual=file_digest(relative))
```

摘要算法：读字节 → `\r\n` 归一为 `\n` → `sha256` hexdigest
（行尾归一抵消 `core.autocrlf=true` 检出的假失败）。
**该模块只做诊断呈现，不改任何摘要常量、不放宽断言。**

### 11.3 合法同步摘要（确认磁盘内容正确后）

1. 复制失败信息里给出的 `路径: "摘要"` 行，替换常量中的对应值。
2. 在常量处**加一行声明注释**（改了哪个文件、为什么、日期）。
3. 只改摘要常量 + 声明注释，**不要顺手改被测文件**。
4. 重跑该钉测文件（`--run-legacy`，见 §3 提示）确认转绿。

### 11.4 其他需同步的钉测点（改迁移 / 改 schema 时）

- `tests/support/schema_pins.py`：`MIGRATION_HEAD` / `SCHEMA_PREVIOUS_HEAD` /
  `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`（全仓唯一定义，禁止本地字面量）。
- 各版本测试内的硬编码断言（如 `tests/v40/test_ledger_migration_0054.py::test_schema_table_count_is_49`）。
  **加一个迁移会打破约 22 个跨版本钉测**，上述两处都要查，只改前者会漏。
- `tests/v24/test_tool011_security.py::EXPECTED_TASK_GLOBALS` / `EXPECTED_CREATE_TASK_COUNT`：
  `main.py` 常驻 task 清单期望值——**增删 `main.py` 的 `create_task` 必须同步**。
