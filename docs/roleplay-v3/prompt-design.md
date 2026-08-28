# Prompt Design

## 1. 背景

Prompt 组装统一走 `prompts/builder.py`（PromptBuilder），禁止手工拼接（backend AGENTS.md 约束）。V2 已有按 mode 分节的机制。

## 2. 目标

在现有 Prompt 上新增两个分节，不改动角色人设资产（`character/asuna/`）。

## 3. 新增分节

### scene 段（`prompts/scene.py`）

仅当 SceneState 有内容时渲染：

```text
【当前场景】
地点：{location}
活动：{current_activity}
正在做：{current_action}
待完成动作：{pending_action.action}（状态：{status}）
氛围：{scene_mood}

【本轮指令】（由 Resolver 根据确定性迁移生成，非 LLM）
- continue_scene：先完成待完成动作"……"，再自然回应
- correct_scene：用户指出你之前的行为没完成，本轮必须先执行"……"
- interrupt：用户已取消"……"，不要继续，自然接话
- request_action：用户要求你做新的事，行动后记录新的待完成动作
```

"本轮指令"段由 Resolver 代码生成，保证确定性迁移反映到 Prompt。

### rhythm 段（`prompts/scene.py` 与 rhythm 一起提供）

response-rhythm.md 中的规则列表（0~2 动作、不替用户行动等）。

## 4. 组装

- `PromptBuilder.build(mode, state, analysis)` → 扩展为 `build(mode, state, analysis, scene_ctx=None)`，`scene_ctx` 为 None 时（非 V3 路径/降级）行为与 V2 完全一致。
- 保持 V1 布局兼容：无 scene_ctx 时输出与现在逐字节一致（沿用 V2 的兼容测试模式）。

## 5. 边界情况

- 首轮无场景 → scene 段整体省略，rhythm 段保留（约束始终生效）。
- scene_intent 降级为 chat → 无"本轮指令"，仅展示场景信息。

## 6. 验收标准

- PromptBuilder 单测：scene 段渲染/省略、指令段内容与 SceneIntent 一致、无 scene_ctx 时输出不变。
- rhythm + scene 段总 token 开销 ≤ 500。
