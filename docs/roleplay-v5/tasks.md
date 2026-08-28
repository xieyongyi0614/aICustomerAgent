# Roleplay V5 任务注册表

> 开发入口。按依赖顺序执行；P0 = V5 必须，P1 = 推荐，P2 = 延期。
> 策略：一次只执行一个 Task，完成后运行测试、展示改动，再进入下一个。

## Task 列表

### V5-001 Emotion 模型（P0）

- **目标**：CharacterEmotion(intensity/cause) + EmotionEvent + EMOTION_EVENTS 表。
- **前置**：无。
- **涉及文件**：`app/models/character_state.py`（扩展）、`app/models/emotion.py`（扩展）、`app/services/state_engine.py`（常量表）。
- **实现内容**：8 值情绪沿用；intensity/cause 字段；事件类型/档位 Literal。
- **验收标准**：模型校验、非法值拒绝、档位封顶。
- **测试要求**：`tests/test_emotion_models.py`。Priority: P0

### V5-002 character_state 表扩展（P0）

- **目标**：intensity/cause/last_event_at 列 + Alembic 迁移。
- **前置**：V5-001。
- **涉及文件**：`app/core/db.py`、`migrations/`、`app/repositories/character_state_repository.py`。
- **实现内容**：加列（mood 复用不改名）；repository upsert 扩展。
- **验收标准**：迁移与 ORM 一致；V2 数据兼容。
- **测试要求**：迁移一致性测试。Priority: P0

### V5-003 Emotion Updater + Decay（P0）

- **目标**：事件驱动情绪更新 + 衰减曲线。
- **前置**：V5-001、V5-002。
- **涉及文件**：`app/services/state_engine.py`、`app/services/state_service.py`、`app/core/settings.py`。
- **实现内容**：EMOTION_EVENTS × magnitude 转移算法、强情绪保护、20% 惯性、读取侧两段衰减、底线复位；`StateUpdateDecision.mood` 退役。
- **验收标准**：emotion-update/emotion-decay 全部规则；单轮 ≤0.4。
- **测试要求**：`tests/test_emotion_update.py`、`tests/test_emotion_decay.py`。Priority: P0

### V5-004 Relationship 模型扩展 + tension（P0）

- **目标**：RelationshipState 加 tension；V5 RelationshipEventType + delta 表扩充。
- **前置**：V5-001。
- **涉及文件**：`app/models/relationship.py`、`app/core/db.py`、`migrations/`、`app/repositories/relationship_repository.py`、`app/services/state_engine.py`。
- **实现内容**：tension 列（默认 0）+ 正向互动消耗规则 + 新 EVENT_DELTA 表。
- **验收标准**：迁移一致；tension 参与 clamp。
- **测试要求**：`tests/test_relationship_models.py`。Priority: P0

### V5-005 事件检测链扩展（P0）

- **目标**：turn_analysis_chain 输出 EmotionEvent + RelationshipEventType。
- **前置**：V5-001、V5-004。
- **涉及文件**：`app/chains/turn_analysis_chain.py`、`app/prompts/turn_analysis.py`、`app/models/emotion.py`。
- **实现内容**：结构化输出扩展（类型/档位/置信度/cause）；V2 EventCategory 映射；降级策略沿用。
- **验收标准**：LLM 只输出分类与档位，无分数。
- **测试要求**：`tests/test_event_detection.py`（FakeLLM）。Priority: P0

### V5-006 relationship_events 表 + Event Builder（P0）

- **目标**：事件账本落库。
- **前置**：V5-004、V5-005。
- **涉及文件**：`app/models/relationship.py`（RelationshipEvent）、`app/core/db.py`、`migrations/`、`app/repositories/relationship_event_repository.py`（新增）。
- **实现内容**：RelationshipEvent 落库（含实际 impact）、无事件零写入。
- **验收标准**：event 行 impact 与状态变化一致。
- **测试要求**：`tests/test_relationship_events.py`。Priority: P0

### V5-007 Relationship Updater + 防跳变 + Stage 冻结（P0）

- **目标**：三层上限 + tension 冻结升级。
- **前置**：V5-006。
- **涉及文件**：`app/services/state_engine.py`、`app/services/state_service.py`、`app/core/settings.py`。
- **实现内容**：单事件/单轮/每日上限 clamp、tension>0.5 冻结、next_stage 保留迟滞。
- **验收标准**：Case 9/10/11 全部规则生效。
- **测试要求**：`tests/test_relationship_update.py`、`tests/test_relationship_stage.py`。Priority: P0

### V5-008 编排接入（P0）

- **目标**：V5 管线接入 _post_process；state_update_chain 的 mood 路径退役。
- **前置**：V5-003、V5-007。
- **涉及文件**：`app/services/state_service.py`、`app/services/agent_service.py`、`app/chains/state_update_chain.py`、`app/services/trace_collector.py`。
- **实现内容**：情绪/关系更新后台执行、trace `emotion_update`/`relationship_event` step、降级容错。
- **验收标准**：SSE 零影响；失败降级。
- **测试要求**：`tests/test_v5_e2e.py`。Priority: P0

### V5-009 Prompt 集成（P0）

- **目标**：情绪段/关系段新格式 + 人格优先约束。
- **前置**：V5-008。
- **涉及文件**：`app/prompts/builder.py`。
- **实现内容**：强度分档文案、cause 注入、tension 档、人格优先约束句、预算控制。
- **验收标准**：prompt-integration.md 全部要求；无 analysis 兼容。
- **测试要求**：`tests/test_prompt_v5.py`。Priority: P0

### V5-010 Memory Replay 集成（P1）

- **目标**：V4 relationship_event 记忆召回补记折价事件。
- **前置**：V5-006、V4 全部完成。
- **涉及文件**：`app/services/memory_service.py`、`app/services/state_service.py`、`app/core/settings.py`。
- **实现内容**：replay 触发、0.5 折价、每记忆一次限制。
- **验收标准**：memory-integration.md 规则。
- **测试要求**：`tests/test_memory_replay.py`。Priority: P1

### V5-011 17 项必测 + 全量回归（P0）

- **目标**：testing.md 矩阵全绿。
- **前置**：V5-009（010 可并行后补）。
- **涉及文件**：`tests/`（补充聚合用例）。
- **实现内容**：Case 1~17 + 真实模型回归清单（温柔但生气/自然回落/tension 距离感）。
- **验收标准**：全量通过，V2/V3/V4 零回归。
- **测试要求**：同左。Priority: P0

### V5-012 Debug 展示（P1）

- **目标**：前端展示 Emotion(intensity/cause)/tension/事件轨迹。
- **前置**：V5-008。
- **涉及文件**：`app/api/v1/state.py`、`app/api/v1/schemas.py`、前端 DebugPanel。
- **验收标准**：面板可见情绪强度/成因/tension/事件账本。
- **测试要求**：API 单测 + 前端 Vitest。Priority: P1

### V5-013 多事件叠加评估（P2，仅文档）

- **目标**：评估同轮多事件叠加（当前取最高 confidence）是否引入。
- **前置**：V5-011。
- **验收标准**：结论文档化。Priority: P2

## 依赖图

```text
V5-001 → V5-002 → V5-003 ↘
   │        ↘ V5-004 → V5-006 → V5-007 → V5-008 → V5-009 → V5-011 → V5-013(P2)
   └→ V5-005 ↗                  V5-010(P1) ↗         V5-012(P1) ↗
```
