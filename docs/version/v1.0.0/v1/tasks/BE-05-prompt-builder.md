# BE-05 Prompt 模板与 PromptBuilder

| 字段 | 内容 |
|---|---|
| Task ID | BE-05 |
| Task Name | Prompt 模板与 PromptBuilder |
| Type | BE |
| Priority | P0 |

## Description

实现模块化 Prompt 组装（`app/prompts/builder.py` 与各模板文件），替代"每请求拼接巨型字符串"的方案。PromptBuilder 将静态角色资产（BE-04）与动态上下文（memory / summary / history / input）分节组装为 `ChatPromptTemplate`。解决架构文档 A8 与 §6 要求。

## Scope

- `app/prompts/router.py`：路由模板（占位符 `{user_message}`）
- `app/prompts/summary.py`：摘要模板（占位符 `{old_summary}`、`{new_messages}`）
- `app/prompts/extractor.py`：提取模板（占位符 `{user_input}`、`{ai_reply}`）
- `app/prompts/builder.py`：`PromptBuilder`
  - `build_identity_sections()`：组装静态角色段（identity + personality + relationship + behavior）
  - `build(mode, state) -> ChatPromptTemplate`：静态段 + 动态段（User Memory / Summary / Recent / Current Input）按序组装

## Out of Scope

- LLM 调用与链构建（BE-06 / BE-08 / BE-09 / BE-12）
- 动态段数据如何产生（BE-07 / BE-08 / BE-10 / BE-11）

## Dependencies

- BE-03（ConversationState / UserMemory 类型）
- BE-04（角色资产常量）

## Input

- `docs/version/v1.0.0/v1/v1-architecture.md` §6「角色 Prompt 架构优化」与 §7
- BE-04 导出的角色常量
- BE-03 的 `ConversationState`

## Output

- `app/prompts/router.py`、`summary.py`、`extractor.py`、`builder.py`

## Business Rules

1. Prompt 分节顺序：Identity → Personality → Relationship → Behavior Rules → User Memory（动态）→ Conversation Context / Summary（动态）→ Recent Messages（动态）→ Current State（mode 指令）→ 当前用户输入。
2. 动态段为空时（无 memory / 无 summary / 无历史）**跳过该节**，不留空占位。
3. mode 指令段从 `MODE_INSTRUCTIONS[mode]` 取，非法 mode 降级 `default`。
4. 组装结果必须返回 `ChatPromptTemplate`（支持 LCEL），禁止返回预格式化字符串。
5. 构建逻辑每次调用实时组装（state 随请求变化），不做缓存。

## API Dependencies

- 无

## Data Dependencies

- `ConversationState`（BE-03）字段：memories / summary / messages / current_input / role_mode

## Permission

- 无鉴权要求。

## Error Handling

- 非法 mode：静默降级 default，不打日志（正常分支）。
- 缺失 state 字段：抛 `ValueError` 并指明缺失字段。

## Subtask 拆分

- S1：`prompts/router.py`、`summary.py`、`extractor.py` 模板
- S2：`builder.py` 静态段组装
- S3：`builder.py` 动态段组装（含空段跳过）
- S4：`build()` 完整链路

## Acceptance Criteria

- `build(mode, state)` 返回 `ChatPromptTemplate`，`invoke` 后 message 顺序符合分节规则
- 无 memory / 无 summary 时对应节不出现
- mode 非法时使用 default 指令段
- 完整输入时 5 个动态/静态层次齐全

## Test Requirements

- 分节顺序断言（messages 列表顺序）
- 空动态段跳过断言
- mode 降级断言
- 模板占位符完整（无 `{...}` 残留）