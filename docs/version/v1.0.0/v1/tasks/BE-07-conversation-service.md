# BE-07 conversation_service（短期记忆）

| 字段 | 内容 |
|---|---|
| Task ID | BE-07 |
| Task Name | conversation_service（短期记忆/多轮上下文） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/services/conversation_service.py`，管理短期记忆：按会话加载最近消息窗口（含裁剪策略）、保存每轮消息。实现"第二轮知道第一轮"（V1 功能目标一）。

## Scope

- `ensure_conversation(session_id, user_id) -> Conversation`
- `load_window(session_id, max_messages, max_chars) -> list[ChatMessage]`：
  - 取最近 `max_messages` 条
  - 超出 `max_chars` 字符预算时，从最早的消息向前丢弃
  - 只影响返回结果，不改库
- `save_turn(session_id, user_message, ai_reply)`：保存一轮 Human + AI 两条
- `message_count(session_id) -> int`（供摘要触发）

## Out of Scope

- 摘要生成（BE-08）
- 长期记忆（BE-10）
- Repository 层 SQL（DB-02）

## Dependencies

- DB-02（conversation_repository）
- BE-03（ChatMessage）

## Input

- `app/repositories/conversation_repository.py`
- `settings.CONVERSATION_MAX_MESSAGES`（20）、`CONVERSATION_MAX_CHARS`（8000）

## Output

- `app/services/conversation_service.py`

## Business Rules

1. 裁剪策略：**优先保留最近消息**；超字符预算时向前丢弃更早消息。
2. 返回消息按时间升序（保持聊天顺序）。
3. 保存一轮 = 一次事务内写两条（human + ai）。
4. 会话不存在时自动创建（`ensure_conversation` 幂等）。

## API Dependencies

- 无

## Data Dependencies

- `conversations` / `messages` 表（经 DB-02）

## Permission

- 无鉴权要求。

## Error Handling

- 会话不存在读取：返回空窗口（不抛异常）。
- 保存失败：事务回滚，向上抛异常。

## Subtask 拆分

- S1：`ensure_conversation`
- S2：`load_window`（裁剪策略）
- S3：`save_turn`
- S4：`message_count`

## Acceptance Criteria

- 同一 session："我在学 LangGraph" → 保存 → "我今天刚学 Runnable" 读取窗口包含前一轮，供回答链引用
- 不同 session 读取互不可见
- 写 50 条，`max_messages=20` 只返回最近 20 条，顺序正确
- 长文本超 `max_chars` 时最早消息被丢弃

## Test Requirements

- 多轮上下文连贯性、会话隔离、窗口上限、字符预算裁剪、保存一轮写两条。