# Roleplay V5：Emotion & Relationship System

> 状态：规划完成，待实现
> 前置：V2（角色状态）、V3（Scene State）、V4（Long-term Memory）

## 一句话定义

角色的情绪随对话短期起伏并自然衰减，与用户的关系随事件长期渐进——两者独立建模、代码驱动数值、Prompt 表达"人格底色上的情绪"。

## V 系列 × 状态分层全景

```text
V2 CharacterState   内在：精力 / 心情标签 / 内心戏     （每轮）
V3 SceneState       外部：地点 / 活动 / PendingAction  （每轮）
V4 Memory           过去：长期事实与事件               （跨会话）
V5 CharacterEmotion 短期情绪：primary/intensity/cause  （分钟~小时级，带衰减）★本次
V5 Relationship    长期关系：trust/familiarity/intimacy/tension + stage（天~周级）★本次
```

**Emotion = 短期状态，Relationship = 长期状态，禁止混用一个字段。**

## 文档导航

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | V2 现状分析、V5 差距、整体架构 |
| [emotion-model.md](emotion-model.md) | 情绪集合、CharacterEmotion 模型 |
| [emotion-update.md](emotion-update.md) | 事件→情绪更新的分工（LLM 判定/代码计算） |
| [emotion-decay.md](emotion-decay.md) | 强度衰减、覆盖、叠加 |
| [relationship-model.md](relationship-model.md) | 关系维度、tension 新增 |
| [relationship-events.md](relationship-events.md) | RelationshipEvent 事件模型与影响表 |
| [relationship-update.md](relationship-update.md) | 变化上限、防跳变 |
| [relationship-stage.md](relationship-stage.md) | Stage 代码计算（沿用 V2 迟滞机制） |
| [prompt-integration.md](prompt-integration.md) | "温柔但生气"的表达约束 |
| [memory-integration.md](memory-integration.md) | V4 事件记忆 → V5 事件检测的复用边界 |
| [testing.md](testing.md) | 17 项测试设计 |
| [tasks.md](tasks.md) | 任务注册表（开发入口） |

## 核心决策记录

1. **升级而非重建**：V2 `state_engine`（事件 delta 表/stage 迟滞/energy 衰减）与 `emotion_history` 全部保留复用；V5 只补缺口。
2. **情绪 8 值沿用 V2**：happy/sad/angry/worried/shy/excited/tired/calm，不新增情绪（embarrassed≈已有 shy，neutral 用 calm 兼任）。
3. **关系 4 维**：沿用 intimacy/trust/familiarity，**新增 tension**；stage 沿用 V2 的 stranger/friend/close_friend/partner 四级 + 迟滞，不采纳 5 级建议（见 relationship-stage.md）。
4. **LLM 只分类，代码只算数**：沿用 V2 模式并强化——LLM 输出事件类型/强度档位，所有分数计算/上限/衰减/持久化由代码完成；`StateUpdateDecision` 不再直接写 mood（这是 V2 的主要缺陷）。
5. **变化上限**：单事件 delta 表封顶（每维 ≤ 0.12）、单轮合计封顶（每维 ≤ 0.15）、情绪强度单轮 ≤ 0.4。
6. **不阻塞 SSE**：全部更新在 `_post_process` 后台（沿用 V2/V4 模式）。
7. **不重复存储**：relationship_event 只在 V5 事件表记录增量与影响；文本事实仍归 V4 Memory。

## 验收判据

1. 夸奖/安慰/批评后角色情绪与强度正确变化，并在无新事件时按曲线衰减回 calm。
2. 一次普通对话不可能使任何关系维度变化超过 0.15；stage 只能按阈值+迟滞迁移。
3. Prompt 中人格块在前、情绪块在后，且带"人格底色不覆盖"约束（温柔角色生气是"温柔地生气"）。
4. V3 Scene / V4 Memory / V5 全链路后台执行，SSE 零影响，全量回归通过。
