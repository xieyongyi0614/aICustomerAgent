# TEST-02 核心单元测试

| 字段 | 内容 |
|---|---|
| Task ID | TEST-02 |
| Task Name | 核心单元测试（路由/短期记忆/长期记忆） |
| Type | TEST |
| Priority | P0 |

## Description

编写核心业务路径的单元测试，覆盖：路由链（BE-06）、短期记忆（BE-07 + DB-02）、长期记忆提取与检索（BE-09 + BE-10 + DB-04）、Context Builder（BE-11）、回答链（BE-12）。

## Scope

- `tests/test_router.py`：BE-06 路由解析、模板渲染完整
- `tests/test_conversation.py`：BE-07 + DB-02 多轮上下文、会话隔离、窗口上限、字符裁剪、save_turn
- `tests/test_extractor.py`：BE-09 两种分支解析
- `tests/test_memory.py`：BE-10 + DB-04 保存/过滤/去重/检索
- `tests/test_context.py`：BE-11 组装与降级
- `tests/test_answer_chain.py`：BE-12 流式拼接

## Out of Scope

- 摘要专项（TEST-03）
- 端到端（TEST-04）
- 路由降级 BE-14（P1，可并入本集）

## Dependencies

- TEST-01（conftest）
- BE-06 / BE-07 / BE-09 / BE-10 / BE-11 / BE-12 均已实现
- DB-02 / DB-04

## Input

- 各 Task 的验收标准（`docs/version/v1.0.0/v1/tasks/*.md` 中 Test Requirements）

## Output

- `tests/test_router.py`、`test_conversation.py`、`test_extractor.py`、`test_memory.py`、`test_context.py`、`test_answer_chain.py`

## Business Rules

1. 全程 mock LLM + 内存库，禁止真实网络。
2. 用例命名 `test_*`，可独立运行。
3. 覆盖"正例 + 边界 + 异常"三态。

## API Dependencies

- 无

## Data Dependencies

- 内存库三表

## Permission

- 无鉴权要求。

## Error Handling

- 每个异常路径有独立用例（非法 role、非法类型、解析失败降级等）。

## Subtask 拆分

- S1：router + answer_chain
- S2：conversation
- S3：extractor + memory
- S4：context_builder

## Acceptance Criteria

- `pytest tests/` 全绿
- 断言覆盖：多轮引用、会话隔离、窗口上限、保存过滤、去重、检索打分、降级、流式完整
- 覆盖率不低于各文件主要分支（可用 `--cov` 观测，V1 不设强制阈值）

## Test Requirements

- 本 Task 即测试本身。