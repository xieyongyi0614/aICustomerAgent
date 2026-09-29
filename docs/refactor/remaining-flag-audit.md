# 剩余开关阀门审查 —— 用处 / 去除后果 / 清理批次

> **审查对象**：`vXX_` 版本开关体系删除（2026-09-19 收官）**之后**，`apps/backend/app/core/settings/` 中仍然存在的功能开关与门控字段
> **审查范围**：仅 `apps/backend`；`docs/` 按约定不纳入改动面
> **本文数据**：均为**实测**（字段定义 + 全仓读取点 grep + 真实 `.env` / `.env.example` 内容），非估算
> **配套文档**：`flag-removal-audit.md`（上一代 `vXX_` 体系的删除成本审查，已收官）、`flag-rename-map.md`（历史字段名对照）
> **审查日期**：2026-09-22

---

## 一、执行摘要

### 1.1 结论

**剩余阀门共 53 个**，但它们的性质**极不均匀**——按「去除后果」可分为七类，其中只有一类值得删：

| 类 | 数量 | 性质 | 去除后果 | 建议 |
|---|---|---|---|---|
| **A 死开关** | **2** | 全仓**零业务读取点**（含动态读取路径） | **零后果** | ✅ **已删（批次 1，2026-09-22）** |
| **B 应急关断位** | **20** | 默认 ON，读取处为「不满足则跳过」 | **行为不变，但失去应急关断手段** | ⚠️ 择机固化（需先接受代价） |
| **C 待激活预留位** | **13** | 默认 OFF，能力未启用 | **删除未启用的能力路径**（含测试） | ⏸ 需逐项决策 |
| **D 部署闸** | **1** | 控制外部依赖启停 | **环境耦合**（无该依赖则无法启动） | ❌ **保留** |
| **E 策略裁决位** | **4** | 同一路径的两个**合法**取值 | **失去策略可调性** | ❌ **保留** |
| **F csv 集合闸** | **4** | 控制「已纳管范围」 | 失去范围可配性 | ⏸ 视需要 |
| **G 维度开关（动态读取）** | **8** | `evaluation_{dimension}_enabled`，由 f-string 动态解析 | **静默退化为「永远开启」**（`getattr` 兜底 `True`），开关能力丧失 | ❌ **保留** |
| ⚠️ 特殊 | **1** | `character_action_sync_enabled`：默认与部署不一致 | 固化任一值都会改变某类环境行为 | ⚠️ 单独裁决 |

**一句话结论：真正该删的只有 2 个死开关；20 个"默认常开"的开关不是门控残留，而是应急关断位——删掉它们省不下代码，却会失去"出事时关掉子系统而不用回滚代码"的能力；另有 8 个评估维度开关是"活的"，但只能通过动态方式被发现（见 §2.4）。**

> ⚠️ **本结论已修正**：初版审查把 8 个 `evaluation_{dimension}_enabled` 误判为死开关（数量记为 10）。执行批次 1 时被测试暴露，真实数量为 **2**。误判根因与修正方法见 **§2.4** 与 **附录 D**。

### 1.2 三条必须先接受的前提

**前提一：53 个阀门里，真实部署**只**设置过 4 个。**

实测 `apps/backend/.env`（生产在跑的配置）全文仅 4 个开关被显式设置：

```
CHARACTER_ACTION_SYNC_ENABLED=true
INVENTORY_GROUNDING_ENABLED=true
FEISHU_ENABLED=true
TOOL_CONFIRM_TTL_REUSE=True
```

`apps/backend/.env.example` 另设 `FEISHU_ENABLED=false` 并把 3 个 FEISHU 子闸写成注释。

**其余 49 个开关从未在任何部署配置里被显式设置**——它们全部按字段默认值运行。

> **这条事实有两面**：一方面说明「纸面可配置性」远大于「实际在用」；另一方面**不能据此判定可删**——默认 ON 的删掉行为不变（安全），默认 OFF 的删掉就是删未启用路径（功能损失）。

**前提二：基线口径已滞后，须在回写时校正。**

`docs/current-system-architecture-baseline.md` §7.1 记「settings 字段总数 405、**37 个布尔字段**」——那是 **2026-09-20（V3.0.0 落地前）** 的口径。V3.0.0 随后新增 13 个 `runtime_*` 字段，因此**实测 bool 字段为 49 个**（+4 个 csv 集合闸 = 53 个阀门）。

**前提三：删除门控分支的风险远高于删除字段本身。**

字段定义删掉是机械操作；**但删除 `if not flag: return` 这类分支会改变路径**——上一代 `vXX_` 体系删除的审查已明确记录：「改名是廉价的，删分支是昂贵的，而把功能全量转正的验证成本远超前两者之和，且目前没有可用的验证资产」（`flag-removal-audit.md` §1.1）。

---

## 二、现状盘点

### 2.1 规模实测

| 维度 | 实测值 |
|---|---|
| 阀门字段总数 | **53** |
| ├ bool 字段 | 49 |
| └ csv / 集合型字段 | 4 |
| 默认 `True` | 31 |
| 默认 `False` | 18 |
| 默认 `""`（空集合） | 4 |
| 真实部署显式设置过的 | **4**（含 1 个 csv 无关项） |
| **零业务读取点（死开关）** | **10** |
| 分布领域模块 | 14（action / feishu / autonomy / database / evaluation / life_loop / agent_runtime / observability / pipeline / plan / relationship / tool / world） |

### 2.2 五类判定标准（本审查的分类依据）

| 类 | 判定标准 | 判据来源 |
|---|---|---|
| **A 死开关** | 全仓（`app/` + `tests/`）**零处**按该字段名读取 | grep 实测 |
| **B 应急关断位** | 默认 `True`，读取处形态为「不满足则跳过 / 提前返回」；关闭 = 子系统静默降级 | 读取点代码形态 |
| **C 待激活预留位** | 默认 `False`，读取处形态为「满足则执行新路径」；生产路径不含该分支 | 读取点代码形态 + 默认值 |
| **D 部署闸** | 控制**外部依赖**是否存在（如通道 / 供应商），关闭时应用仍应能启动 | 读取点位于 `main.py` lifespan / 通道入口 |
| **E 策略裁决位** | 两个取值**都是合法运行态**，只是策略不同（不是「功能开关 vs 关闭」） | 字段 docstring + 读取点语义 |
| **F csv 集合闸** | 控制「已纳管范围」（渠道白名单 / 可选段清单 / 升级事件白名单） | 字段类型与解析函数 |

### 2.3 A 类死开关清单（10 个，零读取点）

| 字段 | 默认 | 位置 | 读取点 |
|---|---|---|---|
| `autonomy_enabled` | `True` | `settings/autonomy.py:13` | **无**（已核：含动态读取路径） |
| `rel_signal_llm_enabled` | `False` | `settings/relationship.py:32` | **无**（已核：含动态读取路径） |

**去除后果**：**零行为变化**。两条均已随批次 1 删除（见 附录 D）。

> **`autonomy_enabled` 的成因**：它曾用于门控独立的 `autonomy_worker`。该 worker 已被 `life_loop` 归并（`main.py:64-65` 只起 `run_life_loop_worker`，日志写「life loop 已接管周期调度（归并 autonomy/world/action 三循环）」），门控随 worker 一起失效，字段与文档残留。**旁证**：`apps/backend/README.md` 曾把它记为「自主行为总开关（关闭则 Worker 不启动）」——该描述早已不成立，批次 1 一并修正。
>
> **`rel_signal_llm_enabled` 的成因**：V8.5 关系信号设计为「词表 + 既有 LLM 可选字段，**P0 零新增 LLM**」，该可选 LLM 路径从未实现，字段空留。

### 2.4 G 类：维度开关（8 个）——**静态 grep 抓不到的一类**

> ⚠️ **本节是初版审查的误判修正。** 初版把这 8 个字段判为「死开关」，依据是「全仓零读取点」。**结论错误**——它们被**动态 f-string 读取**，静态 grep 字段名无法命中。

**真实读取点**（`app/services/evaluation_rules/__init__.py`）：

```python
# :38  rule_active() 内
return bool(getattr(settings, f"evaluation_{rule.dimension.value}_enabled", True))

# :73  _dimension_enabled() 内
return bool(getattr(settings, f"evaluation_{dimension.value}_enabled", True))
```

`EvaluationDimension`（`app/models/evaluation.py:23-33`）取值：`persona` / `emotion` / `memory` / `behavior` / `autonomy` / `relationship` / `action` / `reflection` / `development` / `goal`。

**因此以下 8 个字段是"活的"**（读者为动态解析）：

| 字段 | 默认 | 维度 |
|---|---|---|
| `evaluation_persona_enabled` | `True` | persona |
| `evaluation_emotion_enabled` | `True` | emotion |
| `evaluation_memory_enabled` | `True` | memory |
| `evaluation_behavior_enabled` | `True` | behavior |
| `evaluation_goal_enabled` | `True` | goal |
| `evaluation_reflection_enabled` | `True` | reflection |
| `evaluation_relationship_enabled` | `True` | relationship |
| `evaluation_action_enabled` | `True` | action |

（`evaluation_autonomy_enabled` 同时被动态与静态读取——`evaluation_engine.py:270`；`development` 维度**没有对应字段**，动态 `getattr` 恒兜底 `True`，即该维度开关缺失，属设计缺口而非本次范围。）

**去除后果**：**静默退化为「永远开启」**——`getattr` 的默认值是 `True`，删掉字段不会报错、不会改变默认行为，**但会静默失去「按维度关掉评估规则」的能力**，且**不会报错**（这正是最危险的形式：能力消失而无人察觉）。

**暴露方式**：执行批次 1 时，`tests/unit/test_evaluation_rule_engine.py:83` 用 `monkeypatch.setenv("EVALUATION_BEHAVIOR_ENABLED", "false")` 验证维度开关生效——删除字段后该用例失败，才暴露了误判。

**建议**：**保留**。它们是按维度的评估策略开关（E 类性质），不是门控残留。

> **方法论补正**：本项目的 settings 字段读取存在**两种形态**——① 静态属性访问 `settings.X`；② **动态 f-string** `getattr(settings, f"prefix_{var}_enabled", True)`。**只查形态 ① 会得出"零读取点"的错误结论**。审计 settings 字段时必须额外检索动态构造模式（见 附录 D 复现命令）。


---

## 三、逐类审查（用处 + 去除后果）

### 3.1 B 类：应急关断位（20 个）

**共同特征**：默认 `True`；读取形态为 `if not settings.X: <跳过/返回 None/降级>`。**关闭 = 该子系统静默降级**。

**共同去除后果**：**行为不变**（默认值即固化值），**但失去应急关断手段**——出问题时只能回滚代码，不能再「一键关掉某个子系统」。

> 这正是 V4.0.0 架构裁决 C-1「禁止新增功能开关」登记过的**显式代价**（见 `docs/version/v4.0.0/tasks.md` 风险 R17）：用「配置面干净」换「回滚粒度粗」。

| 字段 | 用处（关掉会发生什么） | 去除后果 | 备注 |
|---|---|---|---|
| `action_detector_enabled` | 行动意图检测（`services/action/detector.py:176`）。关掉 = 所有轮次不做行动意图识别 | 行为不变 / 失去关断 | 行动能力入口 |
| `action_memory_policy_enabled` | 行动 → 记忆策略（`memory_bridge.py:93,140`）。关掉 = 行动不产记忆候选 | 同上 | |
| `db_pool_pre_ping` | 连接池取连接前探活（`core/db.py:461`）。关掉 = 减少一次往返，但可能取到失效连接 | 同上 | ⚠️ **属运维调优位**，非功能位 |
| `scene_idle_reset_enabled` | 场景空闲重置（`services/scene_service.py:33,53`）。关掉 = 场景状态不因空闲复位 | 同上 | |
| `observability_persist_enabled` | 观测落库总闸（**14 处读取**：`main.py:103`、`chains/{answer,proactive,summary}_chain.py`、`application/observability.py` ×7、`post_process.py:614`、`api/v1/proactive.py` ×2）。关掉 = 全链观测不落库 | 同上 | 关断价值高（性能/隐私） |
| `world_enabled` | 世界域总闸（**11 处读取**）。关掉 = 世界域整体旁路，聊天链路照常 | 同上 | 世界旁路纪律的载体 **（已删 2026-09-28，固化常开，见 附录 E.8）** |
| `world_household_autoseed_enabled` | 家居库存幂等播种（`world_engine.py:427`）。关掉 = 不自动播种 | 同上 | |
| `world_interpreter_enabled` | 用户消息 → 世界迁移解释（`world_engine.py:919`）。关掉 = 世界不随对话演进 | 同上 | |
| `world_memory_bridge_enabled` | 世界 → 记忆桥（`world_engine.py:860,908`）。关掉 = 世界事件不入记忆 | 同上 | |
| `inventory_grounding_enabled` | 库存 grounding 缓冲（`chat_pipeline.py:725`）。关掉 = 回答不再被库存约束 | 同上 | **真实 `.env` 已设为 true** |
| `rel_evolution_enabled` | 关系演化引擎（`relationship_evolution.py:215`、`state_service.py:193`）。关掉 = 关系不演化 | 同上 | |
| `rel_milestone_enabled` | 关系里程碑检测（`relationship_milestone.py:215`） | 同上 | |
| `rel_conflict_enabled` | 关系冲突状态机（`relationship_conflict.py:121`） | 同上 | |
| `plan_context_digest_enabled` | 计划上下文摘要（`services/planning/engine.py:309`） | 同上 | |
| `evaluation_enabled` | 评估总闸（`evaluation_engine.py:182,270`） | 同上 | 评估是旁路，关断价值存在 |
| `evaluation_autonomy_enabled` | 自治域评估（`:270`） | 同上 | |
| `evaluation_llm_judge_enabled` | LLM Judge 路（`:44`） | 同上 | 关掉 = 评估只走规则路（省 LLM） |
| `evaluation_world_consistency_enabled` | 世界一致性评估（`evaluation_rules/memory.py:93`，`getattr` 默认 True） | 同上 | |
| `runtime_foreground_loop_enabled` | 前台收编开关（`chat_pipeline.py:401`）。关掉 = 走 `_drive_foreground_linear` 线性旧链 | 同上 | **V4.0 PLA-018 已登记清理**（已转常开） |
| `runtime_orphan_run_sweep_enabled` | 孤儿 Run 清扫（`life_loop.py:686`、`recovery.py:48`） | 同上 | 建议保持 True，**阈值可调**（`runtime_orphan_run_timeout_minutes`） |
| `character_action_sync_enabled` | 角色行动同步（`world_engine.py:1040`、`post_process.py:328`）；**默认 False 但真实 `.env` 设为 true** | ⚠️ **固化为 True = 改变未设置该变量的环境行为** | **特殊：不是应急位，是"默认与部署不一致"** |
| `tool_confirm_ttl_reuse` | 工具批准是否跨轮复用（`services/tool/confirmation.py:576`）；`True` = 落 TTL 持久授权，`False` = 只放行当次 | ❌ **策略位**（见 §3.3 E 类） | docstring 自述「不是部署闸门」 |

### 3.2 C 类：待激活预留位（18 个）

**共同特征**：默认 `False`；读取形态为 `if settings.X: <执行新路径>`；**生产路径不含该分支**（即当前跑的是 `else` / 跳过）。

**共同去除后果**：**删除未启用的能力路径**（含对应测试与 `override_settings` 断言）。若该能力确认不做，删除是净收益；若将来要启用，需重写。

#### 3.2.1 Agent Runtime 收编位（V3.0.0 新增，7 个）

| 字段 | 用处（开启后发生什么） | 去除后果 |
|---|---|---|
| `runtime_session_tracking_enabled` | 把 `session_id` 写入 `loop_runs`（`controller.py:54`） | 删 = `session_id` 永远写 NULL → **会话台账不可查** |
| `runtime_state_versioning_enabled` | 状态版本化视角（`state.py:246`） | 删 = 状态读回到「Run 开始时刻」约定 |
| `runtime_context_freeze_enabled` | Run 内冻结上下文（`context.py:237`、`chat_pipeline.py:411`） | 删 = 逐段即时读（**注意：生产恒不进入此分支**，V3.0 遗留 L2） |
| `runtime_event_bus_enabled` | 进程内事件总线（`events.py:85`） | 删 = 段级事件不发（观测面收窄） |
| `runtime_reflect_in_loop_enabled` | 循环内 Reflect 慢时钟段（`stages/reflect.py:80`） | 删 = 循环内反思不启用（**且它依赖影子实现**） |
| `runtime_autonomous_cycle_enabled` | 后台自治走 Agent Runtime（`controller.py:330`） | 删 = 后台固定走 legacy 路径 → **与 V4.0 PLA-018「统一到 Runtime」目标冲突** |
| `runtime_six_stage_loop_enabled` | 六段认知循环（`loop.py:121,528`） | 删 = 六段**影子实现**永久不可达（`SHADOW_STAGE_IMPLEMENTATION=True`） |

> ⚠️ **这 7 个不是"门控残留"，而是 V3.0.0 的显式灰度设计**（`docs/version/v3.0.0/tasks.md` §0.4 首批字段清单）。其中 `runtime_six_stage_loop_enabled` 是**影子实现的开关**——删掉它等于宣布「方案 A 真收编」永不推进，需先决策。
> **V4.0 已登记处置**：`runtime_foreground_loop_enabled` 与 `runtime_autonomous_cycle_enabled` 由 PLA-018 置为唯一有效值并登记 `flag-removal-audit.md` 待清理。

#### 3.2.2 飞书通道子闸（4 个）

| 字段 | 用处 | 去除后果 |
|---|---|---|
| `feishu_enabled` | 飞书通道总闸（`main.py:66`、`api/v1/feishu/webhook.py:36`、`client.py:187`、settings 校验器 `:107`）；**也是 `channel_tools_enabled()` 的唯一剩余闸**（`channel_tools.py:89`） | ❌ **部署闸**，见 D 类 |
| `feishu_dedupe_persistent_enabled` | 入站去重落库（`api/v1/feishu/webhook.py:151`、校验器 `:175`）；关闭 = 仅进程内去重 | 删 = 固定为「不落库」→ **多实例部署下重复消费风险**（架构文档已记多实例硬前置） |
| `feishu_ingress_sharded_routing_enabled` | 分片路由（校验器 `:171`） | 删 = 固定为不分片 → **多实例部署能力丧失** |
| `feishu_router_enabled` | 路由器入口（`api/v1/feishu/ingress.py:50`、校验器 `:121,171`） | 删 = 该入口永久不可用 |

> 三个子闸在 `.env.example` 中**均为注释状态**（即示例配置不启用），真实 `.env` 也未设置。

#### 3.2.3 行动 / 自治 / 业务预留位（7 个）

| 字段 | 用处 | 去除后果 |
|---|---|---|
| `action_relationship_enabled` | 行动 → 关系信号投递（`relationship_bridge.py:43`） | 删 = 行动不影响关系 |
| `autonomy_action_enabled` | 自治动作分支（`autonomy_engine.py:373`；`character/asuna/action.py:224` 注明「开关开启且命中才求值，否则零路径」） | 删 = 自治动作能力移除 |
| `action_outbox_enabled` | 行动写世界的 outbox 路径（**8 处读取**：`life_loop.py:663,721`、`action_engine.py:634`、`capabilities/world_action.py` ×4、`capabilities/reminder.py` ×2） | 删 = 固定为「直写 / 非 outbox」路径 → **破坏 `deferred_world_op → outbox → world_engine` 唯一写面纪律**（基线 §9 记为「未收敛门控」） |
| `rel_signal_llm_enabled` | — | **死开关**（见 A 类） |
| `foreground_gateway_enforced` | 前台预算闸**硬/软**裁决（`llm_gateway.py:105,111,152`、`llm_budget_gate.py:42,46`） | ❌ **策略位**（见 E 类） |
| `observability_prompt_redact` | Prompt 脱敏（`services/observability/prompt_capture.py:58`） | ❌ **隐私策略位**——删掉须选定一个值（见 E 类） |
| `character_action_sync_enabled` | 角色行动同步（见 B 类备注） | ⚠️ **默认与部署不一致**，需单独裁决 |

### 3.3 D 类：部署闸（1 个，保留）

| 字段 | 用处 | 去除后果 |
|---|---|---|
| `feishu_enabled` | 决定是否注册飞书通道（适配器 / 通道工具 / 出站网关 / 幂等持久化 4 处注册点，`main.py:66-91`），以及 `channel_tools_enabled()` 的唯一判据 | ❌ **环境耦合**：删掉后，未部署飞书的环境也必须加载飞书客户端与注册链；且**失去「本地不起飞书」的能力** |

> **结论：保留。** 这是 53 个开关里**唯一名副其实的部署门控**。

### 3.4 E 类：策略裁决位（3 个，保留）

**判定关键**：这些字段的**两个取值都是合法运行态**，不是「启用 / 关闭功能」。

| 字段 | 两个取值的含义 | 去除后果 |
|---|---|---|
| `tool_confirm_ttl_reuse` | `True` = 工具批准落 TTL 持久授权；`False` = 批准只放行当次（`services/tool/confirmation.py:438,576`） | ❌ **失去策略可调性**：必须写死一个值，而两者都是合理安全策略（可用性 vs 严格性） |
| `plan_tool_required` | `True` = 要求工具面可用时步骤必须绑定工具；`False` = 允许无面规划（`services/planning/decompose.py:440`、`context.py`、`api/v1/debug.py:970`） | ❌ 同上；且字段 docstring 自述「不是『激活计划编排』的开关」 |
| `foreground_gateway_enforced` | `True` = 前台 LLM 预算超限**硬拒绝**；`False` = 软模式（仅置 `degraded` 不拒绝，`llm_gateway.py:105,111,152`） | ❌ **成本策略位**：硬拒绝可能中断用户回复，软模式保证可用性；取舍需按运营情况调 |

> 基线 §9 曾把 `foreground_gateway_enforced` 记为「未收敛门控」并注明「缺 `light_llm_profile` 裁决保留」——本审查确认：**它是策略位，应当保留，不应按门控清理。**

### 3.5 F 类：csv 集合闸（4 个）

| 字段 | 用处 | 去除后果 |
|---|---|---|
| `runtime_loop_optional_stages` | 可选段清单（`loop.py:148`）；控制 Plan / Reflect 是否进入循环 | 删 = 固定段集合（当前为空 = 全不进，与现状等价） |
| `runtime_inbound_gateway_channels` | 已纳管入站归一渠道（`inbound.py:52`） | 删 = 固定集合；**新增渠道时需改代码而非配置** |
| `runtime_outbound_gateway_channels` | 已纳管出站渠道（`outbound.py:74`） | 同上 |
| `agent_event_escalation_types` | 事件驱动 Profile 白名单（`trigger_router.py:33`、`controller.py:432`） | 删 = 固定白名单；**未来新增可升级事件类型需改代码** |

> 这四个都是「范围可配位」——**它们的存在让"新增渠道 / 新增可选段 / 新增升级事件"不必改代码**。在当前阶段（渠道数少）价值有限，但删除会把「扩展点」变成「硬编码改造」。

---

## 四、去除后果判定矩阵（汇总）

| 去除后果类型 | 字段数 | 代表字段 | 风险 | 建议 |
|---|---|---|---|---|
| **零后果**（无读取点） | **2** | `autonomy_enabled`、`rel_signal_llm_enabled` | 极低 | ✅ **批次 1（已执行，见 附录 D）** |
| **行为不变，失去应急关断** | 20 | `world_enabled`、`observability_persist_enabled`、`action_detector_enabled`… | 低（代码层）／中（运维层） | ⚠️ **批次 2 择机**，需先接受 R17 代价（`world_enabled` 已提前执行，见 附录 E.8） |
| **删除未启用能力路径** | 13 | `runtime_*` 7 位、`feishu_*` 3 子闸、`autonomy_action_enabled`、`action_relationship_enabled` | 中（需逐项决策能力去留） | ⏸ **批次 3 逐项裁决** |
| **静默退化为「永远开启」** | 8 | `evaluation_{dimension}_enabled`（动态读取） | **中高**（能力消失且不报错） | ❌ **保留** |
| **环境耦合** | 1 | `feishu_enabled` | 高 | ❌ **保留** |
| **失去策略可调性** | 4 | `tool_confirm_ttl_reuse`、`plan_tool_required`、`foreground_gateway_enforced`、`observability_prompt_redact` | 中 | ❌ **保留** |
| **失去范围可配性** | 4 | 4 个 csv 闸 | 低 | ⏸ 视扩展需求 |
| ⚠️ **默认与部署不一致** | 1 | `character_action_sync_enabled`（默认 False，`.env` 设 true） | 中 | ⚠️ **单独裁决** |

> **合计**：2 + 20 + 13 + 8 + 1 + 4 + 4 + 1 = **53** ✓（与 §2.1 实测规模一致）

---

## 五、与 V4.0「禁止新增功能开关」裁决的关系

V4.0.0 已立下**铁律 5：禁止新增功能开关阀门**（`docs/version/v4.0.0/architecture.md` §0.2 / §9 / §10 不变量 11），并登记了该裁决的代价：

> **R17 无开关带来的回滚粒度变粗**——出问题时只能整版代码回滚，无法单点关闭。用**设计层隔离**对冲（append-only / 新增端点不改既有契约 / 迁移可逆），接受「回滚粒度粗」换「配置面干净」。（`docs/version/v4.0.0/tasks.md` §5.1）

**本审查为该裁决提供了存量侧的实证**：

- 存量 53 个阀门中，**真实被设置过的只有 4 个** → 印证「纸面可配置性 ≫ 实际在用」；
- **2 个是真死开关**（另有 8 个**看似死、实为动态读取**）→ 印证「开关会随演进腐化」，**同时也印证「字段的可达性不能靠静态 grep 断言」**；
- **但 20 个是应急关断位、8 个是维度策略开关** → 印证 R17 的取舍是真的存在：**存量开关里有相当一部分有实际运维价值**，V4.0 选择不加新开关、靠设计层隔离换取，是一笔**明账**而非无知。

**结论**：V4.0 的「不加新开关」与存量「不急着删开关」**并不矛盾**——新代码用设计层隔离保证可回滚，存量开关按本文批次逐步收敛，**不做运动式清理**。

---

## 六、清理批次建议

| 批次 | 范围 | 前置条件 | 出口判据 |
|---|---|---|---|
| **批次 1（无风险）** | **2 个死开关**（`autonomy_enabled` / `rel_signal_llm_enabled`）：删字段 + 删测试侧登记项 + 修 README 中的过时描述 | 无 | 全量测试零回归；`grep` 确认零残留引用 —— **✅ 已执行，见 附录 D** |
| **批次 2（需先接受代价）** | 默认 ON 的应急关断位中，**确认永不会关**的子集（如 `rel_milestone_enabled`、`world_household_autoseed_enabled`、`plan_context_digest_enabled`） | 需确认对应回归清单已执行（`AGENTS.md`：V4 / V7 / V7.5 / V7.8 / V8 / V2.0.0 / V2.1.0~V2.6.1 的真实模型人工回归**尚待执行**） | 逐项固化后行为对照；**未执行人工回归前不得开工** |
| **批次 3（需逐项决策）** | `runtime_*` 7 位 + 3 个 feishu 子闸 + `autonomy_action_enabled` / `action_relationship_enabled` | 需先决策：① 六段方案 A 是否推进；② 飞书多实例部署是否需要；③ 自治动作 / 行动关系信号是否启用 | 每项有明确的能力去留结论 |
| **保留批（不动）** | `feishu_enabled`（部署闸）、`tool_confirm_ttl_reuse` / `plan_tool_required` / `foreground_gateway_enforced`（策略位）、4 个 csv 闸 | — | — |
| **特殊裁决** | `character_action_sync_enabled`（默认与 `.env` 不一致）、`action_outbox_enabled`（关掉会破坏 outbox 唯一写面纪律） | 需架构裁决 | 二者都不宜按普通门控处理 |

### 6.1 与 V4.0 的衔接

- **PLA-018** 会处置 `runtime_foreground_loop_enabled` 与 `runtime_autonomous_cycle_enabled`（置唯一有效值 + 登记台账）——**这两项不重复登记在本审查的批次里**；
- **PLA-001** 会把迁移链头钉测收敛为单点，与开关无关但同属「降低后续改动成本」的地基工作；
- 本审查的**批次 1 可作为独立 refactor 任务**插入 V4.0 之前/并行，风险最低、收益明确（删掉 10 个无人读取的字段与登记项）。

---

## 附录 A：完整阀门清单（53 个）

> 字段 → 默认 → 读取点数量 → 分类 → 去除后果

| # | 字段 | 默认 | 读取点 | 类 | 去除后果 |
|---|---|---|---|---|---|
| 1 | `action_detector_enabled` | T | 1 | B | 行为不变/失去关断 |
| 2 | `action_memory_policy_enabled` | T | 2 | B | 同上 |
| 3 | `action_relationship_enabled` | F | 1 | C | 删除未启用路径 |
| 4 | `autonomy_action_enabled` | F | 1 | C | 同上 |
| 5 | `action_outbox_enabled` | F | 8 | C ⚠️ | **破坏 outbox 唯一写面** |
| 6 | `feishu_enabled` | F | 4 + 校验器 | **D** | 环境耦合 → 保留 |
| 7 | `feishu_dedupe_persistent_enabled` | F | 1 + 校验器 | C | 多实例去重能力丧失 |
| 8 | `feishu_ingress_sharded_routing_enabled` | F | 校验器 | C | 分片路由能力丧失 |
| 9 | `feishu_router_enabled` | F | 1 + 校验器 | C | 路由入口不可用 |
| 10 | ~~`autonomy_enabled`~~ | T | **0** | **A** | **零后果**（**已删，批次 1**） |
| 11 | `db_pool_pre_ping` | T | 1 | B | 行为不变/失去关断（运维调优位） |
| 12 | `evaluation_enabled` | T | 2 | B | 行为不变/失去关断 |
| 13 | `evaluation_persona_enabled` | T | **动态** | **G** | **静默退化为「永远开启」** |
| 14 | `evaluation_emotion_enabled` | T | **动态** | **G** | 同上 |
| 15 | `evaluation_memory_enabled` | T | **动态** | **G** | 同上 |
| 16 | `evaluation_behavior_enabled` | T | **动态** | **G** | 同上 |
| 17 | `evaluation_autonomy_enabled` | T | 1 + **动态** | **G/B** | 同上（另有静态读取点） |
| 18 | `evaluation_goal_enabled` | T | **动态** | **G** | 同上 |
| 19 | `evaluation_llm_judge_enabled` | T | 1 | B | 关断 = 评估省 LLM |
| 20 | `evaluation_world_consistency_enabled` | T | 1（`getattr` 静态名） | B | 行为不变/失去关断 |
| 21 | `evaluation_reflection_enabled` | T | **动态** | **G** | **静默退化为「永远开启」** |
| 22 | `evaluation_relationship_enabled` | T | **动态** | **G** | 同上 |
| 23 | `evaluation_action_enabled` | T | **动态** | **G** | 同上 |
| 24 | `observability_persist_enabled` | T | 14 | B | 行为不变/失去关断（价值高） |
| 25 | `observability_prompt_redact` | F | 1 | **E** | 失去隐私策略可调性 → 保留 |
| 26 | `scene_idle_reset_enabled` | T | 2 | B | 行为不变/失去关断 |
| 27 | `plan_tool_required` | T | 3 | **E** | 失去策略可调性 → 保留 |
| 28 | `plan_context_digest_enabled` | T | 1 | B | 行为不变/失去关断 |
| 29 | `rel_evolution_enabled` | T | 2 | B | 同上 |
| 30 | ~~`rel_signal_llm_enabled`~~ | F | **0** | **A** | **零后果**（**已删，批次 1**） |
| 31 | `rel_milestone_enabled` | T | 1 | B | 行为不变/失去关断 |
| 32 | `rel_conflict_enabled` | T | 1 | B | 同上 |
| 33 | `tool_confirm_ttl_reuse` | T | 1 | **E** | 失去策略可调性 → 保留 |
| 34 | `world_enabled` | T | 11 | B | 行为不变/失去关断（价值高）**（已删 2026-09-28，见 附录 E.8）** |
| 35 | `world_household_autoseed_enabled` | T | 1 | B | 同上 |
| 36 | `world_interpreter_enabled` | T | 1 | B | 同上 |
| 37 | `character_action_sync_enabled` | F（`.env`=T） | 2 | ⚠️ 特殊 | 默认与部署不一致 |
| 38 | `inventory_grounding_enabled` | T（`.env`=T） | 1 | B | 行为不变/失去关断 |
| 39 | `world_memory_bridge_enabled` | T | 2 | B | 同上 |
| 40 | `foreground_gateway_enforced` | F | 5 | **E** | 失去成本策略可调性 → 保留 |
| 41 | `runtime_session_tracking_enabled` | F | 1 | C | 会话台账不可查 |
| 42 | `runtime_state_versioning_enabled` | F | 1 | C | 回到「Run 开始时刻」读约定 |
| 43 | `runtime_context_freeze_enabled` | F | 2 | C | 逐段即时读（生产恒不进入） |
| 44 | `runtime_event_bus_enabled` | F | 1 | C | 段级事件不发 |
| 45 | `runtime_reflect_in_loop_enabled` | F | 1 | C | 循环内反思不启用 |
| 46 | `runtime_autonomous_cycle_enabled` | F | 1 | C | 后台固定走 legacy（**与 PLA-018 冲突**） |
| 47 | `runtime_foreground_loop_enabled` | T | 1 | B（PLA-018 处置） | 失去 kill switch |
| 48 | `runtime_six_stage_loop_enabled` | F | 2 | C ⚠️ | 六段影子永久不可达 |
| 49 | `runtime_orphan_run_sweep_enabled` | T | 2 | B | 行为不变/失去关断 |
| 50 | `runtime_loop_optional_stages` | `""` | 1 | **F** | 固定段集合 |
| 51 | `runtime_inbound_gateway_channels` | `""` | 1 | **F** | 固定入站纳管集合 |
| 52 | `runtime_outbound_gateway_channels` | `""` | 1 | **F** | 固定出站纳管集合 |
| 53 | `agent_event_escalation_types` | `""` | 2 | **F** | 固定升级白名单 |

> **读取点数量**为 `apps/backend/app` 内实测（不含 settings 字段定义与校验器自身读取）；测试侧引用（`override_settings` / `monkeypatch` / conftest 字段映射）未计入。

## 附录 B：复现命令

```powershell
# 1) 枚举全部 bool 字段
rg -n "^\s+[a-z_]+:\s*bool\s*=" apps/backend/app/core/settings

# 2) 统计阀门规模
rg -c "^\s+[a-z_]+:\s*bool\s*=" apps/backend/app/core/settings

# 3) 查某字段的全部读取点
rg -n "\.autonomy_enabled\b|rel_signal_llm_enabled" apps/backend

# 4) 真实部署显式设置了哪些开关（判定"是否真有人关它"）
rg -n "_ENABLED=|_REDACT=|PRE_PING=|TOOL_REQUIRED=|TTL_REUSE=|GROUNDING=|AUTOSEED=|INTERPRETER=|IDLE_RESET=|DIGEST=|EVOLUTION=|MILESTONE=|CONFLICT=|OUTBOX=|SYNC=|JUDGE=" apps/backend/.env apps/backend/.env.example

# 5) 确认 csv 集合闸
rg -n "runtime_loop_optional_stages|runtime_inbound_gateway_channels|runtime_outbound_gateway_channels|agent_event_escalation_types" apps/backend
```

---

## 附录 C：本次审查发现的基线偏差（待回写）

| # | 基线记载 | 实测 | 处置 |
|---|---|---|---|
| 1 | `current-system-architecture-baseline.md` §7.1：「settings 字段总数 405、**37 个布尔字段**」 | bool 字段 **49**（+ csv 闸 4 = 53 阀门） | V3.0.0 新增 13 个 `runtime_*` 所致；**建议在 V4.0 基线回写时校正** |
| 2 | 基线 §9：「残留的少数布尔开关是策略位 / 裁决位 / 调试位」+「`foreground_gateway_enforced` / `action_outbox_enabled` 两个门控未收敛」 | 实测 53 个阀门，其中 **2 个为死开关**、**20 个为应急关断位**、**8 个为动态维度开关** | 分类需细化：**「策略位」只占 4 个**；多数是应急关断位，仅 2 个应删 |
| 3 | 基线 §7.2 未提 `evaluation_*` 维度闸，也未提**动态读取**形态 | `evaluation_rules/__init__.py:38,73` 用 f-string 动态读取 8 个维度开关 | 建议**在基线中登记「settings 字段存在动态读取形态」**，否则后续审计会重复踩坑（见 附录 D） |
| 4 | `apps/backend/README.md`：`AUTONOMY_ENABLED` 为「自主行为总开关（关闭则 Worker 不启动）」 | 该字段零读取点，对应 worker 已被 life_loop 归并 | **已随批次 1 修正** |

---

## 附录 D：批次 1 执行记录与方法论补正（2026-09-22）

> 按 `flag-removal-audit.md` 的约定：正文保持**审查期口径**，执行进展记在附录。

### D.1 执行结果

| 项 | 内容 |
|---|---|
| 批次范围 | 2 个死开关（`autonomy_enabled` / `rel_signal_llm_enabled`） |
| 最终 diff | **4 文件 / +1 −6**：`settings/autonomy.py`（−1）、`settings/relationship.py`（−1）、`tests/conftest.py`（−2）、`README.md`（+1/−2） |
| 附带清理 | `tests/conftest.py:17` 删 `os.environ.setdefault("AUTONOMY_ENABLED", "false")`（死 env 默认）；`tests/conftest.py` 的 `env_map` 删 `rel_signal_llm_enabled` 条目；`README.md` 删 `AUTONOMY_ENABLED` 两处过时描述 |
| 残留核验 | 精确 grep（含**大小写与词边界**）→ **零命中** |
| Fast Test | `pytest -m "(unit or api) and not slow"` → **2 failed / 1879 passed**；2 个失败均为 `tests/unit/test_feishu_settings.py`，**基线对照法确认既存**（原因：真实 `.env` 含飞书 App ID / Secret，用例期望空默认值——与本改动无关） |
| 域级回归 | `tests/evaluation + tests/eval + tests/v8.5 + tests/v2` → **2 failed / 737 passed / 8 skipped**；2 个失败同样经基线对照确认既存（`test_aut005_goal_evaluation.py` 见 V3.0.0 验收报告既存失败清单；`test_life002_controller.py::TestUserCycle` 基线同样失败） |

### D.2 方法论补正（本次最重要的产出）

**初版审查把 8 个 `evaluation_{dimension}_enabled` 误判为死开关，真实数量是 2。** 根因与修正：

| # | 环节 | 初版做法（有缺陷） | 修正后做法 |
|---|---|---|---|
| 1 | **查找读取点** | 只检索字段属性访问 `\.字段名\b` 与裸字段名 | **必须额外检索动态构造**：`getattr(settings, f"..."` / f-string 拼接的字段名 |
| 2 | **大小写** | 只检索**小写字段名** | **必须同时检索大写 env 名**（测试侧常用 `monkeypatch.setenv("XXX_ENABLED", ...)`、`os.environ.setdefault` 字面量） |
| 3 | **验证手段** | 仅靠静态 grep 断言「零读取点」 | **必须以测试为最终裁判**——本次误判正是被 `tests/unit/test_evaluation_rule_engine.py::test_run_rules_honors_dimension_toggle` 暴露的 |

**本项目的两种字段读取形态（必须同时查）**：

```python
# 形态 ①：静态属性访问（grep 字段名可命中）
if not settings.action_detector_enabled:
    return None

# 形态 ②：动态 f-string（grep 字段名【无法】命中）★ 易漏
return bool(getattr(settings, f"evaluation_{dimension.value}_enabled", True))
```

> **为什么形态 ② 特别危险**：`getattr(..., True)` 的默认值使**字段缺失时静默退化为「永远开启」**——不报错、不改变默认行为，**能力消失而无任何信号**。这类字段一旦被误删，问题只会在「有人想关掉它」时才暴露，可能延迟数月。

### D.3 复现命令（补正版审计流程）

```powershell
# 1) 枚举全部 bool 字段（含 csv 集合闸需另行枚举 : str = ""）
rg -n "^\s+[a-z_]+:\s*bool\s*=" apps/backend/app/core/settings

# 2) 静态读取点（形态 ①）
rg -n "\.字段名\b" apps/backend

# 3) ★ 动态读取点（形态 ②，初版漏掉的一步）
rg -n "getattr\((self\.)?_?settings, f\"" apps/backend/app
rg -n "f\"[a-z_]*_enabled\"" apps/backend/app

# 4) ★ 大写 env 名引用（测试侧常见，初版漏掉的一步）
rg -n "\bFIELD_NAME\b" apps/backend        # 字段名大写形式

# 5) 真实部署是否设置过（判定"是否真有人关它"）
rg -n "_ENABLED=|_REDACT=|PRE_PING=|TOOL_REQUIRED=|TTL_REUSE=|GROUNDING=|AUTOSEED=|INTERPRETER=|IDLE_RESET=|DIGEST=|EVOLUTION=|MILESTONE=|CONFLICT=|OUTBOX=|SYNC=|JUDGE=" apps/backend/.env apps/backend/.env.example

# 6) ★ 删字段后的仲裁：跑 Fast Test，并对失败项做基线对照
uv run --directory apps/backend pytest -m "(unit or api) and not slow" -q
#   基线对照法（本机 git stash 不可信，用文件级备份）：
#   备份改动 → git checkout -- <改动文件> → 同命令复跑 → 恢复改动 → 比对失败集合
```

### D.4 对批次 2 / 3 的修正影响

- **批次 2（应急关断位择机固化）**：范围由「31」修正为 **20**，判断标准不变（需先接受 R17 代价 + 人工回归前置）。
- **批次 3（预留位逐项决策）**：范围由「~14」修正为 **13**，内容不变。
- **新增建议**：把 §D.2 的「动态读取形态」登记进 `docs/current-system-architecture-baseline.md` 与 `docs/TESTING.md`，避免后续审计重复踩坑。

## 附录 E：两个 `v2_` 段开关删除记录（2026-09-28）

### E.1 执行结果

按「先删 `INVENTORY_GROUNDING_ENABLED`、再删 `CHARACTER_ACTION_SYNC_ENABLED`」顺序执行，两者均**固化常开**（与真实 `.env` 取值一致），settings 字段与 env 键一并删除。

| 开关 | 原代码默认 | `.env` | 处置 | 关断能力去向 |
|---|---|---|---|---|
| `inventory_grounding_enabled` | True | true | 删字段 + 删 env 键 | **保留**：`INVENTORY_GROUNDING_MODE=off` 是逐字节等价的关断位 |
| `character_action_sync_enabled` | **False** | true | 删字段 + 删 env 键 | **失去**：无等价关断位（`character_action_sync_context_lines` **实测 `limit<=0` 仍返回 1 条**，无法清零读侧；写侧更不受它控制） |

改动文件（11）：`core/settings/world.py`、`application/chat_pipeline.py`、`application/post_process.py`、`application/world_engine.py`、`tests/v40/support.py`、`tests/integration/test_character_action_sync.py`、`tests/e2e/test_{foreground_cutover_parity,six_stage_loop_parity,chat_http_integration,turn_meta_stream}.py`、`.env.example`。

### E.2 对 §3.1 / §3.3 结论的修正

- §3.1 第 38 行判 `inventory_grounding_enabled`「失去关断能力」**不准确**。`chat_pipeline.py` 的表达式
  `mode if enabled and world_ctx is not None else "off"` 使 `enabled=False, mode=rewrite` 与
  `enabled=True, mode=off` 产出**完全相同的 `grounding_mode="off"` / `buffer_reply=False`**。
  故该字段是**冗余开关**，删除成本远低于同类 B 类位——本次据此直接删除，无需应急关断位豁免。
- §3.3 对 `character_action_sync_enabled` 的「⚠️ 单独裁决」已由本次执行裁决为**固化 True**。
  已接受代价：无 `.env` 的环境从「不同步」变为「同步」（§3.1 备注所指的行为变化）。

### E.3 冻结面再冻结（必须显式声明）

本次触及 3 个被整文件哈希钉死的冻结面，已同步摘要并加声明注释：

| 文件 | 钉测 | 原摘要 | 新摘要 |
|---|---|---|---|
| `app/application/chat_pipeline.py` | `tests/v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` | `25f71edc…` | `4aec8e65…` |
| `app/application/post_process.py` | 同上 | `3f154e76…` | `c1702717…` |
| `app/application/world_engine.py` | `tests/v24/test_tool007_integration.py::FROZEN_SOURCES` | `3bdcd4f4…` | `baa7aa5e…` |

⚠️ `world_engine.py` 的原摘要 `3bdcd4f4` **在本次改动前已 stale**（HEAD `16f76cb` 实测 `178b6024`）——
`test_frozen_sources_have_zero_diff[app/application/world_engine.py-3bdcd4f4…]` 在改动前即为红。
本次一并纠正，该红转绿属**顺带修复**，非本次引入。

### E.4 测试与基线对照

- 全量：本次 **33 failed / 7145 passed**；基线树（`git worktree` @ `16f76cb` + 同 `.env`）**26 failed / 7154 passed**。
- 集合差「仅本次独有」8 条：3 条为上述冻结面钉测（已修）；其余 5 条经隔离重复 3 次判定为 flaky 或既有——
  `test_debug_state_history::test_state_reflects_turn_and_respects_limit` 在两棵树上均以同一断言
  `assert 3 >= 4` 间歇失败（基线 1/3、本次 2/3），属既有 flaky。
- 结论：**零真回归**。
- 修复后定向复跑 `tests/v24/test_tool00{7,8,10}_*.py` + `tests/integration/test_character_action_sync.py`
  + `tests/v40/*` + `tests/unit/test_settings_flag_guard.py` = **150 passed / 1 failed**；唯一失败
  `test_tool008_integration::test_reminder_create_end_to_end_deposits_memory` 在两棵树上均失败（既有）。
- 测试侧为何零行为变化：`tests/conftest.py` 未隔离 CAS 与 grounding 两个键，而 `Settings` 的
  `env_file=".env"` 在 `apps/backend` 为 CWD 时生效（实测 `answer_max_tokens=60` 来自 `.env`）——
  即测试环境**改动前 CAS/grounding 已为 ON**，固化常开在测试侧等价。

### E.5 遗留运维动作（必须同步部署侧）

`unknown_versioned_env_keys()` 只识别 `^V[0-9]+_` 前缀（原 `app/core/settings/__init__.py:88`），
而本次删除的两个键**无版本前缀**，部署侧 `.env` 若仍保留
`CHARACTER_ACTION_SYNC_ENABLED=true` / `INVENTORY_GROUNDING_ENABLED=true`，会被 `extra="ignore"`
**静默吞掉**。

🚨 **该守卫已于 2026-09-28 整体删除**（连同 `app/main.py` lifespan 的告警循环、`__all__` 条目与 3 条自测）。
删除时实测全仓 `^V[0-9]+_` 键为 **0 个**、函数返回 `[]`，故**删除本身零行为变化**；代价是
**生产启动边界不再有任何「env 键 ↔ settings 字段」一致性检查**（另一条守卫
`tests/conftest.py::set_known_env` 只在测试进程生效）。`docs/current-system-architecture-baseline.md`
§7.2 已同步登记。

因此部署侧清理由「可选」升级为**必须人工核对**：逐条删除
`CHARACTER_ACTION_SYNC_ENABLED` / `INVENTORY_GROUNDING_ENABLED`，并按 `flag-rename-map.md`
的「旧 env」列清掉 `V2_*` / `V23_*` / `V24_TOOL_*` / `V26_ACTION_*`
（`flag-removal-audit.md:1506` 遗留待办②至今未见关闭记录）。本仓库 `.env` / `.env.example` 已清。

### E.6 删除后审核发现的问题与修复（2026-09-28，同日）

删除落地后做了一轮审核（探针实测，非静态推断），发现 **1 条真隐患 + 2 处本次交付自身的缺陷**，均已修：

| # | 级别 | 问题 | 修法 |
|---|---|---|---|
| 1 | **P1** | **CAS 成了唯一绕过 `world_enabled` 的世界创建路径**：第 8 步 `run_world_update` 先判 `world_enabled` 再 `ensure_world`，第 9 步 CAS 直接 `ensure_world`，而 `ensure_world` 自身也不检查该闸 → `world_enabled=False` 的部署每轮建出**永远读不到的孤儿 world**（`build_context` 仍被 `world_enabled` 挡住）。此前该路径可被 `character_action_sync_enabled=False` 关掉，本次固化常开后不再可关。**探针实测**：CAS 前 `worlds` 行数 0 → CAS 后 1。 | `run_character_action_sync` 开头补 `if not get_settings().world_enabled: return`（与第 8 步对称）；新增集成用例 `test_world_disabled_short_circuits_without_creating_world`——该路径此前**零测试覆盖**（两个 e2e parity 用例设了 `world_enabled="false"` 却断言不到它） |
| 2 | **P1** | E.1 原写「`character_action_sync_context_lines=0` 只清读侧」——**实测 `limit<=0` 仍返回 1 条**（`context_selector.py` 先 `append` 再判 `len(rows) >= limit`），该字段**无法清零读侧**且无 validator | 更正 E.1 措辞；`recent_world_changes_from_events` 补 `if limit <= 0: return []`，使 `<=0` 语义确定为「不注入」；新增 `test_derivation_non_positive_limit_yields_nothing` |
| 3 | **P1** | `tests/v40/support.py::V30_ENABLED_FLAGS` docstring 自称「V3.0.0 冻结基线…静态快照」，本次是其**首次删除条目**（git 历史全 `+` 零 `-`）却未登记 | docstring 补「首次删除记录（2026-09-28）」并指向本附录 |
| 4 | P2 | `.env.example` 未记录 `INVENTORY_GROUNDING_MODE` 的 `off` 取值，而 `off` 是 grounding 唯一关断位（唯一记载处是 `flag-rename-map.md:44` 历史表） | `.env.example` / `.env` 注释块重写，列出 `off / rewrite / annotate` 语义 |
| 5 | P3 | `.env.example` 的 CAS 注释块只剩一个调参字段却仍写 "extract CREATE/MOVE/CONSUME" | 注释块改为「调参（开关已固化常开，无配置面）」，与同文件 World Simulation 段同风格 |
| 6 | P3 | 基线 §7.2「settings 字段总数 405」 | 改为日期戳记的实测值 **427**（原 405 系 2026-09-20 口径，附录 C 已登记「待 V4.0 回写校正」） |

**冻结面**：修复再次触及 `app/application/post_process.py`（`test_tool010_e2e.py::ZERO_DIFF_HASHES`），摘要 `c1702717…` → `ff3b9a47…`，已同步并加声明注释。

> 未做（属设计裁决，非缺陷）：`character_action_sync_context_lines` 字段名保留了 `character_action_sync` 前缀——CAS 子系统本身仍在（只是开关删除），命名仍准确。

### E.7 world 域三个子闸删除（2026-09-28，同日后半）

用户裁决「`world_interpreter_enabled` / `world_household_autoseed_enabled` / `world_memory_bridge_enabled` 都删」。实测三者性质**不对称**，处置也不同：

| 开关 | app 门控点 | 行为测试依赖 | 处置 |
|---|---|---|---|
| `world_interpreter_enabled` | 1（`world_engine.py:936`，与 `world_enabled` 合取） | **0** | 删字段，条件收窄为 `if not settings.world_enabled` |
| `world_memory_bridge_enabled` | 2（`:877` `complete_events` / `:925` `expire_stale`） | **0** | 删字段，两处 if 展开为无条件 `materialize_event_memory` |
| `world_household_autoseed_enabled` | 1（`:431` 播种） | **16 个测试依赖** | 删字段 **+ 删依赖测试**（用户裁决） |

🚨 **`world_household_autoseed_enabled` 不是死开关**：11 处测试显式设 `=False` 拿「确定性空世界」，实测强制播种常开后 **16 个用例挂**（`v24/test_tool007_world_context.py` 一个文件就 8 个）。已按用户裁决删除字段并删除依赖用例，**验收覆盖损失**：

- `tests/v8/scenarios/world_scenarios.json` 删 `watermelon_full_chain` 条目（3 → 2 条场景链）
- `tests/v9/scenarios/milk_chain.json` **整文件删除**（3 → 2 条场景链）
- 删测试函数 **9 个**：`v8/test_object_lifecycle::test_object_survives_new_sessions`；`v24/test_tool007_integration::test_build_snapshot_assembles_world_facts_when_master_flag_on`；`v24/test_tool007_world_context::{test_all_facts_land_on_tool_context, test_segment_success_path_is_unaffected_by_other_segment_degradation, test_sub_builders_are_independently_callable}`；`v24/test_tool008_integration::test_reminder_create_end_to_end_deposits_memory`；`integration/test_household_inventory::test_ensure_world_no_autoseed_when_disabled`；`v25/test_plan008_world_paths::{TestReadOnlyWorldPath::test_env_query_step_writes_nothing, TestDeferredWorldWritePath::test_s3_reminder_step_defers_then_lands_through_the_consumer}`
- 掏空 3 个 autouse 隔离夹具（`v24/test_tool007_{integration,world_context}.py`；`v24/test_tool007_surface.py` 整体移除）

**已评估但未采用的替代方案**：`monkeypatch.setattr(world_engine, "seed_default_household", ...)` 夹具（技术可行——`seed_default_household` 是模块级裸名调用，已实测确认）——用户选择删测试，而非重构 12 处测试隔离。

**其余改动**：`tests/v40/support.py::V30_ENABLED_FLAGS` 删 3 名（本会话累计删 **5** 名）；`tests/conftest.py` env_map 删 3 条；`.env` / `.env.example` 本就未设置这三个键。settings 字段总数 427 → **424**。

**冻结面**：`app/application/world_engine.py` 本次会话**第四次** re-freeze，`354581b4…` → `e0bad4c0…`。

**验证**：受影响文件定向复跑 **8 failed / 1859 passed**，8 条全部落在基线失败集内（`v24/test_tool009_reflector` × 6、`v8` 性能预算、`tool012` 迁移）→ **零新增失败**。

⚠️ **过程中的一处自纠**：首轮从 `_segment_cases()` 里删了 6 个条目，导致**共用该参数源**的 `test_all_segments_failing_still_returns_usable_structure` 连带失败——已恢复参数源，改为整函数删除 `test_segment_success_path_is_unaffected_by_other_segment_degradation`。教训：**删除参数化用例前先查该 `parametrize` 源是否被多个测试共用**。

### E.8 世界域主闸 `world_enabled` 删除（2026-09-28，同日收尾）

前置：E.1~E.7 已删 world 域 3 子闸与 2 个 `v2_` 段开关；本批删除**主闸本身**（§3.2 表判「批次 2 择机」，本批提前执行固化常开裁决——代码默认 True、`.env` 从未设 false，全部已知部署取值一致）。

**字段**：`WorldSettings.world_enabled` 删除（settings 字段总数 424 → **423**）。

**门控点展开**（§3.1 记 11 处读取；E.7 子闸删除后实测剩主门控 8 处 + 恒真死读 4 处，全部展开为无条件路径）：

| 文件 | 处置 |
|---|---|
| `application/life_loop.py` | `_step_goal_supply` / `_step_world_experience` / `_run_maintenance`（world_maintenance、world_simulation 两处）/ `_maintenance_pending` 守卫删除 |
| `application/world_engine.py` | `ensure_world`（播种合取收窄）/ `run_turn_update` / `build_context` / `collect_facts` / `run_maintenance` / `run_simulation_maintenance` 守卫删除 |
| `application/chat_pipeline.py` | grounding 合取收窄为 `world_ctx is not None` |
| `application/post_process.py` | CAS 守卫删除（E.6 为 world_enabled=False 补的短路随主闸一并移除） |
| `services/character_action/{extractor,validator}.py`、`services/evaluation_context.py`、`services/planning/{context,observer}.py` | 守卫删除；`planning` 的 `DEGRADED_WORLD_DISABLED` 保留（无世界记录路径仍用） |
| `application/action_engine.py` | `world_available` 赋值的恒真 getattr 删除（字段本身保留，`planner.py` G6 仍消费） |
| `services/action/capabilities/reminder.py` | `world_gate` 整体删除（恒放行），`world_action.py` / `environment_query.py` 两处导入同步移除 |
| `services/tool/{context,world_context,surface}.py` | `ToolContext.world_enabled()` / `_world_reason`（配置态维度）/ surface_hash 配置项 / `_world_enabled` helper 与 builder False 分支删除 |

**保留（非配置开关）**：`WORLD_ENABLED_KEY` 装配标记与 `world_facts_assembled()` / `world_facts_enabled()` —— TOOL-007「已装配 vs 未装配」数据契约；`world["world_enabled"]` 恒为 True，False 态仅作为消费方防御语义存在（E1 用例改由字面事实包覆盖）。

**冻结面**：`test_tool010_e2e.py::ZERO_DIFF_HASHES` 再冻结 **4** 个文件（`reminder.py` / `world_action.py` / `environment_query.py` / `action_engine.py`），附声明注释。

**测试**：配置态维度用例（`test_tool004_surface::test_world_disabled_cuts_world_namespace`）与 builder False 分支用例（`test_tool007_world_context::test_e1_world_disabled_returns_only_flag_and_reads_nothing`）删除；E1 消费方契约改由字面 False 事实包覆盖；`tool004/006/007_support` 假 settings 删该字段；`test_life002_controller::test_first_tick_runs_reconcile_and_records` 的 `== 3` 断言在 HEAD `16f76cb` 上即已 stale（实测 5），本批改按维护步 kind 集合断言。`test_ws019` 用例名去掉 `when_world_enabled` 后缀。

**行为变化**：世界域从「可配置旁路」变「常开」；失去运维应急关断（§3.2 批次 2 预案作废，R17 代价随裁决接受）。`remaining-flag-audit` 正文表（§3.1 / §3.2 / §3.3）为审查期快照，**保留不改**，以本附录为准。

**验证**：定向复跑 v2 / v23 / v24 / v25 / unit / integration 全量 **13 failed / 5549 passed**，13 条逐一归因为既有（`git worktree` @ `16f76cb` 复跑同样失败）：`v24/test_tool009_reflector` × 6、`tool012` 迁移 × 1（E.7 基线失败集）；`test_life002_controller::test_step_error_does_not_block_following_steps`（degraded vs done）、`test_aut005::test_clean_slice_passes_all`、`v25/test_plan001/011/012` 三条 planning prompt 字节锚 —— 四类在 HEAD 上同挂，与开关无关；`test_redis_client::test_get_redis_without_url_raises` 受本地 `.env` 的 REDIS 键干扰（无 `.env` 的基线树通过）。主流程 e2e（chat_http / 六阶段 parity / 前台切换 parity / turn_meta / world_chat）+ v8 / v9 / v40 = **321 passed / 0 failed** → **零新增失败**。

---

> **文档结束**。正文为审查期（改造前）口径实测；批次 1 的执行结果与**方法论补正**见 附录 D，两个 `v2_` 段开关与世界域四闸（3 子闸 + 主闸 `world_enabled`）的删除记录见 附录 E。所有「读取点」结论均由全仓 grep 实测得出，「是否有人关它」结论由真实 `.env` / `.env.example` 实测得出。
