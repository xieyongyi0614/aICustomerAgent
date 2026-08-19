# Task 2 — 短期记忆（多轮上下文）

> 实现"第二轮知道第一轮"。会话消息落库，读取时做窗口裁剪。
> 架构参考：`docs/v1/v1-architecture.md` §8 Task 2

## 目标

- 消息持久化到 SQLite（conversations / messages 表）
- 支持 `session_id` 区分对话
- 多轮对话中第二轮能引用第一轮内容

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `app/core/db.py` |
| 新建 | `app/repositories/conversation_repository.py` |
| 新建 | `app/services/conversation_service.py` |
| 新建 | `app/models/conversation.py` |
| 新建 | `app/api/v1/schemas.py` |
| 修改 | `app/api/v1/chat.py` |

## 实现步骤

1. `core/db.py`：SQLite engine + SQLAlchemy 2.0 ORM，统一建表入口（conversations / messages），支持内存 SQLite（测试用）。
2. `repositories/conversation_repository.py`：`get_or_create_conversation(conv_id, user_id)`、`save_message(conv_id, role, content)`、`get_recent_messages(conv_id, limit)`。
3. `services/conversation_service.py`：`load_window(conv_id, max_messages=20, max_chars=8000)` 返回 `list[ChatMessage]`。裁剪策略：
   - 优先保留最近消息
   - 超出字符预算时向前丢弃更早消息
   - 只改读取结果，不动库
4. `api/v1/schemas.py`：`ChatRequest(session_id: str | None, content: str)`、`ChatResponse` 定义。
5. `api/v1/chat.py`：端点接收 `session_id`，不存在则自动新建 conversation；流式输出改为 HTTP 流式响应（`StreamingResponse`）返回前端。
6. `services/agent_service.py`：流结束后保存 HumanMessage + AIMessage（回答内容在流式时累计）。

## 验收标准

- 同一 `session_id` 下："我在学 LangGraph" → "我今天刚学 Runnable"，第二轮回答能引用第一轮
- 不同 `session_id` 互不可见（各自独立窗口）
- 超长对话时窗口读取有上限，prompt 长度受控
- 第二次请求不重建会话（同 id 复用）