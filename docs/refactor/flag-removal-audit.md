# vXX_ 版本开关体系删除 —— 成本审查报告

> 审查对象：`apps/backend` 中以版本号作前缀的 settings 配置与开关体系（`v2_*` / `v21_*` / `v22_*` / `v23_*` / `v24_*` / `v25_*` / `v26_*`）
> 审查范围：仅 `apps/backend`；`docs/` 按约定不纳入改动面
> 本文只做成本评估，**不含任何代码改动**。所有数据由脚本实测得出，非估算。

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
