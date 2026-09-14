# V2.3.0 World Simulation System Scenario Test

> **上游依据**：[architecture.md](./architecture.md) §4（总体架构）、§5（核心组件）、§6（数据模型）、§7（运行链路）、§8（集成契约）、§9.3（边界不变量）；[tasks/](./tasks/)（WS-001 ~ WS-019 任务注册表）
> **定位**：V2.3.0 统一验收的场景级测试执行文档。以「用户视角的可观察行为」为单位组织用例，覆盖端到端链路，作为最终 V2.3 验收与人工回归的场景层补充。
> **与既有验收资产的关系**：
> - `apps/backend/tests/v23/test_ws019_acceptance.py` — CI 可跑的自动化验收（Flag 矩阵 / 逐字节一致 / 四链路 / 八不变量 / 迁移）。**本文件不重复其断言**，场景用例的「Related Modules」直接指回对应自动化用例，形成「自动化跑结构 + 场景跑行为」的双层验收。
> - [regression-checklist.md](./regression-checklist.md) — 真实模型人工回归执行单（按 R-2.x/R-3.x 分组）。本文件以「完整用户故事」为线索，是回归清单的**场景聚合视图**。
> **状态**：待执行（执行结论回写「执行记录」区）。
> **三条硬约束**（本文件全部用例遵守）：
> 1. **不新增功能** — 全部期望值来自已实现代码的既有行为，不得引入架构未定义的能力；
> 2. **基于已有 Architecture** — 组件、数据表、Flag、事件类型一律引用 architecture.md 既有定义；
> 3. **用于最终 V2.3 统一验收** — 每条用例都是可执行、可观测、可判定的验收单元。

---

## 0. 场景测试总则

### 0.1 测试对象与验收目标

| 维度 | 内容 |
|---|---|
| 被测系统 | V2.3.0 World Simulation Layer（Context + Trigger Layer） |
| 验收目标 | 世界能自主运行、角色有可观察的生活、事件三源汇流、场景与时间进入消费面、离线后可追溯；且全程不越边界（零新设施 / 0 LLM 默认 / 世界不写 Character 域 / Flag 可回退） |
| 判定基准 | 每条用例的 **Acceptance Criteria** 全部为布尔可判定项；任一 FAIL 即场景不通过 |
| 失败分级 | P0（越界、不可复现、Flag 回退失效）= 阻断发布；P1（行为偏差）= 修复后重测；P2（呈现瑕疵）= 登记 |

### 0.2 环境与观测三件套

| 项 | 说明 |
|---|---|
| Flag 基线 | 全部 `v23_*` 默认 off。每条用例「Preconditions」显式声明所需 Flag（按 architecture.md §8.4 启用链，子闸必须总闸先开） |
| 时钟控制 | `WORLD_TIME_MODE=real_sync|simulated|story`；`simulated` 配 `WORLD_SIM_RATE` 控制推进倍率；`V23_DEBUG_TICK_ENABLED=true` 开放手动 tick |
| 手动推进 | `POST /api/v1/debug/world/simulation/tick`（`world_engine.run_debug_tick`），用于确定性复现时序场景 |
| 观测面 ① | 调试端点：`GET /debug/world/simulation`（时间/简报/当前块/活跃处境/近期事件/flag 快照/额度丢弃）、`GET /debug/world/plan`、`GET /debug/world/situations` |
| 观测面 ② | prompt trace：`runtime_traces` 的 `world_context` 步骤快照（验证 WorldBrief 入 prompt 与预算） |
| 观测面 ③ | 库断言：`worlds` / `world_entities` / `world_events` / `daily_plans` / `user_situations` 直查（SQL 见 regression-checklist §1） |

### 0.3 场景编号规则

| 段 | 主题 | 对应 architecture 章节 |
|---|---|---|
| ST-1.x | World Lifecycle | §5.1 / §6.2 / V8 保留面 |
| ST-2.x | Entity Simulation | §5.5 / V8 `world_entities` 状态机 |
| ST-3.x | Event System | §5.4 / §6.3 |
| ST-4.x | Time Simulation | §5.2 / §7.1 / §7.4 |
| ST-5.x | Agent Interaction | §7.2 / §7.3 / §8.2 |
| ST-6.x | Multi-step Scenario | §7.1~§7.4 综合 |

---

## 1. World Lifecycle（世界生命周期）

> 覆盖：世界创建/幂等初始化 → 世界状态读取 → 世界快照 → 世界域写面边界。世界是全系统的持久化事实基座，本节确认「世界存在且只存在于世界域」。

### ST-1.1 世界幂等初始化

- **Scenario Name**：首次对话触发世界创建；重复触发不产生第二个世界
- **Preconditions**：`world_enabled=true`；用户 `U1` 从未建立世界；`v23_world_simulation_enabled` 任意
- **Input**：对 `U1` 连续两次调用 `world_engine.ensure_world("U1")`
- **Execution Flow**：
  1. 第一次 `ensure_world` → 仓储 `world_repository.ensure_world` 创建 `worlds` 行（`world_id = home:U1`）；
  2. 第二次 `ensure_world` → 返回同一行，不新增；
  3. 读 `world_repository.get_world("U1")`。
- **Expected Result**：两次返回同一 `world_id`；`worlds` 中该 user 仅 1 行；`time_mode` 为配置默认值；`environment` 合法。若 `world_household_autoseed_enabled=true`，默认家庭库存被播种且重复调用不重复播种。
- **Related Modules**：`app/application/world_engine.py: ensure_world` / `seed_default_household`；`app/repositories/world_repository.py`；`app/core/settings/world.py`
- **Acceptance Criteria**：
  1. `worlds` 该 user 行数 == 1；
  2. 两次 `ensure_world` 返回 `world_id` 相同；
  3. 播种幂等：连续两次 `seed_default_household` 后物品数不翻倍。

### ST-1.2 世界状态读取与调试总览

- **Scenario Name**：世界当前状态可被完整读出（供消费侧与观测面使用）
- **Preconditions**：`v23_world_simulation_enabled=true`；`U1` 已有世界
- **Input**：`GET /api/v1/debug/world/simulation`
- **Execution Flow**：
  1. `world_engine.build_debug_simulation("U1")` 装配；
  2. 依次取 `time_context` / `brief` / `current_block` / `active_situations` / `recent_events` / `flags` / `event_quota_drops`；
  3. 局部缺失时降级为字段 null/空，不整体失败。
- **Expected Result**：返回 200；`time_context` 含 `now` / `part_of_day`；`flags` 为 8 个 v23 开关当前值；`recent_events` 仅含模拟相关类型（`world_digest` / `time_marker` / `weather_change` / `calendar_event` / `life_event` / `world_event`）或 source 属于 `simulation`，上限 10 条。
- **Related Modules**：`world_engine.build_debug_simulation` / `v23_flag_snapshot`；`app/api/v1/world.py`；自动化对照 `test_ws018_debug_api.py`
- **Acceptance Criteria**：
  1. HTTP 200 且 JSON 含全部 7 个顶层字段；
  2. 世界不存在时返回 404；
  3. 总闸关时 `flags.v23_world_simulation_enabled == false`。

### ST-1.3 世界快照与快照恢复

- **Scenario Name**：世界可打快照并在变更后恢复
- **Preconditions**：`U1` 有活跃实体与事件
- **Input**：`POST /debug/world/snapshots` → 修改位置/天气 → `POST /debug/world/snapshots/{id}/restore`
- **Execution Flow**：
  1. `world_engine.snapshot("U1", label)` 落 `world_snapshots`；
  2. 通过 `set_location` / `set_environment` 改变世界；
  3. `restore_snapshot("U1", snapshot_id)` 恢复。
- **Expected Result**：恢复后 `worlds.current_location` / `environment` 回到快照时点；`world_entities` 与 `world_events` 状态与快照一致。
- **Related Modules**：`world_engine.snapshot` / `restore_snapshot`；`world_snapshots` 表
- **Acceptance Criteria**：
  1. 快照创建返回 snapshot_id；
  2. 恢复后关键字段与快照时刻一致；
  3. 恢复幂等（连续两次恢复结果相同）。

### ST-1.4 世界域写面边界（红线用例）

- **Scenario Name**：模拟全链路运行后，Character 域零新增（不变量 2）
- **Preconditions**：`v23_world_simulation_enabled` + `v23_time_advance_enabled` + `v23_event_detection_enabled` 全开
- **Input**：对同一 user 依次执行维护步 + 处境检出，对比前后 Character 域行数
- **Execution Flow**：
  1. 扫描 `character_state` / `personality_state` / `relationship_state` / `character_goals` 行数（before）；
  2. `world_engine.run_simulation_maintenance(U1)` + `user_situation.detect_from_message(U1, "我今天感冒了")`；
  3. 再次扫描（after）。
- **Expected Result**：`after == before`；世界侧只写 `worlds` / `world_entities` / `world_events` / `world_snapshots` / `daily_plans` / `user_situations`。
- **Related Modules**：自动化对照 `test_invariant_simulation_never_writes_character_domain`；architecture §9.3 不变量 2
- **Acceptance Criteria**：
  1. 四个 Character 域表行数增量为 0；
  2. 写域扫描零违规；
  3. 目标写入若发生，必须来自 `goal_service` 决策链路而非世界模拟路径。

---

## 2. Entity Simulation（实体模拟）

> 覆盖：角色（Character 实体，世界侧只读其事实）、物品（`world_entities` 状态机）、地点（`current_location` + LocationRegistry）、环境（`environment` weather/lighting）。本节的实体写操作全部发生在 V8 保留面，V2.3.0 只读其事实并间接触发（到期过期、位置迁移）。

### ST-2.1 地点实体：位置事实的读写

- **Scenario Name**：世界位置可显式设置并进入世界简报
- **Preconditions**：`v23_world_simulation_enabled=true`；LocationRegistry 含 `home.living_room` 等
- **Input**：`POST /debug/world/location {"location_id": "home.living_room"}`
- **Execution Flow**：
  1. `world_engine.set_location("U1", "home.living_room")`；
  2. 读 `GET /debug/world/simulation`；
  3. 检查 `brief.parts.place_line`。
- **Expected Result**：`worlds.current_location == "home.living_room"`；`brief` 的地点行含该地点的中文名。
- **Related Modules**：`world_engine.set_location`；`app/services/world/locations.py: location_name`；`world_brief._place_line`
- **Acceptance Criteria**：
  1. `current_location` 已更新；
  2. 简报地点行含地点中文名；
  3. 未知 location_id 被拒（不落非法事实）。

### ST-2.2 地点实体：运动裁决优先级

- **Scenario Name**：同一时段内「用户叙事迁移」优先于「日程推进迁移」
- **Preconditions**：`v23_daily_life_enabled=true`；当日计划含位置为 A 的块；当前 `part_of_day=P`
- **Input**：先发用户叙事「我在咖啡店」→ 触发一次块推进（目标位置 B）
- **Execution Flow**：
  1. 解释器 `_location_move` 命中 → `movement.apply(source=user_narrative)` 成功，落 `location_change` 事件（source=`user_mention`）；
  2. 同 part 内日程推进 `movement.apply(source=schedule)`；
  3. 读取 `MoveResult`。
- **Expected Result**：步骤 2 返回 `applied=False, skipped_reason="narrative_priority"`；`current_location` 保持用户叙事位置。
- **Related Modules**：`app/services/world/movement.py: apply / _narrative_move_in_current_part`；`app/services/world/interpreter.py: _location_move`
- **Acceptance Criteria**：
  1. 叙事迁移 `applied=True` 且事件 source=`user_mention`；
  2. 后续日程迁移 `skipped_reason=="narrative_priority"`；
  3. 跨 part 后日程迁移恢复生效。

### ST-2.3 物品实体：状态机合法迁移

- **Scenario Name**：物品按合法动作迁移状态，非法迁移不造事实
- **Preconditions**：`U1` 库存含可消耗物品 `O`（`quantity=3`）
- **Input**：`POST /debug/world/consume {"object_ref": "O", "quantity": 1}`
- **Execution Flow**：
  1. `consume_object(U1, "O", 1)` → 校验 `consumable` / 数量；
  2. 扣减 `quantity`，`last_action_at` 更新；
  3. `quantity==0` 时 `state="empty"`；对非活跃/不存在物品调用返回结构化错误。
- **Expected Result**：`ConsumeResult.ok=True`；`quantity` 由 3 → 2；再次消耗至 0 后 `state="empty"`；消耗超额返回 `INSUFFICIENT_QUANTITY` 且**不部分扣除**。
- **Related Modules**：`world_engine.consume_object / _find_inventory_object`；`OBJECT_STATE_MACHINES`；`app/api/v1/world.py`
- **Acceptance Criteria**：
  1. 合法消耗后数量精确递减；
  2. 超额消耗返回错误码且数量不变；
  3. 非 `consumable` 物品返回 `NOT_CONSUMABLE`。

### ST-2.4 物品实体：时间演化的到期过期

- **Scenario Name**：`expiry_at` 到期的活跃物品自动迁移为 expired（世界自主演化）
- **Preconditions**：`U1` 库存物品 `F` 的 `properties.expiry_at` 早于当前时点；状态机支持 `expire` 动作
- **Input**：`world_engine.expire_due_objects("U1", now)`
- **Execution Flow**：
  1. 遍历活跃物品取 `expiry_at`；
  2. `deadline <= now` 且状态机允许 `expire` → 迁移状态；
  3. 未到期/状态机不允许 → 跳过。
- **Expected Result**：返回过期条数 ≥1；`F.state` 迁移为状态机定义的过期态；重复调用幂等（不重复计数）。
- **Related Modules**：`world_engine.expire_due_objects`；`apply_machine_action(..., "expire")`
- **Acceptance Criteria**：
  1. 到期物品状态已迁移；
  2. 未到期物品不受影响；
  3. 二次调用过期条数为 0（幂等）。

### ST-2.5 环境实体：天气与光照落库

- **Scenario Name**：环境（weather/lighting）作为世界事实可读写并被简报消费
- **Preconditions**：`v23_world_simulation_enabled=true`
- **Input**：`POST /debug/world/environment {"weather": "rain"}`
- **Execution Flow**：
  1. `set_environment` 更新 `worlds.environment`；
  2. 组装简报；
  3. 读取 `brief.time_line`。
- **Expected Result**：`environment.weather == "rain"`；简报时间行追加中文天气（「雨天」）。
- **Related Modules**：`world_engine.set_environment`；`world_brief._time_line` / `WEATHER_CN`
- **Acceptance Criteria**：
  1. `environment` 落库正确；
  2. 简报时间行含对应中文天气词；
  3. 天气为空时不产生多余分隔符。

### ST-2.6 角色实体：世界只读角色事实（不写回）

- **Scenario Name**：角色状态由 Character 域权威维护，世界侧只作为输入信号消费
- **Preconditions**：`v23_world_simulation_enabled=true`；角色处于某情绪/关系状态
- **Input**：执行一轮对话（含世界上下文注入）后扫描写域
- **Execution Flow**：
  1. 记录角色状态快照；
  2. 完整走一轮前台链路（WorldBrief 入 prompt）；
  3. 复查角色状态写入来源。
- **Expected Result**：世界模拟路径未写入任何 `character_state`；角色状态若变化，写入源为既有状态服务。
- **Related Modules**：architecture §8.2（Emotion/Character State 行「永不改变」列）；自动化对照 `test_invariant_simulation_never_writes_character_domain`
- **Acceptance Criteria**：
  1. 世界侧调用链零 Character 域写；
  2. 角色状态变更可追溯到既有更新点。

---

## 3. Event System（事件系统）

> 覆盖：三源事件（用户/世界/角色）汇入唯一表 → 事件影响裁决 → 触发通道（到期/升级/闲置/记忆）→ 风暴防护。核心红线：唯一 SoT + 幂等 + 额度。

### ST-3.1 用户事件源：确定性处境检出

- **Scenario Name**：用户叙述触发处境落库 + 事件产生
- **Preconditions**：`v23_world_simulation_enabled=true` + `v23_event_detection_enabled=true`；`v23_world_llm_assist_enabled=false`
- **Input**：`user_situation.detect_from_message("U1", "我今天感冒了，头疼")`
- **Execution Flow**：
  1. `_match_dimension` 命中 HEALTH 模式（intensity_hint=4）；
  2. `_supersede_active` 处理同维度旧处境（转 expired）；
  3. `save_situation` 落 `user_situations`；
  4. `_emit_condition_event(kind="detected")` 落 `world_events`（type=`user_condition`，importance=high）。
- **Expected Result**：新增 1 条 `health` active 处境（intensity=4，source=`conversation_pattern`）；`world_events` 新增 `user_condition`（payload.kind=`detected`，dimension=`health`）；全程 0 LLM 调用。
- **Related Modules**：`app/services/world/user_situation.py`；`world_engine.create_event`；自动化对照 `test_ws009_situations.py`
- **Acceptance Criteria**：
  1. 处境 dimension/intensity 正确；
  2. 事件 type/payload 正确；
  3. `fake_llm.seen_messages == []`（0 LLM）。

### ST-3.2 用户事件源：处境消解与过期

- **Scenario Name**：处境可被用户声明消解，也可按有效期自动过期
- **Preconditions**：ST-3.1 已产生 active health 处境
- **Input**：① 发「我好了，没事了」；② 另造处境并设 `USER_SITUATION_VALID_HOURS=1` 后 tick
- **Execution Flow**：
  1. `dismiss_matching` 命中恢复词 → 处境转 `dismissed`，发 `user_condition`（kind=`ended`）；
  2. `expire_and_notify` 检查 `valid_until < now` → 转 `expired` 并发结束事件。
- **Expected Result**：① 原处境 `dismissed` + ended 事件；② 超期处境 `expired` + 结束事件；两种情况事件 importance=low。
- **Related Modules**：`user_situation.dismiss_matching / expire_and_notify / _match_dismissal`
- **Acceptance Criteria**：
  1. 状态迁移到 dismissed / expired；
  2. 分别产生 kind=ended 的事件；
  3. `active_situations` 不再返回已消解/过期处境。

### ST-3.3 世界事件源：日循环与天气事件

- **Scenario Name**：DayCycleEngine 与 WeatherEvolver 产生世界自主事件
- **Preconditions**：`v23_world_simulation_enabled=true` + `v23_time_advance_enabled=true`
- **Input**：冷启动一次 tick；再推进跨越 `day_start` 与 `part` 边界
- **Execution Flow**：
  1. `day_cycle.emit_time_markers` → 冷启动只发 `time:day_start:<date>`；
  2. 跨日 → `time:day_close:<prev>` + 新 `day_start`（+ 季节/节假日按需）；
  3. `weather.evolve_daily_weather` → 天气变化时落 `weather_change`。
- **Expected Result**：`world_events` 出现 `time_marker`（幂等键如 `time:day_start:2026-09-14`）；同日重复 tick 不重复落库；天气变化时出现 `weather_change` 且 `worlds.environment.weather` 同步更新。
- **Related Modules**：`app/services/world/day_cycle.py: compute_due_markers / emit_time_markers`；`app/services/world/weather.py: evolve_daily_weather`
- **Acceptance Criteria**：
  1. `day_start` 标记产生且幂等键唯一；
  2. 重复 tick 不产生重复事件；
  3. `weather_change` 与 `environment.weather` 一致。

### ST-3.4 角色事件源：目标完成与兴趣涌现桥接

- **Scenario Name**：角色域状态变更经 outbox 单向投递到世界事件表
- **Preconditions**：`v23_world_simulation_enabled=true` + `v23_event_detection_enabled=true`
- **Input**：① `register_goal_event(U1, G, "描述", "completed")`；② `on_insight_created` 投递 scope=self 且 confidence ≥ 0.7 的 insight
- **Execution Flow**：
  1. `_register_world_op` 经 `outbox_repository.insert` 登记（幂等键 `char:goal_done:<id>`）；
  2. outbox consumer 消费后落 `world_events`（`goal_completed` / `interest_emerged`）；
  3. 低于置信阈值的 insight 不投递。
- **Expected Result**：生成 `goal_completed`（outcome=completed，importance=normal）与 `interest_emerged` 事件；重复登记因幂等键被去重；世界不直写 `character_goals`。
- **Related Modules**：`app/services/world/event_bridge.py`；`outbox_repository`；自动化对照 `test_ws010_event_bridge.py`
- **Acceptance Criteria**：
  1. 事件落 `world_events` 且 type 正确；
  2. outbox 幂等键防重生效；
  3. 低置信 insight 不产生事件。

### ST-3.5 事件影响裁决（EventImpactRules）

- **Scenario Name**：事件被换算为统一影响包（urgency / care / topic / goal_opportunity）
- **Preconditions**：构造降温和用户处境两类事件
- **Input**：`event_impact.evaluate_batch(events, {"part_of_day": "evening"})`
- **Execution Flow**：
  1. `_base_rules` 按 type 出基础裁决；
  2. `late_night` 降级 urgency；有日程块时低优先级事件 topic 下调；
  3. 已存在同维度活跃处境时 `user_condition` urgency 降级；
  4. 按 urgency 降序排序。
- **Expected Result**：`weather_change(next=rain, changed=True)` → care=0.7、goal_opportunity.domain=`user_care`（remind_weather）；`user_condition(intensity=4)` → urgency=high、care=0.9；`time_marker` → 不产生 goal_opportunity。
- **Related Modules**：`app/services/world/event_impact.py`；自动化对照 `test_ws011_event_impact.py`、`test_flow_weather_drop_triggers_care_opportunity`
- **Acceptance Criteria**：
  1. 各事件类型的 urgency/care/topic 取值符合规则表；
  2. 上下文修饰（深夜/日程/活跃处境）生效；
  3. 返回列表按 urgency 降序。

### ST-3.6 事件触发通道：升级白名单

- **Scenario Name**：白名单内事件升级为完整 Run，白名单外不升级（0 LLM 预闸）
- **Preconditions**：`v23_world_simulation_enabled=true` + `v23_event_detection_enabled=true`
- **Input**：`evaluate_event_escalation("weather_change")` / `evaluate_event_escalation("time_marker")`
- **Execution Flow**：
  1. `escalation_whitelist()` 合并 v21 基础白名单与 v23 扩展（`user_condition,weather_change,calendar_event,goal_completed`）；
  2. `evaluate_event_escalation` 判定；
  3. 命中者经 outbox → `run_event_pregate` → event_driven Run。
- **Expected Result**：`weather_change` / `user_condition` / `calendar_event` / `goal_completed` 命中；`time_marker` / `world_digest` 不命中；总闸或 detection 关时白名单回落为 v21 基础集。
- **Related Modules**：`app/application/agent_runtime/trigger_router.py: escalation_whitelist / evaluate_event_escalation`
- **Acceptance Criteria**：
  1. 四个 v23 类型命中白名单；
  2. 白名单外类型不升级；
  3. Flag 关时白名单不含 v23 类型。

### ST-3.7 事件风暴防护与额度可观测

- **Scenario Name**：单 tick 事件数超上限时折叠为摘要，且丢弃量可观测
- **Preconditions**：`WORLD_EVENT_TICK_CAP=8`；`v23_world_simulation_enabled=true` + `v23_event_detection_enabled=true`
- **Input**：构造单 tick 产出 `cap + 5` 条低重要度事件草稿
- **Execution Flow**：
  1. `_rank_drafts` 按 `(-importance_index, idempotency_key)` 稳定排序；
  2. 超出 cap → 折叠为一条 `world_digest`（幂等键 `world_digest:<user>:<hash>`）；
  3. `create_event` 对非豁免类型做额度检查，丢弃计入 `event_quota_drop_snapshot`。
- **Expected Result**：落库事件总数 ≤ cap；存在 `world_digest`；`_QUOTA_EXEMPT_EVENT_TYPES`（`time_marker` / `calendar_event` / `world_digest` / `weather_change`）不被额度拦截；调试总览 `event_quota_drops` 反映丢弃计数与分类型明细。
- **Related Modules**：`world_engine._rank_drafts / _digest_idempotency_key / _emit_simulation_events / create_event / event_quota_drop_snapshot`；自动化对照 `test_invariant_event_storm_cap`、`test_ws020_review_fixes.py`
- **Acceptance Criteria**：
  1. 单 tick 事件总数 ≤ cap；
  2. `world_digest` 存在且幂等键确定；
  3. 豁免类型不被额度丢弃。

### ST-3.8 唯一 SoT 与幂等键唯一性

- **Scenario Name**：模拟事件全部落 `world_events`，幂等键无重复
- **Preconditions**：`v23_world_simulation_enabled=true` + `v23_event_detection_enabled=true`
- **Input**：执行维护步后全量扫描事件
- **Execution Flow**：
  1. `list_events(world_id)`；
  2. 提取所有非空 `idempotency_key`；
  3. 校验无第二事件存储。
- **Expected Result**：非空幂等键集合无重复；不存在 `world_events` 以外的事件持久化。
- **Related Modules**：`world_repository.list_events`；`0045` 部分唯一索引（`WHERE idempotency_key IS NOT NULL`）；自动化对照 `test_invariant_events_single_source_of_truth`
- **Acceptance Criteria**：
  1. 幂等键唯一；
  2. 无第二事件表；
  3. 重复 marker 尝试写入被唯一索引拒绝。

---

## 4. Time Simulation（时间模拟）

> 覆盖：三种 time_mode 推进语义 → 日循环标记 → 有界推进 → 长离线追赶 → 时间影响消费面。核心红线：确定性、可复现、有界。

### ST-4.1 simulated 模式增量推进与幂等锚点

- **Scenario Name**：模拟时间按真实流逝 × rate 前进，重复推进锚点条件写
- **Preconditions**：`WORLD_TIME_MODE=simulated`；`WORLD_SIM_RATE=60`；总闸 + `time_advance` 开
- **Input**：`time_advancer.advance_world_time("U1", now)`
- **Execution Flow**：
  1. `_advance_simulated` 计算增量，受 `sim_advance_max_minutes` 截断；
  2. `commit_time_advance` 条件写：新锚点 ≤ 当前锚点则拒绝（返回 False）；
  3. 返回 `TimeAdvanceResult`（含 advanced_minutes / truncated / mode）。
- **Expected Result**：`sim_time` 前进；`sim_last_advanced_at` 更新；锚点回退时推进被拒。
- **Related Modules**：`app/services/world/time_advancer.py`；`world_simulation_repository.commit_time_advance`；自动化对照 `test_ws003_time_advancer.py`、`test_ws020_review_fixes.py`
- **Acceptance Criteria**：
  1. `sim_time` / `sim_last_advanced_at` 前进；
  2. 非前进锚点被拒绝（不后退时间）；
  3. 单次跨度 ≤ 上限。

### ST-4.2 real_sync 模式不推进世界时钟

- **Scenario Name**：real_sync 模式只对齐锚点，不人为推进
- **Preconditions**：`WORLD_TIME_MODE=real_sync`；总闸 + `time_advance` 开
- **Input**：手动 tick
- **Execution Flow**：`advance_world_time` → real_sync 分支（`advanced_minutes == 0`）；`sim_last_advanced_at` 落锚。
- **Expected Result**：`sim_time` 不变；时间上下文与真实钟一致。
- **Related Modules**：`time_advancer`；`app/services/world/time_provider.py`
- **Acceptance Criteria**：
  1. `advanced_minutes == 0`；
  2. 时间上下文与系统钟一致。

### ST-4.3 日循环标记完整性

- **Scenario Name**：跨日/跨时段/跨周/季节更替产生对应标记，且冷启动只发 day_start
- **Preconditions**：总闸 + `time_advance` 开
- **Input**：依次推进跨越 day 边界、part 边界、周界
- **Execution Flow**：
  1. `compute_due_markers(prev, curr)` 纯函数比对；
  2. 冷启动（prev=None）仅 `day_start`；
  3. 跨日含 `day_close` + `day_start`（+季节/节假日）；
  4. 周界按 ISO 周变化发 `time:week:<year>-W<xx>`。
- **Expected Result**：各边界产生对应幂等键标记；同一日重复 tick 不重复。
- **Related Modules**：`app/services/world/day_cycle.py: compute_due_markers`；`app/character/asuna/calendar.py`
- **Acceptance Criteria**：
  1. 冷启动仅 day_start；
  2. 跨日产生 day_close + day_start；
  3. 周界/季节/节假日按条件产生。

### ST-4.4 时间推进有界（防补帧风暴）

- **Scenario Name**：长时间未推进时单次跨度被截断
- **Preconditions**：`WORLD_TIME_MODE=simulated`；`WORLD_SIM_RATE=120`；`sim_last_advanced_at` 落后 1 天
- **Input**：`advance_world_time(U1, now)`
- **Execution Flow**：计算增量 > 上限 → 截断至 `sim_advance_max_minutes`；`truncated=True`。
- **Expected Result**：`advanced_minutes <= sim_advance_max_minutes`；`truncated is True`。
- **Related Modules**：`time_advancer._advance_simulated`；自动化对照 `test_invariant_time_advance_bounded`
- **Acceptance Criteria**：
  1. 跨度不超上限；
  2. `truncated == True`；
  3. 世界时间单调不减。

### ST-4.5 长离线追赶（≤7 天）

- **Scenario Name**：离线 3 天回来自动逐日折叠补发 day_summary
- **Preconditions**：`CATCH_UP_MAX_DAYS=7`；`catch_up.run_catch_up` 可执行；世界最后覆盖日落后 3 天
- **Input**：触发 tick
- **Execution Flow**：
  1. `_latest_covered_day` 从 `time_marker` 幂等键解析最后覆盖日；
  2. `compute_catch_up_plan` → mode=`daily`，`missing_days` 为中间日；
  3. 逐日发 `time:day_summary:<date>`（importance=low），不重放 part 跃迁。
- **Expected Result**：`mode=="daily"`；`missing_days` 数量 = days_behind - 1；每日一条 day_summary 事件；今日边界交 DayCycleEngine 正常处理。
- **Related Modules**：`app/services/world/catch_up.py`；自动化对照 `test_ws017_catch_up.py`、`test_flow_long_offline_catch_up`
- **Acceptance Criteria**：
  1. 逐日 day_summary 且幂等；
  2. 不重放 part 标记；
  3. 重复 tick 不重复补发。

### ST-4.6 长离线追赶（>7 天）

- **Scenario Name**：离线 15 天折叠为单条 long_gap + 日程只生成今天
- **Preconditions**：`CATCH_UP_MAX_DAYS=7`；落后 15 天；`v23_daily_life_enabled=true`
- **Input**：触发 tick
- **Execution Flow**：
  1. `compute_catch_up_plan` → mode=`long_gap`，`gap_from=last_covered`，`gap_to=today`；
  2. 发单条 `time:long_gap:<from>:<to>`（kind=long_gap，days=N）；
  3. 天气按 N 天演化落终态；`daily_plans` 仅生成今日。
- **Expected Result**：`mode=="long_gap"`；`recent_events` 仅一条 long_gap；当日计划存在、历史计划不批量生成。
- **Related Modules**：`catch_up.run_catch_up`；`weather.evolve_daily_weather`；`daily_plan.ensure_day_plan`
- **Acceptance Criteria**：
  1. 仅一条 long_gap 事件；
  2. 天气演化至终态；
  3. `daily_plans` 仅有今日数据。

### ST-4.7 时间维度的消费面（Habit / Autonomy / Emotion）

- **Scenario Name**：时间事实作为输入信号被既有系统拉取消费
- **Preconditions**：总闸 + `time_advance` 开；`v23_habit_time_enabled` 视场景（RESERVED 见 §7 已知偏差）
- **Input**：构造深夜/晚间 TimeContext
- **Execution Flow**：
  1. `state_engine` 在既有 idle_recovery 点读 TimeContext；
  2. `autonomy` / `decision timing` 读 `part_of_day` + 日程块；
  3. habit 触发评估读取时间条件（当前 RESERVED，无行为分支）。
- **Expected Result**：世界只广播事实；消费侧新增输入不改变既有硬约束优先级。
- **Related Modules**：architecture §5.2「影响通道」；§8.2 逐系统契约表
- **Acceptance Criteria**：
  1. 世界侧无直接写 Consumption 域；
  2. 消费为读路径；
  3. Flag off 时消费面与 V2.2.0 一致。

---

## 5. Agent Interaction（Agent 交互全链）

> 覆盖用户给定的主链路：**User Input → Agent Decision → World Change → Event Trigger → Memory Update → Response**。分正向（前台对话）与反向（世界事件驱动主动行为）两条。

### ST-5.1 主链路：用户输入驱动的世界变更与记忆沉淀

- **Scenario Name**：一轮对话完成「输入 → 世界更新 → 事件 → 响应 → 记忆候选」
- **Preconditions**：`v23_world_simulation_enabled=true`；`v23_event_detection_enabled=true`
- **Input**：发消息「我在咖啡店，顺便买了杯咖啡」
- **Execution Flow**：
  1. 解释器 `interpret` → `_location_move` 命中 → 位置迁移 + `location_change` 事件；`_object_lines` 处理物品语义；
  2. `run_turn_update` 应用世界更新；
  3. `build_context` → WorldBrief 注入 prompt（world_ctx 段）；
  4. answer_chain 生成回复；
  5. `post_process` 第 8 步 world_update + UserSituationTracker 处境检出；
  6. 显著事件经 `memory_bridge` 单向投递记忆候选。
- **Expected Result**：`current_location` 更新；产生 `location_change`（source=`user_mention`）；回复基于含世界简报的上下文；重要事件进入记忆候选（低重要度被评估器过滤）。
- **Related Modules**：`app/application/world_engine.py: run_turn_update / build_context / collect_facts`；`app/services/world/interpreter.py`；`app/services/world/memory_bridge.py`
- **Acceptance Criteria**：
  1. 位置世界事实已更新；
  2. `location_change` 事件产生；
  3. 记忆候选投递走既有单向通道；
  4. 回复链路 0 中断（异常均降级）。

### ST-5.2 主链路：WorldBrief 入 prompt 与预算

- **Scenario Name**：世界简报进入 prompt 且受预算约束
- **Preconditions**：`v23_world_simulation_enabled=true`
- **Input**：发一轮对话，抓 `runtime_traces` 的 `world_context` 步骤
- **Execution Flow**：
  1. `build_world_brief` 装配 time/place/situations/events 行；
  2. 超预算时按序裁剪（先 events_line，再 situations_line，最后硬截断）；
  3. `render_world_section(context, budget=1000, brief)` 注入。
- **Expected Result**：`【当前世界】` 段含 brief 行；`len(brief.text) ≤ world_brief_char_budget(400)`；总世界段预算 `world_context_char_budget_v23=1000`；总闸关时无 brief 段、预算回落 600。
- **Related Modules**：`app/services/world/world_brief.py`；`app/services/world/context_selector.py: render_world_section`；自动化对照 `test_flow_foreground_brief_assembly`、`test_prompt_world_section_identical_when_brief_absent`
- **Acceptance Criteria**：
  1. brief 段进入 prompt；
  2. `brief.text` 长度 ≤ 400；
  3. 总闸关时与基线逐字节一致。

### ST-5.3 主链路：世界事件驱动的主动行为

- **Scenario Name**：降温事件触发 Autonomy → Goal → Action 全链（架构 §7.2 主链）
- **Preconditions**：全开（含 `daily_life` / `event_detection`）；处于 evening 在家
- **Input**：产生 `weather_change`（next=rain，changed=true）
- **Execution Flow**：
  1. `EventImpactRules` → care=0.7 + goal_opportunity(`user_care`/`remind_weather`)；
  2. escalation 白名单命中 → outbox → event_driven Run；
  3. Decision Pipeline 产出 `world_affordance` 候选；
  4. Goal 层写 L1 `origin=world_event`（由 goal_service 写，非世界直写）；
  5. `proactive_executor` 两阶段投递主动消息。
- **Expected Result**：决策候选含保暖关怀项；`character_goals` 中 `origin=world_event` 的目标（经 goal_service）；主动消息投递。
- **Related Modules**：`event_impact`；`trigger_router.escalation_whitelist`；architecture §7.2
- **Acceptance Criteria**：
  1. impact 包字段正确；
  2. 目标经决策链路写入且 `origin=world_event`；
  3. 世界侧零直写 goals。

### ST-5.4 情境：场景塑造表达风格

- **Scenario Name**：同人格在「咖啡店」与「深夜卧室」的表达可区分，但不越硬约束
- **Preconditions**：总闸开；`v23_scene_expansion_enabled` 视场景（RESERVED 见 §7）
- **Input**：分别在两个场景对话
- **Execution Flow**：
  1. 场景档插入 StyleContract（关系档之后、人格之前）；
  2. `behavior_engine` 读 `topic_affordances`；
  3. StyleContract `forbidden` / `principles` 仍由 Persona 产生。
- **Expected Result**：场景 `tone_bias` / 话题面产生可观察差异；`forbidden` / `principles` 与 Persona 一致。
- **Related Modules**：`app/services/experience/style_assembler.py`；自动化对照 `test_invariant_brief_and_style_do_not_add_hard_constraints`
- **Acceptance Criteria**：
  1. 场景输入可观察；
  2. 硬约束产生权不变；
  3. Flag off 恢复 V2.2 四路原序。

### ST-5.5 情境：稀缺资源消耗的一致性

- **Scenario Name**：用户请求消耗物品时，世界事实与回复一致
- **Preconditions**：`U1` 库存含物品 `O`（可消耗），上下文含该物品
- **Input**：发「再给我一杯咖啡」
- **Execution Flow**：
  1. 解释器/动作面解析消耗意图；
  2. `consume_object` 扣减数量（超额则返回错误码，不部分扣除）；
  3. 回复基于消耗结果。
- **Expected Result**：消耗成功时数量精确递减；库存不足时返回 `INSUFFICIENT_QUANTITY` 且世界不变，回复不谎报。
- **Related Modules**：`world_engine.consume_object`；`app/services/world/interpreter.py: _object_lines`
- **Acceptance Criteria**：
  1. 世界事实与回复一致；
  2. 失败不产生部分扣除；
  3. 库存归零时 `state="empty"`。

### ST-5.6 情境：世界事件触发记忆更新（分层）

- **Scenario Name**：短期入 prompt、中期入记忆、长期入 Insight 的三层分流
- **Preconditions**：总闸开；具备记忆与反思链路
- **Input**：制造天气/日程/处境事件序列
- **Execution Flow**：
  1. 短期（今天天气/当前块/处境）→ 只进 WorldBrief，不落 memories；
  2. 中期（重要活动）→ memory_bridge 单向投递记忆候选（幂等 materialized）；
  3. 长期 → 世界事件摘要作反思证据，经三道闸固化为 Insight；
  4. 处境类结束后若重要 → 转事件走中期路径。
- **Expected Result**：低重要度事件被评估器过滤；重要事件可溯源到 `world_events`；短期内容不进 `memories`。
- **Related Modules**：architecture §8.3；`app/services/world/memory_bridge.py`
- **Acceptance Criteria**：
  1. 三层分流符合表；
  2. 溯源链完整；
  3. 短期内容不污染 memories。

---

## 6. Multi-step Scenario（多步综合场景）

> 三条端到端用户故事，每条跨多个组件，验证「世界自主运行 + 用户交互 + 消费面」的联合行为。执行方式：Flag 按用例声明开启，用 `WORLD_TIME_MODE=simulated` + 手动 tick 精确控制时序。

### ST-6.1 多步场景一：用户回家

- **Scenario Name**：用户离家—在外面—回家，世界位置、日程与简报连续一致
- **Preconditions**：`v23_world_simulation_enabled` + `v23_time_advance_enabled` + `v23_daily_life_enabled` 开；用户初始在家
- **Input**：
  1. 用户发「我出门了，去公司」；
  2. 推进时间跨越一个 part 边界（世界日程推进）；
  3. 用户发「我到家了」。
- **Execution Flow**：
  1. 步骤 1：解释器 `_location_move` 命中 → `movement.apply(user_narrative)` → `current_location` 变为公司 + `location_change`（source=`user_mention`）；
  2. 步骤 2：`advance_daily_plan` 块切换 → 日程目标位置与叙事优先级仲裁（同 part 内 `narrative_priority` 跳过，跨 part 生效）；
  3. 步骤 3：`movement.apply(user_narrative)` → 回家 + `location_change`；
  4. 每步后读 `/debug/world/simulation` 的 `brief.place_line`。
- **Expected Result**：位置按用户叙事迁移；日程迁移不与叙事冲突（被仲裁）；简报地点行每步与世界位置一致；每次成功迁移有 `location_change` 事件且幂等键 `location:<date>:<part>:<target>` 唯一。
- **Related Modules**：`interpreter._location_move`；`movement.apply`；`daily_plan.advance_daily_plan`；`world_brief._place_line`
- **Acceptance Criteria**：
  1. 三次位置变化均落世界事实与事件；
  2. 同 part 内叙事优先生效（`narrative_priority`）；
  3. 简报与库中位置一致；
  4. 跨 part 后日程迁移恢复。

### ST-6.2 多步场景二：物品消耗

- **Scenario Name**：从库存充足到耗尽，世界事实、事件与回复全程一致
- **Preconditions**：`v23_world_simulation_enabled` 开；库存含可消耗物品 `O`（`quantity` 可配，如 2）；可配 `expiry_at` 制造过期场景
- **Input**：
  1. 消耗 1 份（正常）；
  2. 再消耗 1 份（耗尽）；
  3. 继续请求消耗（库存不足）；
  4. 另备到期物品，tick 一次触发过期。
- **Execution Flow**：
  1. `consume_object` 两次递减 → 第二次后 `quantity==0`、`state="empty"`；
  2. 再次消耗 → 返回 `INSUFFICIENT_QUANTITY`，扣减中止（事务边界内无部分扣除）；
  3. `expire_due_objects` 将到期物品迁移到 expired；
  4. 各步读库断言数量/状态。
- **Expected Result**：数量单调递减至 0；超额不扣减；到期物品自动过期；回复与事实一致。
- **Related Modules**：`world_engine.consume_object / expire_due_objects / get_available_consumables`
- **Acceptance Criteria**：
  1. 数量精确递减；
  2. 超额失败且无部分扣除；
  3. 归零 `state="empty"` 且 `get_available_consumables` 不再返回；
  4. 到期过期幂等。

### ST-6.3 多步场景三：关系变化

- **Scenario Name**：共同活动 + 处境关怀推动关系证据沉淀（关系状态由关系域权威写）
- **Preconditions**：`v23_world_simulation_enabled` + `v23_time_advance_enabled` + `v23_daily_life_enabled` + `v23_event_detection_enabled` 开
- **Input**：
  1. 用户发「我今天加班到很晚，好累」→ 处境检出；
  2. 推进至角色晚间日程块（如居家陪伴）完成；
  3. 触发降温事件；
  4. 用户发「谢谢你陪我」。
- **Execution Flow**：
  1. 处境检出 → `user_situations`(work_pressure) + `user_condition` 事件；
  2. 日程块完成 → `life_event(activity_done)` → 经 memory_bridge 成为共同活动记忆候选；
  3. `weather_change` → EventImpactRules → `world_affordance` 候选（关怀）；
  4. 上述世界事实经既有 relationship narrative listener / milestone 评估作为**证据**被消费。
- **Expected Result**：World 侧只产生事实与事件；`relationship_state` / `relationship_milestones` 若变化，写入由既有关系链路完成；证据可溯源到 `world_events`。
- **Related Modules**：`user_situation`；`daily_plan.advance_daily_plan`；`event_impact`；architecture §8.2（Relationship 行）
- **Acceptance Criteria**：
  1. 处境/事件产生正确；
  2. 共同活动事件进入记忆候选；
  3. 关系域变更经既有链路（世界零直写 `relationship_*`）；
  4. 关系证据可追溯。

### ST-6.4 综合韧性：多场景并发下的有序与幂等

- **Scenario Name**：同一用户连续多 tick，多源事件共存时无重复、无越界、顺序稳定
- **Preconditions**：全开；`WORLD_EVENT_TICK_CAP=8`
- **Input**：连续手动 tick 5 次，期间夹杂一次用户消息
- **Execution Flow**：
  1. 每 tick 走 `run_simulation_maintenance`（子步骤顺序固定不可换）；
  2. catch_up → day_cycle → weather → 处境过期 → daily_life；
  3. 每 tick 后全量扫描幂等键与写域。
- **Expected Result**：幂等键无重复；事件总数每 tick ≤ cap；Character 域零新增；子步骤顺序不变。
- **Related Modules**：`world_engine._run_simulation_substeps`（含顺序纪律 docstring）；不变量 1/2/7
- **Acceptance Criteria**：
  1. 5 tick 后幂等键唯一；
  2. 每 tick 事件数 ≤ cap；
  3. 写域零违规；
  4. 子步骤顺序与定义一致。

---

## 7. 边界不变量验收矩阵（§9.3 八条）

> 场景层对八条红线的覆盖映射；每条在自动化（`test_ws019_acceptance.py`）与场景（本文件）两侧均有落点。

| # | 不变量 | 场景落点 | 自动化落点 | 判定 |
|---|---|---|---|---|
| 1 | 事件唯一 SoT = `world_events` | ST-3.8, ST-6.4 | `test_invariant_events_single_source_of_truth` | ☐ |
| 2 | 世界写面受限（不写 Character 域） | ST-1.4, ST-2.6, ST-6.3 | `test_invariant_simulation_never_writes_character_domain` | ☐ |
| 3 | 默认路径 0 LLM | ST-3.1, ST-5.1 | `test_invariant_zero_llm_on_deterministic_path` | ☐ |
| 4 | 随机性可复现（显式种子） | ST-6.1（同日重建计划） | `test_invariant_seeded_randomness_reproducible` | ☐ |
| 5 | `scene_state`(V3) 语义零改动 | ST-5.4 | —（diff 对照） | ☐ |
| 6 | Flag 全 off 逐字节一致 | ST-5.2, ST-6.4 | `test_flags_off_*` / `test_prompt_world_section_identical_when_brief_absent` | ☐ |
| 7 | 有界：时间跨度 / 事件上限 / 追赶折叠 | ST-3.7, ST-4.4, ST-4.5, ST-4.6 | `test_invariant_time_advance_bounded` / `test_invariant_event_storm_cap` | ☐ |
| 8 | WorldBrief/场景档只增输入 | ST-5.4 | `test_invariant_brief_and_style_do_not_add_hard_constraints` | ☐ |

---

## 8. 已知偏差与验收口径

> 以下为**已实现范围内的既有状态**，非测试缺陷；场景执行时按此口径判定，避免误报。

| # | 状态 | 说明 | 影响用例 |
|---|---|---|---|
| D1 | `v23_scene_expansion_enabled` / `v23_habit_time_enabled` 为 **RESERVED** | 已定义并纳入总闸校验，但当前无行为分支（SceneProfile 资产就绪未接线）。开启不产生行为变化，启动时经 `enablement.v23_reserved_flag_warnings` 告警 | ST-4.7、ST-5.4 场景档/习惯时间项判定为「无行为变化」而非 FAIL |
| D2 | WS-016 部分完成 | 场景分层（Style/Emotion/Habit 世界信号）未全量接入；见 `tasks/README.md` 状态列 | ST-4.7、ST-5.4 |
| D3 | 位置自主迁移不在本版 | 位置变化仅来自节律与叙事；V9 move 类自主动作列为 Non-Goal | ST-2.2、ST-6.1 |

---

## 9. 执行方式与结果记录

### 9.1 执行顺序建议

1. **环境组**（ST-1.x）→ 确立世界基座与写面边界；
2. **实体组**（ST-2.x）→ 确立实体状态机与位置裁决；
3. **事件组**（ST-3.x）→ 确立三源汇流与触发通道；
4. **时间组**（ST-4.x）→ 确立节律与追赶；
5. **交互组**（ST-5.x）→ 确立全链消费；
6. **综合组**（ST-6.x）→ 端到端用户故事；
7. **不变量矩阵**（§7）→ 红线终检。

### 9.2 场景执行记录

> 执行人：____　执行日期：____　代码版本：____　模型：____　环境：____

| 段 | 用例 | 结果 | 证据（端点 JSON / trace / SQL） |
|---|---|---|---|
| ST-1 World Lifecycle | ST-1.1 ~ ST-1.4 | ☐ PASS ☐ FAIL | |
| ST-2 Entity Simulation | ST-2.1 ~ ST-2.6 | ☐ PASS ☐ FAIL | |
| ST-3 Event System | ST-3.1 ~ ST-3.8 | ☐ PASS ☐ FAIL | |
| ST-4 Time Simulation | ST-4.1 ~ ST-4.7 | ☐ PASS ☐ FAIL | |
| ST-5 Agent Interaction | ST-5.1 ~ ST-5.6 | ☐ PASS ☐ FAIL | |
| ST-6 Multi-step Scenario | ST-6.1 ~ ST-6.4 | ☐ PASS ☐ FAIL | |
| §7 边界不变量 | 八条 | ☐ PASS ☐ FAIL | |
| §8 已知偏差口径 | D1 ~ D3 | ☐ 符合 ☐ 偏差 | |

**场景验收结论**：☐ ACCEPTED　☐ REJECTED（原因：____）

---

## 附：场景 → 组件 → 自动化 对照索引

| 场景段 | 主要组件 | 主责 Task | 自动化对照 |
|---|---|---|---|
| ST-1 World Lifecycle | `world_engine`、`world_repository`、`world_snapshots` | WS-002 / WS-018 | `test_ws002_models.py`、`test_ws018_debug_api.py` |
| ST-2 Entity Simulation | `world_entities` 状态机、`movement`、`set_location` | WS-006 / WS-008 | `test_ws006_scene_assets.py`、`test_ws008_plan_runner.py` |
| ST-3 Event System | `user_situation`、`event_bridge`、`event_impact`、`trigger_router` | WS-009~011 / WS-013 | `test_ws009_situations.py`、`test_ws010_event_bridge.py`、`test_ws011_event_impact.py`、`test_ws013_ws014_autonomy.py` |
| ST-4 Time Simulation | `time_advancer`、`day_cycle`、`weather`、`catch_up` | WS-003~005 / WS-017 | `test_ws003_time_advancer.py`、`test_ws004_day_cycle.py`、`test_ws005_weather.py`、`test_ws017_catch_up.py` |
| ST-5 Agent Interaction | `world_brief`、`context_selector`、`memory_bridge`、`style_assembler` | WS-012 / WS-015 / WS-016 | `test_ws012_world_brief.py`、`test_ws019_acceptance.py` |
| ST-6 Multi-step | 全组件联合 | WS-019 | `test_ws019_acceptance.py`（四全链路） |
| 补丁回归 | 复审修复面 | WS-020 | `test_ws020_review_fixes.py` |
