# V5 Architecture

## 1. V2 现状分析（复用资产）

V2 已实现（`services/state_engine.py`、`services/state_service.py`）：

| 能力 | 现状 | V5 处理 |
|---|---|---|
| 情绪标签 | `CharacterState.mood` 8 值 Literal，由 LLM `StateUpdateDecision` **直接指定** | 保留标签集；**改为事件驱动 + 代码计算**，补 intensity/cause |
| 情绪衰减 | 仅 `apply_idle_recovery`：超时把 tired/angry 重置 calm | **升级为强度衰减曲线**（emotion-decay.md） |
| 关系维度 | intimacy/trust/familiarity ∈ [0,1] | 保留，**新增 tension** |
| 关系变化 | `EVENT_DELTAS`/`BEHAVIOR_DELTAS` 固定 delta 表，代码 clamp | 保留并补齐事件类型；**增加单轮合计上限** |
| Stage | 阈值 + 迟滞（`next_stage`），纯代码 | 原样保留 |
| 事件识别 | `turn_analysis_chain` → `TurnAnalysis(event, behavior, user_emotion)` | 保留为事件来源之一；新增情绪事件分类（emotion-update.md） |
| 历史 | `emotion_history` 每轮落库 | 保留；新增 `relationship_events` 事件表 |
| 后台执行 | `state_service.apply_and_save` 在 `_post_process` | 保留 |
| Prompt | `PromptBuilder` mood/energy/relationship 分节 + STAGE_DESCRIPTIONS | 保留结构；情绪段升级 + 人格优先约束 |

## 2. V5 缺口清单

1. 情绪无 intensity / cause，无法表达"有点开心"vs"非常开心"。
2. 情绪由 LLM 每轮直写，无覆盖/叠加/衰减规则 → 情绪跳变。
3. 关系缺 tension 维度（冲突/尴尬无独立刻画）。
4. delta 表只对 event/behavior 分类粗粒度生效，无强度档位、无单轮合计上限。
5. 关系事件只进了 emotion_history（轨迹），没有独立 RelationshipEvent 模型，无法支撑"事件→影响"的审计与调参。

## 3. 目标架构

```text
Conversation
   │（_post_process 后台，与 V3/V4 并行）
   ▼
Event Detector（LLM：复用 turn_analysis_chain，扩展输出 EmotionEvent + RelationshipEventType + 强度档位）
   │
   ├─► Emotion Updater（纯代码：强度转移/覆盖/叠加 → CharacterEmotion）
   │
   └─► Relationship Event Builder（纯代码：查 delta 表 × 强度档位 → RelationshipEvent 落库）
            │
            ▼
       Relationship Updater（纯代码：clamp + 单轮上限 + stage 迟滞）
            │
            ▼
       repositories 落库（character_state 扩展 / relationship_state 扩展 / relationship_events 新表 / emotion_history 保留）
```

下一轮读取：`state_service.load_states` → `ConversationState` → `PromptBuilder`（人格块 → 情绪块 → 关系块 → scene → memory）。

## 4. 与 V3/V4 边界

- V3 SceneState：完全独立，互不读写。
- V4 Memory：提供历史事实供事件检测上下文参考（memory-integration.md）；`relationship_event` 类型记忆记录"发生了什么"，V5 事件表记录"数值影响"，**不重复存文本**。
- Prompt 注入顺序固定：人格（V2 资产）→ 情绪 → 关系 → scene（V3）→ memory（V4）。

## 5. 边界情况

- 事件检测失败/低置信度：情绪按纯衰减处理（无新事件），关系零变化，trace 记 degraded。
- state_update_chain 的 `StateUpdateDecision`（mood/inner_state/topic）：inner_state/topic 保留 LLM 直写（叙事性字段），mood 剥离为代码计算。
- 全链路失败：沿用"状态停在上一轮，不影响回答"。

## 6. 验收标准

- V2 既有 state 测试迁移后通过；V3/V4 全量回归零破坏。
- trace 新增 `emotion_update` / `relationship_event` step。
- 17 项测试（testing.md）通过。
