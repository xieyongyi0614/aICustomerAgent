# BE-12 answer_chain

| 字段 | 内容 |
|---|---|
| Task ID | BE-12 |
| Task Name | answer_chain（角色回答链） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/chains/answer_chain.py`：按 mode + ConversationState 动态组装 Prompt，`PromptBuilder.build(mode, state) | llm`，支持流式输出。是"Context → 亚丝娜回答"的最终生成链。

## Scope

- `build_chain(mode, state) -> Runnable`：`prompt | llm`
- `astream(mode, state)`：流式迭代生成
- 保留 V0 流式行为（首 token 尽快返回）

## Out of Scope

- Prompt 组装细节（BE-05）
- 路由判断（BE-06）
- 编排与 post-process（BE-13）

## Dependencies

- BE-02（llm_factory）
- BE-05（PromptBuilder）
- BE-03（ConversationState / RoleMode）

## Input

- `app/prompts/builder.py`（PromptBuilder.build）
- `app/core/llm_factory.py`（get_llm）
- `ConversationState`、`RoleMode`

## Output

- `app/chains/answer_chain.py`

## Business Rules

1. 每次请求实时构建链（state 随请求变化），不做全局缓存。
2. `build_chain` 返回 Runnable，供 `astream`/`ainvoke` 使用。
3. 流式输出的 token 由调用方（BE-13/API-01）收集与转发，本链不持有流式缓冲。
4. mode 为 `RoleMode.mode` 字段。

## API Dependencies

- 无

## Data Dependencies

- 无（依赖组装好的 state）

## Permission

- 无鉴权要求。

## Error Handling

- LLM 流式异常：向上抛，由 BE-13 转为用户可读错误。

## Subtask 拆分

- S1：`build_chain`
- S2：`astream` 流式接口
- S3：mock LLM 冒烟

## Acceptance Criteria

- `build_chain` 返回可 `astream` 的 Runnable
- mock LLM 下 `astream` 产出分块 token 并完整拼接
- prompt 分节与 BE-05 定义一致

## Test Requirements

- mock LLM 固定分块输出，验证流式拼接完整性。
- 验证 chain 输入 prompt 包含 memory/summary/history 动态段。