# BE-03 Pydantic 数据模型定义

| 字段 | 内容 |
|---|---|
| Task ID | BE-03 |
| Task Name | Pydantic 数据模型定义 |
| Type | BE |
| Priority | P0 |

## Description

按 `docs/v1/v1-architecture.md` §6 定义全部 Pydantic 数据模型，作为跨层流通的 DTO（Domain Transfer Object）。划分到 `app/models/` 四个文件：`router.py`、`conversation.py`、`summary.py`、`memory.py`。

## Scope

- `app/models/router.py`：`RoleMode`（含原有字段，预留 `confidence` 消费位）
- `app/models/conversation.py`：`ChatMessage`、`ConversationState`
- `app/models/summary.py`：`ConversationSummary`
- `app/models/memory.py`：`MemoryDecision`、`UserMemory`、`MemoryType`（枚举或 Literal）
- 各模型字段、类型、校验与架构文档 §6 一致

## Out of Scope

- ORM Model（DB-01 的表定义）
- 任何业务逻辑 / 序列化到 API 的响应 DTO（API-01 的 schemas.py）

## Dependencies

- ARCH-01（目录结构与 RoleMode 迁移）

## Input

- `docs/v1/v1-architecture.md` §6 Pydantic Model 设计
- `app/models/router.py`（ARCH-01 已迁移的 RoleMode）

## Output

- `app/models/conversation.py`
- `app/models/summary.py`
- `app/models/memory.py`
- 修正/确认 `app/models/router.py`

## Business Rules

1. 字段类型与默认值严格遵循架构文档 §6。
2. `MemoryType` 用 `Literal["preference","fact","goal","experience","relationship"]` 或 `StrEnum`，两处（MemoryDecision / UserMemory）必须共用同一类型，禁止重复定义。
3. `ConversationState.memories` 引用 `UserMemory`。
4. `ChatMessage.role` 为 `Literal["human","ai"]`。
5. 模型仅做数据载体，不挂方法（除必要的验证器）。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- 非法 `memory_type` / `role` 由 pydantic 原生校验拒绝（构建时抛出 `ValidationError`）。

## Subtask 拆分

- S1：`models/conversation.py`（ChatMessage / ConversationState）
- S2：`models/summary.py`（ConversationSummary）
- S3：`models/memory.py`（MemoryType / MemoryDecision / UserMemory）
- S4：统一导入冒烟

## Acceptance Criteria

- 四个模型文件均可独立导入
- 非法枚举值实例化抛 `ValidationError`
- `ConversationState` 可容纳 messages / summary / memories / current_input 全字段
- `MemoryDecision(memory=None, should_save=False)` 合法；`should_save=True` 时 `memory` 必填（validator）

## Test Requirements

- 每个模型的构建/校验冒烟测试。
- 必填字段与默认值断言（如 `importance` 范围 0~1）。