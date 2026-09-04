# BE-07 后处理状态落库

| 字段 | 内容 |
|---|---|
| Task ID | BE-07 |
| Task Name | _post_process 状态更新与 emotion_history |
| Type | BE |
| Priority | P0 |

## Description

V2 收敛节点二：回答完成后，状态按「LLM 决策 + 确定性规则」更新并持久化，每轮留下 emotion_history 观测行。与 V1 摘要 / 记忆提取互不影响。

## Scope

- `app/services/state_service.py`（补全）：
  - `apply_and_save(user_id, session_id, character_state, relationship_state, analysis, user_input, ai_reply, llm)`
  - 流程：BE-04 链取 decision（None 则纯代码规则）→ `apply_idle_recovery` → `update_energy` → `apply_relationship` → `next_stage` → `apply_character` → upsert 两表 → append history
- `app/services/agent_service.py`（修改）：`_post_process` **首位**插入状态更新调用，透传预侧快照与 analysis；整体 try/except 隔离
- emotion_history 字段：user_id、session_id、user_emotion、event、behavior、mood_before、mood_after、energy_after、stage_after

## Out of Scope

- emotion_history 的查询 API（V2 P2 backlog）
- 同用户并发覆盖问题（架构文档已知限制，P2）

## Dependencies

- BE-02、BE-04、BE-06、DB-01

## Input

- 预侧快照（context 阶段读到的 CharacterState / RelationshipState，避免二次读库）
- `docs/version/v1.0.0/v2/v2-architecture.md` §6.4

## Output

- `app/services/state_service.py`（补全）、`app/services/agent_service.py`（修改）
- `tests/test_state_update_flow.py`

## Business Rules

1. 状态更新排在摘要与记忆提取**之前**（写入轻量，先落保证可观测性）。
2. decision=None 时纯代码规则照常更新 energy / relationship，mood 保持旧值。
3. emotion_history **每轮必写**一行（含降级轮）。
4. 整个状态更新 try/except 包裹，失败只记日志，不影响摘要 / 记忆 / 已产出的回答。
5. 闲置恢复基准用快照携带的 `updated_at`（首次落库前为 None → 不触发恢复）。

## API Dependencies

- 无

## Data Dependencies

- 三张状态表（经 repository）

## Permission

- 无

## Error Handling

- BE-04 链异常 → 内部已降级为 None，继续纯代码路径
- 落库异常 → `logger.exception`，本轮状态丢失但不影响其余后处理

## Subtask 拆分

- S1：apply_and_save 编排（LLM → 规则 → 落库）
- S2：_post_process 接入（首位 + 隔离）
- S3：快照透传（stream_chat → create_task）
- S4：测试

## Acceptance Criteria

- `wait_until` 断言：两轮对话后 energy 下降精确值（−0.05 × 轮数 + 修正）
- achievement 事件轮后 intimacy / familiarity 增量正确落库
- state_update 链失败（FakeLLM raise_exc）时 energy / relationship 照常更新、mood 保持旧值、history 仍落库
- 摘要与记忆提取行为与 V1 完全一致（既有测试不改动即通过）

## Test Requirements

- `tests/test_state_update_flow.py`：正常更新、LLM 失败降级、history 每轮一行、与摘要 / 记忆互不影响
- 复用 V1 `wait_until` + FakeLLM 机制
