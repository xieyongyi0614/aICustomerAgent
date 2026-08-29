# 多事件叠加评估（V5-013 结论文档）

> tasks.md V5-013（P2，仅文档）：评估同轮多事件叠加是否引入。本文档为结论记录。

## 1. 现状（V5-001~012 已实现）

- 检测层：`TurnAnalysis` 输出**单个** `EmotionEvent` 与**单个** `RelationshipEventDecision`（各含 type/magnitude/confidence/cause）。
- 更新层：`update_emotion` / `apply_relationship_v5` 每轮只处理一个主事件。
- 等价语义：**同轮多事件天然取最高置信者**——结构上不可能叠加，无需运行时挑选逻辑。

## 2. 评估：是否引入叠加？

| 维度 | 分析 |
|---|---|
| 收益 | 同轮既夸奖又吐槽的混合场景表达更细腻；但 magnitude 档位已能表达"强弱"，收益有限 |
| 风险 | 叠加顺序敏感（先 criticized 后 praise 与反序结果不同）；情绪震荡、关系分数被同轮多次推高，防跳变上限需重设计（现有 0.4/0.15/0.30 均按单事件口径） |
| 复杂度 | 检测 schema、Updater、事件账本对账、全部既有测试需重写 |
| 替代方案 | strong 档 + cause 文本已可承载混合语义；用户可在下一轮继续表达 |

**结论：V5 第一版维持"单主事件（结构上取最高置信）"不引入叠加。** 与 emotion-decay.md §4 的第一版决策一致。

## 3. 未来若引入的触发条件（记录备查）

1. 真实回归中出现可归因于"单事件丢失"的明显情绪失真案例（≥3 个可复现案例）；
2. 检测器对混合事件的 type 判定准确率稳定（无档位摇摆）。

## 4. 若引入的设计草图（不在本版实现）

- `TurnAnalysis.emotion_events: list[EmotionEvent]`（≤3，按 confidence 降序）；
- 叠加规则：同情绪合并取最大 raw_delta，异情绪仅执行 confidence 最高者的切换，其余折叠为 tension 微调；
- 单轮/每日上限不变，但单轮内多次叠加后必须整体复检 emotion_max_turn_delta；
- 事件账本每条候选一行（impact 为各自实际生效值），对账口径不变。

## 5. 实施边界

- 本文档仅为结论文档，不包含代码变更；引入叠加时需新增 Task 并重写 emotion/relationship 更新器测试。
