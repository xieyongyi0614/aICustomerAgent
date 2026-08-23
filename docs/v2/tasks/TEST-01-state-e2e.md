# TEST-01 多轮状态演化集成测试

| 字段 | 内容 |
|---|---|
| Task ID | TEST-01 |
| Task Name | 多轮状态演化端到端 + HTTP 集成 |
| Type | TEST |
| Priority | P0 |

## Description

V2 收官任务：端到端验证状态随对话演化、各降级路径不伤人格稳定、HTTP 契约未变。

## Scope

- `tests/test_state_e2e.py`（新建）：
  1. comfort 路径：用户「我今天压力很大」→ behavior=comfort → prompt 含 comfort 行为指令、事后 intimacy 增加
  2. celebrate 路径：achievement 事件 → energy 回升（+0.10 抵消 −0.05 衰减后为正）、stage 不变
  3. stage 升级：`override_settings` 调低 `stage_close_intimacy` / `stage_close_trust`（如 0.3），两轮 share_goal 后 stage 变 close_friend
  4. 全链降级：FakeLLM 对 TurnAnalysis 抛异常 → 回答流照常、状态按默认分析更新（daily 路径 familiarity +0.01）
- `tests/test_chat_http_integration.py`（扩展）：真实 uvicorn 线程 + NDJSON 断言与 V1 用例同构（delta 流 + done 行 + 状态落库 roundtrip）

## Out of Scope

- 真实 LLM 调用（禁止）
- 性能 / 并发压测

## Dependencies

- BE-01 ~ BE-07 全部完成

## Input

- V1 conftest 全套设施（FakeLLM / db_session_factory / override_settings / wait_until）

## Output

- `tests/test_state_e2e.py`
- `tests/test_chat_http_integration.py`（扩展）

## Business Rules

1. 全部用例禁止真实 LLM 调用（AGENTS.md 测试约定）。
2. 状态断言用 repository 直查（不新增 API）。
3. HTTP 用例只断言既有 NDJSON 契约，不引入新事件类型。

## API Dependencies

- `POST /api/v1/chat/message`（契约不变）

## Data Dependencies

- 内存 SQLite（e2e）/ 真实 uvicorn + 测试库（HTTP 集成，沿用 V1 模式）

## Permission

- 无

## Error Handling

- 测试本身覆盖降级路径（TurnAnalysis 失败、state_update 失败），断言回答照常。

## Subtask 拆分

- S1：comfort 路径 e2e
- S2：celebrate 路径 + stage 升级 e2e
- S3：全链降级 e2e
- S4：HTTP 集成扩展 + 全量回归

## Acceptance Criteria

- 四个 e2e 场景全部通过
- 既有全量 pytest 通过（V1 回归无损）
- 无任何真实 LLM 调用（FakeLLM 注入全覆盖）
- `pylint` 不低于既有基线（约 7.4，docstring 类告警不修）

## Test Requirements

- 本任务自身即测试；合入前跑全量 `pytest`
