# Roleplay V8：World State System（World Runtime）

> 状态：**设计完成，待实现**。任务入口 tasks.md。前置：V1~V7.8 全部完成。
> 设计原则：**World 是与 Character 平行的外部世界层**——World 只维护"世界上有什么、发生了什么"，永远不写 Character 状态；Character 只通过 Context Builder 看到世界的切片。

## 1. V8 解决什么问题

V7.8 为止，角色已经知道"我是谁 / 我喜欢什么 / 我和用户什么关系 / 我为什么行动 / 我该怎么行动"，但**不知道世界长什么样**。用户说"给我拿个西瓜"，系统有目标（帮助用户）和行为（照顾），却不知道冰箱里有没有西瓜、现在是几点、厨房在哪。

```text
V7.8 为止：
Character State ──→ Response（世界的缺失由 LLM 想象兜底，跨轮不一致）

V8 之后：
World Runtime（时间/地点/环境/物品/事件，独立持久化与演化）
      ↓ World Context Builder（选择性切片）
Character Runtime（身份/情绪/记忆/目标/行为/自治，零修改）
      ↓
Response
```

V8 之后必须能回答：

1. **现在几点、什么时段？** 晚上 11 点的语气与上午 10 点不同。
2. **我在哪、这里能做什么？** 厨房能拿食物，卧室能休息。
3. **物品的持续状态？** 西瓜被吃掉 0.2，第二天过期——跨会话、跨轮持久。
4. **世界上发生了什么 / 将发生什么？** "明天面试"成为可触发、可完结的事实。
5. **世界如何影响角色？** 下雨 → 提醒带伞成为自治候选（World 给事实，Autonomy 做决定）。

## 2. 硬边界（V8 明确不做）

- **World 与 Character 严格分离**：情绪、关系、记忆、目标、行为策略、评估六大系统零修改；World 没有任何写回 Character 状态的通道——环境影响只经"上下文切片"与"自治事实"两个只读出口。
- **World 是状态系统，不是 Prompt**：世界存数据库、有状态机与演化规则；Prompt 只接收 Context Builder 的有界切片。
- **空世界零行为变更**：所有挂载点都是加法；`world_ctx` 为空时 Prompt 字节与 V7.8 完全一致（golden 字节不变是机器可证底线）。
- **不实现真实世界 API**：TimeProvider / WeatherProvider 只提供 manual 与 simulated 两种实现，接口为未来预留。
- **不实现 Tool Calling / Agent Workflow / Multi Character**：物品动作是声明式状态迁移，不是工具调用；一个世界一个角色。
- **时间消费者不迁移**：既有的 datetime.now() 消费者（深夜目标、静音时段、模式空闲）保持原样；V8 时间是世界域上下文，不接管它们。

## 3. 核心设计一览

| 模块 | 职责 | 核心载体 | 落点 |
|---|---|---|---|
| M1 World State Core | 世界聚合根与生命周期 | World / WorldEntity / WorldContext / StateSnapshot | `app/models/world.py`（Domain） |
| M2 Time System | 时间与时段 | TimeContext / TimeProvider / TimeEvent | real_sync 默认，simulated/story 预留 |
| M3 Location System | 层级地点与可用动作 | Location / LocationRelation / LocationContext | 默认 home 布局为角色资产 |
| M4 Object State | 物品实体与状态机（**核心**） | WorldObject / ObjectState / ObjectAction | world_entities 表 + 迁移规则 |
| M5 Environment | 天气/温度/光照/噪声/氛围 | EnvironmentContext + 效果标签 | 每世界一行，manual 更新 |
| M6 Event System | 影响未来的世界事件 | WorldEvent / EventTrigger / EventTimeline | world_events 表 + due 检查 |
| M7 Context Builder | 世界切片进 Prompt | WorldContextSelector + WorldContext | PromptBuilder 增可选 world_ctx |
| M8 Persistence | 世界存储与快照 | worlds / world_entities / world_events / world_snapshots | 迁移 0017+ |
| M9 Memory Integration | 事件完结 → 记忆候选 | 边界表 + 素材投递 | post_process 增量步骤 |
| M10 Autonomy Integration | 世界事实 → 自治裁决 | PolicySnapshot.world_facts（只读） | V7 policy 增可选参数 |

一条纪律贯穿全程：**World 生产事实，Character 消费事实；World 永远是旁路，失败只降级。**

## 4. 与既有系统的边界（最容易混淆的三对）

| 概念 | 域 | 归属 | 例子 |
|---|---|---|---|
| Scene（V3） | 会话 | 叙事连续性：pending action、current activity | "用户刚让我拿水，动作进行中" |
| World（V8） | 用户（跨会话） | 持久世界事实：物品、环境、事件 | "冰箱有 0.8 个西瓜；明天面试" |
| Memory（V4） | 用户（跨会话） | 角色对过去的长期记忆 | "用户上次提过在准备考试" |

- `scene_state.location`（V3 既有列）保持既有语义不动；World location 是事实源，两者关系见 location-system.md §6。
- Memory 记录过去，Event 影响未来：事件完结后才可能沉淀为 Memory（§memory-integration）。

## 5. 文档导航

- [architecture.md](architecture.md) — 总体架构、分层归属、挂载点清单、失败契约（先读这篇）
- [world-model.md](world-model.md) — M1：World / Entity / Context / Snapshot 核心模型与生命周期
- [time-system.md](time-system.md) — M2：时间模式、时段推导、TimeEvent
- [location-system.md](location-system.md) — M3：地点层级、可用动作、与 scene_state 的关系
- [object-system.md](object-system.md) — M4：物品状态机、生命周期、数量演化（核心）
- [environment-system.md](environment-system.md) — M5：环境字段、效果标签、影响通道
- [event-system.md](event-system.md) — M6：事件模型、调度与触发、与 V7 followup 的边界
- [context-builder.md](context-builder.md) — M7：切片选择规则、预算、Prompt 挂载、golden 不变量
- [memory-integration.md](memory-integration.md) — M9：事件 → 记忆的边界表与素材投递
- [autonomy-integration.md](autonomy-integration.md) — M10：world_facts 进 policy、职责分离
- [persistence.md](persistence.md) — 表结构、快照、TTL、回滚
- [testing.md](testing.md) — 测试分层 + `tests/v8/` 五套件 + 回归底线
- [tasks.md](tasks.md) — 任务注册表（V8-001 ~ 014）

## 6. 关键架构事实

```text
1. World 挂载点全部是加法：PromptBuilder 可选 world_ctx 参数、post_process 追加第 8 步
  （STEP_HANDLERS 是 AGENTS.md 明示的官方扩展点）、policy 可选 world_facts——空世界
   时不产生任何行为差异，golden prompt 字节不变。
2. 世界变更的解释器是确定性规则优先（动词模式 + 实体匹配，零成本零幻觉），LLM 辅助链
   仅采样启用——不做每轮新增 LLM 调用（成本与 state_update 同量级的教训）。
3. World 是用户域：每用户一个默认世界（跨会话持久），会话只是观察窗口；物品数量、
   事件日程天然跨会话成立。
4. 事件与记忆分工：Event 影响未来（due 未到 → 上下文 + policy 事实），Memory 记录过去
  （事件完结且重要 → 才沉淀为记忆候选，经既有 memory 仓储写入）。
5. 时间系统 real_sync 默认：世界时间 = 真实时钟，与 V6/V7 既有时间消费者天然一致；
   simulated/story 模式仅在 world 域内生效，不接管 runtime 的 datetime.now()。
6. 一切阈值与开关进 settings world_* 组；world 相关测试默认使用隔离夹具，
   全量既有测试（1050+）零回归是每个 Task 的底线。
```
