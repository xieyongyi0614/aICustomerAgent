# BE-06 上下文与预侧编排接入

| 字段 | 内容 |
|---|---|
| Task ID | BE-06 |
| Task Name | context_builder 扩展 + stream_chat 并发编排 |
| Type | BE |
| Priority | P0 |

## Description

V2 收敛节点一：状态进入上下文，`stream_chat` 中 router 与 turn_analysis 并发执行、独立降级，analysis 透传到回答链。完成后预侧链路（状态读取 → 并发分析 → prompt 注入）全部打通。

## Scope

- `app/services/state_service.py`（新建）：
  - `load_states(user_id) -> tuple[CharacterState, RelationshipState]`：读两表，应用 `apply_idle_recovery`（仅内存，不写库）
- `app/services/context_builder.py`（修改）：读取顺序 窗口 → 摘要 → 记忆 → 状态，填入 ConversationState 两个新字段
- `app/services/agent_service.py`（修改）：
  - `asyncio.gather(router_chain.route(...), turn_analysis_chain.analyze(...), return_exceptions=True)`
  - router 异常 / 低置信 → mode=default（V1 逻辑原样保留）
  - analysis 异常 → `TurnAnalysis()` 默认值 + 记日志
  - `answer_chain.astream(mode, state, analysis, llm=llm)`
- `app/chains/answer_chain.py`（修改）：astream 增 `analysis` 参数，内部调 `PromptBuilder.build(mode, state, analysis)`

## Out of Scope

- 后处理状态落库（BE-07）
- HTTP 层改动（零改动）

## Dependencies

- BE-01、BE-02（idle recovery）、BE-03、BE-05、DB-01

## Input

- `docs/v2/v2-architecture.md` §6.2、§6.3

## Output

- `app/services/state_service.py`、`app/services/context_builder.py`（改）、`app/services/agent_service.py`（改）、`app/chains/answer_chain.py`（改）
- 对应测试扩展

## Business Rules

1. gather 必须带 `return_exceptions=True`，两个预侧任务**各自独立降级**，一个失败不影响另一个。
2. V1 的 router 降级逻辑（低置信 → default、异常 → default）一行不动。
3. 闲置恢复只在读取时计算，不产生写库副作用（写入出链原则）。
4. analysis 降级值必须就是 `TurnAnalysis()` 默认实例（neutral / daily / normal_reply）。

## API Dependencies

- 无（NDJSON 契约不变）

## Data Dependencies

- character_state / relationship_state 两表（经 repository）

## Permission

- 无

## Error Handling

- turn_analysis 异常 → 默认 TurnAnalysis + `logger.warning`，回答照常
- 状态读取异常 → context_builder 内兜底为默认状态（回答不因状态缺失败北）

## Subtask 拆分

- S1：state_service.load_states（含闲置恢复）
- S2：context_builder 填充两个新字段
- S3：stream_chat gather 并发 + 双降级
- S4：answer_chain 签名扩展
- S5：测试

## Acceptance Criteria

- FakeLLM 注入 RoleMode + TurnAnalysis 双结构化返回，流式照常
- turn_analysis 抛异常时回答照常，prompt 含默认状态 section
- router 抛异常 / 低置信时 mode=default（V1 既有测试不改动即通过）
- 全量 pytest 绿

## Test Requirements

- 扩展编排层测试：正常并发路径、analysis 降级路径、router 降级回归
- FakeLLM `structured_responses` 同时提供 RoleMode 与 TurnAnalysis
