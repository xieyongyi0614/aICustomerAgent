# BE-04 状态更新链

| 字段 | 内容 |
|---|---|
| Task ID | BE-04 |
| Task Name | state_update_chain（mood / inner_state / current_topic） |
| Type | BE |
| Priority | P0 |

## Description

实现后处理侧 LLM 链：依据旧状态快照、本轮 TurnAnalysis、双方发言，输出 `StateUpdateDecision`（新 mood、mood_reason、inner_state、current_topic）。承担"LLM 负责理解"的三个字段更新。

## Scope

- `app/prompts/state_update.py`：`state_update_prompt` 模板，变量 `{character_snapshot}` `{relationship_snapshot}` `{user_emotion}` `{event}` `{behavior}` `{user_input}` `{ai_reply}`
- `app/chains/state_update_chain.py`：
  - `update(state, analysis, user_input, ai_reply, llm=None) -> StateUpdateDecision | None`
  - `ChatPromptTemplate.from_messages([("system", prompt)]) | (llm or get_llm()).with_structured_output(StateUpdateDecision)`

## Out of Scope

- energy / relationship 数值更新（BE-02 纯代码规则）
- 落库编排（BE-07）

## Dependencies

- BE-01（StateUpdateDecision / TurnAnalysis / ConversationState）

## Input

- 预侧快照（`ConversationState.character_state` / `relationship_state`）
- `docs/version/v1.0.0/v2/v2-architecture.md` §6.1

## Output

- `app/chains/state_update_chain.py`、`app/prompts/state_update.py`
- `tests/test_state_update.py`

## Business Rules

1. prompt 明确约束：「心情变化要有连续性，不剧烈跳变」「topic 只在话题明确切换时更换，否则沿用旧值」——人格稳定性优先。
2. `mood_reason` 必须输出（观测与调试用），inner_state 一句话、current_topic 短语。
3. **任何异常返回 None** 并记日志（与 BE-03 相反：本链在后台任务内，自行降级为纯代码规则更合理）。
4. 旧状态完整注入 prompt，LLM 基于旧值做增量判断而非凭空生成。

## API Dependencies

- 无

## Data Dependencies

- 无直接 DB 访问

## Permission

- 无

## Error Handling

- LLM 异常 / 结构化解析失败 → 返回 `None` + `logger.exception`，绝不向上抛（后处理隔离原则）。

## Subtask 拆分

- S1：prompt 模板（旧状态注入 + 连续性约束）
- S2：chain + update 函数（异常→None）
- S3：单测

## Acceptance Criteria

- FakeLLM 注入返回 `StateUpdateDecision`，字段完整
- `seen_messages` 断言旧状态快照、user_input、ai_reply 均已渲染
- FakeLLM `raise_exc` 时返回 None 且不抛出

## Test Requirements

- `tests/test_state_update.py`：正常返回、变量渲染、异常→None
- 复用 V1 FakeLLM 机制
