# DB-02 conversation_repository

| 字段 | 内容 |
|---|---|
| Task ID | DB-02 |
| Task Name | conversation_repository（会话/消息仓储） |
| Type | DB |
| Priority | P0 |

## Description

实现 `app/repositories/conversation_repository.py`，封装 conversations / messages 两表的全部读写，供短期记忆服务使用。仓储层是数据访问的唯一入口，业务层禁止直接操作 ORM。

## Scope

- `get_or_create_conversation(conv_id, user_id) -> Conversation`
- `save_message(conv_id, role, content) -> Message`
- `get_recent_messages(conv_id, limit) -> list[Message]`（按 created_at 升序返回最近 limit 条）
- `count_messages(conv_id) -> int`（供摘要触发判断）
- `touch_conversation(conv_id)`（更新 updated_at）

## Out of Scope

- 窗口裁剪 / 字符预算逻辑（BE-07 conversation_service）
- 摘要相关读写（DB-03）
- 长期记忆读写（DB-04）

## Dependencies

- DB-01（engine / ORM Model / Session）
- BE-03（ChatMessage 作为对外 DTO 映射参照）

## Input

- `app/core/db.py`（engine、Session、Conversation/Message ORM Model）
- `docs/version/v1.0.0/v1/v1-architecture.md` §5 表设计

## Output

- `app/repositories/conversation_repository.py`

## Business Rules

1. `save_message` 的 `role` 仅允许 `human` / `ai`。
2. `get_recent_messages` 时间升序返回（最早的在前），供 prompt 保持聊天顺序。
3. `get_or_create_conversation` 幂等：存在返回既有记录，不存在新建。
4. 所有方法通过统一 Session 管理（上下文自动提交/回滚），单方法内事务。
5. 方法签名返回 ORM 对象或 Pydantic DTO 均可，但对外稳定（本 Task 建议直接返回 ORM，BE-07 负责 DTO 转换）。

## API Dependencies

- 无

## Data Dependencies

- `conversations` / `messages` 表（DB-01）

## Permission

- 无鉴权要求。

## Error Handling

- 非法 role：抛 `ValueError`，不落库。
- 会话不存在且无创建权限场景（如删除后）：`get_recent_messages` 返回空列表，不抛异常。
- DB 异常：回滚后向上抛，由调用方处理。

## Subtask 拆分

- S1：`get_or_create_conversation`
- S2：`save_message` + 非法 role 校验
- S3：`get_recent_messages` + `count_messages`
- S4：`touch_conversation`

## Acceptance Criteria

- 同 id 两次 `get_or_create_conversation` 返回同一条记录
- 写入 5 条消息，`get_recent_messages(limit=3)` 返回最新 3 条且升序
- `count_messages` 正确计数
- 非法 role 抛错且表中无脏数据

## Test Requirements

- 内存 SQLite 下：幂等创建、分页窗口、升序、计数、非法 role 拒绝。
- 测试不得依赖真实网络。