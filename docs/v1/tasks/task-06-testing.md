# Task 6 — 测试

> 核心模块可测：LLM 用 mock 注入，DB 用内存 SQLite。
> 架构参考：`docs/v1/v1-architecture.md` §8 Task 6

## 目标

- 覆盖三层核心逻辑的单元/集成测试
- 验证记忆、摘要、提取、检索四个核心行为

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `tests/conftest.py`（mock LLM、内存 DB fixture） |
| 新建 | `tests/test_conversation.py` |
| 新建 | `tests/test_summary.py` |
| 新建 | `tests/test_extractor.py` |
| 新建 | `tests/test_retrieval.py` |
| 新建 | `tests/test_memory.py` |

## 实现步骤

1. `conftest.py`：`core/llm_factory.set_llm(FakeLLM)` 注入固定输出；SQLite 内存库（`sqlite:///:memory:`）每个测试独立 fixture。
2. `test_conversation.py`：窗口裁剪（最近优先、字符预算截断）、多轮上下文（第二轮能看到第一轮）、会话隔离（不同 session_id 互不可见）。
3. `test_summary.py`：阈值触发（40 条触发 / 39 条不触发）、滚动压缩（old_summary + new_messages 正确拼接）、upsert 幂等。
4. `test_extractor.py`：`should_save=true`（偏好/目标示例）、`should_save=false`（"今天吃了拉面"）、`importance < 0.6` 不落库。
5. `test_retrieval.py`：关键词打分、top-K 排序、低于阈值不返回。
6. `test_memory.py`：去重（相同内容重复不新增）、类型落库正确。

## 验收标准

- `pytest` 全绿（含 `pytest-asyncio` 异步用例）
- `pylint` 通过
- 测试不发起真实 LLM 调用（全部 mock）