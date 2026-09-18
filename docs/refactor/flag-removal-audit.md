# vXX_ 版本开关体系删除 —— 成本审查报告

> 审查对象：`apps/backend` 中以版本号作前缀的 settings 配置与开关体系（`v2_*` / `v21_*` / `v22_*` / `v23_*` / `v24_*` / `v25_*` / `v26_*`）
> 审查范围：仅 `apps/backend`；`docs/` 按约定不纳入改动面
> 本文正文的数据均为**改造前**口径实测（非估算），不回写执行结果；执行进展一律记在**附录 F**。
> 当前状态（2026-09-18）：批次 1（v2 段）与轨道 A（200 字段去前缀）**已完成并提交**；附录 A/B 的旧字段名已失效，剩余执行清单以 `flag-rename-map.md` §四/§五 的新名为准。轨道 B：**v22 / v21 / v23 已完成**（F.9~F.14）；剩余 **v24 → v25 → v26 → 收尾删 `enablement.py`**。
>
> **剩余批次执行清单见 [附录 H](#附录-h剩余批次任务编排批次-58)**（2026-09-18 实测口径，替代 §8 表头的过时计数）。

---

## 一、执行摘要

### 1.1 结论

删除这套开关体系的成本**不是均匀分布**的，实际由三段性质完全不同的工作构成：

| 段 | 内容 | 工作量占比 | 风险 |
|---|---|---|---|
| **A 段：机械改名** | 212 个字段去版本号前缀 + 环境变量同步 + 测试字面量同步 | 约 65% 的 diff 行数，但**认知负荷最低** | 低（仅 2 处撞名需人工裁决） |
| **B 段：删门控分支** | 92 处 guard、63 处正向分支、**17 处遗留回退路径** | 约 25% 的 diff，但**风险集中在此** | **高** |
| **C 段：转正验证** | 61 个开关固化为 ON 后的行为验证 | 不产生 diff，但**是真正的成本大头** | **最高** |

**一句话结论：改名是廉价的，删分支是昂贵的，而"把 V2.0~V2.6 全量转正"的验证成本远超前两者之和，且目前没有可用的验证资产。**

### 1.2 必须先接受的三个前提

**前提一：本次操作实质是「功能转正上线」，不是「清理冗余门控」。**

实测 `apps/backend/.env` 全文只开启了 **2 个** V2 开关：

```
V2_CHARACTER_ACTION_SYNC_ENABLED=true
V2_INVENTORY_GROUNDING_ENABLED=true
```

而 `V2.1.0 ~ V2.6.0` 的全部功能闸门**在真实运行配置下均为 off**。`.env.example` 更是把 V2.3 / V2.4 / V2.6 的闸门显式写成 `false`，并注明"总闸 off 时行为与上一版本逐字节一致"。

这意味着：`app/main.py:77-90` 里 `v2_life_loop_enabled` 为 off 时走的那条 `else` 分支（`autonomy_worker` + `world_engine.run_world_maintenance_loop` + `run_action_retry_loop` 三个旧循环），**才是当前生产实际在跑的路径**。固化 ON 会删掉它。

同时，`AGENTS.md` 明确记载：

> 上线前待办：按各版本 regression-checklist 执行真实模型人工回归（V4 / V7 / V7.5 / V7.8 / V8 / V2.1.0 已有清单）

即 V2.1.0 及之后的回归**尚未执行**。因此"全量转正"= 一次性上线一整套未端到端验证过的功能。

**前提二：`docs/` 保持原样会在仓库内留下 1,589 处"死引用"。**

`docs/` 下 169 个文件、1,589 处 `vXX_` 引用（`docs/version/v2.5.0/planning-system/tasks/PLAN-002.md` 96 处、`architecture.md` 63 处等）。按决策不改写，则改完之后**代码与文档的闸门命名将不一致**。这是有意选择（历史设计文档是事实记录，改写即篡改历史），但必须接受这个代价。

**前提三：`override_settings` 会静默骗过测试，是本次改造最大的隐蔽风险。**

见 §7.3。

---

## 二、现状盘点

### 2.1 字段规模

| 维度 | 实测值 |
|---|---|
| settings 字段总数 | 434 |
| 带 `vXX_` 前缀 | **212**（占 48.8%） |
| ├ 其中 bool 开关 | **61** |
| └ 其中非 bool 调参 | **151** |
| 按前缀分布 | `v2_`=113 / `v21_`=28 / `v22_`=5 / `v23_`=12 / `v24_`=19 / `v25_`=27 / `v26_`=8 |

### 2.2 开关角色分布

| 角色 | 数量 | 说明 |
|---|---|---|
| 总闸 | 12 | 控制一整个版本域是否参与 |
| 子闸 | 33 | 总闸开启后才有意义 |
| 独立 | 16 | 不与总闸绑定 |
| 其中标记 RESERVED | 4 | 声明但（部分）未接线 |

12 个总闸：`v2_life_loop_enabled`、`v2_autonomy_advanced_enabled`、`v2_memory_enabled`、`v2_reflection_enabled`、`v2_development_enabled`、`v2_relationship_evolved_enabled`、`v21_agent_runtime_enabled`、`v22_experience_enabled`、`v23_world_simulation_enabled`、`v24_tool_system_enabled`、`v25_planning_enabled`、`v26_action_execution_enabled`。

### 2.3 消费点分布

| 维度 | 实测值 |
|---|---|
| `app/` 中开关名出现次数（排除 `app/core/settings/`） | **308 处**，分布在 79 个模块 |
| ├ 其中**实际门控点** | **182 处** |
| │ ├ guard 型（`if not flag:`） | 92 |
| │ ├ 正向分支型（`if flag:`） | 63 |
| │ ├ `getattr(settings, "vXX_…")` 防御式 | 26 |
| │ └ 单行三元 | 1 |
| └ 其余 126 处 | docstring / 注释 / 函数名等非门控提及（删除时需一并清理文案） |
| 测试中开关名出现次数 | **1,015 处** |
| 测试中整串恰为闸门名的字符串字面量 | **544 处 / 64 个文件** |

> 注：182 处"实际门控点"之外，§4.2 另列 **8 处跨行三元表达式**（如 `app/application/chat_pipeline.py:537-541` 的 `grounding_mode` 选择、`app/application/action_engine.py:227` 的 `tool_registry` 选择）。它们因跨行书写未被单行正则计入，属于**独立于 guard/branch 的第三种删除形态**，需人工逐个处理。

引用最密的开关（`app/` 侧）：`v24_tool_system_enabled` 29 处、`v2_reflection_enabled` 18 处、`v23_world_simulation_enabled` 18 处、`v26_action_execution_enabled` 11 处、`v2_autonomy_advanced_enabled` 11 处、`v25_planning_enabled` 11 处、`v2_memory_enabled` 10 处。

### 2.4 配置层与前端

| 维度 | 实测值 |
|---|---|
| `.env.example` 中 `VXX_*` 行 | 42 |
| `.env` 中 `VXX_*` 行 | 4 |
| 前端引用 | 仅 `world-sim` 调试面板：`WorldSimPanel.tsx:113,142`、`WorldSimPanel.test.tsx:46-53,159`、`api/world-sim.ts:51,77,107`（`flags` 字段透传） |
| `docker-compose.yml` / `Dockerfile` | 无直接引用（compose 走 `env_file: ./apps/backend/.env`） |
| `apps/backend/scripts/` | 8 个脚本，仅 `replay_development.py:26-27` 读一个开关 |

**环境变量名映射机制**：`app/core/settings/_shared.py:14` 的 `DOMAIN_MODEL_CONFIG` **没有** `env_prefix`、**没有** `alias_generator`、全仓库**没有任何** `Field(alias=...)`。因此环境变量名 = 字段名大写（`v2_memory_enabled` ↔ `V2_MEMORY_ENABLED`）。这是"改名必然连带 env 名变更"的根因。

`Settings` 由 25 个领域类多继承组合而成（`app/core/settings/__init__.py:41-68`），`get_settings()` 是 `@lru_cache` 模块级单例（`:80-82`），**没有走 FastAPI 依赖注入**。

---

## 三、闸门类型学

三种形态，删除成本递增。

### 3.1 guard 型（92 处）—— 成本最低

```python
# app/api/v1/world.py:233
if not get_settings().v23_world_simulation_enabled:
    return WorldSimulationOut(enabled=False)
```

固化 ON 后条件恒假，整段 guard 连同类体成为死代码，直接删除即可，**无行为变化**（除了 API 契约上 `enabled` 恒为 `true`）。

同型样例：`app/application/life_loop.py:82,449,473,644,706,734`、`app/application/post_process.py:253,345,572`、`app/services/reflection/triggers.py:101,445`、`app/services/memory2/evaluator.py:261,478`。

### 3.2 正向分支型（63 处）—— 成本中等

```python
# app/application/action_engine.py:793
if settings.v2_action_outbox_enabled:
    ...
```

固化 ON 后条件恒真，把 `if` 体提升一层、去掉缩进即可。**需确认该分支内没有依赖"仅在开关首次开启时成立"的隐含前提**（如首次运行的初始化副作用）。

### 3.3 遗留回退型（17 处）—— 成本最高，风险集中

这类闸门旁边并存一条**当前实际生效**的旧路径。固化 ON 意味着**删掉正在跑的代码**。详见 §4。

---

## 四、高风险清单：遗留回退路径

### 4.1 字面 sibling `else` / `elif`（5 处，已逐行核实）

| # | 位置 | 闸门 | 保留（ON 路径） | **删除（OFF 路径，当前生效）** |
|---|---|---|---|---|
| 1 | `app/main.py:77-90` | `v2_life_loop_enabled` | `run_life_loop_worker()` | `else` 段三个旧循环：`autonomy_worker.run_autonomy_worker()`、`world_engine.run_world_maintenance_loop()`、`run_action_retry_loop()`；连带 `_autonomy_task` / `_world_maintenance_task` / `_action_maintenance_task` 三个全局量（`:35-39`）与 cancel 循环（`:125-147`） |
| 2 | `app/application/post_process.py:152-168` | `v2_memory_enabled` | `_run_memory_ingest_v2` + `_run_memory_evaluate_v2` | `else`：`memory_service.extract_and_save(..., recent_context=...)` |
| 3 | `app/services/context_builder.py:259-271` | `v2_memory_enabled` | `memory2_retriever.retrieve` + insights | `else`：`memory_service.retrieve` / `select_for_context` |
| 4 | `app/services/context_builder.py:305-309` | `v2_relationship_evolved_enabled` | 载入 shared experience + patterns | `else`：`relationship_pattern_list = []` |
| 5 | `app/application/world_engine.py:860-871` | `v23_world_simulation_enabled` **且** `v23_scene_expansion_enabled` | `movement.apply(...)` | `elif`：`set_location(user_id, result.location_move)` |

### 4.2 早返回 + 调用点回退型（12 处）

这类不写成 `else`，而是"闸门关了就早返回 / 走另一个函数"，旧路径藏在调用点。代码里的 docstring 直接写明了这一点（如 `life_loop.py:602`："off → 既有 `goal_execution` 原路径（行为与 V2.4.0 一致）"）。

| # | 位置 | 闸门 | 保留（ON 路径） | **删除（OFF 路径，当前生效）** |
|---|---|---|---|---|
| 6 | `app/application/action_engine.py:215-238` | `v26_action_execution_enabled` → `v24_tool_system_enabled` | `_execute_plan_via_action_executor` | `:227` `tool_registry = get_tool_registry() if … else None`；`:228-238` `_execute_plan_via_tools`；`:240+` 裸 `executor.run` 循环 |
| 7 | `app/services/planning/context.py:305-306` | `v25_plan_context_enabled` | `_gather_sources`（四来源） | 空 `_PlanSources()`（**内容差异**，非简单展开） |
| 8 | `app/services/planning/context.py:346-351` | `v25_plan_tool_required` | 硬要求 registry（缺则 `PlanUnavailable`） | `ToolSurfaceResolver(None, …).resolve(...)`（无面规划）。**转正后 `PLAN_UNAVAILABLE_TOOL_SYSTEM_DISABLED` / `PLAN_UNAVAILABLE_REGISTRY_UNAVAILABLE` 成为新的可达失败面** |
| 9 | `app/api/v1/debug.py:1115-1123` | `v25_plan_tool_required` + `v24_tool_system_enabled` | registry resolver | `ToolSurfaceResolver(None, …)` / `return None` |
| 10 | `app/application/life_loop.py:473-474` | `v25_planning_enabled` | `engine.enqueue` / `run_jobs` | no-op 早返回 |
| 11 | `app/application/life_loop.py:526-528` | `v25_plan_scheduler_enabled` | `PlanScheduler.current_step(plan)` | `goal_observation._current_step(list(plan.sub_goals))` |
| 12 | `app/application/life_loop.py:605-610` | `v25_plan_execution_enabled` | `_execute_plan_step(...)` | `goal_execution.attempt_current_step(goal, plan, now)` |
| 13 | `app/application/life_loop.py:621-630` | `v25_plan_observation_enabled` | `PlanObserver.collect_facts` + `observe_user_goals` | `_observation_facts(user_id, now)` + `goal_observation.advance_user_goals(...)` |
| 14 | `app/application/world_engine.py:1000-1007` | `v23_daily_life_enabled` | 活跃日计划块 | `block = None` |
| 15 | `app/application/world_engine.py:1008-1012` | `v23_event_detection_enabled` | `situation_service.active_situations(user_id)` | `[]` |
| 16 | `app/application/autonomy_engine.py:561-564` | `v21_goal_stack_enabled` | 分层目标 | 扁平目标 |
| 17 | `app/application/chat_pipeline.py:276-281` / `app/services/context_builder.py:296-300` | `v21_goal_stack_enabled` | `layered_goals` | `layered_goals = []` |

### 4.3 附带影响：整模块变死

`app/application/autonomy_worker.py` 的**唯一调用点**就是 §4.1 第 1 条的 `else` 段。删除旧循环后该模块整体失效（`autonomy_worker.py:21-23` 自身还有一个 `v2_life_loop_enabled` 早返回守卫）。

### 4.4 附带影响：API 契约变化

以下端点在闸门转正后**不再可能返回"未启用"**，响应契约中的 `enabled` 字段恒为 `true`，相关 403 分支与错误文案成为死代码：

| 位置 | 闸门 | 当前行为 |
|---|---|---|
| `app/api/v1/world.py:233-234` | `v23_world_simulation_enabled` | `WorldSimulationOut(enabled=False)` |
| `app/api/v1/world.py:247-248` | 同上 | `WorldPlanOut(enabled=False)` |
| `app/api/v1/world.py:263-264` | 同上 | `WorldSituationsOut(enabled=False)` |
| `app/api/v1/world.py:278-279` | 同上 | `WorldSimTickOut(enabled=False)` |
| `app/api/v1/world.py:280-281` | `v23_debug_tick_enabled` | HTTP 403「调试 tick 未启用」 |
| `app/api/v1/debug.py:309-313` | `v24_tool_surface_enabled` | HTTP 403 |
| `app/api/v1/debug.py:1119-1120` | `v24_tool_system_enabled` | `return None` |
| `app/api/v1/action_execution.py:15-16,24` | `v26_action_execution_enabled` / `v26_action_debug_enabled` | HTTP 403 |

**前端连带**：`apps/frontend/src/features/world-sim/WorldSimPanel.tsx:113` 读 `flags.v23_debug_tick_enabled` 决定按钮可用性、`:142` 显示文案「世界模拟未启用（v23_world_simulation_enabled=false）」。这两处在前端改名前会失效（读不到 key 则恒为 `false` / 恒显示未启用文案）。

---

## 五、死闸门与失准标记

### 5.1 纯死开关（2 个）

| 开关 | 状态 |
|---|---|
| `v26_action_abstraction_enabled` | `app/` 中 0 处引用，仅出现在 settings 定义与 RESERVED 常量中 |
| `v26_action_multistep_enabled` | 同上 |

固化 ON 对这两个是**空操作**——开了也不会有任何行为变化。它们应当直接**删除**而非转正。

### 5.2 近乎失效（1 个）

`v23_habit_time_enabled`：`app/` 中仅 1 处引用，且只是出现在 `world_engine.py:1274` 的 `_V23_FLAG_NAMES` 快照列表里（供调试端点输出），**无任何行为分支**。

### 5.3 RESERVED 标记已失准（1 处）

`app/core/settings/world_simulation.py:12-16` 把 `v23_scene_expansion_enabled` 列入 `RESERVED_V23_SUB_FLAGS`，注释称"当前版本尚未接线"。但实测它在 `app/application/world_engine.py:860` 与 `app/services/tool/world_context.py:207` **都被实际读取**，且是 §4.1 第 5 条双路径的组成部分。

即：**RESERVED 标记与代码事实矛盾**。审查中若依赖该标记判断"哪些开关可以无痛删除"，会做出错误结论。报告建议在删除前先修正或直接废弃这组标记。

### 5.4 默认 ON 的"伪开关"（4 个）

| 开关 | 默认 |
|---|---|
| `v24_tool_confirm_ttl_reuse` | `True` |
| `v25_plan_context_digest_enabled` | `True` |
| `v25_plan_tool_required` | `True` |
| `v2_inventory_grounding_enabled` | `True` |

这 4 个默认开启，语义上更接近"策略修饰位"而非"部署闸门"。其中 `v25_plan_tool_required` 还参与 `enablement.py` 的依赖判定，且 `enablement.py:26-33` 专门留了一段文字解释它为何**不能**按字面量参与"子闸 → 总闸"循环（否则默认配置自我否决）。这类特殊语义在删除时需逐个确认，不能机械处理。

---

## 六、改名与 env 破坏性变更

### 6.1 撞名分析：仅 2 处

212 个字段去掉 `vXX_` 前缀后，与既有字段或彼此撞名的只有 **2 处**：

| 冲突 | 说明 | 建议 |
|---|---|---|
| `v23_world_llm_assist_enabled` → `world_llm_assist_enabled` | 与 `world.py` 中**已存在**的 `world_llm_assist_enabled` 同名（两者是不同的字段，都在 `WorldSettings`/`WorldSimulationSettings` 中） | 合并为一个，或给其中一个更具体的名字 |
| `v21_event_escalation_types` ↔ `v23_event_escalation_types` | 两者去前缀后都变成 `event_escalation_types` | 需人工区分语义命名 |

**这是本次改造少有的好消息**：去前缀本身是低风险的机械操作，99% 的字段可以脚本化批量替换。

### 6.2 环境变量连带变更

由于无 alias 层，字段改名 = 环境变量改名。受影响：

- `apps/backend/.env.example`：42 行
- `apps/backend/.env`：4 行
- `docker-compose.yml` / `Dockerfile`：无直接引用（走 `env_file`），**但部署侧的 `.env` 副本会失效**

**关键风险**：`DOMAIN_MODEL_CONFIG` 的 `extra="ignore"`（`_shared.py:15`）会让**未识别的旧环境变量被静默忽略**。也就是说，改名后若运维侧 `.env` 未同步更新，服务会**正常启动**，但所有闸门静默回落到代码默认值（绝大多数是 `off`）——表现为"功能莫名其妙全没了"，且日志中**没有任何警告**。

**缓解建议**：在 `lifespan` 中加一段一次性检查——扫描 `os.environ` 中匹配 `^V[0-9]+_` 的键，若不在 `Settings.model_fields` 的大写集合中则 `logging.warning` 列出。成本极低，能把这个静默故障变成显式告警。

### 6.3 不建议使用 `extra="forbid"`

`extra="forbid"` 看似能捕获此类错误，但会连带拒绝 `.env` 中所有无关键，风险大于收益。用 §6.2 的显式告警替代。

---

## 七、测试侧改造工作量

### 7.1 测试引用分布

| 目录 | .py 文件 | 含 `vXX_` 文件 | `vXX_` 出现次数 |
|---|---|---|---|
| `tests/v24` | 61 | 54 | 661 |
| `tests/v25` | 80 | 55 | 634 |
| `tests/v2` | 41 | 36 | 268 |
| `tests/e2e` | 30 | 29 | 154 |
| `tests/v26` | 19 | 15 | 86 |
| `tests/v23` | 19 | 4 | 57 |
| `tests/unit` | 106 | 6 | 56 |
| `tests/integration` | 70 | 14 | 37 |
| `tests/v21` | 12 | 8 | 35 |
| `tests/eval` | 5 | 4 | 24 |
| `tests/v22` | 9 | 2 | 23 |
| `tests/v7.8` | 3 | 3 | 10 |
| `tests/v8` | 7 | 4 | 5 |
| `tests/v9` | 15 | 1 | 1 |
| **合计** | **489** | **236** | **2,053** |

### 7.2 必须改造的机制层

| 位置 | 规模 | 改造方式 |
|---|---|---|
| `tests/conftest.py:297-384` `override_settings` | 516 个调用点，其中 **467 次带 `vXX_` kwarg**（66 个文件） | `env_map` 中显式列出与 `key.upper()` 兜底逻辑均需同步；**并加 §7.3 的防呆** |
| `tests/conftest.py:15-25` 导入期 env | — | `V2_MEMORY_ENABLED` 等字面量同步 |
| `tests/v24/conftest.py:10-17` autouse 钉死 | — | `V24_TOOL_SYSTEM_ENABLED=false` 等 |
| `tests/v24/conftest.py:40-52` `v24_tool_env` | **164 次调用** | 同 `override_settings` |
| `tests/v25/conftest.py:26-33` autouse 钉死 | — | `V2_AUTONOMY_ADVANCED_ENABLED` 等 |
| `monkeypatch.setenv("VXX_…")` 字面量 | **35 处 / 15 个文件** | 逐个同步 |

35 处 `setenv` 字面量分布：`tests/unit/test_v2_memory_settings.py`(2)、`tests/v23/test_ws003_time_advancer.py`(2)、`test_ws004_day_cycle.py`(2)、`test_ws005_weather.py`(2)、`test_ws008_plan_runner.py`(3)、`test_ws010_event_bridge.py`(3)、`test_ws012_world_brief.py`(1)、`test_ws013_ws014_autonomy.py`(2)、`test_ws018_debug_api.py`(2)、`test_ws020_review_fixes.py`(3)、`tests/v24/conftest.py`(2)、`tests/v24/test_tool001_settings.py`(2)、`tests/v25/conftest.py`(2)、`tests/v25/test_plan002_settings.py`(3)、`tests/v25/test_plan012_acceptance_fixes.py`(4)。

`override_settings` 带 `vXX_` kwarg 最多的开关：`v2_reflection_enabled`(64)、`v2_autonomy_advanced_enabled`(49)、`v24_tool_system_enabled`(39)、`v2_memory_enabled`(33)、`v25_planning_enabled`(27)、`v25_plan_step_binding_enabled`(21)。

### 7.3 ⚠️ 静默失败陷阱（本次改造最大的隐蔽风险）

`override_settings` 的实现逻辑是：

```python
for key, value in kwargs.items():
    if key not in env_map:
        monkeypatch.setenv(key.upper(), str(value))   # v25_planning_enabled -> V25_PLANNING_ENABLED
get_settings.cache_clear()
```

字段改名后，`override_settings(v25_planning_enabled="true")` 依然会去设环境变量 `V25_PLANNING_ENABLED`。但该字段已不存在，`extra="ignore"` 静默吞掉它。

**后果**：测试**全部通过**，但闸门**根本没开**。而且由于固化 ON 之后闸门恒真，测试甚至会"更通过"——**缺陷被完全掩盖**。这是比"测试失败"危险得多的情况。

**防呆方案（二选一或同时）**：

1. **让 fixture 自检**：在 `override_settings` 与 `v24_tool_env` 中，对每个即将 emit 的 env key 断言
   ```python
   valid = {f.upper() for f in Settings.model_fields}
   assert env_key in valid, f"未知设置项 {env_key}（字段已改名？）"
   ```
2. **加一个收集期用例**：扫描 `tests/` 下所有 `setenv("V…")` 与 `env_map` 字面量，凡不在 `model_fields` 大写集合中即失败。

方案 2 能一次性覆盖 35 处字面量，建议同时采用。

### 7.4 直接失效的测试（删除或改造）

**闸门矩阵 / 依赖链校验类（整体失效）：**
- `tests/v25/test_plan002_enablement.py`（93 处闸门名字面量，是最大的单文件）
- `tests/v25/test_plan002_settings.py`（48 处）
- `tests/v25/test_plan012_flag_matrix.py`（`TestFlagDefaults` / `TestEnablementChainMatrix`）
- `tests/v24/test_tool001_enablement.py`（18 处）
- `tests/unit/test_enablement_chain.py`（10 处）
- `tests/v26/test_v26_p1_flag_and_backoff.py`
- `tests/v23/test_ws001_settings.py:77-114`（14 处）
- `tests/v2/test_v2_all_flags_smoke.py`

**断言 OFF 路径行为的用例（语义反转）：**
- 断言 `skip_reason == "flag_disabled"`：`tests/v2/test_aut002_planning.py`、`test_aut003_observation.py`、`test_aut004_lifecycle.py`、`test_life002_controller.py`
- 断言 `enabled=False` 契约：`tests/v23/test_ws018_debug_api.py:39-40,98`

**依赖 `enablement` 报错文案的用例（需重写断言）：** `tests/v21/test_agent001_compat.py:37-46`、`test_agent003_goal_stack.py:197-201`、`test_agent006_evaluation.py:139-144`、`test_agent007_integration.py:75-97,238`、`tests/v22/test_char007_style_integration.py:302-310`、`tests/v24/test_tool010_channel.py:774`、`tests/v24/test_tool_acceptance.py:20`。

**注意**：`tests/v25/test_plan001_scope_markers.py`（29 处）是"范围标记"类测试，其断言本身就是**有意的契约留痕**（docstring 明确写"后续任务落地对应产物时必须显式更新本模块，更新动作本身就是范围越界已评审的证据"）。改造时必须按此纪律显式更新，不能删。

---

## 八、依赖有序的批次方案

顺序由 `app/core/settings/enablement.py` 的依赖表（`V25_DEPENDENCIES:71-114`、`V25_SUB_FLAGS:51-63`，以及 v2/v21/v22/v23/v24/v26 各段内联表）加运行时耦合推出。

> **执行期修订（2026-09-18）**：本表表头计数、开关清单与批次 6 的依赖描述已由 **附录 F.2** 修订（批次 4 为 8 个而非 7 个、批次 6 为 14 个而非 13 个、批次 7 为 7 个而非 6 个，合计 51 而非 48；批次 6 对 v2 段的依赖已随批次 1 消失）。**执行前请以附录 F 为准**，并从附录 A 重新导出该批清单。

**前置说明：非版本号的基础闸必须保留。** `action_enabled` / `world_enabled` / `autonomy_enabled` / `feishu_enabled` 不带版本前缀，且 vXX_ 的 ON 路径运行时仍依赖它们（如 `v25_plan_execution_enabled` 要求 `action_enabled`、`v26_action_execution_enabled` 要求 `action_enabled`、`v24_tool_channel_enabled` 要求 `feishu_enabled`）。这些**不在本次删除范围内**。

| 批次 | 范围 | 内部顺序 | 依赖说明 |
|---|---|---|---|
| **1** | v2 根（6 个总闸 + 2 个独立） | `v2_life_loop_enabled` → `v2_autonomy_advanced_enabled`、`v2_action_outbox_enabled`；另 `v2_memory_enabled`、`v2_memory_vector_enabled`、`v2_reflection_enabled`、`v2_development_enabled`、`v2_relationship_evolved_enabled` | `autonomy_advanced` 依赖 `life_loop` + `action_enabled`；`action_outbox` 依赖 `life_loop`。**本批含 §4.1 第 1 条（main.py 三循环删除）与第 2~4 条，是风险最高的一批** |
| **2** | v21（6 个） | `v21_agent_runtime_enabled` 先行 → `v21_goal_stack_enabled`、`v21_agent_metrics_enabled` → `v21_personality_evolution_enabled`、`v21_unified_run_enabled`、`v21_foreground_gateway_enforced` | `goal_stack` / `personality_evolution` / `agent_metrics` / `unified_run` 均依赖 `agent_runtime`；`personality_evolution` 还依赖 `agent_metrics` |
| **3** | v22（5 个） | `v22_experience_enabled` 先行 → emotion / relationship_addressing / habit_runtime / style_contract | 四个子闸均要求 `experience` |
| **4** | v23（7 个） | `v23_world_simulation_enabled` → `v23_time_advance_enabled` → `v23_daily_life_enabled`、`v23_event_detection_enabled` → `v23_world_llm_assist_enabled`、`v23_scene_expansion_enabled`、`v23_debug_tick_enabled`；`v23_habit_time_enabled` 直接删（无行为） | `daily_life` 依赖 `time_advance`；`world_llm_assist` 依赖 `event_detection`。含 §4.1 第 5 条与 §4.2 第 14/15 条 |
| **5** | v24（11 个） | `v24_tool_system_enabled` → permission / schema_validation / observation / surface / memory / reflection / external_api / user_defined；`v24_tool_channel_enabled`（依赖 `feishu_enabled`）；`v24_tool_confirm_ttl_reuse` 按策略位处理 | 9 个子闸均要求 `tool_system`；`tool_channel` 额外要求 `feishu_enabled` |
| **6** | v25（13 个） | `v25_planning_enabled`（依赖 `v2_autonomy_advanced_enabled` + `v2_life_loop_enabled`）→ context / step_binding（依赖 v24）/ scheduler / observation / revision / memory（依赖 `v2_memory_enabled`）/ reflection（依赖 `v2_reflection_enabled`）/ world_feedback / autonomy（依赖 `v21_agent_runtime_enabled`）/ debug → `v25_plan_execution_enabled`（依赖 scheduler + `action_enabled`）→ `v25_plan_tool_required` | **依赖面最广的一批**，必须最后做；含 §4.2 第 7~11 条 |
| **7** | v26（6 个） | `v26_action_execution_enabled`（依赖 `action_enabled`）→ scheduler / result / feedback / debug；abstraction / multistep 直接删（无行为） | 含 §4.2 第 6 条 |
| **8** | 收尾 | 删除 `app/core/settings/enablement.py` + `app/main.py:14,50` 调用点 + 三个 warning 函数 | 全部闸门清空后才可执行 |

**批次 1 与批次 6 是两个必须重点验证的节点**：批次 1 删除当前生产实际运行的旧循环，批次 6 涉及 13 个互相关联的开关和 5 条遗留回退路径。

---

## 九、可整文件删除清单与验证命令

### 9.1 可删除文件（附置信度）

| 文件 | 依据 | 置信度 |
|---|---|---|
| `app/core/settings/enablement.py`（13.7 KB） | `app/` 侧唯一导入点是 `app/main.py:14,50`（已核实；`life_loop.py:497`、`debug.py:1054`、`world_simulation.py:7` 仅为 docstring 提及） | **高** |
| `app/main.py:14,50` 的 import 与 `validate_enablement_chain` 调用 | 无闸门可校验 | **高** |
| `enablement.py:262-312` 三个 warning 函数（`v23_reserved_flag_warnings` / `v26_reserved_flag_warnings` / `v24_permission_sub_layer_warnings`） | 随文件一并删除 | **高** |
| `RESERVED_V23_SUB_FLAGS`（`world_simulation.py:12-16`）、`RESERVED_V26_SUB_FLAGS`（`action_execution.py:17-20`） | 依赖已失准（§5.3） | **高** |
| `ActionExecutionSettings.validate_v26_chain`（`action_execution.py:38-46`） | 依赖链消失 | **高** |
| `app/application/autonomy_worker.py` | 唯一调用点是 §4.1 第 1 条的 `else` 段 | **中高** |
| `world_engine.py:1274` `_V23_FLAG_NAMES` 快照列表 | 调试端点契约变更；牵动前端 `world-sim` 面板 | **中** |
| `v23_reserved_flag_warnings` 等对应测试（`tests/unit/test_enablement_chain.py` 等） | 随被测对象删除 | **高** |

### 9.2 验证命令

> 判据修订见 **附录 G.1 / G.2**：① 的「0 命中」目标不可直接达成——历史说明性注释是**有意保留**的（批次 1 已留 7 处），须按「该行是否为可执行语句」过滤；并补充契约层与前端两条命令。

```bash
# ① 源码侧残留扫描（目标：0 命中）
grep -rn '\bv[0-9][0-9a-z_]*\b' apps/backend/app --include=*.py \
  | grep -v 'core/settings'

# ② 测试侧环境变量字面量残留（目标：0 命中）
grep -rn 'V[0-9][0-9A-Z_]*' apps/backend/tests --include=*.py

# ③ 字段完整性与撞名自检
cd apps/backend && python -c "
from app.core.settings import Settings
names = list(Settings.model_fields)
print('字段总数:', len(names))
print('残留 vXX_:', [n for n in names if n[:1]=='v' and n[1:2].isdigit()])
"

# ④ 启动期校验（闸门链应已不存在；重点看是否有未知环境变量告警）
cd apps/backend && python -c "
from app.core.settings import get_settings
get_settings()
print('settings 构建成功')
"

# ⑤ 离线全量回归（conftest 的 autouse _offline_repos 已把仓储指向内存 SQLite）
cd apps/backend && pytest -q

# ⑥ 前端
cd apps/frontend && pnpm vitest run
```

**注意**：本机 `vite build` 在 `prepare-out-dir` 阶段会被 safe-delete 保护拦截（`[SAFE_DELETE_BULK_CONFIRM_REQUIRED]`），这不是代码错误。需要构建验证时用 `vite build --outDir <新目录>` 绕开。

### 9.3 本报告不覆盖的验证

- **真实模型行为回归**：`AGENTS.md` 列出的 V2.1.0 / V2.3.0 / V2.4.0 / V2.5.0 / V2.6.0 regression-checklist **必须逐版本人工执行**。这是本次改造真正的工作量所在，且无法通过单元测试替代。
- **数据库迁移**：迁移链至 0043，本次改造不动 schema，无需新迁移。但转正后首次运行会激活大量此前未执行过的写入路径，建议在**独立数据库**上先跑一轮。

---

## 附录 A：61 个 bool 开关完整台账

> **改造前口径**：本表全部为旧名，现已去前缀（`v24_tool_system_enabled` → `tool_system_enabled`）；其中 10 个 v2 段开关已随批次 1 删除、3 个死开关已随 F.7 删除。**按旧名 grep 代码将 0 命中**，执行清单请用 `flag-rename-map.md` §四（48 个在存开关的新名 + 旧名对照）。本表的价值是「改造前有多少、各自什么形态」的历史账。

列含义：`app` = `app/` 侧引用数（不含 `app/core/settings/`）；`测试` = 测试侧引用数；`guard`/`branch`/`三元`/`getattr` = 该开关在 `app/` 中的门控形态计数。

| 开关 | 定义处 | 默认 | 角色 | app | 测试 | guard | branch | 三元 | getattr |
|---|---|---|---|---|---|---|---|---|---|
| `v21_agent_metrics_enabled` | agent_runtime.py | off | 独立 | 3 | 3 | 1 | 0 | 0 | 0 |
| `v21_agent_runtime_enabled` | agent_runtime.py | off | 总闸 | 5 | 8 | 2 | 0 | 0 | 0 |
| `v21_foreground_gateway_enforced` | agent_runtime.py | off | 独立 | 4 | 0 | 1 | 2 | 0 | 0 |
| `v21_goal_stack_enabled` | agent_runtime.py | off | 独立 | 5 | 6 | 1 | 4 | 0 | 0 |
| `v21_personality_evolution_enabled` | agent_runtime.py | off | 独立 | 5 | 5 | 3 | 0 | 0 | 0 |
| `v21_unified_run_enabled` | agent_runtime.py | off | 独立 | 1 | 3 | 0 | 0 | 0 | 0 |
| `v22_emotion_transition_enabled` | experience.py | off | 独立 | 1 | 2 | 0 | 0 | 0 | 0 |
| `v22_experience_enabled` | experience.py | off | 总闸 | 3 | 5 | 2 | 0 | 0 | 0 |
| `v22_habit_runtime_enabled` | experience.py | off | 独立 | 1 | 2 | 0 | 0 | 0 | 0 |
| `v22_relationship_addressing_enabled` | experience.py | off | 独立 | 1 | 2 | 0 | 0 | 0 | 0 |
| `v22_style_contract_enabled` | experience.py | off | 独立 | 2 | 4 | 1 | 0 | 0 | 0 |
| `v23_daily_life_enabled` | world_simulation.py | off | 子闸 | 7 | 5 | 0 | 6 | 0 | 0 |
| `v23_debug_tick_enabled` | world_simulation.py | off | 子闸 | 5 | 2 | 1 | 0 | 0 | 0 |
| `v23_event_detection_enabled` | world_simulation.py | off | 子闸 | 9 | 6 | 0 | 7 | 0 | 0 |
| `v23_habit_time_enabled` | world_simulation.py | off | 子闸 ⚠RESERVED·无行为 | 1 | 1 | 0 | 0 | 0 | 0 |
| `v23_scene_expansion_enabled` | world_simulation.py | off | 子闸 ⚠RESERVED·已接线 | 5 | 10 | 1 | 1 | 0 | 0 |
| `v23_time_advance_enabled` | world_simulation.py | off | 子闸 | 4 | 4 | 0 | 0 | 0 | 0 |
| `v23_world_llm_assist_enabled` | world_simulation.py | off | 子闸 | 2 | 3 | 1 | 0 | 0 | 0 |
| `v23_world_simulation_enabled` | world_simulation.py | off | 总闸 | 18 | 14 | 5 | 7 | 0 | 0 |
| `v24_tool_channel_enabled` | tool.py | off | 子闸 | 3 | 19 | 1 | 1 | 0 | 0 |
| `v24_tool_confirm_ttl_reuse` | tool.py | **ON** | 独立 | 3 | 10 | 0 | 0 | 0 | 1 |
| `v24_tool_external_api_enabled` | tool.py | off | 子闸 | 8 | 12 | 0 | 1 | 0 | 2 |
| `v24_tool_memory_enabled` | tool.py | off | 子闸 | 3 | 4 | 1 | 1 | 0 | 0 |
| `v24_tool_observation_enabled` | tool.py | off | 子闸 | 1 | 17 | 1 | 0 | 0 | 0 |
| `v24_tool_permission_enabled` | tool.py | off | 子闸 | 10 | 28 | 1 | 0 | 0 | 6 |
| `v24_tool_reflection_enabled` | tool.py | off | 子闸 | 5 | 3 | 2 | 0 | 0 | 2 |
| `v24_tool_schema_validation_enabled` | tool.py | off | 子闸 | 1 | 23 | 0 | 1 | 0 | 0 |
| `v24_tool_surface_enabled` | tool.py | off | 子闸 | 5 | 9 | 2 | 0 | 0 | 0 |
| `v24_tool_system_enabled` | tool.py | off | 总闸 | 29 | 140 | 15 | 1 | 1 | 3 |
| `v24_tool_user_defined_enabled` | tool.py | off | 子闸 | 7 | 7 | 0 | 0 | 0 | 2 |
| `v25_plan_autonomy_enabled` | plan.py | off | 子闸 | 2 | 27 | 1 | 0 | 0 | 0 |
| `v25_plan_context_digest_enabled` | plan.py | **ON** | 独立 | 1 | 3 | 0 | 1 | 0 | 0 |
| `v25_plan_context_enabled` | plan.py | off | 子闸 | 3 | 20 | 0 | 1 | 0 | 0 |
| `v25_plan_debug_enabled` | plan.py | off | 子闸 | 2 | 12 | 0 | 0 | 0 | 0 |
| `v25_plan_execution_enabled` | plan.py | off | 子闸 | 3 | 15 | 0 | 0 | 0 | 0 |
| `v25_plan_memory_enabled` | plan.py | off | 子闸 | 4 | 11 | 2 | 0 | 0 | 0 |
| `v25_plan_observation_enabled` | plan.py | off | 子闸 | 3 | 15 | 0 | 0 | 0 | 0 |
| `v25_plan_reflection_enabled` | plan.py | off | 子闸 | 8 | 24 | 3 | 1 | 0 | 1 |
| `v25_plan_revision_enabled` | plan.py | off | 子闸 | 1 | 10 | 0 | 0 | 0 | 0 |
| `v25_plan_scheduler_enabled` | plan.py | off | 子闸 | 1 | 16 | 0 | 0 | 0 | 0 |
| `v25_plan_step_binding_enabled` | plan.py | off | 子闸 | 5 | 34 | 0 | 0 | 0 | 0 |
| `v25_plan_tool_required` | plan.py | **ON** | 独立 | 7 | 31 | 3 | 0 | 0 | 0 |
| `v25_plan_world_feedback_enabled` | plan.py | off | 子闸 | 2 | 13 | 1 | 0 | 0 | 0 |
| `v25_planning_enabled` | plan.py | off | 总闸 | 11 | 41 | 2 | 0 | 0 | 0 |
| `v26_action_abstraction_enabled` | action_execution.py | off | 子闸 ⚠RESERVED·无行为 | 0 | 1 | 0 | 0 | 0 | 0 |
| `v26_action_debug_enabled` | action_execution.py | off | 子闸 | 2 | 2 | 0 | 0 | 0 | 0 |
| `v26_action_execution_enabled` | action_execution.py | off | 总闸 | 11 | 48 | 2 | 1 | 0 | 3 |
| `v26_action_feedback_enabled` | action_execution.py | off | 子闸 | 1 | 7 | 0 | 0 | 0 | 1 |
| `v26_action_multistep_enabled` | action_execution.py | off | 子闸 ⚠RESERVED·无行为 | 0 | 2 | 0 | 0 | 0 | 0 |
| `v26_action_result_enabled` | action_execution.py | off | 子闸 | 1 | 4 | 0 | 0 | 0 | 1 |
| `v26_action_scheduler_enabled` | action_execution.py | off | 子闸 | 2 | 14 | 0 | 0 | 0 | 1 |
| `v2_action_outbox_enabled` | life_loop.py | off | 独立 | 9 | 16 | 0 | 8 | 0 | 0 |
| `v2_autonomy_advanced_enabled` | autonomy_advanced.py | off | 总闸 | 11 | 69 | 8 | 1 | 0 | 0 |
| `v2_character_action_sync_enabled` | world.py | off | 独立 | 2 | 10 | 1 | 1 | 0 | 0 |
| `v2_development_enabled` | reflection_development.py | off | 总闸 | 9 | 20 | 4 | 2 | 0 | 0 |
| `v2_inventory_grounding_enabled` | world.py | **ON** | 独立 | 1 | 0 | 0 | 1 | 0 | 0 |
| `v2_life_loop_enabled` | life_loop.py | off | 总闸 | 9 | 37 | 1 | 7 | 0 | 0 |
| `v2_memory_enabled` | memory.py | off | 总闸 | 10 | 52 | 6 | 3 | 0 | 0 |
| `v2_memory_vector_enabled` | memory.py | off | 独立 | 4 | 20 | 3 | 1 | 0 | 0 |
| `v2_reflection_enabled` | reflection_development.py | off | 总闸 | 18 | 72 | 10 | 1 | 0 | 3 |
| `v2_relationship_evolved_enabled` | reflection_development.py | off | 总闸 | 8 | 12 | 3 | 2 | 0 | 0 |

> 说明：`app` 列合计 308，与 §2.3 一致。`v2_character_action_sync_enabled` 与 `v2_inventory_grounding_enabled` 是当前 `.env` 中**仅有的两个已开启开关**，转正对它们无行为影响（唯一变化是删掉那层已恒真的判断）。

---

## 附录 B：151 个 `vXX_` 调参字段（仅需改名，无语义变更）

> **改造前口径·已完成**：149 个待去前缀调参字段已随轨道 A 全部改名（见 F.6），本表仅作「旧名 → 领域名」的历史对照；当前字段清单请用 `flag-rename-map.md` §五或 `Settings.model_fields`。

**action_execution.py**（1）

`v26_action_schedule_default_priority`

**agent_runtime.py**（22）

`v21_agent_evolution_interval_seconds`, `v21_decision_weight`, `v21_event_escalation_types`, `v21_evolution_max_drift_per_week`, `v21_evolution_window_days`, `v21_foreground_run_llm_budget`, `v21_goal_medium_timeout_days`, `v21_goal_short_timeout_hours`, `v21_interest_top_n`, `v21_interest_weight_goal`, `v21_interest_weight_memory`, `v21_interest_weight_preference`, `v21_interest_weight_world`, `v21_light_llm_profile`, `v21_metric_breach_streak`, `v21_metric_floor_action_quality`, `v21_metric_floor_decision_quality`, `v21_metric_floor_goal_progress`, `v21_metric_floor_persona_consistency`, `v21_metric_trend_windows`, `v21_state_snapshot_min_interval_minutes`, `v21_state_snapshot_retention_days`

**autonomy_advanced.py**（16）

`v2_autonomy_abandon_min_progress_days`, `v2_autonomy_arbitration_interval_minutes`, `v2_autonomy_goal_max_active_hours`, `v2_autonomy_observation_window_minutes`, `v2_autonomy_planning_llm_profile`, `v2_autonomy_planning_max_attempts`, `v2_autonomy_priority_layer_weight_long`, `v2_autonomy_subgoal_execute_cooldown_minutes`, `v2_autonomy_subgoal_failure_threshold`, `v2_autonomy_subgoal_max_count`, `v2_autonomy_subgoal_max_depth`, `v2_autonomy_supply_interval_minutes`, `v2_autonomy_supply_personal_min_weight`, `v2_autonomy_supply_relationship_min_strength`, `v2_autonomy_supply_templates_json`, `v2_autonomy_supply_world_min_salience`

**life_loop.py**（15）

`v2_life_loop_budget_cache_seconds`, `v2_life_loop_cycle_llm_budget`, `v2_life_loop_daily_llm_call_budget`, `v2_life_loop_daily_llm_token_budget`, `v2_life_loop_degraded_usage_ratio`, `v2_life_loop_memory_digest_chars`, `v2_life_loop_memory_limit`, `v2_life_loop_memory_min_salience`, `v2_life_loop_outbox_backoff_seconds`, `v2_life_loop_outbox_max_attempts`, `v2_life_loop_reflection_check_interval_minutes`, `v2_life_loop_storm_daily_limit`, `v2_life_loop_tick_seconds`, `v2_life_loop_trigger_backoff_seconds`, `v2_life_loop_trigger_max_attempts`

**memory.py**（34）

`v2_embedding_batch_size`, `v2_embedding_batch_window_seconds`, `v2_embedding_dimensions`, `v2_embedding_max_input_chars`, `v2_embedding_model`, `v2_embedding_profile`, `v2_job_max_attempts`, `v2_job_poll_interval`, `v2_job_retry_backoff_seconds`, `v2_job_running_timeout`, `v2_memory_decay_batch_size`, `v2_memory_decay_lambda_json`, `v2_memory_eval_threshold_high`, `v2_memory_eval_threshold_low`, `v2_memory_eval_weight_affinity`, `v2_memory_eval_weight_novelty`, `v2_memory_eval_weight_salience`, `v2_memory_eval_weight_source`, `v2_memory_forget_retention_days`, `v2_memory_hypothetical_triggers_json`, `v2_memory_ingest_max_per_turn`, `v2_memory_llm_fallback_rate_cap`, `v2_memory_penalty_contradicts`, `v2_memory_penalty_rejected`, `v2_memory_reinforce_boost`, `v2_memory_rejected_cooldown_hours`, `v2_memory_retrieval_budget`, `v2_memory_salience_floor`, `v2_memory_temporal_recency_boost`, `v2_memory_transient_triggers_json`, `v2_memory_vector_recall_k`, `v2_memory_weight_affinity`, `v2_memory_weight_semantic`, `v2_memory_weight_structured`

**plan.py**（13）

`v25_plan_context_insight_limit`, `v25_plan_context_memory_limit`, `v25_plan_llm_profile`, `v25_plan_max_depth`, `v25_plan_max_steps`, `v25_plan_memory_importance_floor`, `v25_plan_observation_window_minutes`, `v25_plan_reflection_min_samples`, `v25_plan_replan_min_confidence`, `v25_plan_revision_budget`, `v25_plan_step_cooldown_minutes`, `v25_plan_step_max_attempts`, `v25_plan_ttl_hours`

**reflection_development.py**（36）

`v2_development_answer_min_tokens`, `v2_development_belief_habit_templates_json`, `v2_development_belief_topic_rules_json`, `v2_development_pattern_goal_tier_delta_max`, `v2_development_preference_max_token_delta`, `v2_development_preference_tone_rules_json`, `v2_reflection_ai_inferred_cap`, `v2_reflection_cluster_cosine`, `v2_reflection_confidence_count_curve_json`, `v2_reflection_context_max_items`, `v2_reflection_context_scopes_json`, `v2_reflection_context_statement_chars`, `v2_reflection_event_cooldown_hours`, `v2_reflection_event_threshold`, `v2_reflection_evidence_content_chars`, `v2_reflection_evidence_max_members`, `v2_reflection_invalidate_match_threshold`, `v2_reflection_llm_profile`, `v2_reflection_max_insights_per_run`, `v2_reflection_min_coherence`, `v2_reflection_min_confidence`, `v2_reflection_min_evidence`, `v2_reflection_min_span_hours`, `v2_reflection_run_timeout_minutes`, `v2_reflection_schedule_hour`, `v2_reflection_statement_max_chars`, `v2_reflection_window_days`, `v2_relationship_narrative_daily_cap`, `v2_relationship_narrative_min_confidence`, `v2_relationship_narrative_whitelist_json`, `v2_relationship_pattern_budget_chars`, `v2_relationship_pattern_max_items`, `v2_relationship_pattern_min_strength`, `v2_relationship_shared_budget_chars`, `v2_relationship_shared_limit`, `v2_relationship_shared_min_salience`

**tool.py**（8）

`v24_tool_audit_retention_days`, `v24_tool_breaker_cooldown_seconds`, `v24_tool_breaker_threshold`, `v24_tool_confirm_timeout_hours`, `v24_tool_disabled_ids`, `v24_tool_ext_allowed_hosts`, `v24_tool_ext_manifest_path`, `v24_tool_surface_max_tools`

**world.py**（2）

`v2_character_action_sync_context_lines`, `v2_inventory_grounding_mode`

**world_simulation.py**（4）

`v23_event_escalation_types`, `v23_interest_confidence_threshold`, `v23_llm_assist_sample_rate`, `v23_part_boundaries_json`

> 合计 151。这些字段去掉版本前缀后**只有 2 处撞名**（`v21_event_escalation_types` ↔ `v23_event_escalation_types`，以及 §6.1 的开关撞名），其余可脚本化批量替换。

---

## 附录 C：改造前的建议前置动作

按优先级排序：

1. **先修 RESERVED 标记的失准**（§5.3）。当前 `v23_scene_expansion_enabled` 被标"未接线"却实际接线，会导致删除范围判断错误。
2. **先加 §7.3 的防呆断言**，再动任何字段名。否则改名过程中测试会大面积静默通过，缺陷无法暴露。
3. **先加 §6.2 的未知环境变量告警**，再改 env 名。
4. **先补 `tests/v25/test_plan001_scope_markers.py` 的更新纪律**（该文件是"范围越界已评审"的证据链，不能当普通测试删）。
5. **批次 1 单独作为一个可回滚的提交**，因为它删除的是当前生产实际运行的代码路径。

> 前置动作 1~4 已完成（提交 `a74c5a6`），配套守卫见 `tests/unit/test_settings_flag_guard.py`。

---

## 附录 D：批次 1（v2 段）执行清单

### D.1 已核实的技术前提

**前提一：life_loop 确实覆盖了 `main.py` 旧三循环的全部职责。** 逐条证据：

| 旧循环 | life_loop 中的对应实现 |
|---|---|
| `world_engine.run_world_maintenance_loop()` | `life_loop.py:762-767` `_run_maintenance` → `world_engine.run_maintenance` |
| `run_action_retry_loop()` | `life_loop.py:778-805` `_run_maintenance` → action retry |
| `autonomy_worker.run_autonomy_worker()` | `life_loop.py:338` → `autonomy_engine.tick(user_ids=[user_id])`（按用户粒度，替代旧的全量 tick） |
| （另含）世界模拟维护 | `life_loop.py:770-776` → `world_engine.run_simulation_maintenance` |
| （另含）trigger 对账 | `life_loop.py:817-824` `trigger_reconcile` |

`autonomy_worker.py` 自身的 docstring（`:3-5`）也明确写着"life_loop 为唯一周期入口，本 worker 仅作为其关闭时的兜底 tick 源"。

**前提二：`v2_life_loop_enabled` 的 OFF 回退路径依赖的 DB 表已存在。** `trigger_evaluator.py` 的 5 处 `v2_life_loop_enabled` 分支在 ON 时走 `trigger_registry_repository`（持久化登记表），OFF 时回退内存 dict（docstring 称"迁移窗口内 drain 遗留 dict 登记项"）。该表由 `migrations/versions/0028_trigger_registry.py` 建立，已在迁移链内，**无需新迁移**。

### D.2 规模（脚本实测）

| 维度 | 数量 |
|---|---|
| `app/` 门控点 | **63**（guard 33 / branch 27 / getattr 3） |
| settings 字段定义 | **8**（分布在 4 个文件） |
| 测试调用点 | **207**（`override_settings` kwarg 200 / `setenv` 3 / `settings.X` 4） |
| 受影响测试文件 | **69** |

### D.3 逐 Flag 站点分布

| Flag | app 站点 | 测试 kwarg | 定义处 | OFF 路径性质 |
|---|---|---|---|---|
| `v2_life_loop_enabled` | 8 | 19 | `life_loop.py:9` | **删 3 个旧循环 + 整模块 `autonomy_worker.py` + trigger 内存回退** |
| `v2_autonomy_advanced_enabled` | 9 | 56 | `autonomy_advanced.py:11` | 纯 guard（自治步转常开） |
| `v2_action_outbox_enabled` | 8 | 14 | `life_loop.py:18` | 纯 branch（outbox 转常开） |
| `v2_memory_enabled` | 9 | 33 | `memory.py:28` | **双路径 D3/D4：删 memory v1 的 ingest/retrieve** |
| `v2_memory_vector_enabled` | 4 | 1 | `memory.py:29` | 纯 guard（向量召回转常开） |
| `v2_reflection_enabled` | 14 | 64 | `reflection_development.py:11` | 纯 guard + 3 处 getattr |
| `v2_development_enabled` | 6 | 12 | `reflection_development.py:40` | 纯 guard（成长层转常开） |
| `v2_relationship_evolved_enabled` | 5 | 1 | `reflection_development.py:59` | **双路径 D5：删 `relationship_pattern_list=[]` 回退** |

### D.4 执行顺序（4 步，不可只做一半）

1. **app 侧去门控**（63 处）：`main.py` 结构改造（删 `else` 段三循环 + 3 个全局量 + cancel 循环）→ 删 `autonomy_worker.py` → 逐模块摘 guard/branch，双路径保留 ON 侧、删除 OFF 侧。
2. **删 settings 字段**（8 个）+ 清理 `enablement.py` 的 v2 段（`v2_autonomy_advanced_enabled` / `v2_action_outbox_enabled` 的依赖判定）。
3. **修测试**（207 处 / 69 文件）：`override_settings(v2_*=...)` 调用点逐个删除——新增的 `set_known_env` 守卫会**逐个报出**失效 env key，等于自带工作清单。断言 `skip_reason == "flag_disabled"` 与 `enabled=False` 契约的用例按 §7.4 改写或删除。
4. **验证**：`pytest -q` 对比基线（§7 说明 HEAD 本就有 ~21 个既存失败），加 `grep` 残留扫描。

### D.5 为什么不能只做一半

`main.py` 的旧三循环是 `v2_life_loop_enabled` 的 `else` 分支。若只摘掉 `else` 而保留 `v2_life_loop_enabled`（默认 off），则**两个调度器都不启动**——应用会静默失去全部周期行为。因此第 1 步必须与「`v2_life_loop_enabled` 字段删除」同批完成。

### D.6 本批次无法在此环境验证的部分

- **真实模型行为回归**：`docs/version/v2.0.0/phases/*/regression-checklist.md` 各阶段清单必须人工执行。
- **首次激活的写入路径**：`v2_memory_enabled` 固化 ON 后首次运行会走 memory V2 的 ingest/evaluate 与向量嵌入，这些路径在真实配置下**从未跑过**。建议在独立数据库上先跑一轮再切正式库。

---

## 附录 E：`v2_action_outbox_enabled` 单独评估

批次 1 执行时发现它与 v26 反馈设计存在冲突，用户裁决「本批次不动它，单独评估」。以下是评估结论。

### E.1 现状

| 维度 | 事实 |
|---|---|
| app 侧读取点 | **8 处**：`action_engine.py:793`（`integrate_result` 分派）、`life_loop.py:797`（维护步消费）、`life_loop.py:844`（idle 判定）、`capabilities/reminder.py:60,102`、`capabilities/world_action.py:53,91,115` |
| 测试侧引用 | 22 处 / 15 个文件 |
| 默认值 | `False` |
| **`.env` 设置** | **未设置 → 生产实际一直走内联直写路径** |
| 所属任务 | V2.0.0 LIFE-004「跨域投递延迟化」 |

### E.2 关键判断：它不是"冗余开关"，OFF 是"灰度未完成"的临时状态

三条设计文档证据：

1. **v24 工具系统架构要求它开启**。`docs/version/v2.4.0/tool-system/architecture.md:869`：「Tool System **不**直接写世界（必须经 `world_engine` 函数 + **outbox 延迟投递**）」；`:783`：「世界写入不经工具直接落库：写 `deferred_world_op` → outbox（V9 既有延迟投递）」。`capabilities/*` 里的 `deferred_world_op` 分支正是这条要求的实现——**只有开关开启时 v24 架构才被满足**。

2. **LIFE-004 的动机是「不丢不重」**。`LIFE-004.md:13`：v1 的跨域投递发生在能力执行的多个事务里，**进程在任意两点之间崩溃都会留下半完成状态且无恢复线索**；outbox 把「行动成功」与「世界知道」解耦为两个可重放的事务（幂等键 = `action_id`），文档称其为 `data-flow.md §2.1 裁决的直接落地`。

3. **它的灰度从未完成**。`LIFE-004.md:24` 明确：「outbox 的端到端灰度**依赖评审通过后开启 v9**（**评审项，非本 Task 改动**）」。即 OFF 状态是**刻意保留的未评审状态**，不是设计选择。

### E.3 与 v26 反馈设计的冲突（批次 1 撞上的）

`v26` 的 feedback 投影 `feedback_kinds` 在 `integrate_result` 时计算。outbox 开启后世界操作被**延迟**到消费器，此刻世界尚未变更，故 `feedback_kinds` 里不再出现 `"world"`。受影响的 4 个用例：
`tests/v26/test_v26_feedback_consumers.py`(3) + `tests/v26/test_v26_source_semantics.py`(1)。
同类还有 `tests/v24/test_tool008_integration.py`(4，行动记忆投递由「直写」改为「经 outbox + P1 摄取补扫收敛」)。

**这不是测试写错了，是 v26 的反馈设计假设了内联世界写入，而 v24/LIFE-004 假设了延迟投递。**

### E.4 三条路的成本

| 方案 | 内容 | 成本 | 风险 |
|---|---|---|---|
| **① 固化 ON** | 删开关，落地既定架构；同时把 v26 的 world 反馈计算从 `integrate_result` 移到消费器之后 | 8 处 app 去门控 + 约 10 个用例改写 + **v26 反馈时序设计变更** | **中高**：等于上线一个 LIFE-004 明确标注"评审未通过"的架构变更；且改变了"行动成功即世界已变更"的既有语义 |
| **② 固化 OFF** | 删开关与整条 outbox 路径（`outbox_consumer.py`、`outbox_events` 表、`deferred_world_op` 载荷、`save_record_with_outbox`、`test_life004_outbox.py`） | 删除一个 V2.0.0 正式任务的全部产物；v24 架构要求无法满足；`test_g_world_outbox_is_the_only_write_path` / `test_s5_*` 等 4~6 个用例废弃 | **高**：放弃「不丢不重」保障，且与 v24 架构文档冲突 |
| **③ 改名保留**（去 `v2_` 前缀） | 字段改名 `action_outbox_enabled`，env 名同步 `ACTION_OUTBOX_ENABLED`（无撞名） | 8 处 app + 22 处测试的**机械改名**；行为零变化 | **低** |

### E.5 结论与建议

**建议方案 ③：改名保留，等 LIFE-004 的灰度评审完成后再决定固化方向。**

理由：

1. **用户的核心诉求是"版本号污染代码审查"，不是"开关本身有罪"。** 改名去 `v2_` 前缀即可消除污染，且行为零变化、零风险。
2. **固化 ON 会把一个明确标注"评审未通过"的架构变更推进生产**，且需要改动 v26 的反馈时序设计——这超出了"删开关"的范围，应当走独立的设计评审。
3. **固化 OFF 会删除 V2.0.0 的一个正式任务，并与 v24 架构文档直接冲突**，代价最大。
4. LIFE-004 文档自己写了灰度前置条件是"评审通过后开启 v9"，**这个前置条件尚未满足**——在它满足前，开关必须保留。

**如果后续确定要固化 ON**，则必须先做一件事：把 v26 的 world 反馈计算从 `integrate_result` 迁到 outbox 消费之后（或在消费时补写投影），否则 `feedback_kinds` 会永久丢失 `"world"`。

### E.6 改名执行的注意点

- 字段 `v2_action_outbox_enabled` → `action_outbox_enabled`；env `V2_ACTION_OUTBOX_ENABLED` → `ACTION_OUTBOX_ENABLED`。已确认**无撞名**（既有字段为 `action_enabled` / `action_detector_enabled` / `action_memory_policy_enabled`）。
- 同批可一并处理 `v2_character_action_sync_enabled`、`v2_inventory_grounding_enabled`（同为 `v2_` 前缀的独立开关，且都在 `.env` 中已开启）——这三者构成「`v2_` 段残留开关」的完整集合。
- 本仓库有 `set_known_env` 防呆守卫，改名前先加「env key ∈ `model_fields`」断言已就位（前置防呆第 2 条已完成）。

---

## 附录 F：批次执行台账（实测 2026-09-18）

> 执行期现状快照，替代 §8 表头的估算计数与 §2 的改造前口径。数据由脚本实测（`app/`、`tests/`、`.env`、`git log`），非估算。
> 配套提交：`a74c5a6`（前置防呆）、`68d85ac`（批次 1 去门控）、`93dcb1e`（批次 1 收尾改名）。

### F.1 批次进度与实测规模

「app 引用 / 测试引用」为开关名在对应目录中出现的总次数（`app/` 侧已排除 `app/core/settings/`；测试侧含 `.md`），含 docstring 与注释提及，故大于门控点数。

| 批次 | 版本 | 开关数 | 其中默认 ON | app 引用 | 测试引用 | 待删 OFF 回退路径 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | v2 段 | 7（已删）+ 3（改名保留） | — | 63 处门控（见 D.2） | 207 调用点 | 5（§4.1 #1~#4 + D 段） | **已完成** |
| 2 | v21 | 6 | 0 | 51 | 19 | 2（§4.2 #16、#17） | **已完成**（F.10/F.11/F.12；`foreground_gateway_enforced` 保留门控） |
| 3 | v22 | 5 | 0 | 19 | 15 | 0 | **已完成**（见 F.9） |
| 4 | v23 | **8** | 0 | 79 | 47 | 3（§4.1 #5、§4.2 #14/#15） | **已完成**（F.14） |
| 5 | v24 | 11 | 1（`v24_tool_confirm_ttl_reuse`） | 106 | 272 | 1（§4.2 #9） | 待做（测试量最大） |
| 6 | v25 | **14** | 2（`v25_plan_tool_required`、`v25_plan_context_digest_enabled`） | 103 | 266 | 6（§4.2 #7/#8/#10~#13） | 待做（依赖面最广） |
| 7 | v26 | **7** | 0 | 35 | 76 | 1（§4.2 #6） | 待做 |
| 8 | 收尾 | — | — | `enablement.py` 284 行 / 146 处版本名 | — | — | 待做（必须最后） |

**上表为轨道 A 之前的快照，两处口径已过时**（2026-09-18 重测）：

| 维度 | 表内 | 当前 | 说明 |
|---|---|---|---|
| 开关总数 | 6+5+8+11+14+7 = 51 | **48** | 第 0 步删 3 个死开关（F.7）：v23 8→**7**、v26 7→**5** |
| app 引用 | 308（§2.3 旧口径含 v2 段） | **234 处 / 53 个模块** | v21 27 / v22 8 / v23 50 / v24 81 / v25 53 / v26 15 |
| 表内开关名 | `v24_tool_confirm_ttl_reuse` 等 | **全部已去前缀** | 按旧名 grep 现在 0 命中；导出清单请用 `flag-rename-map.md` §四 |
| 轨道 A（去前缀） | 未列 | **已完成并提交** | 与批次划分正交，见 F.6 |

**执行顺序**：G.5 已把「改名」与「去门控」拆成两条轨道，轨道 A 做完后轨道 B 不再受改名依赖约束，因此按**风险递增**而非 §8 的依赖序执行：**v22（已完成）→ v21（已完成）→ v23（已完成）→ v24 → v25 → v26 → 收尾删 `enablement.py`**。

**批次 1 的实际边界**（与本报告 D.3 / E.5 的差异）：

- **删除 7 个字段**：`v2_life_loop_enabled`、`v2_autonomy_advanced_enabled`、`v2_memory_enabled`、`v2_memory_vector_enabled`、`v2_reflection_enabled`、`v2_development_enabled`、`v2_relationship_evolved_enabled`；连带删除 `app/application/autonomy_worker.py`（整模块）与 `main.py` 旧三循环。
- **改名保留 3 个开关**（附录 E 方案③）：`action_outbox_enabled`、`character_action_sync_enabled`、`inventory_grounding_enabled`；另有 2 个相关调参字段随同改名（`character_action_sync_context_lines`、`inventory_grounding_mode`），即批次 1 共改名 5 个字段。注意 `v2_life_loop_outbox_max_attempts` / `v2_life_loop_outbox_backoff_seconds` **沿用原名**，仍计入 F.3 的 149 个待改名调参。
- 因此 D.2 的「settings 字段定义 8」应读作「7 删 + 1 改名」；`enablement.py` 中 v2 段与 v25 对 v2 的跨版本依赖条目已同步移除。

### F.2 §8 需修订之处（执行前必读）

| # | §8 原文 | 实测 | 影响 |
|---|---|---|---|
| 1 | 批次 4「v23（7 个）」 | **8 个** | 漏做 1 个 |
| 2 | 批次 6「v25（13 个）」且清单未列 `v25_plan_context_digest_enabled` | **14 个** | 漏做 1 个 |
| 3 | 批次 7「v26（6 个）」 | **7 个**（转正 5 + 直删 2） | 账目错位 |
| 4 | 表头合计 6+5+7+11+13+6 = 48 | **51**（与附录 A 的 61−10 一致） | 与附录 A 自相矛盾 |
| 5 | 批次 6 依赖「`v25_planning_enabled`（依赖 `v2_autonomy_advanced_enabled` + `v2_life_loop_enabled`）」 | 该依赖**已随批次 1 消失**（`enablement.py` 对应条目已移除） | 排序理由过时；批次 6 仍须最后做（内部依赖 v24/v21 仍在） |

> 执行任何一批前，请从**附录 A** 重新导出该批开关清单，不要沿用 §8 表头计数。

### F.3 剩余字段口径（去前缀工作量的完整盘子）

| 模块 | 开关 | 调参 | 版本段 |
|---|---|---|---|
| `agent_runtime.py` | 6 | 22 | v21 |
| `experience.py` | 5 | 0 | v22 |
| `world_simulation.py` | 8 | 4 | v23 |
| `tool.py` | 11 | 8 | v24 |
| `plan.py` | 14 | 13 | v25 |
| `action_execution.py` | 7 | 1 | v26 |
| `life_loop.py` | 0 | 15 | v2（仅剩调参） |
| `memory.py` | 0 | 34 | v2（同上） |
| `autonomy_advanced.py` | 0 | 16 | v2（同上） |
| `reflection_development.py` | 0 | 36 | v2（同上） |
| **合计** | **51** | **149** | 共 **200 个待去前缀字段** |

去前缀后仍为 **2 处撞名**（与 §6.1 一致，无新增）：`v21_event_escalation_types` ↔ `v23_event_escalation_types`；`v23_world_llm_assist_enabled` ↔ 既有 `world_llm_assist_enabled`。

### F.4 环境变量现状与「首次上线」性质

**轨道 A 执行后的现状**（2026-09-18 实测）：

| 文件 | `VXX_*` 行数 | 跟踪状态 |
|---|---|---|
| `apps/backend/.env.example` | **0**（原 38 行已随字段改名去前缀） | 已跟踪 |
| `apps/backend/.env` | **0**（内容与上表一致） | **未跟踪**（`apps/backend/.gitignore:13`） |

`.env` 中当前**只有 2 个开关为 `true`**：`CHARACTER_ACTION_SYNC_ENABLED` 与 `INVENTORY_GROUNDING_ENABLED`（两者已在批次 1 去 `v2_` 前缀）。其余 51 个待转正开关——含 `.env` 未列出的 v21 / v22 / v25 全部，以及 `.env` 中显式写 `false` 的 v23 / v24 / v26——**取值全为代码默认 off**。

启动侧的静默回落告警已就位：`app/main.py:47` 调 `unknown_versioned_env_keys()`，对形如 `V<数字>_` 且不对应任何字段的遗留键打 warning。注意它**只识别带版本前缀的旧键**；轨道 A 之后的改名把旧键也变成了无前缀形式（如 `WORLD_SIMULATION_ENABLED`），这类"改了名但运维侧没同步"的键不会触发告警——**部署侧 `.env` 必须逐条比对 `flag-rename-map.md` 的「旧 env」列更新**。

因此 **轨道 B 的每一批都是对应路径的首次上线**（§1.2 前提一的具体形态）。每批必须配套执行 `docs/version/<version>/*/regression-checklist.md`，且部署侧 `.env` 副本须同批更新。

### F.5 测试基线（2026-09-18）

```
.venv/Scripts/python.exe -m pytest -q -n 4 --timeout=180 --basetemp=<仓库内目录>
=> 24 failed, 6434 passed, 22 skipped, 3 warnings in 202.05s
```

**环境坑**：`-n 4` 配合默认 basetemp 时，Windows 上 `pytest-current` 符号链接会抛 `PermissionError: [WinError 5]` 使整轮中断（实测已踩）。必须显式 `--basetemp=<仓库内目录>`。

**批次 1 新增的 3 个失败（均为「冻结面零 diff」守卫）**：

| 用例 | 冻结文件 |
|---|---|
| `tests/v24/test_tool010_e2e.py::test_zero_diff_frozen_surfaces` | `app/services/action/capabilities/reminder.py` |
| 同上 | `app/services/action/capabilities/world_action.py` |
| 同上 | `app/application/chat_pipeline.py` |

判定方式：对同一文件取 `b3f5100`（批次 1 前）与工作区字节分别做 sha256，前者与记录值一致、后者不一致。

另有 3 个文件在批次 1 **之前**即已失配（`app/character/asuna/action.py`、`app/application/post_process.py`、`app/application/action_engine.py`），属既存失败，不计入新增。

**24 个失败的初步归因**（供批次 2 逐条比对）：

| 类别 | 数量 | 说明 |
|---|---|---|
| 批次 1 新增 | 3 | 源码哈希冻结（G.3 第一类） |
| 源码哈希冻结·既存 | 4 | 同上，含 `tool008` 的 `asuna/action.py` |
| 表结构与迁移冻结·既存 | 7 | G.3 第二类，与本次改造无关 |
| 其它既存 | 10 | `e2e`（3）、`v2`/`v21`/`v23`/`v25`/`v7.8` 各 1、`tool010` 四步用例 1 等 |

**基线日志已失效**：原文记录的 `.workbuddy/tmp/pytest-baseline2.log` 是本地件、不入库，现已不存在；且该路径违反 `apps/backend/AGENTS.md` 的临时件约定——**临时输出统一落 `apps/backend/.tmp/`**。`--basetemp` 同理应指向 `.tmp/` 下的目录。**当前有效基线以 F.6 为准**，每批开动前重跑一次并逐条归因增量。

### F.6 轨道 A（去前缀）执行结果 —— 2026-09-18

按 G.5 建议拆出的两条轨道中，**轨道 A（纯改名，零行为变化）已执行**；轨道 B（去门控）尚未开始。

| 项 | 改造前 | 改造后 |
|---|---|---|
| settings 字段总数 | 427 | **422**（步骤 0 删 2 个未接线字段 + 第 0 步删 3 个死开关，见 F.7） |
| 带 `vXX_` 前缀 | 200 | **0** |
| 其中开关 / 调参 | 51 / 149 | 0 / 0 |
| 后端全量测试 | 24 failed / 6434 passed / 22 skipped | **16 failed / 6443 passed / 22 skipped** |
| 前端 | — | vitest 29 文件 / 149 用例全绿；`tsc -b` 通过 |
| 提交状态 | — | **已提交 `992f05c`**（`refactor: 设置字段去版本号前缀`），随批次 1 的 `68d85ac` / `93dcb1e` 一并推送到 `origin/feat/feishu_bot` |

- 改动规模：265 个文件、2367 处替换；范围含 `app/`、`tests/`、`scripts/`、`apps/frontend/src/`、`.env`、`.env.example`，**不含 `docs/`**。
- 撞名裁决执行情况：`world_llm_assist_*` 采用「删除未接线对」（§6.1）；`event_escalation_types` 采用 `agent_` / `world_` 前缀（§6.2）。命名一致性建议（对照表 §七）**未采纳**，保持机械去前缀结果。
- 失败差额 = 8 条冻结哈希用例修复 + 0 新增；另 2 条 `tests/v7.8/test_performance.py` 用例经 3 次单跑确认为计时 flaky，与本次改造无关。
- 剩余 16 条失败全部落在 F.5 的既存类别（表结构/迁移冻结 7 + 其它 9）。
- 明细与逐步清单见 `docs/refactor/flag-rename-map.md` §九；部署侧 `.env` 需按该表「旧 env」列同步改名（旧键会被 `extra="ignore"` 静默吞掉，告警的覆盖范围见 F.4 的限定）。

### F.7 第 0 步：死开关与 RESERVED 标记清除 —— 2026-09-18

§5.1 / §5.2 判定为「应删除而非转正」的 3 个开关已删除，**零行为变化**（它们在 `app/` 中不产生任何分支）：

| 开关 | 删除依据 | 连带删除 |
|---|---|---|
| `action_abstraction_enabled` | `app/` 0 处读取 | `RESERVED_V26_SUB_FLAGS` 常量、`action_reserved_flag_warnings` |
| `action_multistep_enabled` | `app/` 0 处读取；V2.6.1 裁决 `action_plan_max_steps` 仍为 1 | 同上 |
| `habit_time_enabled` | 仅出现在 `world_engine._V23_FLAG_NAMES` 调试快照，无行为分支 | `RESERVED_V23_SUB_FLAGS` 常量、`world_sim_reserved_flag_warnings` |

- 开关总数 51 → **48**；轨道 B 待转正清单相应缩短（v23 由 8 → 7、v26 由 7 → 5）。
- `validate_enablement_chain` 现只剩 `tool_permission_sub_layer_warnings` 一条提示分支；启动校验与 v26 依赖链本身不变。
- `world_engine.v23_flag_snapshot()` 输出由 8 键变 **7 键**——`tests/v23/test_ws018_debug_api.py` 的键数断言随之更新；前端 `WorldSimPanel.test.tsx` 的 mock 去掉该键。
- `tests/unit/test_settings_flag_guard.py` 的 `TestReservedFlagMarker` 整类删除（被测的 RESERVED 语义已不存在），文件收敛为纯 env 键守卫；`_gate_sites()` 辅助函数一并移除。
- `.env` / `.env.example` 顺带修正一处**失准注释**：`SCENE_EXPANSION_ENABLED` 原标「RESERVED·尚未接线」，实际已接线（§5.3 的同一处矛盾），改为按事实描述。
- 冻结面同步：`tests/v24/test_tool007_integration.py::FROZEN_SOURCES` 的 `app/application/world_engine.py` 哈希重建（属 G.3 第一类的允许改动，提交信息须写明）。

### F.8 当前有效测试基线与豁免清单（2026-09-18，第 0 步之后）

替代 F.5 / F.6 的历史计数。**每批开动前重跑，只对本清单之外的新增失败负责。**

```
.venv/Scripts/python.exe -m pytest -q -n 4 --timeout=180 --basetemp=.tmp/pytest-bt
=> 15 failed, 6439 passed, 22 skipped in 101.93s
```

**观测到的抖动区间是 15~18 failed**：e2e 流式用例（3~4）与 `test_performance` 计时用例（1~2）在多次运行间翻转，非重构引入。判据应为「失败 ID 集合 ⊆ 本清单」，而非失败数相等。

| 类别 | 数量 | 用例 ID | 处置 |
|---|---|---|---|
| **表结构与迁移冻结**（G.3 第二类） | 7 | `v24/test_tool007_integration.py::test_no_new_tables_in_metadata`、`v24/test_tool008_integration.py::{test_no_new_migrations, test_no_new_tables_in_metadata}`、`v24/test_tool012_bans.py::test_session_tables_zero_structural_change`、`v24/test_tool_acceptance.py::{test_migration_chain_head_is_0046, test_zero_migration_model_structure_unchanged, test_zero_migration_reconciliation_records_0046_breakpoint}` | **豁免**：本次改造不触碰 `app/models/` 与 `migrations/`；每批归因时整类排除 |
| **其它既存（稳定）** | 4 | `v2/test_aut005_goal_evaluation.py::TestRules::test_clean_slice_passes_all`、`v21/test_agent008_review_fixes.py::TestLowEnergySuppression::test_low_energy_suppresses_short_term`、`v23/test_ws004_day_cycle.py::test_maintenance_step_emits_markers`、`v25/test_plan010_regression.py::TestEndToEndLoop::test_s1_plan_evidence_becomes_an_insight_and_triggers_a_replan` | **豁免**，但其中 `test_maintenance_step_emits_markers` 已查明是**日期漂移**（硬编码 `time:day_start:2026-09-14`，而 `run_simulation_maintenance` 按真实当天推进）——批次 v23 会重写该路径，届时一并修正 |
| **flaky** | 4（浮动） | `e2e/test_chat_http_integration.py::test_http_chat_streams_chunks_incrementally`、`e2e/test_memory_e2e.py::test_extractor_failure_does_not_break_sse`、`e2e/test_turn_meta_stream.py::test_stream_emits_turn_meta_before_first_delta_and_done_carries_turn_id`、`v7.8/test_performance.py::test_observability_overhead_within_budget`（`v8/test_world_performance.py` 与 `e2e/test_debug_trace_persist.py` 亦偶发） | **豁免**：单跑复现或三轮内翻转即判 flaky |

跑法备忘（Windows）：必须显式 `--basetemp=.tmp/pytest-bt`，否则 `pytest-current` 符号链接抛 `PermissionError: [WinError 5]` 中断整轮（实测已踩两次）。

**抖动成员池（v22 批与 v21 批 1 四轮全量观测累计）**——失败数在 **15~20** 间浮动即视为正常，判据始终是「失败 ID 集合 ⊆ F.8 三类的并集」：

- `tests/e2e/`：`test_chat_http_integration::test_http_chat_streams_chunks_incrementally`、`test_memory_e2e::test_extractor_failure_does_not_break_sse`、`test_turn_meta_stream::test_stream_emits_turn_meta_before_first_delta_and_done_carries_turn_id`、`test_debug_trace_persist::test_lru_evicted_turn_falls_back_to_db`、`test_debug_state_history::test_state_reflects_turn_and_respects_limit`、`test_log_redaction::test_reply_not_logged_in_full_at_info_level`
- 计时类：`v7.8/test_performance::test_observability_overhead_within_budget`、`v7.8/test_performance::test_capture_does_not_change_sent_prompt_bytes`、`v8/test_world_performance::test_world_assembly_overhead_within_budget`

**e2e 目录不可串行判定**：`pytest tests/e2e -n 0` 会出 **12 条失败**（含 `test_v65_matrix.py` 整文件 6 条），而 `-n 4` 分片后只剩个位数——该目录用例之间存在状态泄漏，串行结果不能用作「新增失败」的证据。上面 6 条 e2e 抖动成员均满足「单跑必绿」，已逐条验证。

### F.9 轨道 B 批次 v22（体验层）去门控 —— 2026-09-18

提交 `52c6a87`。**首个真正的行为变更批**，但 §四 判定的 OFF 回退路径为 0 条——删的不是在跑的代码，而是「从未跑过的代码」的门控。

| 项 | 内容 |
|---|---|
| 删除开关 | `experience_enabled` / `style_contract_enabled` / `emotion_transition_enabled` / `relationship_addressing_enabled` / `habit_runtime_enabled`（5 个，全部 off→常开） |
| 整域文件消失 | `app/core/settings/experience.py` **只含这 5 个字段、无调参** → 整文件删除 + `Settings` 继承表去掉一项（25 领域类 → 24）；字段总数 422 → **417** |
| 门控站点 | `chat_pipeline._build_style_context`（总闸早返回，删后 `settings` 局部量一并移除）、`style_context.build_style_context`（双闸早返回） |
| 旋钮收口（裁决：彻底常开） | `assemble_style_contract` 的 `include_addressing/emotion/habits` 三形参与三处 `if` 删除；连带 `_apply_emotion` 的 `relationship_modulation` 与 `_resolve_conflicts` 的 `resolve_expressiveness` 也收成无条件。**依据**：全仓库无任何调用点传过非默认值，且三个默认值本就是 `True` |
| enablement | v22 段（四子闸 → 总闸）循环删除 |
| 测试 | 删 4 个门控矩阵用例（flags off / 仅总闸+风格闸 / relationship 闸关 / emotion 闸关）+ 1 个 skipped 用例 + 1 个 enablement 文案用例；改 3 个为无条件断言；`test_tool001_enablement` 的 v22 链断言删除（用例改名 `test_existing_v21_v23_chain_rules_intact`）。**净 -216 行** |
| 冻结面 | `test_tool010_e2e.py::ZERO_DIFF_HASHES` 的 `chat_pipeline.py` 哈希重建（允许改动）；一条根因同时解释 `test_four_step_tool_addition_keeps_pipelines_untouched` 的失败 |
| 验证 | v22/v24-tool001/v23-ws019 相关 **179 用例全绿**；Fast Test（`-m "(unit or api) and not slow"`）**1449 全绿**；全量 **16 failed / 6431 passed**，失败 ID 集合 **⊆ F.8 豁免清单，零新增归因**；前端无 v22 引用，零改动 |

**行为变化与验证缺口（必读）**：固化后**前台每一轮回复的 prompt 恒带 `【本轮表达风格】` 段**，真实模型的称呼/语气/情绪强度/习惯指令全部进 prompt。单元测试与 golden 快照**都测不到**它（golden 用例不传 `style_ctx`，实测零命中），因此本批补建了 `docs/version/v2.2.0/regression-checklist.md`（同时关闭 `v2.2.0/acceptance-report.md` 四.4 的「建议补 regression-checklist」遗留项）。**该清单尚未执行——它是 v22 上线的前置条件，不是可选项。**

部署侧注意：v22 的 5 个键从未出现在 `.env`，本批**零 env 变更**；但若运维副本里自行加过 `EXPERIENCE_ENABLED` 之类，删字段后它们变成**无前缀的未知键**，`unknown_versioned_env_keys()` 只识别 `^V<数字>_`，**不会告警**（F.4 已限定）。

### F.10 轨道 B 批次 v21-1（目标栈 + 度量 + 演化）去门控 —— 2026-09-18

v21 段按风险拆三批执行（F.11 = `agent_runtime_enabled`、F.12 = `unified_run_enabled`），本批先做**纯增量**的三个开关。

| 项 | 内容 |
|---|---|
| 删除开关 | `goal_stack_enabled`、`agent_metrics_enabled`、`personality_evolution_enabled`；字段 417 → **414**；在存开关 43 → **40** |
| 门控站点（7 处） | `goal_stack.evaluate_stack` 空栈早返回、`goal_stack._apply_evolution_rebalance`、`agent_evaluation.run_daily_snapshot`、`evolution.compile_personality` 与 `propose_rebalance`、`autonomy_engine` 的 `stack=` 三元、`chat_pipeline` 的 `layered_goals` 扩展与 `stack=` 三元、`context_builder` 的 `layered_goals=[]` |
| 辅助量收口 | `agent_evolution_worker.metrics_enabled()` / `evolution_enabled()` 删除；`enabled()` 由三条件复合式简化为 `agent_runtime_enabled`（真正门控留到 F.11）；`chat_pipeline` 与 `goal_stack` 内失去用途的 `settings` 局部量一并移除 |
| enablement | v21 段 5 条规则中删掉 4 条（涉及本批三字段的总闸依赖与「演化⇒度量」链），仅存 `unified_run_enabled ⇒ agent_runtime_enabled` |
| 测试（9 文件） | 删 3 个 flag-off 用例（`test_empty_stack_when_flag_off`、`test_flag_off_no_drift`、`test_flag_off_skips`）与 2 个 enablement 用例类；`ALL_V21_FLAGS` 与 4 个 fixture 收敛为 `AGENT_RUNTIME_ENABLED` 一项；`test_plan007_candidates.stack_on` 只留 `world_enabled=false`；三处链用例改用 `unified_run_enabled` 作存活样本 |
| 冻结面 | `chat_pipeline.py` 哈希第二次重建（本批摘掉其内两处 `goal_stack_enabled`） |
| 验证 | v21/v24/v25 相关 **192 + 1449** 全绿；全量两轮 **20 → 18 failed**，稳定核心（7 表结构 + 4 既存）不变，新增项全部落在 F.8 抖动池（其中 2 条 tool010 由哈希重建消解，其余 e2e/perf 单跑必绿） |

**批前复核的两点更正（重要，供后续批次与 §4 清单读者）**：

1. **§4 漏记一条 v21 的字面 sibling `else`**：`life_loop.py:93-99` 是 `if agent_runtime.enabled(): run_autonomous_cycle(...) else: _run_user_cycle(...)`——`_run_user_cycle` 是**当前实际在跑**的 v2.0.0 自治循环，固化 `agent_runtime_enabled` 会删掉它并换用 `run_autonomous_cycle`。`controller.py:200-202` 自陈差异三处：台账多落 `run_kind`/`profile`、decision **新增第三道 Gateway 闸**、支持事件升级触发源。且软模式豁免只覆盖 `budget_type == "foreground"`（`llm_gateway.py:105,111`），自治能力不在其内 → decision 可能以 `skip_reason=gateway_denied` 被静默跳过（`controller.py:256`）。**裁决：接受为 V2.1.0 既定设计**，并在 v2.1.0 regression-checklist 增补「跑满自治周期、统计 `gateway_denied` 出现率」专项条目。
2. 删 `_run_user_cycle` 还牵动 3 个 v25 测试的**源码文本锚点**（`test_plan003_mount.py:256`、`test_plan005_mount.py:91,103`、`test_plan011_steps_accounting.py:185` 用 `source.split("async def _run_user_cycle", 1)[1]` 断言步骤挂载），须迁到 `run_autonomous_cycle`。

**`foreground_gateway_enforced` 裁决：保留门控，不固化**。理由：`light_llm_profile` 代码默认 `""` 且 `.env.example` 无该键，固化 ON 后 `resolve_answer_llm` 在预算耗尽时抛 `GatewayDeniedError`——**用户该轮回复直接失败**。与附录 E 的 `action_outbox_enabled` 同类：门控不是冗余，而是前置条件未满足。字段已无前缀（F.6），保留零污染；要推翻本裁决，须先让 `light_llm_profile` 成为必配项。

### F.11 轨道 B 批次 v21-2（`agent_runtime_enabled`）去门控 —— 2026-09-18

**本改造至今风险最高的一批**：删掉的是当前实际在跑的自治循环实现（§4.1 型活路径替换，且是 §4 清单漏记的那条）。

| 项 | 内容 |
|---|---|
| 删除字段 | `agent_runtime_enabled`（字段 414 → **413**；在存开关 40 → **39**） |
| 活路径替换 | `life_loop` 的 `if agent_runtime.enabled(): … else: _run_user_cycle(…)` 改为无条件走 `run_autonomous_cycle`；**删除 `life_loop._run_user_cycle`（105 行）与随之变孤儿的 `_append_step`、`_step_action_schedule`** |
| 连带删除 | `agent_runtime/controller.enabled()`（含 `__init__` 的 import 与 `__all__`）、`agent_evolution_worker.enabled()` 及 `run_evolution_tick` 的 `flag_disabled` 早返回、`agent_state_assembler` 的字段判据、`autonomy_engine._pipeline_intention` 的早返回、`main.py` 的 worker 条件启动（改为常驻） |
| **本批引入并被当场抓到的 bug** | `enablement.V25_DEPENDENCIES` 残留 `plan_autonomy_enabled ⇒ agent_runtime_enabled`；字段删除后 `getattr(…, False)` 使该条**恒判配置错误**（`plan_autonomy_enabled` 一开就启动失败）。已删该条 + 同步 `plan002/plan012` 两处依赖表钉测（⑦ → ①~⑥、`len>=6 → >=5`）。**教训：删任一开关前必须先 grep `enablement.py` 的依赖表与子闸表是否引用它**，后续 v23~v26 每批照做 |
| ⚠ **移交 v26 批的缺口（不得丢）** | v2.0.0 周期里由 `action_execution_enabled` + `action_scheduler_enabled` 双闸挂载的 `action_schedule` 步骤，在 v2.1.0 的 `autonomous_tick` profile 里**从来不存在**（`AUTONOMOUS_TICK_STAGES` 止于 `world_experience`）。固化后 v2.0.0 路径消失 ⇒ 该步骤**无任何消费入口**。`scheduler.step_action_schedule` 本体（V2.6.1 REF-004/005）完好且自带 `flag_off` 门控，只是没人调。v26 批必须先裁决：加 profile 阶段，还是挂到 `_run_maintenance`。现已由 `tests/v26/test_review_fixes.py::TestActionScheduleConsumption` 把「profile 里没有该阶段」钉成断言，防止无声失踪 |
| 测试 | 15 个文件；删 7 个纯门控语义用例（含 `test_unified_requires_runtime`、`test_tick_uses_legacy_run_shape`、`test_legacy_cycle_has_no_snapshot_stage_or_rows`、`test_pipeline_intention_flag_off_noop`、`test_flag_off_worker_is_noop`、`test_u13_autonomy_requires_the_agent_runtime` 等）；4 个 v25 源码文本锚点（`source.split("async def _run_user_cycle"…)`）改钉 `autonomous_tick` 的 profile 阶段序列；链样本改用 `tool_channel_enabled ⇒ feishu_enabled` |
| 清单改写 | `docs/version/v2.1.0/regression-checklist.md`：原「用 env 开五 Flag / 逐档关闭回滚 / 链尾 0043」三处随固化失效，改写为「生效确认 P1~P4 + 回滚 = `git revert`」，并新增 **A5.1 专项**：连跑 ≥20 个自治周期统计 decision 的 `skip_reason`，`gateway_denied` 占比 > 5% 判 FAIL（这道 run 级闸是本次固化新引入的静默跳过来源，且软模式豁免不覆盖自治能力） |
| 验证 | 目标 10 文件 **891 passed / 2 failed**（两条均属 F.8 既存豁免）；Fast Test **1449 全绿**；全量 **17 failed**，新增两条（`plan012_flag_matrix`、`v26/test_review_fixes`）均为本批依赖表/锚点问题，已在本批内修 |
| env | v21 各键从未写入 `.env` / `.env.example` ⇒ 零 env 变更；部署侧若自行加过，删除后成**静默无效键**（无版本前缀 ⇒ 不触发启动告警） |

### F.12 轨道 B 批次 v21-3（`unified_run_enabled`）去门控 —— 2026-09-18

| 项 | 内容 |
|---|---|
| 删除字段 | `unified_run_enabled`（字段 413 → **412**；在存开关 39 → **38**） |
| **批前发现的阻塞缺陷** | `agent_runtime/__init__.py` 仍 `from controller import unified_run_enabled`，但 `controller.py` 中该函数在 F.10/F.11 连带清理时已删——**import 断裂，`app.main` / 全部测试无法加载**。本批第一步即修复该 import |
| 行为事实 | `chat_pipeline.run_chat_pipeline` 早已**无条件**调用 `open_foreground_run`，门控读取点在 app 侧为 0；字段本身已无行为分支。固化 = 删死字段 + 把「前台恒写 `foreground_chat` 台账」写成唯一语义 |
| 测试 | 4 文件：删 `UNIFIED_RUN_ENABLED` 覆写；`test_unified_off_creates_no_run_row` / `test_chat_without_unified_creates_no_run_row` / `test_rollback_chain_downgrade_safe` 由「关闸不写台账」反转为「恒写台账」；`ALL_V21_FLAGS` 收敛为空 |
| enablement | 无残留 v21 规则（F.10/F.11 已清）；grep 确认 `enablement.py` 无 `unified_run` 引用 |
| 冻结面 | `chat_pipeline.py` docstring 去版本措辞 → `ZERO_DIFF_HASHES` 哈希重建（允许改动） |
| 清单改写 | `docs/version/v2.1.0/regression-checklist.md` P3：由「尚未收编 / 不应出现 foreground_chat」改为「恒收编 / 应出现」 |
| 验证 | `tests/v21/` **108 passed / 1 failed**；失败为 F.8 既存豁免 `test_agent008_review_fixes::test_low_energy_suppresses_short_term`，零新增归因 |
| env | 本键从未写入 `.env` / `.env.example` ⇒ 零 env 变更；部署侧若自行加过 `UNIFIED_RUN_ENABLED` 则静默无效 |
| 仍保留 | `foreground_gateway_enforced`（F.10 裁决）、`action_outbox_enabled`（附录 E 方案③） |

**移交 v23**：在存开关 38 个；`world_context_char_budget_v23` 仍带**后缀式**版本号（轨道 A 只清 `vXX_` 前缀），属命名残留，与 `world_event_escalation_types` 等一并在 v23 批或命名一致性裁决中处理。

### F.13 裁决：`action_schedule` 消费入口 —— 2026-09-18

F.11 移交项已裁决并落地。

| 项 | 内容 |
|---|---|
| **裁决** | 挂 `life_loop._run_maintenance`，**不**进 `autonomous_tick` Profile 阶段序列 |
| 理由 | ① `scheduler.step_action_schedule` docstring 本就写明「life_loop 维护步」；② 到期认领→执行→收口是维护语义，不是感知/决策阶段；③ 进 profile 会改阶段契约、牵动多处钉测，且与 v25 plan 侧 profile 文本锚点耦合 |
| 实现 | `_run_maintenance` 在 `action_retry` 之后新增 `action_schedule` 步：双闸（`action_execution_enabled` + `action_scheduler_enabled`）+ 与 action_retry 同间隔；`_maintenance_pending` 同步纳入；`step_action_schedule` 本体仍自门控 `flag_off` |
| 当前行为 | 双闸默认 off ⇒ 挂载点零行为变化；v26 批固化 ON 后入口自动生效 |
| 测试 | `tests/v26/test_review_fixes.py::TestActionScheduleConsumption`：钉「profile 无该阶段」+「maintenance 源码含挂载点」；`tests/v24/test_tool007_integration.py::EXPECTED_MAINTENANCE_STEPS` 同步插入 `action_schedule` |
| 冻结面 | `life_loop.py` 已不在 tool007 `FROZEN_SOURCES`（文档注明），无需哈希重建 |

### F.14 轨道 B 批次 v23（世界模拟 7 开关）去门控 —— 2026-09-18

| 项 | 内容 |
|---|---|
| 删除字段 | `world_simulation_enabled` / `time_advance_enabled` / `daily_life_enabled` / `event_detection_enabled` / `scene_expansion_enabled` / `world_llm_assist_enabled` / `debug_tick_enabled`（字段 412 → **405**；在存开关 38 → **31**） |
| OFF 路径删除 | §4.1 #5 scene 双路径（保留 `movement.apply`）；§4.2 #14/#15 daily_life / event_detection 早返回；`build_context` 恒挂 brief；`run_simulation_maintenance` 仅依赖 `world_enabled`；`user_situation` 去 llm_assist 闸（保留 `world_llm_assist_sample_rate` 采样）；`world_context.build_scene` 恒投影场景 |
| 契约层 | API 四端点去 `enabled=False` 早返回与 debug_tick 403；`flags` 恒 `{}`；删除 `_V23_FLAG_NAMES` / `v23_flag_snapshot`；前端 `WorldSimPanel` 去 master/debug 开关读取 |
| enablement | v23 段依赖链整段删除（master/sub/daily_life/llm_assist） |
| 命名残留 | `world_context_char_budget_v23` 仍带后缀版本号（调参，未删）；待命名一致性裁决 |
| 测试 | `tests/v23/` 全量改写（矩阵/flag-off → 常开断言）；enablement/静态扫描/前端 world-sim mock 同步 |
| 冻结面 | `world_engine.py` / `post_process.py` / `prompts/builder.py` 哈希重建 |
| 验证 | `tests/v23/` **165 passed / 2 skipped**；Fast Test **1449 全绿**；前端 vitest 同步为常开断言 |
| env | 部署侧需移除 `WORLD_SIMULATION_ENABLED` 等 7 键（删除后静默无效） |
| 行为变化 | 世界模拟 / 日程 / 处境检出 / 场景投影 / 简报 **首次在生产配置下常开**；需执行 `docs/version/v2.3.0/regression-checklist.md`（尚未跑） |

---

## 附录 G：done 定义与验收判据

### G.1 done 定义（四层边界）

| 层 | 内容 | 是否必须清零 |
|---|---|---|
| 配置层 | `app/core/settings/*` 的字段名、`.env.example` 的键名 | **必须** |
| 代码层 | `app/`（除 `core/settings/`）中的门控表达式与开关名字面量 | **必须** |
| 契约层 | API 响应中的 flag key：`app/api/v1/world.py` 的 `flags`、`app/api/v1/debug.py` 的 `capability_registry_flags`、`app/application/world_engine.py` 的 `_V23_FLAG_NAMES` 快照，以及前端 `WorldSimPanel` 的读取点 | **必须** |
| 历史层 | docstring / 注释中的解释性说明、`tests/v21..v26` 目录名、`migrations/versions/` 文件名、`docs/` 全文 | **允许保留** |

> 结论：可行且应当达成的目标是「**配置层与契约层不出现 `v[0-9]+_`**」。把版本号从 docstring、测试目录名、迁移文件名中彻底抹除既不可能也无必要——它们是历史坐标。
> **契约层是 §4.4 之外的补充**：`flags` / `capability_registry_flags` 是 `dict`，开关名直接作为 JSON key 输出，改名即改 API key；前端读不到 key 会静默回落为 `false`（与 §6.2 的 env 静默失效同构，只是发生在 HTTP 层）。

### G.2 验证命令（修订 §9.2）

```bash
# ① 候选行（含注释与 docstring，需按下列规则二次过滤）
grep -rn '\bv[0-9][0-9a-z_]*\b' apps/backend/app --include=*.py | grep -v 'core/settings'

# ⑦ 前端契约同步
cd apps/frontend && pnpm vitest run

# ⑧ 契约层残留（目标：0 命中）
grep -rn 'v2[1-6]_' apps/backend/app/api apps/frontend/src --include=*.py --include=*.ts --include=*.tsx
```

① 的二次过滤规则（目标 0 命中）：

- 剔除 `#` 之后的注释片段；
- 剔除 docstring 覆盖的行（用 `ast.get_docstring` 取节点行号区间判定）；
- `_V23_FLAG_NAMES` 这类**调试快照名列表**随批次 4 一并删除，不计入残留。

> 批次 1 已有先例：`app/core/settings/enablement.py` 头部、`tests/eval/test_relationship_eval_gate.py`、`tests/v25/test_plan001_flag_regression.py`、`tests/v25/plan009_support.py` 共 **7 处有意保留**的旧名说明注释。这正是原 ① 判据不可直接达成的原因。

### G.3 冻结面守卫清单（每批必须同步）

以下测试用源码/结构哈希做「零 diff」断言，任何重构都会打破它。**每批必须显式更新对应哈希，并在提交信息里写明「属于允许的改动」**，否则守卫会退化为噪音，失败数将单调累积到无法归因。

**第一类：源码文件哈希冻结**（会随每批重构变化，必须同步）

| 守卫位置 | 冻结对象 | 当前状态 |
|---|---|---|
| `tests/v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` | 15 个源码文件（`channels/`、`action/capabilities/`、`application/` 等） | 0 失配（2026-09-18 重建基线） |
| `tests/v24/test_tool008_integration.py::FROZEN_SOURCES` | 5 个 `app/` 文件（记忆桥、`asuna/action.py` 等） | 0 失配（同上） |
| `tests/v24/test_tool007_integration.py::FROZEN_SOURCES` | 4 个 `app/` 文件（`world_engine`、`outbox_consumer`、`life_loop`、`world_context`） | 0 |
| `tests/v24/test_tool002_builtins.py::FROZEN_SOURCE_HASHES` | `action/registry.py`、`models/action.py`、`tool/user_defined.py` | 0 |
| `tests/v24/test_tool003_action_engine.py`（内联哈希） | `models/action.py`、`action/executor.py` | 0 |
| `tests/v25/test_plan001_flag_regression.py::FROZEN_PROMPT_DIGEST` | 提示词摘要 | 0 |
| `tests/v25/test_plan011_regression.py::FROZEN_PLAN_FACE_*` | 计划面签名 | 0 |

> 批次 4（v23）与批次 6（v25）会大面积触碰 `world_engine.py`、`life_loop.py`、`plan_*`，是这类守卫的主要受害批。

**第二类：表结构与迁移冻结**（与本次改造无关，但会持续污染「失败增量」的归因）

| 守卫 | 当前状态 |
|---|---|
| `tests/v24/test_tool007_integration.py::test_no_new_tables_in_metadata` | 失败（既存） |
| `tests/v24/test_tool008_integration.py::test_no_new_tables_in_metadata` / `::test_no_new_migrations` | 失败（既存） |
| `tests/v24/test_tool012_bans.py::test_session_tables_zero_structural_change` | 失败（既存，`tool012_support.SCHEMA_FROZEN_TABLES`） |
| `tests/v24/test_tool_acceptance.py::test_migration_chain_head_is_0046` / `::test_zero_migration_model_structure_unchanged` / `::test_zero_migration_reconciliation_records_0046_breakpoint` | 失败（既存） |

这 7 个失败在批次 1 之前即存在（批次 1 未触碰 `app/models/` 与 `migrations/`），**不要求本次改造修复，但必须从每批的失败增量中排除**。建议在批次 2 开始前单独提交一次「基线豁免清单」或就地修复，避免后续所有批次都要重复解释同一批失败。

> **已重建基线（2026-09-18，轨道 A）**：第一类表格中 12 条源码哈希已同步至当前内容——8 条由去前缀重构引发（`world_engine` / `outbox_consumer` / `action_engine` / `chat_pipeline` / `post_process` / `prompts/builder` / `action/planner` / `decision_pipeline`），另 4 条为**既存失配的基线重建**（`capabilities/reminder.py`、`capabilities/world_action.py` 源自批次 1，`asuna/action.py` 源自 V2.6.1，两处 guard 各一条）。第二类（表结构与迁移冻结）保持原状，仍为 7 条既存失败。

### G.4 每批提交拆分与回滚点

每批固定拆 3 个提交，**禁止合并**：

1. **去门控**（行为变更）——唯一需要回滚的提交，可单独 revert；
2. **测试同步**（`override_settings` 调用点、`setenv` 字面量、断言改写）；
3. **文档回写**（§8 / §F 台账、该版本 regression 记录）。

配套纪律：

- **批次开动前先回写 §8 / §F**：上一批会改变依赖表与剩余清单（F.2 #5 即为实例）；
- **批次完成后记基线**：与上一批的 `passed/failed` 逐条比对归因；
- **每批上线前做该版本真实模型回归**，并在独立数据库上跑首轮（§9.3 未覆盖部分）。

### G.5 执行策略建议：把改名与去门控拆成两条轨道

§8 的批次划分依据是「删除依赖」（谁被依赖谁先删），该顺序对**去门控**是正确的；但它把两种性质不同的工作绑进了同一批：

- **去前缀改名**：200 个字段，零行为变化，可脚本化，依赖关系是**全局一致**的（字段名 / env 名 / 测试字面量 / 契约 key 必须同步）——本质上不适合「分批」；
- **去门控常开化**：行为变更，必须逐点人工判读 OFF 侧可否删除，是真正的风险所在。

批次 1 实际执行时已经不自觉地把两者拆开了（`68d85ac` 去门控、`93dcb1e` 收尾改名），但 §8 并未把这个模式上升为方案。后果是：一个批次的 diff 里约 2/3 是重命名噪音，review 无法分辨哪一行是行为变更——**这恰是「版本号污染代码审查」的另一种表现形式**。

| 轨道 | 内容 | 验收口径 |
|---|---|---|
| **A 去前缀（一次做完）** | 51 个开关 + 149 个调参 + 2 处撞名裁决 + env 键同步 + 契约 key 同步 | 字段集合一致 · 启动未知环境变量告警为 0 · 缓存清空后 `pytest` 与基线一致 · 前端 `vitest` |
| **B 去门控（逐批）** | 批次 2~8，每批 3 个提交（G.4） | 该批的 OFF 路径全部删除 · 断言改写完成 · 该版本 regression-checklist 通过 |

**反方意见（需权衡）**：若计划短期内连做 6 批，先全量改名会让后续每批都二次触碰同一批文件，等于两次改同一行。鉴于每批都需人工真实模型回归、批次之间必然拖长，建议拆开执行。

**其它两项护栏**：

1. 可选用一次性 alias 兼容窗口（pydantic `validation_alias=AliasChoices("新名","旧名")`）让旧 env 名继续生效一个版本——代价是破坏「env 名 = 字段名大写」这一不变式（§7.3 的守卫正依赖它），仅建议在部署侧 `.env` 无法同步修改时使用，且须同步放宽守卫；默认仍用 §6.2 的显式告警。
2. **「旧名 → 新名」对照表已建**：见 `docs/refactor/flag-rename-map.md`（200 个待去前缀字段 + 批次 1 已处理的 12 个 + 2 处撞名裁决 + 命名一致性建议，附校验脚本）。§1.2 前提二选择不改写 `docs/` 的 1,589 处引用，代价是代码中已无版本次命名、文档中仍是旧名——对照表是把这个代价压到可接受的最低成本手段（与 §6.2 的告警同属护栏类改动）。

---

## 附录 H：剩余批次任务编排（批次 5~8）

> **与 §8 的关系**：§8 是**改造前**的批次划分（依赖序 + 过时计数，F.2 已指明其五处需修订）。本附录是**当前实测**的剩余执行清单，**批次 5 起以本附录为准**。
> **数据来源**：`.tmp/audit_remaining.py`（本地临时件，不入库，方法已沉淀在附录中）。口径 = `Settings.model_fields` 取 `bool` 字段（排除基闸）+ `app/`（排除 `core/settings`）逐行定位门控点 + `tests/` 全文计数。
> **前序**：批次 1（v2）、轨道 A（去前缀）、第 0 步（死开关）、v22 / v21 / v23 已完成。HEAD = `29766ff`，工作区干净。

### H.1 剩余盘子（2026-09-18 实测）

「门控点」= `app/` 中该开关的**实际读取点**（guard / branch / getattr / 三联三元），已剔除 docstring 与注释提及；「app 引用」含文案提及，故大于门控点。

| 批次 | 域 | 待办开关 | 门控点 | app 引用 | 测试引用 | OFF 回退路径 |
|---|---|---|---|---|---|---|
| 5 | v24 工具系统 | 11 | 70 | 81 | 278 | 1（§4.2 #9，需拆给批次 6） |
| 6 | v25 计划编排 | 14 | 50 | 53 | 263 | 6（§4.2 #7、#8、#10~#13） |
| 7 | v26 行动执行 | 5 | 17 | 17 | 65 | 1（§4.2 #6） |
| 8 | 收尾 | — | — | — | 12 文件 / 84 处 | — |
| **合计** | — | **30** | **137** | 151 | 606（+84） | 8 |

**三处口径修正（覆盖此前附录的相应说法）**：

1. F.14 记「在存开关 31」应为 **30**（v24 11 + v25 14 + v26 5）。
2. **前端零改动**：`apps/frontend/src` 对 v24 / v25 / v26 的开关名**零引用**（实测）——批次 5~7 无前端任务；v23 批已把 `WorldSimPanel` 的开关读取清完。
3. **收尾批多 3 个配置层/环境层件**（原 §8 未列）：`world_context_char_budget_v23` 的后缀式版本号（见 H.5）、本地 `.env` 的旧键漂移（见 H.5）、`REGISTRY_FLAG_NAMES` 契约收敛（见 H.2）。

**明确不在本编排内**（裁决保留；均已去前缀，零污染）：

| 字段 | 保留理由 |
|---|---|
| `foreground_gateway_enforced` | F.10 裁决：`light_llm_profile` 默认空串，固化 ON 会让预算耗尽那一轮的用户回复**直接失败** |
| `action_outbox_enabled` | 附录 E 方案③：LIFE-004 灰度评审未通过；固化 ON 须先把 v26 的 world 反馈投影从 `integrate_result` 迁到 outbox 消费之后 |
| `character_action_sync_enabled` / `inventory_grounding_enabled` | 批次 1 改名保留（附录 E.6） |

**4 个不带版本段的基闸**（`world_enabled` / `world_household_autoseed_enabled` / `world_interpreter_enabled` / `world_memory_bridge_enabled`）**不在删除范围**——vXX_ 的 ON 路径运行时仍依赖它们（`world_enabled` 一个就有 31 处门控）。

### H.2 批次 5 · v24 工具系统（11 个 / 70 门控点 / 测试 278 处 42 文件）

**执行序**（总闸先行 → 子闸）：

| 序 | 开关 | 门控点 | 主要站点 | 待删 OFF 路径 |
|---|---|---|---|---|
| 1 | `tool_system_enabled` | 27 | `action_engine.py`（166/227/311/626/1155）、`autonomy_engine.py:194`、`post_process.py:468,555`、`planner.py:135`、`planning/context.py:350`、`tool/{channel_tools,confirmation,ext_api}.py`、`main.py` | `execute_plan` 的 `_execute_plan_via_tools`（`action_engine.py:227-238`）与**裸 `executor.run` 循环**（`240-284`）；`_build_tool_context` 的 `None` 早返回（`166`）；`_build_permission_snapshot`（`625-629`）与 `_expire_pending_confirmations`（`1154-1158`）的双闸早返回 |
| 2 | `tool_permission_enabled` | 9 | `permission.py:349,356,380`、`action_engine.py:627,1156`、`post_process.py:469`、`action/context.py:43`、`debug.py:149` | 权限网关 `permission_layer_disabled` fail-closed 档 → 恒读授权存储 |
| 3 | `tool_schema_validation_enabled` | 1 | `executor.py:173` | 校验段跳过分支 |
| 4 | `tool_observation_enabled` | 1 | `executor.py:279` | 观测段早返回 |
| 5 | `tool_surface_enabled` | 3 | `post_process.py:555`、`debug.py:309` | `debug.py:309-313` 的 403 与 `enabled` 契约 |
| 6 | `tool_memory_enabled` | 3 | `action_engine.py:743`、`memory_bridge.py:93` | `_deliver_memory` 的 `deliver_action_memory` 回退（`action_engine.py:745`） |
| 7 | `tool_reflection_enabled` | 5 | `reflector.py:210`、`tool_feed.py:33`、`triggers.py:268`、`autonomy_engine.py:225` | 工具反思子闸早返回（零行为 → 常开） |
| 8 | `tool_channel_enabled` | 8 | `main.py:75`、`channel_tools.py:91`、`triggers.py:101,265,285,364`、`post_process.py:538` | 条件注册 → 常注册（仍受基闸 `feishu_enabled` 约束） |
| 9 | `tool_external_api_enabled` | 6 | `main.py:82`、`ext_api.py:232`、`debug.py:173` | 条件注册 → 常注册（仍受 `tool_ext_manifest_path` / `tool_ext_allowed_hosts` 约束） |
| 10 | `tool_user_defined_enabled` | 5 | `services/tool/user_defined.py`、`action/registry.py` | 注册面恒开 |
| 11 | `tool_confirm_ttl_reuse` | 2 | `confirmation.py:580` | **策略位**（默认 ON）→ 待裁决，见 H.6 |

**契约层（G.1 第三层，必须同批清）**：`app/services/action/registry.py:95-100` 的 `REGISTRY_FLAG_NAMES` 现含 4 项（`tool_system_enabled` / `tool_channel_enabled` / `feishu_enabled` / `tool_external_api_enabled`），本批后应只剩 `feishu_enabled`；`debug.py:289` 的 `capability_registry_flags` 响应随之变化。

**§4.2 #9 必须拆分处理**：`app/api/v1/debug.py:1115-1123` 同时读 `plan_tool_required`（v25）与 `tool_system_enabled`（v24）。批 5 只摘 `tool_system_enabled` 一侧（该处退化为单闸），批 6 收口另一侧。

**enablement 同步（F.11 教训的直接复用：删任一开关前先 grep 依赖表）**：
- `enablement.py:91-115` 的 v24 子闸表 + `tool_channel_enabled ⇒ feishu_enabled` 条目 → 整段删除；
- `enablement.py:71-75` 的 `V25_DEPENDENCIES` 两条（`plan_step_binding_enabled ⇒ tool_system_enabled`、`plan_tool_required ⇒ tool_system_enabled`）→ **必须本批删除**，否则 `getattr(..., False)` 恒判配置错误——这正是 F.11 当场抓到的那个 bug 的同型；
- `enablement.py:149-166` 的 `tool_permission_sub_layer_warnings` → 本批先删其 `tool_permission_enabled` 判据，函数本体随批次 8 删除。

**测试侧要点**：`tests/v24/conftest.py:12` 的 `_pin_v24_tool_env` autouse 钉死、`:40-52` 的 `v24_tool_env`（164 次调用）需收敛；`tests/v24/test_tool001_enablement.py`（18 处）、`test_tool001_settings.py`、`tests/v26/test_v26_p1_flag_and_backoff.py::test_env_example_has_v26_flags` 整体失效或需重写。

**冻结面（G.3 第一类，几乎全数触碰）**：`test_tool010_e2e.py::ZERO_DIFF_HASHES`（15 文件）、`test_tool008_integration.py::FROZEN_SOURCES`（5）、`test_tool007_integration.py::FROZEN_SOURCES`（4）、`test_tool002_builtins.py::FROZEN_SOURCE_HASHES`、`test_tool003_action_engine.py` 内联哈希——须逐条重建并在提交信息写明「属于允许的改动」。

**行为变化（上线前置条件）**：工具系统在真实配置下**首次常开**。最需要人工回归的是权限面——`tool_permission_enabled` 固化后，此前因「无可读授权存储」一律 `deny(permission_layer_disabled)` 的 sensitive / dangerous / `user.*` / `ext.api.*` 工具转为**按真实授权判定**。需执行 `docs/version/v2.4.0/regression-checklist.md`。

### H.3 批次 6 · v25 计划编排（14 个 / 50 门控点 / 测试 263 处 42 文件）

**本批是依赖面最广、OFF 回退路径最多（6 条）的一批**，必须最后做（内部仍依赖 v24 与 v21）。

| 序 | 开关 | 门控点 | 待删 OFF 路径 |
|---|---|---|---|
| 1 | `planning_enabled`（总闸） | 11 | `life_loop.py:352-358` 早返回（no-op）；`life_loop.py:377-399` 四个 `bool(planning_enabled) and …` 复合判据收敛为无条件 |
| 2 | `plan_context_enabled` | 2 | **§4.2 #7**：`planning/context.py:305-306` → 空 `_PlanSources()`（**内容差异，非简单展开**）；`plan_context_digest_enabled` 分支在 `engine.py:309` |
| 3 | `plan_step_binding_enabled` | 5 | `decompose.py:440` 复合判据 + `engine.py:363` 缺省取值 |
| 4 | `plan_scheduler_enabled` | 1 | **§4.2 #11**：`life_loop.py:526-528` → `goal_observation._current_step(...)` |
| 5 | `plan_execution_enabled` | 2 | **§4.2 #12**：`life_loop.py:605-610` → `goal_execution.attempt_current_step(...)` |
| 6 | `plan_observation_enabled` | 3 | **§4.2 #13**：`life_loop.py:621-630` → `_observation_facts(...)` + `goal_observation.advance_user_goals(...)` |
| 7 | `plan_revision_enabled` | 1 | `life_loop.py:399` 复合判据 |
| 8 | `plan_memory_enabled` | 4 | `memory_policy.py:324`、`observer.py:642` 早返回 |
| 9 | `plan_reflection_enabled` | 7 | `main.py:58` 条件注册、`revision_listener.py:138,153,277` 早返回、`evidence.py:1271` |
| 10 | `plan_world_feedback_enabled` | 2 | `observer.py:615` 双闸早返回 |
| 11 | `plan_autonomy_enabled` | 2 | `autonomy_engine.py:337` 早返回 |
| 12 | `plan_debug_enabled` | 2 | `debug.py:1057,1070` 的 `enabled` 契约与 403 |
| 13 | `plan_tool_required` | 7 | **§4.2 #8**：`planning/context.py:308,346` → `ToolSurfaceResolver(None, …)` 无面规划；`debug.py:1114` |
| 14 | `plan_context_digest_enabled` | 1 | `engine.py:309` 摘要分支（**策略位**，默认 ON）→ 待裁决，见 H.6 |

**enablement 同步**：`enablement.py` 的 `V25_MASTER_FLAG` / `V25_TOOL_REQUIRED_FLAG` / `V25_SUB_FLAGS` / `V25_GATE_FLAGS` / `V25_DEPENDENCIES` 五个常量与 `:116-131` 的判定段**整段删除**（批 5 已先摘掉其中两条跨域依赖）——此后该文件只剩 v26 段。

**风险点（§4.2 #8 的连带）**：`plan_tool_required` 是**默认 ON 的策略位**。固化后 `PlanUnavailable("tool_system_disabled")` / `("registry_unavailable")` 成为**新的可达失败面**——工具面不可用时计划编排会硬失败而非退化。这一条必须在批 5（工具系统常开）之后做，且需要 §4.2 #9 的第三个读取点（`debug.py:1114`）一起收口。

**测试侧要点**：`tests/v25/test_plan002_enablement.py`（93 处闸门名字面量，最大单文件）、`test_plan002_settings.py`（48 处）、`test_plan012_flag_matrix.py`（`TestFlagDefaults` / `TestEnablementChainMatrix`）整体失效；`tests/v25/conftest.py:26-33` 的 autouse 钉死需收敛。**`test_plan001_scope_markers.py`（29 处）不能删**——它是「范围越界已评审」的证据链，须按纪律显式更新。

**冻结面**：`test_plan001_flag_regression.py::FROZEN_PROMPT_DIGEST`、`test_plan011_regression.py::FROZEN_PLAN_FACE_*`；另 F.11 记录过 3 个 v25 用例用 `source.split("async def …")` 做源码文本锚点，若再触碰 `life_loop.py` 结构需同步。

**行为变化**：计划编排首次常开；§4.2 #7 的四源装配、#10~#13 四条路径替换会改变自治周期的观测/执行语义。需执行 `docs/version/v2.5.0/regression-checklist.md`。

### H.4 批次 7 · v26 行动执行（5 个 / 17 门控点 / 测试 65 处 15 文件）

| 序 | 开关 | 门控点 | 待删 OFF 路径 |
|---|---|---|---|
| 1 | `action_execution_enabled`（总闸） | 10 | **§4.2 #6**：`action_engine.py:215-284` 的 `_action_execution_enabled` 分派删掉后，**主路径恒为 `_execute_plan_via_action_executor`**；`tool_system_enabled` 分支在批 5 已清，届时 `311-349` 的 `ToolExecutor` 装配转常开；`action_engine.py:1122` 的孤儿 `executing` 恢复扫描早返回 |
| 2 | `action_scheduler_enabled` | 3 | `life_loop.py:675,743` 与 `scheduler.py:179` 的双闸复合判据 |
| 3 | `action_result_enabled` | 1 | `result.py:21` 判据 |
| 4 | `action_feedback_enabled` | 1 | `integration.py:32` 判据 |
| 5 | `action_debug_enabled` | 2 | `api/v1/action_execution.py:15-16,24` 的 403 契约 |

**F.13 挂载点确认（本批必须验证）**：`life_loop._run_maintenance` 的 `action_schedule` 步当前是**双闸 off ⇒ 零行为**（`life_loop.py:674-675` / `742-743`）。本批固化后该入口**自动生效**——这是 F.11 移交项的落地验证点，`tests/v26/test_review_fixes.py::TestActionScheduleConsumption` 的断言需从「双闸 off 确实不跑」改为「常开确实跑」。

**enablement 同步**：`enablement.py:133-145` 的 v26 段整段删除；`action_execution.py` 的 `V26_MASTER_FLAG` / `V26_SUB_FLAGS` 常量与 `validate_action_chain` 一并删除（`action_schedule_default_priority` 的 `>= 0` 校验迁到 `validate_plan_config` 同款写法保留）。

**注意**：本批完成后 `enablement.py` 只剩 `tool_permission_sub_layer_warnings` 与空的 `enablement_violations`，即批次 8 的删除对象。

**行为变化**：行动执行层首次常开（`action_execution_enabled ⇒ action_enabled` 仍受基闸约束）。需执行 `docs/version/v2.6.0/regression-checklist.md`。

### H.5 批次 8 · 收尾（整文件删除 + 配置层清零）

| 项 | 内容 | 依据 |
|---|---|---|
| 删 `app/core/settings/enablement.py` | 含 `tool_permission_sub_layer_warnings`、`enablement_violations`、`validate_enablement_chain` | §9.1 置信度高 |
| 删 `app/main.py:14,46` | import 与启动校验调用 | 同上 |
| 删 `app/core/settings/action_execution.py` 的 `V26_*` 常量与 `validate_action_chain` | 随批次 7 或本批 | §9.1 |
| 同步 12 个测试文件的 `enablement` 引用 | `tests/{v21,v23,v24,v25,v26,unit,v2}`（84 处，含 `test_plan002_enablement.py` 整文件） | 实测 |
| **命名残留清零**：`world_context_char_budget_v23` | 唯一带**后缀式**版本号的配置字段（`world_simulation.py:17`；读取点 `prompts/builder.py:334`；断言 `tests/v23/test_ws001_settings.py:28`、`test_ws012_world_brief.py:135`）。它与 `world.py:16` 的 `world_context_char_budget`（600）**不是同一物**（1000），需按 §七 命名一致性裁决改名为 `world_brief_char_budget` 之类，或与前者合并——**不得机械去后缀**（会撞名） | G.1 配置层要求 |
| **`.env` 漂移修复** | 本地 `apps/backend/.env`（gitignored）仍写着 `V2_CHARACTER_ACTION_SYNC_ENABLED` / `V2_CHARACTER_ACTION_SYNC_CONTEXT_LINES` / `V23_WORLD_SIMULATION_ENABLED` / `V24_TOOL_*`（24 行）/ `V26_ACTION_*`（8 行）——**全部已被 `extra="ignore"` 静默吞掉**，实际取代码默认值。需按 `flag-rename-map.md`「旧 env」列逐条改名，并删掉已删字段的死键 | §6.2 / F.4 |
| 残留扫描 | 按 §G.2 的 ①（二次过滤后 0 命中）、⑧（契约层 0 命中）执行 | G.1 |

**收尾后的 done 判据**（G.1）：配置层与契约层不出现 `v[0-9]+_`；`app/`（除 `core/settings`）门控表达式清零；`pytest` 失败 ID 集合 ⊆ F.8 豁免清单。

### H.6 裁决结果（2026-09-18 落定）

| # | 事项 | 裁决 | 对批次范围的影响 |
|---|---|---|---|
| 1 | 三个**默认 ON 的策略位**：`tool_confirm_ttl_reuse`、`plan_tool_required`、`plan_context_digest_enabled` | **保留为常规配置项**（三者 OFF 态都是有效策略，且已去前缀、零污染） | 批次 5 由 11 → **10 个**；批次 6 由 14 → **12 个**；§4.2 #8 的 OFF 回退路径**保留**，`PlanUnavailable("tool_system_disabled")` / `("registry_unavailable")` 不做固化 |
| 2 | `foreground_gateway_enforced` / `action_outbox_enabled` | **继续保留**（沿用 F.10 与附录 E 的既有裁决，本轮不重开） | 不在任何批次内 |
| 3 | 本地 `.env` 旧键漂移 | **按 `flag-rename-map.md`「旧 env」列同步改名**，并删除已删字段的死键 | 新增到批次 8 的执行项（见 H.5） |
| 4 | 提交授权 | **授权提交，不推送**：每批按 G.4 拆 3 个提交留在本地，不 push、不建 PR | 批次 5~8 各产出 3 个本地提交 |

**修正后的剩余盘子**（替代 H.1 的批次列）：

| 批次 | 域 | 待办开关 | 门控点 | 保留项 |
|---|---|---|---|---|
| 5 | v24 | **10** | 68 | `tool_confirm_ttl_reuse` |
| 6 | v25 | **12** | 42 | `plan_tool_required`、`plan_context_digest_enabled` |
| 7 | v26 | 5 | 17 | — |
| 8 | 收尾 | — | — | — |
| **合计** | — | **27** | **127** | 3 |

### H.7 执行纪律（每批照做）

1. **开批前**：回写本附录的实测计数（上一批会改变依赖表与清单）；跑一次全量基线 `pytest -q -n 4 --timeout=180 --basetemp=.tmp/pytest-bt`；判据是「失败 ID 集合 ⊆ F.8 三类的并集」，不是失败数相等。
2. **删任一开关前**：先 grep `enablement.py` 的依赖表与子闸表（F.11 教训）。
3. **提交拆分**：G.4 的 3 提交，禁止合并；去门控那个提交是唯一需要回滚的。
4. **冻结面**：G.3 第一类逐条重建哈希，提交信息写明「属于允许的改动」。
5. **收批后**：重跑全量 + 该版本 regression-checklist（真实模型人工回归，无法用单测替代）；部署侧 `.env` 副本同批改名。
6. **环境坑**：Windows 上必须显式 `--basetemp=.tmp/pytest-bt`，否则 `pytest-current` 符号链接抛 `PermissionError: [WinError 5]` 中断整轮（已踩三次）。本机 Bash 缺 coreutils（`ls` / `head` / `tail` / `mkdir` 均不可用），shell 操作走 Python；`git` 经 Python subprocess 调用。
7. **批量改测试的脚本纪律**（H.11.1 事故后补）：改完先 `compileall` 整树，再跑测试；判定条件宁可窄，不要用推断式规则（「装饰器后面不是 def 就算孤儿」这类）。
8. **提交边界**：去门控提交（行为变更，可单独 revert）与测试同步提交必须分开——G.4 的三提交纪律正是为此，中途态测试红是设计而非事故。

### H.8 开批前基线归因（2026-09-18 实测）

**基线实测值与 F.8 记载严重不符**：

```
.venv/Scripts/python.exe -m pytest -q -n 4 --timeout=180 --basetemp=.tmp/pytest-bt
=> 47 failed, 6356 passed, 22 skipped in 377.60s
```

F.8 记的是「15 failed / 6439 passed，抖动区间 15~18」。**F.14（v23 批）落地后从未记录全量基线**（其验证段只写了 `tests/v23/` 与 Fast Test），因此差额无人归因。逐条归因如下（合计 47）：

| 类别 | 数量 | 用例 | 处置 |
|---|---|---|---|
| feishu 相关（本分支 WIP，与本次改造无关） | 14 | `e2e/test_feishu_webhook.py` 12 + `unit/test_feishu_settings.py` 2 | 豁免，加入本清单 |
| 冻结面失配（G.3 第一类） | 6 | `test_tool007::test_frozen_sources_have_zero_diff[world_engine / outbox_consumer]`、`test_tool010_e2e::test_zero_diff_frozen_surfaces[chat_pipeline / post_process / action_engine / builder]` | **须重建**（v23 批重建不全） |
| 表结构与迁移冻结（G.3 第二类） | 7 | `test_tool007::test_no_new_tables_in_metadata`、`test_tool008::{test_no_new_tables_in_metadata, test_no_new_migrations}`、`test_tool012_bans::test_session_tables_zero_structural_change`、`test_tool_acceptance::{test_migration_chain_head_is_0046, test_zero_migration_model_structure_unchanged, test_zero_migration_reconciliation_records_0046_breakpoint}` | 既存豁免（其中 3 个是「head 已到 0048 而断言写 0046」的陈旧守卫） |
| **维护步序列钉测漏改（F.13 遗漏）** | 4 | `test_tool005_integration::test_life_loop_maintenance_sequence_unchanged`、`test_tool_acceptance::{test_g_compat_life_loop_maintenance_sequence_unchanged, test_g_compat_life_loop_semantics_replacing_blob_freeze}`、`test_tool012_bans::test_ban_no_second_agent_stage_sequence_unchanged` | **须修**：F.13 只更新了 `test_tool007_integration.EXPECTED_MAINTENANCE_STEPS`，另 4 份序列期望漏改（`At index 3 diff: 'action_schedule' != 'outbox_consume'`） |
| **`loop_runs` kind 值域缺陷（F.14 暴露）** | 4 | `v2/test_life002_controller::test_world_maintenance_dispatched_when_enabled`、`v21/test_agent008::test_background_run_resets_snapshot`、`v24/test_tool012_scenarios::test_s4_autonomy_tick_three_ledgers_aligned`、`v24/test_tool006_integration::test_autonomy_decision_to_world_write_through_outbox` | **阻塞级，见下** |
| 既存（F.8 清单内） | 3 | `v2/test_aut005_goal_evaluation::test_clean_slice_passes_all`、`v21/test_agent008::test_low_energy_suppresses_short_term`、`v25/test_plan010_regression::test_s1_plan_evidence…` | 豁免 |
| 其它待归因 | 9 | `v24/test_tool011_manifests::test_e3_syntax_error_is_logged_without_aborting`、`test_tool010_e2e::test_four_step_tool_addition_keeps_pipelines_untouched`、`v25/test_plan008_broadcast::test_event_system_flags_off_write_nothing`、`e2e` 3 条、计时类 3 条 | 单跑复核（疑为抖动 / 冻结面连带） |

#### H.8.1 阻塞级缺陷：`loop_runs.kind` 值域不含新增维护步

`app/core/db.py:1218-1222` 的 `ck_loop_runs_kind` 值域为：

```
kind IN ('autonomy', 'chat', 'world_maintenance', 'action_retry', 'outbox_consume', 'trigger_reconcile')
```

而 `life_loop._run_maintenance` 实际写入了**两个不在值域内**的 kind：

| 维护步 | 写入点 | 引入提交 | 当前状态 |
|---|---|---|---|
| `world_simulation` | `life_loop.py:642` `_record_maintenance_run("world_simulation", …)` | `e1c0bef`（WS-003 时间推进与模拟维护步） | **活缺陷**：F.14 把该步的门控固化常开后首次真正执行 → `IntegrityError: CHECK constraint failed: ck_loop_runs_kind`，**`run_life_loop_tick` 整轮崩溃** |
| `action_schedule` | `life_loop.py:694` | `d2f431c`（F.13 挂维护步） | **休眠地雷**：双闸默认 off 故未触发；**批次 7 固化 v26 后必然引爆** |

两处都是「新增了维护步、但没有同步扩 `loop_runs` 的 kind 值域」——WS-003 与 F.13 各自遗漏，前者被门控掩盖至 F.14 才暴露。

**裁决见 H.9。在它落定前，批次 5 的失败增量无法干净归因**（该缺陷会让任何调用 `run_life_loop_tick` 的用例都失败，横跨 v2 / v21 / v24 / v25）。

### H.9 阻塞缺陷裁决

| 方案 | 内容 | 成本 | 风险 |
|---|---|---|---|
| **① 新增迁移扩值域**（推荐） | 新增迁移（head 0048 → 0049）扩 `ck_loop_runs_kind` 加 `world_simulation` + `action_schedule`，同步 `app/core/db.py:1218` | 触碰 `migrations/`（G.3 第二类声明不改）；`tests/v25/test_plan012_gates_and_invariants.py:175` 的 `heads == ["0048_action_records_run_id.py"]` **由绿转红**需同批改；`tool012_support.MIGRATION_BREAKPOINT` 等陈旧守卫一并校正 | 低（与 `0038` 扩 `chat` 同款先例） |
| **② 归并到既有 kind** | `world_simulation` 记入 `world_maintenance` 行、`action_schedule` 记入 `action_retry` 行，靠 `steps[].step` 区分 | 零迁移 | 丢失 kind 维度的可观测性；`LIFE_LOOP_MAINTENANCE_SEQUENCE` 钉测与三账对齐语义需改写 |
| **③ 只修钉测，缺陷单列待办** | 只做 F.13 遗漏的 4 处序列期望同步；schema 缺陷登记为独立待办 | 最低 | 批次 7 会再次引爆同一缺陷；且 H.8 的归因表长期带 4 条噪声 |

**裁决结果（2026-09-18）**：采用 **①**。执行记录见 H.10。

### H.10 基线修复执行记录（2026-09-18）

「第 0.5 步」——批次 5 开动前的守卫修复，3 个本地提交。

| 项 | 内容 |
|---|---|
| **阻塞缺陷根因** | `51c8892`（v23 批）把 `world_simulation` 维护步的门控由 `world_simulation_enabled and time_advance_enabled` 改为 `settings.world_enabled`，使一条**从未运行过**的维护步首次落地；该步写入的 `kind='world_simulation'` 不在 `ck_loop_runs_kind` 值域内 → 每次 tick `IntegrityError` |
| **连带缺陷（同源，修一处才暴露）** | 该步把 `run_simulation_maintenance` 的返回值原样写进 `loop_runs.steps`（JSON 列），而它是 `TimeAdvanceResult`（dataclass，含 `datetime`）→ `TypeError: Object of type TimeAdvanceResult is not JSON serializable` |
| 修 ①：扩 kind 值域 | `app/core/db.py` 的 `LoopRunRow.__table_args__` + 新增迁移 `0049_loop_runs_kind_maintenance_steps.py`（值域加 `world_simulation` / `action_schedule`；与 `0038` 扩 `chat` 同款先例） |
| 修 ②：JSON 归一化 | `life_loop._json_safe()`，在 `_record_maintenance_run`（`loop_runs.steps` 唯一写入路径）统一收口；`action_schedule` 那颗休眠地雷一并拆掉（批次 7 固化 v26 时不再引爆） |
| 迁移 head 钉测同步 | **14 个测试文件**把 `0048` 机械升到 `0049`（v24 ×1、v25 ×12、v26 ×1）——`MIGRATION_HEAD` 常量、`test_*_0048` 用例名、`max(numeric) == 48`、`startswith("0048_")` 等 |
| F.13 遗漏的序列钉测 | `tool012_support.LIFE_LOOP_MAINTENANCE_SEQUENCE` 与 `test_tool005_integration.LIFE_LOOP_MAINTENANCE_SEQUENCE` 补入 `action_schedule`（**只有 2 份定义**，`test_tool_acceptance` 与 `test_tool012_bans` 共用 `tool012_support` 的那份） |
| 冻结面重建 | 6 条（G.3 第一类）：`test_tool007_integration` 的 `world_engine` / `outbox_consumer`；`test_tool010_e2e` 的 `chat_pipeline` / `post_process` / `action_engine` / `prompts/builder` |
| feishu 14 条 | 裁决列为**豁免基线**（`feat/feishu_bot` 分支自身 WIP，与本重构无关） |
| 验证 | 受影响 12 个文件：**407 passed / 8 failed → 修复后** 仅余 F.8 既存豁免 1 条（`v21/test_agent008::test_low_energy_suppresses_short_term`）与 5 条 tool012 时代的陈旧结构守卫 |

**批次 5 开批基线（2026-09-18，基线修复后实测）**：

```
.venv/Scripts/python.exe -m pytest -q -n 4 --timeout=180 --basetemp=.tmp/pytest-bt
=> 35 failed, 6368 passed, 22 skipped in 423.51s
```

由 47 → **35**（净修复 12 条）。剩余 35 条的构成即批次 5 的豁免清单：

| 类别 | 数量 | 说明 |
|---|---|---|
| feishu WIP | 14 | `feat/feishu_bot` 分支自身，与本重构无关 |
| tool012 时代陈旧结构守卫 | 5 | 见 H.10.1 |
| `test_tool008` 结构 / 语义 | 4 | `test_no_new_migrations`、`test_no_new_tables_in_metadata`、`test_candidate_with_unresolved_reference_is_rejected_by_r8`、`test_policy_rejection_is_discarded_and_logged` |
| 既存（F.8 清单内） | 3 | `v2/test_aut005_goal_evaluation`、`v21/test_agent008`、`v25/test_plan010_regression` |
| 抖动池（e2e 4 + 计时 2） | 6 | 单跑因抖动翻转 |
| 待复核 | 3 | `v24/test_tool009_evidence`、`v24/test_tool011_ext_api`、`v25/test_plan008_broadcast`（本轮出现，前一轮未见，属 v24 侧抖动） |

#### H.10.1 未修项：tool012 时代的陈旧结构守卫（5 条）

`tests/v24/` 的以下 5 条锚在 **TOOL-012 当时的快照**上，其常数（`MIGRATION_FILE_COUNT_CURRENT = 46`、`MIGRATION_BREAKPOINT = "0046_tool_insight_types.py"`、`SCHEMA_TABLE_COUNT = 42`、`SCHEMA_COLUMNS_DIGEST`）自 `0047` / `0048` 落地起即已失配，属 §G.3 第二类**既存失败**：

`test_tool007_integration::test_no_new_tables_in_metadata`、`test_tool012_bans::test_session_tables_zero_structural_change`、`test_tool_acceptance::{test_migration_chain_head_is_0046, test_zero_migration_reconciliation_records_0046_breakpoint, test_zero_migration_model_structure_unchanged}`。

**本次不动**：重建它们要重新推导整套表/列/索引摘要快照（`SCHEMA_TABLE_COUNT 42 → 43`、`columns_digest`、`table_set_digest`、`MIGRATION_BREAKPOINT` 语义），那是「给一个已完结任务的冻结快照重新定基线」，与开关去门控无关。**失败 ID 集合不变**，故不影响批次归因。建议单开一个清理任务：要么重定基线，要么把这类「零迁移」断言退役（其语义已被 v25 侧的 `MIGRATION_HEAD` 钉测取代）。

### H.11 批次 5 执行记录（v24 工具系统，2026-09-18）

#### 已完成：app 侧去门控（提交 `714a92d`）

| 项 | 内容 |
|---|---|
| 删除的 10 个开关 | `tool_system_enabled`、`tool_permission_enabled`、`tool_schema_validation_enabled`、`tool_observation_enabled`、`tool_surface_enabled`、`tool_memory_enabled`、`tool_reflection_enabled`、`tool_channel_enabled`、`tool_external_api_enabled`、`tool_user_defined_enabled` |
| 保留（裁决） | `tool_confirm_ttl_reuse`（策略位）+ 全部治理参数 |
| 字段总数 | 405 → **395** |
| 改动文件 | 27 个（app 26 + `.env.example`） |
| 关键删除的 OFF 回退路径 | `execute_plan` 的裸 `executor.run` 循环（原 `action_engine.py:240-284`）、`get_tool_registry()` 的 `None` 门控、权限闸的 `permission_layer_off` / `permission_layer_disabled` 三段语义（`permission_sub_layer_disabled` / `_disabled_layer_decision` / `effective_level_without_snapshot` 三函数整体删除）、`_deliver_memory` 的 `deliver_action_memory` 回退、`_persisted` 的 V9 原始形态回退、`tool_feed.is_enabled`、`triggers.tool_channel_enabled` |
| 契约层 | `registry.REGISTRY_FLAG_NAMES` 由 4 项收敛为 `("feishu_enabled",)`；`/debug/tools*` 的 7 个门控函数（含 4 个 403 分支）整体删除；`external_api_enabled` / `user_defined_enabled` / `GATE_DISABLED_REASON` / `is_enabled` / `non_todo_payload_kinds(settings)` 签名同步 |
| `enablement.py` | v24 段整段删除；`V25_DEPENDENCIES` 摘掉两条 `⇒ tool_system_enabled`；`tool_permission_sub_layer_warnings` 删除（其判据已无字段可读） |
| 验证 | `compileall app` 通过；`import app.main` 通过；`Settings.model_fields` 无 `vXX_` 前缀、无残留 v24 开关 |

#### 未完成：测试同步（本批第 2 个提交）

**全量**去门控后：**242 failed + 191 errors / 5970 passed**。
**已完成一轮清理**（提交 `c77efb7` / `e7c5927`）后，`tests/v24` 单目录：**182 failed / 17 errors → 135 failed / 3 errors / 1408 passed**；`tests/` 全量 `compileall` 通过。

已做（均为可重放的脚本化操作，脚本留在 `.tmp/`，不入库）：

| 遍 | 操作 | 量 |
|---|---|---|
| 1 | 摘除字典条目 / 关键字实参 / `monkeypatch.setenv` 中的已删开关 | 30 文件 91 行 |
| 2 | 摘除调用内 kwarg（`v24_tool_env(tool_system_enabled=True)` 一类） | 26 文件 115 处 |
| 3 | 语义定点改写 6 处 + 删除 12 个「闸关即等价上一版本」的失效用例 | 7 文件 |
| 4 | 契约/读面收口：`PERMISSION_ON_SETTINGS = ()`、`capability_registry_flags` 断言改用 `REGISTRY_FLAG_NAMES[0]`、`tool012_support.runtime_fingerprint` 常开化、`REGISTRY_FLAG_NAMES` 单键断言 | 6 文件 |

**剩余（`tests/v24` 135 failed + 3 errors，按文件）**：

| 文件 | 剩余 | 性质与做法 |
|---|---|---|
| `test_tool_acceptance.py` | 34 | **flag 矩阵收敛**：`group_env(group)` 的 13 组开关组合 + `EXPECTED_FINGERPRINTS[group]` 已无意义，须整体收敛为「唯一常开配置」单行期望，并去掉 `parametrize` 的 group 维度 |
| `test_tool003_executor.py` | 17 | 校验 / 观测闸的 OFF 形态断言 → 去掉 `tool_settings(...)` 开关注入后断言常开形态（`_persisted` 恒走 `persisted_result`、校验恒生效） |
| `test_tool012_scenarios.py` | 12 | 同上矩阵收敛（`MASTER_ON` / `PERMISSION_ON` / `CHANNEL_ON` 常量语义已变） |
| `test_tool005_permission.py` | 9 | `REASON_LAYER_OFF` / `REASON_LAYER_DISABLED*` 三个 reason 已不可达 → 对应用例删除；保留快照不可用 / 授权判定用例 |
| `test_tool010_e2e.py` | 8 | 含 `ZERO_DIFF_HASHES` 重建（本批触碰 `post_process.py` / `action_engine.py` / `chat_pipeline.py` / `builder.py`） |
| `test_tool005_confirmation.py` / `test_tool005_integration.py` | 12 | `non_todo_payload_kinds()` 去参数后签名同步；`tool_channel_enabled` 断言失效 |
| `test_tool002_builtins.py`（5）、`test_tool008_integration.py`（4）、`test_tool011_debug_api.py`（4）、`test_tool006_surface.py`（3）、`test_tool007_integration.py`（3，含冻结面重建）、其余 8 文件 | 25 | 逐条：契约键、403 分支、`get_tool_registry()` 非空化 |
| `tests/v9`、`tests/unit`、`tests/v25` 的跨版本连带 | 约 18 | 见上一版清单 |

#### H.11.1 过程事故与纪律补充

本轮出现过一次**工具性事故**：一个「清理 `drop_function` 残片」的脚本用了过宽的判定（「装饰器后面不是 `def` 即视为孤儿」），把 54 个文件中**多行 `@pytest.mark.parametrize(` 的首行**误删，`tests/` 大面积语法报错。

处置：`git checkout -- apps/backend/tests` 回滚，随后**重放**前三遍脚本（全部是确定性的、留在 `.tmp/` 的脚本），并修正 `drop_function` 的边界判定（`async def` 的 `async` 半行也须吞掉）。修复后 `tests/` 全量编译通过，改动量与回滚前一致。

**纪律补充（并入 H.7 §6）**：凡「按 AST/文本结构批量改测试」的脚本，改完**必须先 `compileall` 整树**再跑测试；判定条件宁可窄（只匹配已知模式），不要用「后面不是 def 就算孤儿」这类推断式规则。

**改写纪律**（与 v21 / v22 / v23 批同款，勿机械删断言）：

1. 「闸 off ⇒ 与上一版本逐字节一致」这类断言**整体删除**——前提已不存在；
2. 「闸 on ⇒ 新形态」这类断言**去掉开关注入、保留形态断言**（`_pin_v24_tool_env` / `v24_tool_env` 夹具的开关注入摘除，`TOOL_DISABLED_IDS` 隔离保留）；
3. 支撑模块（`tool00X_support.py`）的 flag env 映射摘除已删键；
4. `tests/v24/conftest.py::_pin_v24_tool_env` 只保留 `TOOL_DISABLED_IDS` 隔离；
5. 冻结面（G.3 第一类）逐条重建 —— 本批触碰 `test_tool010_e2e.ZERO_DIFF_HASHES` 的 `post_process.py` / `action_engine.py` / `chat_pipeline.py` / `builder.py`、`test_tool007_integration.FROZEN_SOURCES` 的 `world_engine.py`。

**§4.2 #9 的收口状态**：`app/api/v1/debug.py` 的 `_autonomous_tool_surface` 已摘掉 `tool_system_enabled` 一侧，现为单闸 `plan_tool_required`；另一侧由批次 6 收口（与 H.2 的计划一致）。

