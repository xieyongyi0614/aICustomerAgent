# M2 Time System

> 目标：让角色知道"现在几点、什么时段、过了多久"。时间是世界演化与事件调度的基准轴。
> 边界：**不接管 Runtime 既有的 datetime.now() 消费者**（深夜目标、静音时段、模式空闲保持真实时钟）；V8 时间是世界域上下文。

## 1. 三种时间推进模式（WorldTimeMode）

| 模式 | 世界时钟 | 用途 | 状态演化 |
|---|---|---|---|
| `real_sync`（默认） | = 真实时钟，不存储 | 日常陪伴；与 V6/V7 既有时间语义天然一致 | 事件 due 按真实时间触发 |
| `simulated` | sim_time 存于 worlds 行，按真实流逝速率推进（上次读取到现在的时间差累加） | 测试时间演化的 SandBox（如"一天 = 24 分钟"可配速率） | 事件 due 按 sim_time |
| `story` | sim_time 存储但**只在剧情推进时步进**（显式 advance 端点驱动） | 剧情时间（"三天后"一次跳变） | 事件 due 按 sim_time |

P0 实现 real_sync；simulated/story 的模型字段与 TimeProvider 分支在 P0 预留、P1 补实现与测试。速率与步进参数进 world_* 配置组。

## 2. 核心模型

### TimeContext（进 WorldContext，只读）

| 字段 | 类型 | 说明 |
|---|---|---|
| now | datetime | 世界当前时间（real_sync = 真实） |
| weekday | str | 周一~周日（中文，prompt 友好） |
| part_of_day | str | morning(5-11) / afternoon(11-14) / dusk(14-18) / evening(18-23) / late_night(23-5) |
| time_mode | WorldTimeMode | 上下文自述，避免角色混淆 |
| note | str \| None | 剧情时间附加说明（story 模式下"距上次对话已过两天"） |

### TimeProvider（services/world/time_provider.py）

```text
now(world) -> datetime        real_sync → datetime.now()；否则 → world.sim_time
advance(world, delta) -> None simulated：sim_time += delta × rate；story：sim_time += delta（仅端点调用）
```

- TimeProvider 是唯一时间读取口；world 域内禁止散落 datetime.now()。
- 不引入第三方时钟库；simulated 推进用"上次推进时间戳 + 速率"的惰性计算，不依赖循环。

### TimeEvent（时间驱动的世界变化）

时间本身不直接写状态，而是**触发既有世界的迁移**：

```text
到期事件：due_at ≤ now 的 scheduled event → active（Event System 触发）
过期物品：properties.expiry_at ≤ now → 迁移 state → expired（Object 状态机）
时段切换：不产生事件（part_of_day 是派生值，每次装配时计算）——避免午夜循环噪音
```

## 3. Duration："用户已经工作 12 小时"

- 事件的 `started_at / due_at / completed_at` 世界时间戳是唯一的时长事实源。
- WorldContextSelector 会在事件摘要里渲染时长（"面试 · 还有 14 小时"），prompt 只收结论字符串，不做时间运算。
- "用户已工作 12 小时"这类**用户状态时长**属于事件（type=work_session，用户陈述开始时间）或将来的人物实体状态（P2+，本阶段人物不入世界）——文档化为边界。

## 4. 与既有系统的关系

| 既有消费者 | 时间源 | V8 是否接管 |
|---|---|---|
| goal_service 深夜目标（23-6 点） | datetime.now() | 否（real_sync 下语义一致；simulated 模式下明知不一致，接受并文档化） |
| autonomy_policy 静音时段 | now 参数（真实） | 否，同上 |
| mode_service idle 重置 | 真实时钟 | 否 |
| 情绪衰减/记忆 recency | 真实时钟 | 否 |

统一时钟是 V9+ 议题；V8 的世界时间只保证**世界域内自洽**。

## 5. 边界

- TimeContext 每次装配即计算，无缓存失效问题；real_sync 下零存储成本。
- 不实现时区配置（单机单用户，本地时区即世界时区）；不实现公历/农历换算（词表级 part_of_day 足够）。
- story 模式的跳变不回写任何 Character 时间敏感状态（原则同 world 不写 character）。
