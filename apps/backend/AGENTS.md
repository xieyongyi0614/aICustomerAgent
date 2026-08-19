# AGENTS.md（backend）

## 工作目录

所有 Python 命令在本目录（`apps/backend/`）下执行（Windows + PowerShell，venv 在 `.venv`）。

```powershell
uv run pytest tests/ -v        # 测试
uv run pylint app tests        # 代码检查
uv run uvicorn app.main:app --reload --port 8000   # 启动服务
```

## 任务入口

开发前先读 `docs/v1/01-task-registry.md`（任务注册表），确认当前 Task 及其 Scope / 依赖。架构细节见 `docs/v1/v1-architecture.md`。

## 架构约束

三层单向依赖，禁止反向引用：`api → services → repositories → core`

- LLM 实例必须来自 `core/llm_factory.get_llm()`，禁止各处新建 `ChatOpenAI`。
- DB 访问只能走 `repositories/`，业务层禁止直接操作 ORM。
- 所有阈值/魔法数字放 `core/settings.py`，禁止硬编码。
- 数据流：读取进链、写入出链——DB 写入在流式回答结束后执行；记忆/摘要后处理失败不得影响已产出的回答。

## 代码规范

- 异步优先：I/O 一律 `async/await`。
- Prompt 组装必须走 `prompts/builder.py`（PromptBuilder），禁止手工拼接字符串。

## 测试约定

- `pytest` + `pytest-asyncio`，fixture 在 `tests/conftest.py`。
- **测试禁止真实 LLM 调用**：用 `core/llm_factory.set_llm(mock)` 注入 FakeLLM。
- DB 用内存 SQLite（`sqlite:///:memory:`），每测试独立建表。