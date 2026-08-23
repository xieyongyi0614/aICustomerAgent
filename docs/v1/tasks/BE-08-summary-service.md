# BE-08 summary_chain 与 summary_service

| 字段 | 内容 |
|---|---|
| Task ID | BE-08 |
| Task Name | summary_chain 与 summary_service（对话摘要） |
| Type | BE |
| Priority | P0 |

## Description

实现对话摘要功能（V1 功能目标二）：历史消息超过阈值（默认 40 条）后触发滚动摘要，`old_summary + new_messages → new_summary`，解决长期聊天 Context Window 无限增长。

## Scope

- `app/chains/summary_chain.py`：`ChatPromptTemplate.from_messages([("system", SUMMARY_PROMPT)]) | llm`（非结构化输出）
- `app/services/summary_service.py`：
  - `should_summarize(message_count) -> bool`（≥ `settings.SUMMARY_THRESHOLD`）
  - `generate(old_summary, new_messages) -> str`（调用 summary_chain）
  - `update(conv_id, new_messages)`：滚动更新并 upsert
- 摘要注入 Prompt 的位置由 BE-05 已定义，此处提供摘要文本

## Out of Scope

- 摘要存储层（DB-03）
- 触发点的调用时机（BE-13 编排）
- 消息裁剪（BE-07）

## Dependencies

- BE-02（llm_factory）
- BE-03（ConversationSummary）
- BE-05（prompts/summary.py 模板）
- DB-03（summary_repository）
- BE-07（message_count）

## Input

- `app/prompts/summary.py`（SUMMARY_PROMPT，占位符 `{old_summary}` `{new_messages}`）
- `settings.SUMMARY_THRESHOLD`（40）
- `app/repositories/summary_repository.py`

## Output

- `app/chains/summary_chain.py`
- `app/services/summary_service.py`

## Business Rules

1. 滚动压缩：新摘要 = `old_summary + "\n" + 新增消息` 的压缩结果，禁止每次从全量消息重算。
2. 首次生成时 `old_summary` 为空字符串。
3. 未达阈值不生成、不落库。
4. `update()` 成功后 upsert 到摘要表，`updated_at` 刷新。

## API Dependencies

- 无

## Data Dependencies

- `conversation_summaries` 表（经 DB-03）
- 消息列表（调用方传入新增消息段）

## Permission

- 无鉴权要求。

## Error Handling

- LLM 调用失败：抛出异常，由 BE-13 决定是否降级（跳过摘要不影响本轮回答）。
- 空消息列表：不调用 LLM，直接返回旧摘要。

## Subtask 拆分

- S1：summary_chain 组装
- S2：`should_summarize` 阈值判断
- S3：`generate` 滚动压缩
- S4：`update` 触发+落库

## Acceptance Criteria

- 消息数 39 → 不触发；40 → 触发
- 摘要内容包含早期关键信息（mock 断言提示词含 old_summary 与 new_messages）
- 再次触发时，new_summary 基于上一次 summary 生成（滚动）
- upsert 后摘要表仅一行且为最新

## Test Requirements

- 阈值边界（39/40）、滚动拼接、空输入不调用 LLM、upsert 幂等。
- LLM 用 mock 固定输出。