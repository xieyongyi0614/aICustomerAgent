# BE-API-403 · 历史消息端点与记忆列表端点

## Task ID

BE-API-403

## Task Name

GET /conversations/{id}/messages 与 GET /memories

## Type

API

## Priority

P1

## Description

补齐前端会话恢复与 MemoryPanel 所需的两个只读端点：按会话拉历史消息；按用户拉记忆列表。

## Scope

- GET `/api/v1/conversations/{conversation_id}/messages`：按时间升序返回消息（id/role/content/created_at），分页参数可选（limit/before_id，默认最近 200 条足够调试场景）
- GET `/api/v1/memories?user_id=&conversation_id=`：返回记忆列表（id/user_id/memory/memory_type/importance/created_at/updated_at），按 importance 或 created_at 排序择一并固定；conversation_id 参数为预留的本轮命中标注口（V1 检索未留痕，本期一律不返回 hit 标注，前端 hitThisTurn=false 兜底）
- 会话不存在返回 404；DTO 进 schemas

## Out of Scope

- 检索命中打分留痕（需改 memory_service，超出只读范围，列入后续 backlog）
- 记忆删除/编辑

## Dependencies

- 无新前置（V1 表与仓储已有）；**与前端并行**

## Input

- `apps/backend/app/repositories/conversation_repository.py`、`memory_repository.py` 现状
- 架构文档第 8.2 节、附录 A2

## Output

- 两个端点 + DTO + 集成测试

## Business Rules

- 只读；排序与分页语义必须确定性（前端依赖稳定顺序渲染）
- role 取值 human/ai 与现库 CHECK 约束一致

## API Dependencies

- 无外部依赖

## Data Dependencies

- conversations / messages / memories 三表（只读）

## Permission

- 沿用后端现状：无鉴权

## Error Handling

- 非法 uuid / 不存在的 conversation_id → 404；非法 limit → 422

## Acceptance Criteria

- 插入若干消息与记忆后两端点返回正确顺序与字段
- 404/422 分支测试通过

## Test Requirements

- HTTP 集成测试：正常、空列表、不存在会话、分页边界
