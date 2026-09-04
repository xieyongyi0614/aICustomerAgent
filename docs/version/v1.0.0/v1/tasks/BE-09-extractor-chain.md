# BE-09 extractor_chain

| 字段 | 内容 |
|---|---|
| Task ID | BE-09 |
| Task Name | extractor_chain（长期记忆提取链） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/chains/extractor_chain.py`：从用户消息 + AI 回复中判断是否有值得长期保存的信息，输出 `MemoryDecision`（Pydantic Structured Output）。实现 V1 功能目标三的"只保存有价值信息"。

## Scope

- 组装链：`ChatPromptTemplate.from_messages([("system", EXTRACTOR_PROMPT)]) | llm.with_structured_output(MemoryDecision)`
- 输入：`{user_input}`、`{ai_reply}`
- `async def extract(user_input, ai_reply) -> MemoryDecision`

## Out of Scope

- 落库 / 去重 / 阈值过滤（BE-10）
- 检索（BE-10）
- 低优先级信息处理

## Dependencies

- BE-02（llm_factory）
- BE-03（MemoryDecision）
- BE-05（prompts/extractor.py 模板）

## Input

- `app/prompts/extractor.py`（EXTRACTOR_PROMPT）
- `app/models/memory.py`（MemoryDecision）

## Output

- `app/chains/extractor_chain.py`

## Business Rules

1. Prompt 必须包含各记忆类型定义（preference / fact / goal / experience / relationship）与负例（日常流水账如"今天吃了拉面"→ `should_save=false`）。
2. 输入同时含用户消息与 AI 回复，供类型判断参考。
3. 输出严格为 `MemoryDecision`，`should_save=true` 时 `memory` 必填（模型层校验）。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- structured output 解析失败：向上抛出，由 BE-10 捕获后跳过本轮提取（不阻塞对话）。

## Subtask 拆分

- S1：链组装
- S2：`extract()` 异步接口
- S3：mock LLM 冒烟

## Acceptance Criteria

- mock 输出 `{"should_save": true, "memory": "用户喜欢寿司", "memory_type": "preference", "importance": 0.8}` → 正确解析为 MemoryDecision
- mock 输出 `should_save=false` → 解析成功且 `memory` 为 None
- 模板含负例指导（审查 EXTRACTOR_PROMPT 内容）

## Test Requirements

- 两种分支解析（save / no-save）均覆盖。
- 类型枚举非法时抛 ValidationError。