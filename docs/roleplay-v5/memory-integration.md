# Memory Integration（V4 ↔ V5）

## 1. 职责切分（不重复存储）

| 信息 | 归属 | 示例 |
|---|---|---|
| 事件文本事实 | **V4 Memory**（`relationship_event` 类型） | "用户在角色难过时安慰过她" |
| 事件的数值影响 | **V5 relationship_events 表** | trust +0.04 / intimacy +0.03 |
| 长期统计结论 | 不单独存 | 需要时按事件表聚合或按记忆召回 |

原则：**V4 记"发生了什么"，V5 记"影响了多少"**。同一个事件，两边各存自己维度，不互相复制内容字段。

## 2. 单向影响流

```text
V4 Memory（历史事件）
   ↓（事件检测时的上下文参考，只读）
V5 Event Detector
   ↓
V5 RelationshipEvent + RelationshipState
```

- V5 检测器可读取本轮召回的 V4 记忆（已在 context 中）辅助事件分类，但不回写 V4。
- V4 Memory 不存分数；V5 事件表不存叙事文本（只存 50 字 cause）。

## 3. memory_replay：历史事件的迟到影响

场景：V4 中存有"用户曾安慰过角色"的记忆，但当时（V4 时代）尚无 V5 记分。

```text
触发：长期未互动会话中，relationship_event 类记忆被召回（score 进入 top_k）
处理：Event Detector 若判定本轮与该记忆相关（如用户提及此事）
     → 正常检测本轮事件；
     → 同时可为该记忆补记一条 source=memory_replay 的 RelationshipEvent，
       impact = 标准表 × 0.5（历史折价系数 settings.rel_replay_discount）
限制：每条记忆只允许 replay 一次（查 relationship_events.source+cause 匹配），
     防止每次提起都反复加分
```

## 4. 边界情况

- V4 记忆与 V5 事件冲突（记忆说关系好、事件表显示冲突多）：以 V5 事件表为准做 stage（数值是唯一事实源），记忆只影响语言表达。
- replay 失败：跳过，不影响主流程。
- V4 `relationship_event` 记忆的提取照旧（V4 管线），V5 不新建记忆。

## 5. 验收标准

- 同一事件不产生重复文本（V4 记忆只一条）。
- replay 折价与一次性限制有单测。
- 关系 stage 只由事件表数值驱动，与记忆条数无关。
