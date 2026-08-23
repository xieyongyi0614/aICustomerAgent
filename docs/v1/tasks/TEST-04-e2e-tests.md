# TEST-04 端到端集成测试

| 字段 | 内容 |
|---|---|
| Task ID | TEST-04 |
| Task Name | 端到端集成测试 |
| Type | TEST |
| Priority | P0 |

## Description

端到端验证：通过 API 层（API-01）调用完整流程（路由 → 记忆 → 上下文 → 流式回答 → 存消息 → 摘要 → 记忆提取），验证三层贯通与流式响应契约。

## Scope

- `tests/test_e2e.py`：
  - `POST /api/v1/chat/message` 正常流：收集 delta 块 → 完整回答 → done 标记
  - 多轮：第二轮回答上下文含第一轮（mock 断言 prompt 输入）
  - 记忆闭环：对话产生可保存信息 → 落库 → 后续检索命中（断言 memories 表）
  - 摘要闭环：构造 40 条后触发摘要落库
  - 错误路径：空 content → 422；LLM 异常 → 502
  - 无 session_id → 自动创建并返回
- 使用 `TestClient`（Starlette）驱动

## Out of Scope

- 各模块细粒度单测（TEST-02/03）
- 真实 LLM / 真实网络

## Dependencies

- TEST-01（conftest）
- API-01（端点已实现）
- BE-13（编排）
- BE-06/07/08/10/11/12（全部业务就绪）

## Input

- `app/api/v1/chat.py`、`app/services/agent_service.py`
- 各 Task 验收标准的端到端表述（如"第二轮知道第一轮"）

## Output

- `tests/test_e2e.py`

## Business Rules

1. 全程 mock LLM（FakeLLM 按调用类型返回不同结果：路由 JSON / 回答文本 / 摘要文本 / 提取 JSON）。
2. 流式响应断言按 chunked JSON 契约（`{"delta": ...}` ... `{"done": true}`）。
3. 每个用例独立内存库。

## API Dependencies

- `POST /api/v1/chat/message`

## Data Dependencies

- 内存库三表（经端到端读写）

## Permission

- 无鉴权要求。

## Error Handling

- 覆盖 422 / 502 响应契约断言。

## Subtask 拆分

- S1：正常流 + done 契约
- S2：多轮上下文
- S3：记忆闭环 + 摘要闭环
- S4：错误路径 + session 自动创建

## Acceptance Criteria

- `pytest tests/test_e2e.py` 全绿
- 断言覆盖：流契约、多轮、记忆落库与检索、摘要触发、422、502、session 创建

## Test Requirements

- 本 Task 即测试本身。