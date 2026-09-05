# AGENTS.md（backend）

## 工作目录

所有 Python 命令在本目录（`apps/backend/`）下执行（Windows + PowerShell，venv 在 `.venv`）。

```powershell
uv run pytest tests/ -v        # 测试
uv run pylint app tests        # 代码检查
uv run uvicorn app.main:app --reload --port 8000   # 启动服务
```

## 任务入口

开发前先读 `docs/version/v1.0.0/v7.5/tasks.md`（当前任务注册表），确认当前 Task 及其 Scope / 依赖；各版本设计文档在 `docs/version/v1.0.0/v*/`。后端分层与边界的权威描述见 `docs/version/v1.0.0/backend-refactor/target-architecture.md`。

## 架构约束

分层单向依赖，禁止反向引用：

```text
api → application（编排） → services → repositories → core
         chains（LLM 链）┘    engines（纯函数）┘
```

- `application/` 只做调度与容错（编排管线、post_process 步骤注册），不做状态计算；新增能力以注册新步骤 / 新 context 段的方式接入。
- 纯函数引擎（如 `behavior_engine` / `state_engine` / `autonomy_policy`）无 IO、无 LLM，可直接单测。
- `api` 层禁止直接依赖 `repositories` 与 langchain。
- LLM 实例必须来自 `core/llm_factory.get_llm()`（profile 机制），禁止各处新建 `ChatOpenAI`；结构化输出统一走 `chains/structured.py` 的 `build_structured_chain`（主链 + 一层降级），禁止自由解析。
- DB 访问只能走 `repositories/`，业务层禁止直接操作 ORM。
- 数据库结构变更只走 Alembic（`migrations/`，当前链尾 `0011`），`create_all` 已退役（单元测试内存建表属豁免）。
- 所有阈值/魔法数字放 `core/settings.py`，禁止硬编码。
- 数据流：读取进链、写入出链——DB 写入在流式回答结束后执行；后处理（post_process）失败不得影响已产出的回答。
- 角色资产按人设分子目录存放于 `character/<persona>/`（如 `character/asuna/`），每人设一套 identity/personality/relationship/behavior/modes/goals/habits。

## 代码规范

- 异步优先：I/O 一律 `async/await`。
- Prompt 组装必须走 `prompts/` 模板（PromptBuilder），禁止手工拼接字符串。

## 测试约定

- 完整规范见 `docs/TESTING.md`（marker、执行级别、AI Coding 测试规则）。
- `pytest` + `pytest-asyncio`，fixture 在 `tests/conftest.py`；目录分层 `unit / integration / e2e / golden / evaluation / v7.8 / v8 / v8.5`。
- **AI 修改代码后禁止默认执行全量 `pytest`**：必须先 Focused Test → Module Test → 必要时 Fast Test（`pytest -m "(unit or api) and not slow"`；多个 `-m` 连用只有最后一个生效，勿拆开写）。
- marker（`unit / api / integration / e2e / golden / slow`）由 `tests/conftest.py::pytest_collection_modifyitems` 自动打标，新测试无需手写。
- **测试禁止真实 LLM 调用**：用 `core/llm_factory.set_llm(mock)` 注入 FakeLLM（结构化输出按 schema 类名分发）。
- 单元 / 集成 / e2e 测试 DB 用内存 SQLite（`sqlite:///:memory:`），每测试独立建表；`tests/integration/test_db_migration.py` 验证 Alembic 与 ORM 一致，需 `TEST_DATABASE_URL` 指向真实 PostgreSQL。
- golden prompt 快照回归：`tests/golden/` + `tests/unit/test_prompt_golden.py`，`UPDATE_GOLDEN=1` 重新生成。
- 慢测试加入 `conftest.py` 的 `SLOW_TEST_FILES`（或 `@pytest.mark.slow`），日常开发用 `-m "not slow"` 排除。
- commit 门槛：影响范围分级测试全绿（Focused Test → Module Test → 必要时 Fast Test；`core/` 基础设施改动走 Fast Test）。全量 pytest 仅在阶段收口 / PR / 发布 / 用户明确要求时执行，执行前先汇报测试规模。
