# TEST-03 摘要专项测试

| 字段 | 内容 |
|---|---|
| Task ID | TEST-03 |
| Task Name | 摘要专项测试 |
| Type | TEST |
| Priority | P0 |

## Description

编写对话摘要（BE-08 + DB-03）专项测试，验证阈值触发、滚动压缩、upsert 幂等。

## Scope

- `tests/test_summary.py`：
  - 阈值边界：39 不触发 / 40 触发
  - 滚动压缩：old_summary + new_messages 正确拼接进 prompt（mock 断言输入）
  - 空消息输入不调用 LLM
  - upsert 幂等、updated_at 刷新
  - 无摘要读取返回 None

## Out of Scope

- 摘要与编排集成（TEST-04）
- 其他模块

## Dependencies

- TEST-01（conftest）
- BE-08（summary_chain + summary_service）
- DB-03（summary_repository）

## Input

- `docs/version/v1.0.0/v1/tasks/BE-08-summary-service.md` 的 Test Requirements

## Output

- `tests/test_summary.py`

## Business Rules

1. mock LLM 记录调用输入，断言 prompt 内含旧摘要与新增消息。
2. 所有用例使用内存库。

## API Dependencies

- 无

## Data Dependencies

- `conversation_summaries` 表（内存库）

## Permission

- 无鉴权要求。

## Error Handling

- LLM 失败路径：断言异常向上抛，不被吞。

## Subtask 拆分

- S1：阈值边界
- S2：滚动压缩输入断言
- S3：upsert 幂等与空输入

## Acceptance Criteria

- 上述场景全部通过，`pytest tests/test_summary.py` 全绿。

## Test Requirements

- 本 Task 即测试本身。