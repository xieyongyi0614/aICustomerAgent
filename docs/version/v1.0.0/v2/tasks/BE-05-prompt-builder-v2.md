# BE-05 行为指令资产与 PromptBuilder 扩展

| 字段 | 内容 |
|---|---|
| Task ID | BE-05 |
| Task Name | 行为指令资产 + PromptBuilder 三新 section |
| Type | BE |
| Priority | P0 |

## Description

新增两份角色资产（7 种行为指令片段、4 档关系阶段文案），并扩展 `PromptBuilder.build` 注入三个新 system section。PromptBuilder 仍是唯一组装入口（AGENTS.md 约束不变）。

## Scope

- `app/character/asuna/behavior_instructions.py`：`BEHAVIOR_INSTRUCTIONS: dict[BehaviorType, str]`，7 种行为各一段指令
- `app/character/asuna/stages.py`：
  - `STAGE_DESCRIPTIONS: dict[RelationshipStage, str]`（按 SAO 语境撰写四档）
  - `describe_level(value) -> str`（< 0.3 低 / < 0.5 一般 / < 0.75 深 / ≥ 0.75 很深）
- `app/prompts/builder.py`：`build(mode, state, analysis=None)`，按架构文档 §7 顺序插入：
  - 【角色当前状态】：mood / 精力档位（≥0.7 充沛 / ≥0.4 一般 / 否则有些疲惫）/ current_topic / inner_state
  - 【与用户的关系】：stage 文案 + 三维定性档位
  - 【本轮行为指令】：`BEHAVIOR_INSTRUCTIONS[analysis.behavior.behavior]`

## Out of Scope

- answer_chain 签名与编排（BE-06）
- 三个 section 的数据来源填充（BE-06 的 context_builder）

## Dependencies

- BE-01（TurnAnalysis / CharacterState / RelationshipState 类型）

## Input

- `docs/version/v1.0.0/v2/v2-architecture.md` §7 Prompt 架构升级

## Output

- `app/character/asuna/behavior_instructions.py`、`app/character/asuna/stages.py`
- `app/prompts/builder.py`（修改）
- `tests/test_answer_chain.py`（扩展）

## Business Rules

1. **向后兼容硬要求**：`analysis=None` 时消息序列与 V1 逐字节一致。
2. 关系三维**禁止以浮点数形式出现**在 prompt 中（架构文档 D2 决策），只出现档位词。
3. `recall_memory` 指令只引导「自然提起相关记忆」，不重复记忆内容（记忆已在【用户记忆】section）。
4. 新 section 插入位置：状态两段在四块人设之后、【用户记忆】之前；行为指令在 MODE 指令之后、当前输入之前。
5. 指令文案用亚丝娜口吻撰写，与既有 `character/asuna/` 五块风格一致。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无

## Error Handling

- 未知 behavior / stage 键 → 回退默认条目（normal_reply / friend），不抛错。

## Subtask 拆分

- S1：`stages.py`（文案 + 档位函数）
- S2：`behavior_instructions.py`（7 段指令）
- S3：builder 扩展（三 section + 兼容路径）
- S4：单测

## Acceptance Criteria

- `analysis=None` 时 build 输出与 V1 相同
- analysis 注入后 `seen_messages` 含三个新 section，且全文无浮点数值
- 同一输入重复 build 结果一致

## Test Requirements

- 扩展 `tests/test_answer_chain.py`：兼容路径、三 section 注入、无浮点断言、未知键回退
