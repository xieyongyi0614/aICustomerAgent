# V2 Behavior 层退役评估（V6.5-012）

> 结论先行：**Keep（当前阶段不退役）**。依据为代码依赖分析；真实回归数据（V6.5-009）产出后可按 §4 触发条件复议。

## 1. 评估对象与现状

V2 时代的行为层组件，在 V6.5 后的存续形态：

| 组件 | 位置 | V6.5 后角色 |
|---|---|---|
| `BehaviorDecision`（7 值） | `app/models/behavior.py`，由 turn_analysis_chain 每轮产出 | V5 引擎活跃输入 + degraded fallback 来源 |
| 【本轮行为指令】段 | `BEHAVIOR_INSTRUCTIONS`，builder tail | 仅 degraded 时渲染（strategy 可用时被【表现方式】取代） |
| `INTENTION_BEHAVIOR_MAP` | `app/models/intention.py` | intention_policy 的 fallback 映射，保留 |

## 2. 依赖分析（为什么不能现在删）

`analysis.behavior.behavior` 有三路**非 prompt** 的活跃消费者，全部属于 V5：

1. **关系增量**：`state_engine.relationship_deltas` → `BEHAVIOR_DELTAS[behavior]` 叠加进 V5 关系更新（state_service.apply_and_save → apply_relationship_v5）。删除 behavior 字段 = V5 关系引擎失去一半输入。
2. **精力修正**：`state_engine.ENERGY_BEHAVIOR_MODIFIERS.get(analysis.behavior.behavior)`（state_engine.py:113）。
3. **情绪史账本**：emotion_history 落库记录 behavior（state_service.py:215），是 /state 展示与回放数据的一部分。

prompt 侧：degraded 路径（intention 链失败/非法/strategy 解析异常）下，`_degraded_directive` 用 `BEHAVIOR_INSTRUCTIONS[behavior]` 渲染【本轮行为指令】段——这是「行为层永不为空」不变式在降级路径的唯一载体。

## 3. 退役收益与成本

| | 收益 | 成本/风险 |
|---|---|---|
| 删 prompt 段（fallback） | 每轮 turn_analysis 少一个字段语义负担；代码 −1 分支 | 降级路径失去行为指令（degraded 轮表现完全无锚）；违反不变式 |
| 删 behavior 字段 | turn_analysis schema 收窄 | **破坏 V5 关系增量与精力修正**（需为两处引擎另找信号源，改动面 = V5 核心引擎） |

结论：字段退役的本质是「给 V5 引擎换输入信号」的重构，不是删一段 prompt，收益不抵风险。

## 4. 复议触发条件（需 V6.5-009 数据）

满足全部条件时可将【本轮行为指令】fallback 段退役（behavior 字段仍保留给 V5）：

1. 真实回归连续两周 `intention degraded` 触发率 < 1%（trace `intention: degraded` 统计）；
2. strategy 解析异常率（`behavior_engine` trace error）≈ 0；
3. 确认降级轮可直接无行为段运行（预算行仍渲染）且人工观感无劣化。

在此之前，fallback 段是廉价保险：7 条短句常量 + 一个 dict 查表，无运行时成本。

## 5. 行动项

- 本版本不动任何 V2 behavior 代码（本报告即 V6.5-012 交付物）。
- 在 V6.5-009 清单执行时顺带记录 degraded 触发次数，作为 §4 的数据输入。
