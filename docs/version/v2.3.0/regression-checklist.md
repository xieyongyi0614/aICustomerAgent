# V2.3.0 World Simulation System 人工回归清单

> 上游：[architecture.md](./architecture.md) §7（运行链路）、§9.3（边界不变量）、§8.4（Flag 启用链）
> 用途：真实模型环境下的人工验收执行单；每条含 **前置 / 操作 / 期望 / 观测点**。
> 状态：待执行（执行结论回写本文件末尾「执行记录」区）。
> 配套自动化：`apps/backend/tests/v23/test_ws019_acceptance.py`（CI 可跑部分）。

---

## 1. 环境准备

| 项 | 说明 |
|---|---|
| Flag 默认态 | 全部 v23 Flag 默认 off；回归时按 **§8.4 启用链** 逐组开启，每组观察后再开下一组 |
| 启用顺序 | `v23_world_simulation_enabled`（总闸）→ `v23_time_advance_enabled` → `v23_daily_life_enabled` → `v23_event_detection_enabled` → `v23_scene_expansion_enabled` / `v23_habit_time_enabled` → `v23_world_llm_assist_enabled` |
| 调试面板 | 前端调试控制台 **World** Tab（WS-018）必须可用；总闸关时显示「世界模拟未启用」空态 |
| 时钟控制 | `WORLD_TIME_MODE=simulated` + `WORLD_SIM_RATE` 控制推进倍率；`V23_DEBUG_TICK_ENABLED=true` 时面板「手动 tick」按钮可用，可单步推进 |
| 调试端点 | `GET /api/v1/debug/world/simulation`、`/plan`、`/situations`；`POST /debug/world/simulation/tick` |
| 观测三件套 | ① 调试端点 JSON ② prompt trace（`runtime_traces` 的 `world_context` 步骤）③ 库断言（下节 SQL） |

库断言速查（SQLite/PG 通用）：

```sql
-- 计划块状态
SELECT seq, part_of_day, activity, location_id, status FROM daily_plans
 WHERE user_id=:u AND plan_date=:d ORDER BY seq;
-- 活跃处境
SELECT dimension, summary, intensity, status, source, valid_until FROM user_situations
 WHERE user_id=:u ORDER BY detected_at DESC;
-- 模拟事件（唯一 SoT）
SELECT type, title, source, status, idempotency_key FROM world_events
 WHERE world_id=:w ORDER BY created_at DESC LIMIT 30;
```

---

## 2. 节律组（时间 / 天气 / 日循环）

### R-2.1 simulated 模式时间推进
- **前置**：总闸 + `time_advance` 开；`WORLD_TIME_MODE=simulated`，`WORLD_SIM_RATE=60`。
- **操作**：等待 ≥1 个 `world_sim_interval_seconds`（默认 60s），或点「手动 tick」。
- **期望**：`worlds.sim_time` 按真实流逝 × rate 前进；`sim_last_advanced_at` 更新；单次跨度不超过 `sim_advance_max_minutes`。
- **观测点**：调试端点 `time_context.now`；`worlds.sim_time` / `sim_last_advanced_at`。

### R-2.2 冷却锚点对齐（real_sync）
- **前置**：`WORLD_TIME_MODE=real_sync`。
- **操作**：手动 tick 一次。
- **期望**：`sim_time` 不被人为推进，仅 `sim_last_advanced_at` 落锚；时间上下文与真实钟一致。
- **观测点**：`time_context`；`advanced_minutes == 0`（tick 结果）。

### R-2.3 日循环标记
- **前置**：总闸 + `time_advance`；跨过一次 `day_start`（或用调试时钟）。
- **操作**：触发 tick。
- **期望**：`world_events` 出现 `time_marker`（`time:day_start:<date>`）；同一日重复 tick 不重复落库（幂等键去重）。
- **观测点**：`/debug/world/simulation` 的 `recent_events`；库断言 `idempotency_key` 唯一。

### R-2.4 时段跃迁与天气演化
- **前置**：总闸 + `time_advance`；跨过一次 `part` 边界。
- **操作**：推进时钟跨越 morning→noon。
- **期望**：出现 `time:part:<date>:<part>` 标记；当日天气按季节转移表演化，出现 `weather_change` 事件（若变化）。
- **观测点**：`recent_events` 中 `time_marker` / `weather_change`；`worlds.environment.weather`。

### R-2.5 跨日与周界
- **操作**：推进跨越一个自然日；再推进至周一。
- **期望**：出现 `day_close`；周一出现周界标记；`daily_plans` 换代。
- **观测点**：`recent_events`；`daily_plans` 按 `plan_date` 分区。

---

## 3. 生活组（日程 / 位置）

### R-3.1 当日计划生成
- **前置**：总闸 + `time_advance` + `daily_life`；清空当日 `daily_plans`。
- **操作**：触发 tick。
- **期望**：按 `ROUTINE_ASSET` 生成当日块（`seq` 连续、时段/时间窗/location 合法）；变化源标注 `fixed` / `variant` / `user_influenced`。
- **观测点**：`/debug/world/plan`；库断言 `daily_plans`。

### R-3.2 计划块推进与状态机
- **操作**：跨过块边界。
- **期望**：上一块 `active→completed` 并发 `life_event`（`activity_done`）；下一块 `planned→active`；`superseded` 仅在同一日重建时出现。
- **观测点**：`/plan` 的 `status` 色标；`recent_events` 的 `life_event`。

### R-3.3 位置迁移
- **操作**：推进至块切换。
- **期望**：`worlds.current_location` 更新为当前块 `location_id`；出现 `life_event`（`location_change`）。
- **观测点**：`/simulation` 的 `time_context` + 世界位置；`recent_events`。

### R-3.4 用户影响绑定
- **前置**：先制造一条活跃处境（如「生病」）。
- **操作**：重建当日计划。
- **期望**：受处境影响的块标注 `variability_source=user_influenced`；计划与处境一致，不出现冲突。
- **观测点**：`/plan` 的 `variability_source`；`/situations`。

---

## 4. 事件组（处境 / 桥接 / 升级 / 提醒）

### R-4.1 确定性处境检出
- **前置**：总闸 + `event_detection`。
- **操作**：发消息「我今天感冒了，头疼」。
- **期望**：`user_situations` 新增 `health` active 处境（intensity 4）；`world_events` 出现 `user_condition`（kind=detected）。
- **观测点**：`/situations`；库断言。

### R-4.2 处境消解
- **操作**：发消息「我好了，没事了」。
- **期望**：原处境转 `dismissed`；出现 `user_condition`（kind=ended）。
- **观测点**：`/situations?include_expired=true`；`recent_events`。

### R-4.3 处境过期
- **前置**：`USER_SITUATION_VALID_HOURS` 调小（如 1）。
- **操作**：过有效期后 tick。
- **期望**：处境转 `expired` 并发结束事件。
- **观测点**：同 R-4.2。

### R-4.4 LLM 辅助检出
- **前置**：总闸 + `event_detection` + `llm_assist`；`V23_LLM_ASSIST_SAMPLE_RATE=1.0`。
- **操作**：发一条确定性规则不命中的隐含处境消息（如「明天要交的活儿还没动」）。
- **期望**：可能新增处境，`source=llm_assist`；LLM 失败时静默降级、不影响回复。
- **观测点**：`/situations` 的 `source`；trace 中仍 0 中断。

### R-4.5 目标完成桥
- **操作**：让某个角色目标达成（经决策/目标链路）。
- **期望**：出现 `goal_completed` 事件（非世界直写 `character_goals`）。
- **观测点**：`recent_events`；`character_goals` 写路径仍由 goal_service 负责。

### R-4.6 Escalation 升级白名单
- **前置**：总闸 + `event_detection`。
- **操作**：产出 `user_condition` / `weather_change` / `calendar_event` 事件。
- **期望**：命中白名单 → 升级为完整 Run；白名单外事件不升级（预闸 0 LLM）。
- **观测点**：`loop_runs` / outbox 投递；`escalation_whitelist()` 返回值。

### R-4.7 主动提醒全链（World → Event → Autonomy → Goal → Action）
- **前置**：全开（含 `daily_life` / `event_detection`）。
- **操作**：制造降温（`weather_change`，`next=rain`，`changed=true`），进入合适的时段（如 evening 在家）。
- **期望**：EventImpactRules 给出 `care_relevance≥0.7` + `goal_opportunity(user_care/remind_weather)`；决策管线产出 `world_affordance` 候选；目标层写 L1 `origin=world_event`；主动消息两阶段投递。
- **观测点**：`collect_facts` 的 `impacts`；trace 决策候选；`character_goals`（`origin=world_event`）；投递记录。

---

## 5. 消费组（prompt / 风格 / 习惯 / 记忆）

### R-5.1 WorldBrief 入 prompt
- **前置**：总闸开。
- **操作**：发一轮对话，抓 prompt。
- **期望**：`【当前世界】` 段含 brief 行（时间/地点/处境/事件），预算 `world_brief_char_budget=400` 内；与 `/simulation` 的 `brief.text` 同源。
- **观测点**：`runtime_traces.world_context` 步骤的 prompt 快照；`/simulation`。

### R-5.2 预算提升（场景档）
- **前置**：`v23_world_simulation_enabled` 开。
- **期望**：world 上下文预算由 600 提升至 `world_context_char_budget_v23=1000`；总闸关时回到 600 且无 brief 段。
- **观测点**：prompt 段长度对比。

### R-5.3 场景风格差异
- **前置**：`scene_expansion` 开。
- **操作**：分别在「家/客厅」「安静书房」等场景对话。
- **期望**：场景 `tone_bias` / `topic_affordances` 影响表达与话题面；**不改变** StyleContract 硬约束优先级。
- **观测点**：风格段；`forbidden` / `principles` 与 Persona 一致。

### R-5.4 习惯时间命中
- **前置**：`habit_time` 开。
- **操作**：在 sleep/meal 等时间窗内触发对应习惯场景。
- **期望**：时间维度习惯被命中（0 LLM 规则匹配）；上限仍 `HABIT_MAX_COUNT=2`。
- **观测点**：风格段 `习惯：...` 行。

### R-5.5 记忆沉淀与反思证据
- **前置**：总闸开。
- **操作**：让模拟事件（处境/天气/日程）落库，走记忆桥。
- **期望**：低重要度事件被评估器自然过滤，世界连续但记忆不被噪声淹没；反思证据可追溯到 `world_events`。
- **观测点**：记忆候选 / 反思记录；溯源链。

---

## 6. 韧性组（追赶 / 风暴 / 回退）

### R-6.1 长离线追赶（≤7 天）
- **前置**：总闸 + `daily_life`；模拟时钟落后 3 天。
- **操作**：触发 tick。
- **期望**：逐日折叠 `day_summary`（`time:day_summary:<date>`），不重放每个 part 跃迁；今日边界正常处理。
- **观测点**：`recent_events`；库断言幂等键。

### R-6.2 长离线追赶（>7 天）
- **前置**：`CATCH_UP_MAX_DAYS=7`；模拟时钟落后 15 天。
- **操作**：触发 tick。
- **期望**：折叠为单条 `time:long_gap:<from>:<to>`；天气按 N 天演化落终态；日程只生成今天。
- **观测点**：`/simulation` 的 `recent_events`；`/plan` 仅今日。

### R-6.3 事件风暴防护
- **前置**：`WORLD_EVENT_TICK_CAP=8`。
- **操作**：构造单 tick 产出 >cap 条事件。
- **期望**：保留高重要度前 cap-1 条，其余折叠为一条 `world_digest`；单 tick 事件总数 ≤ cap。
- **观测点**：`recent_events` 数量与 `world_digest`。

### R-6.4 Flag 逐闸回退
- **操作**：从全开逐级关闭子闸，每关一档观察。
- **期望**：关到「总闸 off」时，prompt / 维护步序列 / 事件产出与 **V2.2.0 基线逐字节一致**；调试端点返回 `{"enabled": false}`。
- **观测点**：prompt 快照 diff 为空；`loop_runs` 步骤序列；`/simulation`。

### R-6.5 迁移可逆放
- **操作**：`alembic downgrade 0043` → `upgrade head`。
- **期望**：0044/0045 双向通过，无残留表/列。
- **观测点**：`alembic current`；`daily_plans` / `user_situations` 存在性。

---

## 7. 边界不变量核查（§9.3 八条）

| # | 不变量 | 核查方式 | 期望 |
|---|---|---|---|
| 1 | 事件唯一 SoT = `world_events` | 全局搜索事件表；库断言 | 无第二事件存储 |
| 2 | 世界写面受限 | 写域扫描（模拟路径对 `character_state` / `personality_state` / `relationship_*` / `character_goals` 零直写） | 扫描零违规 |
| 3 | 默认路径 0 LLM | 关闭 `llm_assist`，观察 LLM 调用记录 | 模拟路径调用数 = 0 |
| 4 | 随机性可复现 | 同日重建计划两次 | 结果一致（显式种子） |
| 5 | `scene_state`(V3) 语义零改动 | diff / 行为对照 | 读写语义不变 |
| 6 | Flag 全 off 逐字节一致 | prompt 快照 / `loop_runs` 序列 diff | diff 为空 |
| 7 | 有界：时间跨度上限 / 单 tick 事件上限 / 长离线折叠 | R-2.1 / R-6.2 / R-6.3 | 均生效 |
| 8 | WorldBrief/场景档只增输入 | StyleContract `forbidden` / `principles` 对照 | 产生权不变 |

---

## 8. 性能预算

| 项 | 预算 | 实测 | 结论 |
|---|---|---|---|
| 维护步单 tick DB 查询数与耗时 | 记录留数据（不设硬阈值） | 待填 | 待填 |
| 前台 snapshot 耗时 | ≤150ms（既有预算，不劣化） | 待填 | 待填 |

---

## 执行记录

> 执行人：____　执行日期：____　代码版本：____

| 组 | 用例 | 结果 | 备注 / 证据 |
|---|---|---|---|
| 节律 | R-2.1~2.5 | ☐ PASS ☐ FAIL | |
| 生活 | R-3.1~3.4 | ☐ PASS ☐ FAIL | |
| 事件 | R-4.1~4.7 | ☐ PASS ☐ FAIL | |
| 消费 | R-5.1~5.5 | ☐ PASS ☐ FAIL | |
| 韧性 | R-6.1~6.5 | ☐ PASS ☐ FAIL | |
| 不变量 | §7 八条 | ☐ PASS ☐ FAIL | |
| 性能 | §8 | ☐ PASS ☐ FAIL | |

**发布结论**：☐ READY FOR RELEASE　☐ BLOCKED（原因：____）
