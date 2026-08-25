# BE-API-404 · GET /api/v1/debug/turns/{turn_id}/trace

## Task ID

BE-API-404

## Task Name

单轮 Debug 快照端点（RoleMode + TurnAnalysis + TraceSteps + 完成态标记)

## Type

API

## Priority

P1

## Description

返回指定轮次的完整 Debug 快照：该轮实际生效的 RoleMode、TurnAnalysis、全部 TraceSteps（含 durationMs/status），以及 `status: pending|complete` 标记——pending 表示 fire-and-forget 后处理尚未完成，前端据此执行有界轮询（D-F2 契约核心）。

## Scope

- 端点 GET `/api/v1/debug/turns/{turn_id}/trace`
- 数据源：BE-TRACE-401 的内存采集器（steps）+ 该轮 meta（RoleMode/TurnAnalysis——由 BE-TURNMETA-201 同源的预侧结果留存，采集器一并保存即可，避免二次查表拼装）
- complete 判定：state_update 与 memory_extractor 两步均已终态（ok/error 都算完成）→ complete；否则 pending
- turn_id 不存在 / 已被 LRU 淘汰 → 404（前端提示刷新或重发）
- 响应 DTO：steps 数组每项含 name/status/durationMs/(first_token_ms)/error?，另含 role_mode/analysis/status/total_ms

## Out of Scope

- input/output 大对象全文（采集器当前只存摘要，端点透传）
- 多轮批量查询

## Dependencies

- BE-TRACE-401（采集器）、BE-TURNMETA-201（turn_id 生成与定位约定）
- **与前端并行**；汇合点 I2（与 API-FE-501 联调轮询）

## Input

- 架构文档第 8.2 节轮询策略、附录 A2/A3

## Output

- 端点 + DTO + 集成测试（覆盖 pending 与 complete 两态）

## Business Rules

- pending 是一等状态而非错误：必须 200 返回已就绪的部分数据
- steps 顺序固定按流水线步骤名序输出（前端 waterfall 依赖稳定顺序）
- status=complete 后数据不再变化（内存不可变性约束），前端停止轮询的依据

## API Dependencies

- 无外部依赖

## Data Dependencies

- BE-TRACE-401 内存存储（唯一数据源，不查业务表）

## Permission

- 沿用后端现状：无鉴权（debug 端点仅限内部部署暴露，部署时由 OPS-DEPLOY-603 决定是否加网关保护）

## Error Handling

- 未知 turn_id → 404 附说明文案；采集器模块不可用（理论不该发生）→ 503 明确报错

## Acceptance Criteria

- FakeLLM 一轮对话后立即查询：多为 pending（后处理异步）→ 稍后变 complete，steps 完整
- 无效 id 404；淘汰后 404
- PostgreSQL 集成测试路径通过（该端点本身不触库，验证夹具环境兼容）

## Test Requirements

- 集成测试：pending→complete 流转、404 分支、steps 序稳定
