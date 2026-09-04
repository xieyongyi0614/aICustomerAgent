# API-FE-101 · ChatStreamTransport 抽象与 NDJSON 事件归一化

## Task ID

API-FE-101

## Task Name

ChatStreamTransport 接口、NDJSON Real 实现与 StreamEvent 归一化层

## Type

API

## Priority

P0

## Description

实现前端唯一的流式通道抽象：接口定义、基于 fetch + ReadableStream 的 NDJSON Real 实现、原始行到类型化 StreamEvent 的归一化解析。该层是「前端唯一允许感知传输格式的位置」，上游全部面向事件回调工作。

## Scope

- `transport.ts`：ChatStreamTransport 接口——send(request 包含 sessionId?/content, 监听器 onEvent/onError/onClose, signal)
- `chat-stream.ts`：Real 实现——POST `/api/v1/chat/message`、读取 body reader、按换行分帧（保留半行缓冲至下一 chunk）、逐行 JSON.parse、逐事件回调；AbortController 贯穿并在 close 时清理
- `parseStreamEvent` 归一化：
  - `{"delta":...}` → delta 事件
  - `{"type":"turn_meta", role_mode, analysis}` → turn_meta 事件（新契约，可能缺失）
  - `{"done":true,...}` 或含 turn_id 的新格式 → done 事件（提取 session_id / turn_id）
  - `{"detail":...}` 及带 error 体的变体 → error 事件（归一 detail/code/message）
  - 未知行 → 忽略并计数（容错旧/新契约混布）
- `http.ts` 基础封装与 ApiError 归一化（供 501 REST 复用的公共底座，本任务先落 baseURL/错误形状约定）
- `types/backend` 镜像类型与 `types/domain` 的 StreamEvent 判别联合在本任务内定稿

## Out of Scope

- mock 实现（FE-MOCK-102）
- React/Hook/store（FE-CHAT-103）
- REST 端点（API-FE-501）

## Dependencies

- ARCH-FE-001

## Input

- 后端现行契约：`apps/backend/app/api/v1/chat.py`、`schemas.py`（delta/done/detail 行、X-Session-Id/X-Session-New 头）
- 架构文档第 8.1 节目标契约与附录 A1（turn_meta 行）

## Output

- transport 接口 + Real 实现 + 解析器 + StreamEvent 类型 + http 底座
- 可独立运行的解析单元（纯函数，便于单测）

## Business Rules

- 分帧必须正确处理一条 JSON 行跨多个 TCP chunk（半行缓冲）与一个 chunk 含多行
- turn_meta 缺失不是错误：整轮无 turn_meta 时正常走完 done，由上层决定降级展示
- abort 触发后不再向监听器派发任何事件
- 响应头 X-Session-Id / X-Session-New 必须被读取并随事件流暴露给上层（首响应回填会话）

## API Dependencies

- POST /api/v1/chat/message（现行契约；turn_meta 为增量兼容项）

## Data Dependencies

- 无持久化；仅内存中的事件流

## Permission

- 同全局：无鉴权

## Error Handling

- 网络/HTTP 错误 → onError(ApiError)，流终止
- 单行 JSON.parse 失败 → 跳过该行并计数，不中断整轮
- 流中途断开（reader 结束但未见 done）→ 以 aborted/close 语义通知上层，由上层标记消息 stopped/error

## Acceptance Criteria

- 对真实后端（BE-TURNMETA-201 完成前亦可）：delta/done/detail 三类行正确归一；session 头回填链路可用
- 半包/粘包字节序列的单测全部通过
- abort 后无残留定时器/读取循环

## Test Requirements

- 单测：分帧器（跨 chunk 行、多行同 chunk、CRLF）、四类事件归一、未知行忽略、错误体两种形状
- 集成冒烟：真实后端一轮对话事件序列快照（FakeLLM 场景下由 BE 测试环境提供）
