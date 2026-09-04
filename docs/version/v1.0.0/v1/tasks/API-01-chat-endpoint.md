# API-01 chat 端点（流式响应 + 错误处理）

| 字段 | 内容 |
|---|---|
| Task ID | API-01 |
| Task Name | chat 端点（流式响应 + 错误处理） |
| Type | API |
| Priority | P0 |

## Description

实现聊天 HTTP 端点：接收 `session_id` 与用户消息，调用 BE-13 编排流式返回亚丝娜回答。解决 V0 中"流式输出打到控制台、端点无返回、无错误处理"问题（架构文档 A5/A6）。

## Scope

- `app/api/v1/schemas.py`：`ChatRequest(session_id: str | None, content: str)`；响应 DTO
- `app/api/v1/chat.py`：
  - `POST /api/v1/chat/message`
  - 无 session_id 时自动生成新 session（返回创建结果）
  - 流式响应（`StreamingResponse`，SSE 或 chunked JSON）
  - 错误转 HTTP 状态码 + 结构化 JSON
- `app/api/v1/router.py` 挂载

## Out of Scope

- 鉴权（P2）
- 前端
- 业务编排（BE-13）

## Dependencies

- BE-13（agent_service.stream_chat）

## Input

- `app/services/agent_service.py`
- `app/main.py` / `app/api/v1/router.py`（现有路由挂载点）

## Output

- `app/api/v1/schemas.py`
- `app/api/v1/chat.py`（改造现有端点）
- 路由注册

## Business Rules

1. `content` 必填且非空；空串返回 422。
2. `session_id` 可选：缺失时服务端生成 UUID 并返回。
3. 流式格式：V1 采用简单 chunked JSON（`{"delta": "..."}` 逐 token），便于前端逐字渲染；不引入完整 SSE 协议。
4. 正常流结束后追加一个结束标记（如 `{"done": true}`）。
5. 异常时返回 `{"detail": "..."}`，状态码按错误类型（LLM 失败 502 / 参数错误 422 / 内部错误 500）。

## API Dependencies

- `POST /api/v1/chat/message`（本任务新增）

## Data Dependencies

- 经 BE-13 间接读写三张表

## Permission

- V1 无鉴权；会话隔离由 `session_id` 保证（文档明确标注为临时方案，鉴权为 P2）。

## Error Handling

- `content` 空 → 422
- LLM 调用失败 → 502 + 结构化 detail（不泄漏内部堆栈）
- 其他未预期异常 → 500 + 日志记录
- 流中断（客户端断开）：服务端停止生成，清理后台任务

## Subtask 拆分

- S1：`schemas.py` 请求/响应 DTO
- S2：流式响应实现（chunked JSON）
- S3：session 自动创建
- S4：异常映射与日志
- S5：路由挂载

## Acceptance Criteria

- `curl` POST 正常返回流式 delta 块并以 done 结束
- 无 session_id 请求返回新 session_id
- 空 content 返回 422
- mock LLM 抛错时返回 502 且 detail 为结构化 JSON
- 响应整体可通过 `/health` 同进程共存

## Test Requirements

- 用 `TestClient`（Starlette）测试流式响应完整性、422、502、session 自动创建。
- LLM 全程 mock，不发真实请求。