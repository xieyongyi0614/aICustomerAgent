# DB-03 summary_repository

| 字段 | 内容 |
|---|---|
| Task ID | DB-03 |
| Task Name | summary_repository（摘要仓储） |
| Type | DB |
| Priority | P0 |

## Description

实现 `app/repositories/summary_repository.py`，封装 `conversation_summaries` 表读写。一对话一行摘要，滚动更新。

## Scope

- `get_summary(conv_id) -> ConversationSummary | None`
- `upsert_summary(conv_id, summary) -> ConversationSummary`（存在则更新 summary + updated_at，不存在则插入）
- `delete_summary(conv_id)`（清理用，可选）

## Out of Scope

- 摘要生成逻辑（BE-08 summary_service）
- 触发阈值判断（BE-08）
- 其他表读写

## Dependencies

- DB-01（engine / ORM Model / Session）
- BE-03（ConversationSummary DTO）

## Input

- `app/core/db.py`（ConversationSummary ORM Model）
- `docs/version/v1.0.0/v1/v1-architecture.md` §5 表设计

## Output

- `app/repositories/summary_repository.py`

## Business Rules

1. `conversation_id` 为主键，`upsert` 必须幂等（多次调用最终只一行）。
2. `updated_at` 在更新时刷新为当前时间。
3. 摘要文本为空字符串时按 None 处理（不落空摘要）。

## API Dependencies

- 无

## Data Dependencies

- `conversation_summaries` 表（DB-01）

## Permission

- 无鉴权要求。

## Error Handling

- 未找到摘要返回 `None`（不抛异常）。
- DB 异常：回滚后抛出，由调用方处理。

## Subtask 拆分

- S1：`get_summary`
- S2：`upsert_summary`（含幂等）
- S3：`delete_summary`

## Acceptance Criteria

- 无摘要时 `get_summary` 返回 None
- 连续两次 `upsert_summary` 后表中仅一行，summary 为最后一次内容
- 更新后 `updated_at` 变化

## Test Requirements

- 内存 SQLite 下：get/upsert 幂等/delete、updated_at 刷新。
- 测试不依赖真实网络。