# BE-TURNMETA-201 · turn_meta 行下发与 done 行附 turn_id

## Task ID

BE-TURNMETA-201

## Task Name

/chat/message 流内新增 turn_meta 行与 done 行附 turn_id（D-F3 最小契约改动）

## Type

BE

## Priority

P0

## Description

按架构文档附录 A1：在预侧并发（router ∥ turn_analysis）完成后、首个 delta 之前，向 NDJSON 流追加一行 `{"type":"turn_meta",...}`（内容为实际生效值，含降级默认值）；并在 done 行附 `turn_id` 以便 Phase 2 按轮定位 debug 快照。这是 Phase 1 唯一后端改动。

## Scope

- `services/agent_service.py` stream_chat 编排调整：将预侧 gather 结果（role_mode、analysis）以一行 turn_meta 形式并入产出序列（保持既有 delta 产出逻辑不变；实现方式可为编排层 yield 事件或在 api 层组装，以最小侵入为准）
- turn_id 定位方案（任务内决策并记录）：优先采用「本轮 AI message 落库后的 id」——done 由 api 层在流耗尽后 yield，此时 save_turn 已完成，需让编排层把 ai message id 透出；若实现中发现不可得，退化为 conversation_id+序号并在代码命名中体现
- done 行扩展：`{"done":true,"session_id":...,"turn_id":...}`
- 兼容性保证：新行带 type 字段；现有测试与旧客户端行为回归
- pytest 新增：流式行序列断言（首行 turn_meta、中间 delta、末行 done 带 turn_id；LLM 异常场景 detail 行为不变）

## Out of Scope

- trace 采集与 debug 端点（BE-TRACE-401 / BE-API-40x）
- snapshot / trace_event 等其他流内事件（明确不做，见 D-F2）

## Dependencies

- 无前置（基于 V2 现状）；**与前端泳道全程并行**，汇合点 I1（FE-CHAT-103 真实联调）

## Input

- `apps/backend/app/api/v1/chat.py`、`app/services/agent_service.py` 现状
- 架构文档第 8.1 节契约、附录 A1；V2 架构文档第 2 节降级矩阵（turn_meta 必须携带实际生效值含默认值）

## Output

- 修改后的流式端点行为 + 新增测试
- 契约说明补充（在任务完成说明中记录最终行格式样例，供前端镜像类型核对）

## Business Rules

- turn_meta 内容必须是「实际生效值」：router 低置信降级为 default 时照发 default；turn_analysis 失败取默认 TurnAnalysis 时照发默认值——绝不因降级而省略该行（前端据此做降级徽章）
- 不改变任何既有序列化行为：delta/done/detail 既有字段一字不动，只做增量
- LLM 异常路径（detail 行）不发 turn_meta 也可接受（异常发生在预侧之后则 turn_meta 已发；发生在预侧本身则直接走 detail，两种时序都合法，测试覆盖其一即可）

## API Dependencies

- 仅涉及 POST /api/v1/chat/message 响应体（增量）

## Data Dependencies

- messages 表（读取本轮 ai message id 作为 turn_id 来源）；不改表结构

## Permission

- 沿用后端现状：无鉴权（内部工具）

## Error Handling

- 组装 turn_meta 的过程不得引入新的失败面：序列化失败时跳过该行继续流式（记日志），保证「观测增强永不影响回答」（铁律三）

## Acceptance Criteria

- 正常轮：行序列 = turn_meta → delta×N → done(含 turn_id)；curl/python 旧客户端忽略新行正常工作
- 降级轮（FakeLLM 模拟 router 异常）：turn_meta 仍存在且 mode=default
- 既有全量 pytest 通过，新增用例通过；pylint 无新增告警

## Test Requirements

- tests/ 新增流式 e2e 断言（FakeLLM 注入，内存 SQLite 单测级即可）
- 兼容回归：跑一遍既有 HTTP 流式测试确认零破坏
