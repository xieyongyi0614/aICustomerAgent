# V8 架构设计

> World Runtime 是 Character Runtime 的**外部世界层**：平行、独立、只读出口。本篇定义分层归属、与既有管线的挂载点、失败契约与开关矩阵。

## 1. 总体架构

```text
                ┌──────────────── World Runtime ────────────────┐
                │  WorldEngine（编排：世界生命周期与演化）            │
                │   ├─ Time System        （TimeProvider/TimeContext）│
                │   ├─ Location System    （层级 + 可用动作）          │
                │   ├─ Object State       （实体状态机，核心）           │
                │   ├─ Environment        （天气/温度/光照/氛围）        │
                │   ├─ Event System       （调度/触发/完结）             │
                │   └─ WorldStateManager  （聚合根 + 快照）             │
                └───────────────┬──────────────────────────────┘
                                │ 只读切片（WorldContextSelector）
                                ▼
  User Request ──→ Character Runtime（V2~V7.8，零修改）──→ Response
                  Identity/Emotion/Memory/Goal/Behavior/Autonomy
                                ▲
                 两个只读出口：WorldContext（进 Prompt）
                              world_facts（进 Autonomy 裁决）
                ┌───────────────┴──────────────────────────────┐
                │ World Update Interpreter（用户消息 → 世界状态迁移）│
                │ Event→Memory 素材投递（完结事件 → 记忆候选）         │
                └──────────────────────────────────────────────┘
```

数据流（一次前台 turn）：

```text
t0  begin_trace（现状）
t1  world_engine.build_context(user_id, session_id)  ← 新增一次有界世界读（缓存于 WorldContext）
t2~tn  既有管线步骤不变；answer_chain 组 prompt 时
       PromptBuilder.build(..., world_ctx=world_ctx) → 追加【世界】段（空则不追加）
tn+1  save_turn（现状）
tn+2  schedule_post_process：既有 7 步不变，末尾追加 run_world_update（第 8 步）
       ├─ 解释用户消息 → 世界状态迁移（拿/吃/放回/移动…）
       ├─ due 事件检查 → 触发/过期
       └─ 完结的高重要度事件 → 记忆候选（经既有 memory 仓储）
```

## 2. 分层归属（Domain / Application / Infrastructure）

沿用 `api → application → services → repositories → core` 单向依赖：

| 层 | 位置 | 内容 | 约束 |
|---|---|---|---|
| Domain | `app/models/world.py` | World / WorldObject / WorldLocation / WorldEnvironment / WorldEvent / TimeContext / LocationContext / WorldContext / StateSnapshot + 枚举（WorldTimeMode、EntityKind、EventStatus、ObjectAction）+ 迁移规则表引用 | 纯 Pydantic，零 IO；状态机定义为纯函数 |
| Application | `app/application/world_engine.py` | WorldEngine：世界生命周期（ensure/create/snapshot/restore）、每 turn 的 WorldContext 组装调度、post_process 第 8 步 run_world_update 的编排 | 只做调度与容错；解释/选择逻辑在 services |
| Services | `app/services/world/` | `interpreter.py`（确定性规则解释器 + 可选 LLM 辅助链封装）、`context_selector.py`（WorldContextSelector 纯函数）、`time_provider.py`、`transitions.py`（物品状态机）、`memory_bridge.py`（事件→记忆候选） | 纯计算或经仓储读写世界自身；不写 Character 状态 |
| Chains | `app/chains/world_update_chain.py`（P1，可选） | LLM 辅助解释（采样启用），schema `WorldUpdateResult` | 走 build_structured_chain；失败返回 None |
| Infrastructure | `app/repositories/world_repository.py` 等 + 迁移 0017+ + `core/settings.py` | worlds / world_entities / world_events / world_snapshots 四表读写、prune | 沿用模块级函数仓储惯例 |
| Interfaces | `app/api/v1/world.py` | /debug/world 查询与运维端点（状态/实体/事件/快照/回滚/手动更新） | 只读为主，手动更新端点显式标注 |
| Character 资产 | `app/character/asuna/world.py`（新增） | 默认 home 地点布局、物品类目状态机定义、环境效果词表 | 世界"设定"属于角色资产，与世界"状态"分离 |

## 3. 挂载点清单（全部是加法）

| # | 挂载点 | 文件 | 变更形态 | 归属 Task |
|---|---|---|---|---|
| H1 | turn 前世界上下文组装 | `app/application/chat_pipeline.py` | +1 行 `world_ctx = world_engine.build_context(...)`（内部带缓存与降级） | 007 |
| H2 | Prompt 组装 | `app/prompts/builder.py::build` | 增可选参数 `world_ctx=None`；非空时追加【世界】段 | 007 |
| H3 | 生成链透传 | `app/chains/answer_chain.py` | 增可选参数 `world_ctx=None` 透传 | 007 |
| H4 | post_process 第 8 步 | `app/application/post_process.py::STEP_HANDLERS` | 追加 `run_world_update`（官方扩展点；persist/evaluation 同构） | 006 |
| H5 | 自治裁决事实 | `app/application/autonomy_engine.py::_snapshot_for` | PolicySnapshot 增 `world_facts` 字段（默认空 dict，行为不变） | 011 |
| H6 | lifespan 循环 | `app/main.py` | 事件 due 检查循环（P1，world_enabled 门控） | 008 |
| H7 | Router 注册 | `app/api/v1/router.py` | world debug router | 002 |
| H8 | 记忆候选投递 | `app/services/world/memory_bridge.py` | 只调用既有 memory 仓储 save，不改 extractor | 010 |

明确不改的文件：`state_service` / `emotion` 相关 / `relationship` 相关 / `goal_service` / `behavior_engine` / `memory_service`（extractor）/ `evaluation_rules` / `autonomy_policy.evaluate` 的既有裁决逻辑（只增可选输入）/ `scene_service` 既有语义。

## 4. 与 V3 Scene 的共存规则

- `scene_state.location`（会话域、叙事语义）保持既有读写路径不动；V8 不写 scene_state。
- World location 是跨会话事实源。P0 阶段两者独立并存（可能暂不一致，属可接受）；Prompt 中 World 段标注地点事实，Scene 段维持叙事动作连续性。
- P2 预留：WorldContextSelector 在 scene.location 与 world.location 冲突时以 world 为准的调和对齐策略（先观测差异频率再决定）。

## 5. 失败与降级契约（与 V7.5/V7.8 同源）

1. World 任何异常（读库、解释、选择、写迁移）只 log + 降级：**chat 无 World 段照常回答**，post_process 第 8 步失败不影响其余步骤。
2. 解释器单条迁移失败不影响同批其余迁移；不确定的解释**宁可不迁移**（不造事实）。
3. 世界数据缺失（未初始化/迁移未跑/world_enabled=false）→ WorldContext 为 None，全部挂载点短路。
4. 字符超限截断打标；事件错过触发（宕机跨过 due_at）→ 下次检查补触发一次，幂等。

## 6. 开关矩阵（world_* 配置组，完整清单见 persistence.md §6）

| 开关 | 默认 | 作用 |
|---|---|---|
| `world_enabled` | true | 总开关；false 时全部挂载点短路（回到 V7.8 行为） |
| `world_context_char_budget` | 600 | 世界段 prompt 字符预算 |
| `world_interpreter_enabled` | true | 确定性解释器开关 |
| `world_llm_assist_enabled` | false | LLM 辅助解释（采样），默认关——成本与确定性双考虑 |
| `world_time_mode` | real_sync | real_sync / simulated / story |
| `world_memory_bridge_enabled` | true | 事件完结 → 记忆候选 |

测试默认约定：world 夹具显式创建/播种世界数据；既有测试在无世界数据下运行 → 行为与 V7.8 全量一致。

## 7. 验收底线（全局）

- 既有全量测试（1050+）零回归；`tests/golden/` 在无世界数据时字节不变——"没改行为"的机器可证证据。
- 空 world_ctx 不进入 PromptBuilder 输出；世界段总字符 ≤ `world_context_char_budget`。
- World 对 Character 状态（character_state / relationship_state / emotion_history / memories 直写路径）**零写入**——以代码评审 + 测试断言固化。
