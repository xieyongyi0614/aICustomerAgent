# BE-11 context_builder

| 字段 | 内容 |
|---|---|
| Task ID | BE-11 |
| Task Name | context_builder（上下文组装） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/services/context_builder.py`：将短期记忆窗口、摘要、长期记忆、当前输入统一组装为 `ConversationState`，作为 PromptBuilder 的输入。是三层中"记忆 → Prompt"的桥接层（V1 功能目标五）。

## Scope

- `build(session_id, user_id, current_input) -> ConversationState`：
  - 调 conversation_service 加载窗口
  - 调 summary_service 读取摘要
  - 调 memory_service 检索长期记忆
  - 组装为 `ConversationState`
- `ConversationState` 字段齐全校验

## Out of Scope

- 各数据源实现（BE-07 / BE-08 / BE-10）
- Prompt 渲染（BE-05）
- LLM 调用（BE-12）

## Dependencies

- BE-03（ConversationState）
- BE-07（conversation_service）
- BE-08（summary 读取能力）
- BE-10（memory_service.retrieve）

## Input

- `app/models/conversation.py`（ConversationState）
- `app/services/conversation_service.py`、`summary_service.py`、`memory_service.py`

## Output

- `app/services/context_builder.py`

## Business Rules

1. `build()` 为 async（内部多次 DB 访问）。
2. 任一数据源缺失不阻塞整体：无摘要 → `summary=None`；无记忆 → `memories=[]`；无历史 → `messages=[]`。
3. `current_input` 必填，缺失抛 `ValueError`。
4. 组装结果直接作为 PromptBuilder 输入，不在此层渲染文本。

## API Dependencies

- 无

## Data Dependencies

- 会话/摘要/记忆三张表（经各自 service）

## Permission

- 无鉴权要求。

## Error Handling

- 数据源异常：各 source 内部已降级；`build()` 不吞未预期异常，向上抛。
- 缺失输入：`ValueError`。

## Subtask 拆分

- S1：`build()` 组装流程
- S2：空数据源降级
- S3：输入校验

## Acceptance Criteria

- 完整数据下 `ConversationState` 五字段齐全
- 无摘要 / 无记忆 / 无历史三场景均能返回合法 state
- `current_input` 缺失抛 ValueError
- 多轮数据下 messages 顺序与窗口一致

## Test Requirements

- 三降级场景、字段完整、顺序保持、输入校验。