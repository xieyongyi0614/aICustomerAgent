# M9 World + Memory Integration

> 目标：世界事件完结后沉淀为长期记忆（"用户参加过考试"），让世界经历变成角色的过去。
> 边界：**World→Memory 是单向投递**——V8 只生产记忆候选、调用既有 memory 仓储写入；V4 记忆系统（extractor/policy/召回）零修改。

## 1. 关系总图

```text
World Event（影响未来）
   │ scheduled/active：进 WorldContext / world_facts（不是记忆）
   ▼
completed（事件结束）
   │ importance ≥ normal（门槛）
   ▼
memory_bridge（services/world）→ 记忆候选（content/type/importance）
   ▼
既有 memory 仓储 save（V4 既有写入口，复用去重/置信默认值）
   ▼
Memory（记录过去）→ 未来召回 → 影响行为
```

## 2. 哪些进入 Memory，哪些只存在 World（边界表）

| 世界变化 | 进 Memory？ | 理由 |
|---|---|---|
| 高/普通重要度事件完结（面试、考试、旅行） | **是** | 叙事性经历，"参加过"影响长期态度 |
| low 重要度事件完结（临时提醒） | 否 | 噪音；上下文已给过一次机会 |
| 物品数量/位置变化（吃了西瓜、搬了椅子） | **否，永远只存 World** | 世界现状查询即得；写成记忆会过时且膨胀 |
| 环境变化（下雨了/雨停了） | 否 | 瞬时世界态 |
| 事件被取消 | 否（cancelled 不沉淀） | 没发生的事不进记忆 |
| 用户陈述的世界观事实（"我家阳台朝南"） | 候选 | 属资产级事实，按 importance 规则表判定 |

一句话规则：**会过时的状态 → World；构成"过去经历/稳定事实"的叙事 → Memory。**

## 3. 投递机制（memory_bridge）

- 位置：post_process 第 8 步（run_world_update）的收尾阶段——事件被标记 completed 的同一事务后投递（fire-and-forget 语义与既有步骤一致，失败只 log）。
- 候选构造（纯函数 `to_memory_candidates(event) -> list[MemoryDraft]`）：
  - content：模板渲染（"用户在 {completed_at 日} 完成了{title}"），有界；
  - type：映射表（interview/exam → important_event；trip → important_event；birthday → user_fact…）；
  - importance：事件 importance → 记忆重要度映射表（normal→0.6，high→0.8，进 settings）；
  - source：`world_event`（可溯源，审计友好）。
- 写入走**既有** memory 仓储 save（V4 的唯一写入口语义不变）；去重靠 V4 既有 conflict 策略，V8 不重复实现。

## 4. 反向：Memory → World？

**不做（P0/P1）**。记忆召回不反哺世界状态（"记得用户说过下雨"不会自动把环境置为 rain）——环境来自解释器对当前消息的确定性解释。反向通道留待真实需求出现（文档化为非目标，防止系统边界糊掉）。

## 5. 与 V7.5 评估的关系

- 由事件沉淀的记忆与任何其他记忆同权参与召回；V7.5 memory 维（FABRICATION/MISSED）照常审计——世界产生的记忆**不会**获得豁免，反而让"角色引用世界经历"进入既有质量闭环。

## 6. 边界

- 不修改 memory_service.extract_and_save 与 extractor_chain（世界素材不进消息抽取链，避免双重提取）。
- 投递幂等：event 标记 `memory_materialized` 标志位（payload 内），重复投递直接跳过。
- 候选数量上限：单事件 1 条；不批量生成。
