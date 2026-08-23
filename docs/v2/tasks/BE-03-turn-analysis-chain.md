# BE-03 轮次分析链

| 字段 | 内容 |
|---|---|
| Task ID | BE-03 |
| Task Name | turn_analysis_chain（情绪 + 事件 + 行为） |
| Type | BE |
| Priority | P0 |

## Description

实现 V2 预侧核心：一次 LLM 结构化输出同时产出用户情绪（`UserEmotion`）与行为决策（`BehaviorDecision`），合称 `TurnAnalysis`。与 V1 四条链同构（build-per-call 短链），供编排层与路由并发调用。

## Scope

- `app/prompts/turn_analysis.py`：`turn_analysis_prompt` 模板，变量 `{user_message}` `{recent_context}` `{character_snapshot}` `{relationship_snapshot}`
- `app/chains/turn_analysis_chain.py`：
  - `analyze(content, state, llm=None) -> TurnAnalysis`
  - `ChatPromptTemplate.from_messages([("system", prompt)]) | (llm or get_llm()).with_structured_output(TurnAnalysis)`
- 最近上下文：取 `state.messages` 尾部 `analysis_recent_messages` 条格式化为多行文本

## Out of Scope

- 并发编排与降级（BE-06）
- prompt 中三个新 section 的注入（BE-05）

## Dependencies

- BE-01（TurnAnalysis 及嵌套模型）
- V1 conftest（FakeLLM 结构化注入能力）

## Input

- `ConversationState`（messages + character_state + relationship_state）
- `docs/v2/v2-architecture.md` §6.1

## Output

- `app/chains/turn_analysis_chain.py`、`app/prompts/turn_analysis.py`
- `tests/test_turn_analysis.py`

## Business Rules

1. prompt 必须含三组枚举的取值说明（每项一句中文释义），否则结构化输出易漂移。
2. 每个 behavior 至少 1 条少样本示例（如「我今天压力很大」→ comfort）。
3. 注入角色快照（mood / energy 档位）与关系 stage，让行为决策知上下文。
4. 链内**不捕获异常**——降级职责在编排层（BE-06），链保持诚实抛错。
5. `(llm or get_llm())` 兜底 + `llm=None` 参数透传，与 V1 链一致。

## API Dependencies

- 无

## Data Dependencies

- 无直接 DB 访问（状态经 `state` 参数传入）

## Permission

- 无

## Error Handling

- 结构化解析失败 / LLM 异常：向上抛（由 BE-06 统一降级为默认 TurnAnalysis）。

## Subtask 拆分

- S1：prompt 模板（枚举说明 + 少样本 + 快照变量）
- S2：chain build + analyze 函数
- S3：recent_context 格式化
- S4：单测（含异常传播）

## Acceptance Criteria

- FakeLLM 按 `TurnAnalysis` schema 注入，返回正确嵌套结构
- `seen_messages` 断言渲染含用户消息、角色快照、最近上下文
- FakeLLM `raise_exc` 时异常向上传播（不被吞）

## Test Requirements

- `tests/test_turn_analysis.py`：结构化返回、prompt 变量渲染、异常传播
- 复用 V1 FakeLLM `structured_responses` 机制
