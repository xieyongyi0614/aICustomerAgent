# TEST-01 测试基础设施（conftest）

| 字段 | 内容 |
|---|---|
| Task ID | TEST-01 |
| Task Name | 测试基础设施（conftest） |
| Type | TEST |
| Priority | P0 |

## Description

搭建测试基座：`tests/conftest.py` 提供 mock LLM 与内存 SQLite 的全局 fixture，确保所有测试不发起真实网络调用。是 TEST-02/03/04 的共同前置。

## Scope

- `tests/conftest.py`：
  - 内存 SQLite fixture（`sqlite:///:memory:`，每测试独立建表）
  - `FakeLLM`：可配置返回固定文本 / 分块 / 结构化 JSON / 抛异常
  - `set_llm(fake)` 注入，`reset_llm()` 恢复（调用 BE-02）
  - settings 覆盖 fixture（临时阈值）
- `tests/__init__.py` / 目录结构
- 确认 `pytest` + `pytest-asyncio` 可用（dev 依赖）

## Out of Scope

- 具体业务用例（TEST-02/03/04）
- 真实 LLM 联调

## Dependencies

- BE-01（settings）
- BE-02（llm_factory 注入机制）
- DB-01（建表）

## Input

- `app/core/llm_factory.py`、`app/core/settings.py`、`app/core/db.py`

## Output

- `tests/conftest.py`
- `tests/` 目录与空占位

## Business Rules

1. 每个测试独立内存库，互不污染。
2. `FakeLLM` 需支持 async `ainvoke` 与流式 `astream`（用于 BE-06/08/09/12/13）。
3. 结构化输出场景：FakeLLM 直接返回 dict/JSON 字符串，验证 `with_structured_output` 解析路径。
4. 所有 fixture 作用域默认 function（除非明确需要 session）。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- FakeLLM 支持"抛出指定异常"模式，供错误路径测试。

## Subtask 拆分

- S1：内存 SQLite fixture
- S2：FakeLLM（文本/分块/结构化/异常四种模式）
- S3：set/reset LLM 注入
- S4：settings 覆盖 fixture

## Acceptance Criteria

- `pytest -q` 空测试集可运行
- 任意依赖该基座的测试不产生网络请求（可用 mock 拦截断言）
- FakeLLM 四种模式均可驱动

## Test Requirements

- 本 Task 自身：写 1 个冒烟用例验证 fixture 可被消费。