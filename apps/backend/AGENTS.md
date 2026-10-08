# AGENTS.md（backend）

## 工作目录

所有 Python 命令在本目录（`apps/backend/`）下执行（Windows + PowerShell，venv 在 `.venv`）。

```powershell
uv run pytest tests/ -v        # 测试
uv run pytest --cov -n 0       # 覆盖率（xdist 多 worker 不收集，须 -n 0 单进程）
uv run pylint app tests        # 代码检查
uv run uvicorn app.main:app --reload --port 8020   # 启动服务
```

## 任务入口

- **架构类问题先查** `docs/current-system-architecture-baseline.md`（当前系统唯一可信架构基线，描述已实现的真实系统；**分层与边界的权威描述**以其 §2 为准）。
- 开发前读对应版本的 `tasks.md` 确认 Task 及其 Scope / 依赖：当前版本 `docs/version/v2.6.1/tasks.md`，各版本设计文档在 `docs/version/<版本>/`。
- 飞书通道相关改动另见 `docs/integrations/feishu/architecture.md`（本域唯一架构依据）+ `review-v1.1.md`（已知缺陷与多实例硬前置）。

## 架构约束

分层单向依赖，禁止反向引用：

```text
channels（通道层：base.py 契约 + feishu/ 适配器）
   ↓
api → application（编排） → services → repositories → core
         ├── agent_runtime（Run 生命周期唯一管理者）┘
         └── chains（LLM 链）┘
```

- `application/` 只做调度与容错（编排管线、post_process 步骤注册），不做状态计算；新增能力以注册新步骤 / 新 context 段的方式接入。
- `agent_runtime/`（`application/agent_runtime/`）是 Run 生命周期的唯一管理者：`open → 执行阶段 → close`，**唯一写面 = `loop_runs`**；三种 Run Profile（`foreground_chat` / `autonomous_tick` / `event_driven`）在 `profiles.py` **唯一声明**，禁止另开阶段序列。
- 纯函数引擎（`app/engines/`：如 `behavior.py` / `state.py` / `autonomy.py`）无 IO、无 LLM，可直接单测。
- `api` 层禁止直接依赖 `repositories` 与 langchain。
- **通道层边界**：`channels/` 只做「消息归一为 `InboundMessage` + 经 `OutboundMessage` 契约出站」，**不得**包含 Agent / Memory / World 逻辑，也不得 import 任何 Autonomy 模块；核心层（`application` / `services` / `repositories` / `chains` / `core` / `character`）**不得** import `app.channels.<impl>`（如 `app.channels.feishu`），**仅可** import `app.channels.base`（零第三方依赖、零 `app.*` 依赖的契约）。
- LLM 实例必须来自 `core/llm_factory.get_llm()`（profile 机制），禁止各处新建 `ChatOpenAI`；结构化输出统一走 `chains/structured.py` 的 `build_structured_chain`（主链 + 一层降级），禁止自由解析。
- DB 访问只能走 `repositories/`，业务层禁止直接操作 ORM。
- 数据库结构变更只走 Alembic（`migrations/`，**基线迁移 `0001`（2026-09-29 全链折叠）+ 增量迁移 `0002` 起**），`create_all` 已退役（单元测试内存建表属豁免）。
- 所有阈值/魔法数字放 `core/settings/` 包（**24 个领域模块**，平铺字段名），禁止硬编码。
- 数据流：读取进链、写入出链——DB 写入在流式回答结束后执行；后处理（post_process）失败不得影响已产出的回答。
- 单一写面纪律：计划落库只经 `goal_repository` 计划面；行动写世界只走 `deferred_world_op → outbox → world_engine`；Run 只写 `loop_runs`；关系状态只经 `relationship_evolution` / 状态只经 `state_service`。
- 角色资产按人设分子目录存放于 `character/<persona>/`（如 `character/asuna/`），每人设一套 identity/personality/relationship/behavior/modes/goals/habits。

## 代码规范

- 异步优先：I/O 一律 `async/await`；**同步阻塞调用（如同步 SQLAlchemy）不得直接跑在事件循环上**，须 `asyncio.to_thread` 下放。
- Prompt 组装必须走 `prompts/` 模板（PromptBuilder），禁止手工拼接字符串。

## 测试约定

- 完整规范见 `docs/TESTING.md`（marker、执行级别、AI Coding 测试规则）。
- `pytest` + `pytest-asyncio`，fixture 在 `tests/conftest.py`；目录分层 `unit / integration / e2e / golden / evaluation / eval / v7.8 / v8 / v8.5 / v9 / v2 / v21~v26`。
- **AI 修改代码后禁止默认执行全量 `pytest`**：必须先 Focused Test → Module Test → 必要时 Fast Test（`pytest -m "(unit or api) and not slow"`；多个 `-m` 连用只有最后一个生效，勿拆开写）。
- marker（`unit / api / integration / e2e / golden / slow`）由 `tests/conftest.py::pytest_collection_modifyitems` 自动打标，新测试无需手写。
- **测试禁止真实 LLM 调用**：用 `core/llm_factory.set_llm(mock)` 注入 FakeLLM（结构化输出按 schema 类名分发）。
- 单元 / 集成 / e2e 测试 DB 用 worker 级文件库 SQLite（`.tmp/offline-db/`，WAL + 每 Session 独立连接），每测试重建表；`tests/integration/test_db_migration.py` 验证 Alembic 与 ORM 一致，需 `TEST_DATABASE_URL` 指向真实 PostgreSQL。
- **新增仓储 / 服务必须注册进 `tests/conftest.py`**（仓储 → `_REPO_MODULES`；服务内使用模块级 `SessionLocal` → `_SERVICE_DB_MODULES`），否则内存库补丁被绕过、测试连真实 PG 而挂起。
- golden prompt 快照回归：`tests/golden/` + `tests/unit/test_prompt_golden.py`，`UPDATE_GOLDEN=1` 重新生成。
- 慢测试加入 `conftest.py` 的 `SLOW_TEST_FILES`（或 `@pytest.mark.slow`），日常开发用 `-m "not slow"` 排除。
- 历史版本套件（`tests/v2`、`v8.5`、`v22`~`v26`）默认不收集（`legacy` marker + `--run-legacy` 开关）；改这些域时聚焦命令需带 `--run-legacy`。
- commit 门槛：影响范围分级测试全绿（Focused Test → Module Test → 必要时 Fast Test；`core/` 基础设施改动走 Fast Test）。全量 pytest 仅在阶段收口 / PR / 发布 / 用户明确要求时执行，执行前先汇报测试规模。

## 临时文件处理

- **禁止在仓库工作区内创建临时文件**：验证脚本、草稿、日志、测试输出一律不写入仓库目录；确需落盘时统一放 `apps/backend/.tmp/`（已 gitignore），或系统临时目录。
- **pytest 输出重定向**：需要落盘测试输出时重定向到 `apps/backend/.tmp/` 下；`pytest_out.txt` / `pytest_err.txt` / `*.log` / `.pytest_tmp/` 虽已 gitignore 兜底，但生成后应随手删除，不留到任务结束。
- **任务结束前清理**：每次任务收口（提交前）必须检查 `git status`，保证无未跟踪的临时产物（重定向日志、`pytest_last.log`、快照 diff、临时迁移草稿等）；已 gitignore 的临时目录（如 `.pytest_tmp/`）也应删除，避免磁盘残留。
- **commit message 不落盘**：多行 commit message 用 `git commit -F <系统临时目录文件>` 或命令行传参，禁止在仓库根创建 `.git-commit-msg.txt` 之类文件（即便事后删除，也会污染 `git status`）。
- **测试快照 / 报告产物**：golden 更新（`UPDATE_GOLDEN=1`）与 eval 报告属版本产物，按各自规范处理；其余一次性输出用完即删。
