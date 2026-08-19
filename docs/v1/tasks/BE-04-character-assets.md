# BE-04 角色资产模块（character/）

| 字段 | 内容 |
|---|---|
| Task ID | BE-04 |
| Task Name | 角色资产模块（character/） |
| Type | BE |
| Priority | P0 |

## Description

将 V0 巨型 System Message（`config.py:5-167` 的 `ASUNA_CORE` 与 `MODE_INSTRUCTIONS`）拆分为模块化角色资产，存放于 `app/character/`。解决巨型字符串拼接问题（架构文档 A8），为 PromptBuilder 提供分节素材。

## Scope

- `app/character/identity.py`：亚丝娜核心人格（来自 ASUNA_CORE 的【核心人格】段）
- `app/character/personality.py`：人格细化描述（温柔、独立、认真等具体化）
- `app/character/relationship.py`：与用户的关系设定（用户=桐人默认、称呼规则）
- `app/character/behavior.py`：行为原则（先解决问题再体现角色、不机械说爱、不无条件赞同等）
- `app/character/modes.py`：三档模式指令（professional / default / immersive，迁移自 MODE_INSTRUCTIONS）
- 语言风格段归属：identity 或 personality，由实现者按内容就近放置

## Out of Scope

- Prompt 组装逻辑（BE-05 的 PromptBuilder）
- 角色内容的语义改写（仅结构拆分，文案保留原意）
- 动态段（User Memory / Summary / Recent）的注入（BE-05 起）

## Dependencies

- ARCH-01（character/ 空壳目录与内容迁移）

## Input

- V0 `app/modules/llm/config.py`（已被 ARCH-01 迁移到 `app/character/`）
- 架构文档 A8 与 §3 模块划分

## Output

- `app/character/identity.py`、`personality.py`、`relationship.py`、`behavior.py`、`modes.py`
- 每个文件导出语义化常量（如 `IDENTITY_BLOCK`、`PERSONALITY_BLOCK`、`RELATIONSHIP_BLOCK`、`BEHAVIOR_BLOCK`、`MODE_INSTRUCTIONS`）

## Business Rules

1. 内容必须保持 V0 原语义，只做结构拆分，不得丢失任何行为约束。
2. 每个文件内容自包含、可独立引用。
3. `modes.py` 保持 `MODE_INSTRUCTIONS` dict 结构（key 为三种模式），供 PromptBuilder 按 mode 取用。
4. 所有常量字符串为"构建时素材"，不含任何用户/会话动态数据。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- 无运行期错误；模式 key 非法由调用方（PromptBuilder）降级到 default。

## Subtask 拆分

- S1：identity / personality
- S2：relationship / behavior
- S3：modes.py（MODE_INSTRUCTIONS）
- S4：导入冒烟 + 内容比对

## Acceptance Criteria

- 五个文件均可独立导入，常量存在
- 将拆分后的各块按原顺序拼接，与 V0 `ASUNA_CORE + "\n\n" + MODE_INSTRUCTIONS[mode]` 内容逐字一致（diff 验证）
- 角色行为约束无缺失（如"不无条件赞同""不机械说爱你"均保留）

## Test Requirements

- 拼接一致性测试：拆分块按序拼接 = 原文（保留空行规则）。
- 模式 key 完整性测试：`professional / default / immersive` 齐全。