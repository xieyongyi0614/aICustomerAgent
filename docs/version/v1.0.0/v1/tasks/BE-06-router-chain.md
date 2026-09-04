# BE-06 role_router_chain

| 字段 | 内容 |
|---|---|
| Task ID | BE-06 |
| Task Name | role_router_chain（角色模式路由链） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/chains/router_chain.py`：根据用户消息判断角色表现模式（professional / default / immersive），使用 Pydantic Structured Output 输出 `RoleMode`。修正 V0 模板变量失效问题（架构文档 A7）。

## Scope

- 组装 LCEL 链：`ChatPromptTemplate.from_messages([("system", ROLE_ROUTER_PROMPT)]) | llm.with_structured_output(RoleMode)`
- 模板使用真正的 `{user_message}` 占位符（禁止手动 `.format`）
- 提供 `async def route(user_message) -> RoleMode`

## Out of Scope

- 低置信度降级逻辑（BE-14，P1）
- 回答链（BE-12）
- intent 字段的业务消费（BE-14 一并处理）

## Dependencies

- BE-01（settings）
- BE-02（llm_factory）
- BE-03（RoleMode）
- BE-05（prompts/router.py 模板）

## Input

- `app/prompts/router.py`（ROLE_ROUTER_PROMPT）
- `app/models/router.py`（RoleMode）
- `app/core/llm_factory.py`（get_llm）

## Output

- `app/chains/router_chain.py`

## Business Rules

1. 链结构固定为 `prompt | llm.with_structured_output(RoleMode)`。
2. 输入变量名必须与模板占位符一致（`user_message`）。
3. `route()` 为 async，内部 `ainvoke`。
4. `confidence` 字段保留输出，是否消费由 BE-14 决定。

## API Dependencies

- 无（链不直接暴露给 HTTP）

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- LLM 返回解析失败（structured output 异常）：向上抛出，由 BE-13 编排层兜底为 default 模式。

## Subtask 拆分

- S1：链组装
- S2：`route()` 异步接口
- S3：mock LLM 冒烟

## Acceptance Criteria

- `route("Python 报错怎么排查")` → mode 为 `professional`（mock 断言输出透传）
- 模板中无 `{user_message}` 残留未替换
- 返回类型为 `RoleMode` 实例

## Test Requirements

- mock LLM 返回固定 JSON，验证解析为 RoleMode。
- 验证调用时传入 prompt 已渲染完整（无未替换占位符）。