# BE-API-402 · GET /api/v1/state 观测端点

## Task ID

BE-API-402

## Task Name

GET /api/v1/state：角色状态 + 关系状态 + 最近情绪历史

## Type

API

## Priority

P1

## Description

落实 V2 P2 backlog 既有的「状态调试 API」规划：一次性返回 character_state、relationship_state 与最近 N 条 emotion_history，供前端 StatePanel 拉取快照。

## Scope

- 新端点 GET `/api/v1/state?user_id=&limit=`：聚合 character_state_repository / relationship_repository / emotion_history_repository 既有读方法
- 未命中返回 V2 默认值语义（与 repositories 现状一致：get_state 未命中返回默认值）
- limit 默认值进 settings；响应 DTO 进 api schemas
- 注册进 v1 router

## Out of Scope

- 写操作 / 手动改状态（不做调试写入口）
- relationship 完整历史快照回放（emotion_history 表设计如此，遵循）

## Dependencies

- 无新前置（V2 三表与三个 repository 已交付）；**与前端并行**

## Input

- `apps/backend/app/repositories/` 三个状态仓储现状
- 架构文档附录 A2；V2 P2 backlog 第一条

## Output

- 端点 + schemas DTO + 集成测试

## Business Rules

- 只读端点；响应结构与前端镜像类型对齐（mood/energy/current_topic/inner_state/updated_at；intimacy/trust/familiarity/stage；emotion_history 各列）
- updated_at 必须返回（前端判断闲置恢复与数据新鲜度）

## API Dependencies

- 无外部依赖

## Data Dependencies

- character_state / relationship_state / emotion_history 三表（只读）

## Permission

- 沿用后端现状：无鉴权

## Error Handling

- user_id 缺省时使用后端现行默认用户（与 chat 端点 hardcode 的 default-user 语义一致）；limit 非法时 422

## Acceptance Criteria

- 有状态数据时返回正确聚合；全新用户返回 V2 默认值组合而非 404
- PostgreSQL 集成测试通过（alembic upgrade head 建表路径）

## Test Requirements

- HTTP 集成测试：命中/未命中/limit 边界三用例（沿用 conftest 的 PG 夹具约定）
