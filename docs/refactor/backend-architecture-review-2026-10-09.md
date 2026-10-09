# 后端架构审查报告（apps/backend）

> 审查日期：2026-10-09 ｜ 范围：`apps/backend/app/` 全量静态审查（不执行测试）
> 基线：HEAD `dda3f7e2`（分支 `feat/feishu_bot`）
> 方法：分层依赖矩阵扫描 + 单一写面/边界纪律核查 + 规模度量 + 并发/内存态风险定位
> 定位：**增量审查报告**，不是 `docs/current-system-architecture-baseline.md` 的替代；架构演进的唯一权威描述仍以基线文档为准。

---

## 0. 结论摘要

这套后端的分层纪律、单一写面纪律、Run Profile 单管线约束做得**明显高于同类个人项目水准**：`repositories` 零反向依赖、`engines` 纯函数无 IO、`api` 层 async 下放纪律近乎完美（全仓仅 1 处漏网）。真正的问题不在「边界被破坏」，而在**规模的三个临界点**已经到顶：

1. **`services/` 已成为事实上的单体**（233 文件 / 47.7k 行，占全 app 66%），领域间无隔离，`services → chains` / `services → character` 大量穿透。
2. **`application/` 编排层出现 3 个「上帝文件」**（`world_engine.py` 1561 行、`action_engine.py` 1076 行、`chat_pipeline.py` 922 行），且 `chat_pipeline` 同时承担前台 + 后台编排两类职责。
3. **进程内内存态在多实例部署下会失效**（`_user_write_locks` / `active_generations` / `_session_locks` 随用户无界增长，且无法跨进程同步）。

**优先级排序：P0（多实例正确性）→ P1（services/ 领域化拆分）→ P1（编排层拆分）→ P2（进程内状态外置）→ P3（工程卫生）。**

| 维度 | 评级 | 一句话依据 |
|---|---|---|
| 分层依赖方向 | 🟢 优 | 除 1 处例外，`api→application→services→repositories→core` 严格单向 |
| 单一写面纪律 | 🟢 优 | `world_events` / `loop_runs` / 计划面 / 账本面均未见绕过写 |
| 通道边界 | 🟢 优 | `channels/` 仅 import `base` 契约（组合根豁免），符合铁律 |
| API 异步纪律 | 🟡 良 | 仅 `debug/plans.py:332` 1 处同步仓储调用未下放 |
| 模块规模 | 🔴 差 | services 47.7k 行 / 233 文件，5 个 >800 行文件集中在 application |
| 多实例就绪度 | 🔴 差 | 写锁/生成态/会话锁全为进程内内存，跨实例语义错误 |
| 可测试性 | 🟡 良 | 498 测试文件，但 22 个跨版本钉测对任何结构变更是强耦合 |
| 可拓展性 | 🟡 良 | 扩展点（Profile/PostProcess/Capability/Tool）清晰，但新增成本因 services 耦合上升 |

---

## 1. 现状量化

### 1.1 各层规模

| 层 | 文件数 | 行数 | 职责 |
|---|---:|---:|---|
| `services/` | 233 | 47,714 | 领域业务逻辑 |
| `application/` | 41 | 13,102 | 编排 / 引擎 / 生命周期 |
| `repositories/` | 39 | 6,652 | DB 访问（364 个同步函数） |
| `api/` | 34 | 5,680 | HTTP 表现层 |
| `models/` | 29 | 4,473 | Pydantic 领域模型 |
| `core/` | 58 | 4,357 | 基础设施 + 31 个 settings 子模块 |
| `engines/` | 14 | 2,760 | 纯函数引擎（无 IO / 无 LLM） |
| `character/` | 26 | 2,584 | 角色资产（asuna 人设） |
| `channels/` | 12 | 1,972 | 通道适配（飞书） |
| `prompts/` | 20 | 1,409 | Prompt 模板 |
| `chains/` | 14 | 963 | LLM 链 |
| **合计** | **520** | **71,666** | |

**关键比例**：`services` 占 66.6%；`application + services` 占 84.9% → 业务体积高度集中在两层，repositories/api/core 维持薄壳，这是**健康信号**（基础设施层薄 = 抽象稳定），但也意味着**复杂度全部压在业务两层**。

### 1.2 最大文件（前 10）

```
1561  application/world_engine.py
1076  application/action_engine.py
1016  services/tool/ext_api/schema.py
 922  application/chat_pipeline.py
 921  services/reflection/evidence/windows.py
 917  services/reflection/evidence/collectors.py
 894  application/post_process.py
 865  services/planning/observer.py
 811  application/life_loop.py
 793  application/autonomy_engine.py
```

`application/` 5 个文件合计 **5,264 行**，是本届审查最集中的结构问题。

### 1.3 数据模型规模

- ORM 表 **57** 张（`core/db/` 14 个领域子模块），基线迁移 `0001` 折叠原 58 个迁移，现有增量 `0002~0009`。
- 表最多的域：`runtime`(7) / `autonomy`(7) / `world`(6) / `relationship`(5) / `identity`(5)。
- 迁移头钉测单点 `tests/support/schema_pins.py`（`MIGRATION_HEAD="0009"`）。

---

## 2. 做得好的地方（先说清楚，避免误判为「全是问题」）

1. **`repositories/` 零反向依赖**：无任何 service/application import，364 个函数全同步、纯 DB 语义。这是最干净的一层。
2. **`engines/` 纯函数纪律**：仅 `decision.py:386` 有一处延迟 import `services.life.gate.preview_budget`，其余零 IO / 零 LLM，可直接单测。
3. **通道边界 fail-closed 生效**：`channels/feishu/` 只 import `app.application.channel_gateway` + `services.agent_service` + `services.identity`，**没有** import `app.repositories`（这是 allowlist 硬拦），组合根 `main.py` 承担了注入职责。
4. **单一写面纪律未见破坏**：未发现绕过 `world_events` 直写 Character 域、绕过计划面写 goal、绕过 outbox 写 world 的代码。
5. **API 异步纪律实际执行到位**：59 处 `to_thread`，全仓仅 `debug/plans.py:332` 一处 async 路由里裸调同步仓储。
6. **扩展点已收敛为 4 个显式机制**：Run Profile Registry（`profiles.py` 唯一声明）、post_process 步骤注册、Capability Registry、Tool Registry。新增能力的路径是清晰的。
7. **契约冻结有测试兜底**：`contracts.py` 的字段元组 + `test_runtime_contracts.py` 的 `EXPECTED_EVENT_TYPES` fail-closed，`CONTRACT_REVISION` 显式 bump。

---

## 3. 架构问题（按优先级）

### P0 — 多实例部署正确性缺口

**问题**：全部并发互斥与「生成中」状态都是**进程内内存**，多实例（或多 worker）下语义错误。

| 状态 | 位置 | 多实例后果 |
|---|---|---|
| per-user 写锁 `_user_write_locks` | `core/runtime_state.py:14` | 两台实例可同时处理同一用户，账本/关系/状态出现竞态写入 |
| `active_generations` | `core/runtime_state.py:26` | 实例 A 生成中，实例 B 看该用户「空闲」→ 主动消息打断 |
| `_session_locks` / `_session_refs` | `channels/feishu/adapter.py:60-61` | 同一会话两条消息被并发处理，顺序与去重语义失效 |
| 限流窗口 `_windows` | `api/rate_limit.py:17` | 限流阈值 ×N 实例数失效 |
| 飞书事件去重 `_seen_events` | `channels/feishu/events.py:44` | 内存 LRU，重启/多实例丢去重（已知有持久化兜底，但内存层仍是第一道） |
| life_loop 周期节流 `_maintenance_last` 等 | `application/life_loop.py:60-62` | 每实例各跑一份维护步 → 重复执行 |
| 事件总线 `_SUBSCRIBERS` | `application/agent_runtime/events.py:33` | 仅进程内，跨实例事件不传播 |

**为什么是 P0**：`docker-compose.yml` 目前单实例，问题不显现；但飞书通道已实现 `feishu_instance_count` 分片（`api/v1/feishu/webhook.py:196`），说明多实例是**已规划的部署形态**。一旦横向扩，上表每一项都是静默的数据正确性问题（不是崩溃，是「偶发重复/丢失」）。

**更隐蔽的第二层**：`_user_write_locks` 与 `active_generations` 均为**无上限 `dict`**，按 `user_id` 累积、只在测试里 `clear()`。长跑进程内存单调增长 → 长期 OOM 风险（属 P2，但与 P0 同源，建议同批修）。

**建议**

- 写锁：改为 Redis 分布式锁（`SET NX PX` + 续约），或明确降级为「单实例约束」并在启动期断言 `instance_count == 1` 时打印硬警告。
- `active_generations`：迁 Redis（`SET user:gen:1 EX ttl`），TTL 兼做僵尸清理。
- 内存 dict：统一加 LRU/上限 + 空闲回收，或同样外置。
- 建议在 `core/runtime_state.py` 抽出 `RuntimeStateStore` 协议，内存实现 + Redis 实现二选一，避免散落各处。

---

### P1 — `services/` 已成事实单体，领域间无隔离

**问题**：233 文件、47.7k 行、33 个子包（`ledger` 19 / `tool` 18 / `world` 17 / `action` 16 / `memory` 15 …）。子包之间**互相自由 import**，没有「领域间只能经 port/契约通信」的约束。

穿透证据（`services → 跨层/跨域`）：

```
services → chains       10 文件（autonomy/executor, conversation/scene, conversation/state,
                                conversation/summary, evaluation/engine, evaluation/offline,
                                goal/planning, memory/evaluator, reflection/reflector, world/user_situation）
services → character    49 文件
services → models      134 文件
services → core        141 文件
```

`services → chains` 尤其值得注意：`chains/` 是 LLM 链层，本应由 `application/` 编排层调用，现在 `services/` 直接调链（如 `services/conversation/scene.py` 直接 import `scene_update_chain`）→ **「谁负责调 LLM」这条线在 services 内部被模糊了**，与 `agent_runtime/llm_gateway` 「调用权收归唯一裁决面」的设计意图存在张力（Gateway 覆盖的是 `CallSite` 枚举内的调用点，services 里这 10 处是否全部经 Gateway 记账，需逐点核查）。

**为什么是 P1**：这是所有后续问题的**根因**。新增一个领域能力时，作者会自然地在 `services/` 里横向 import 任意其他领域，久而久之契约消失。它也解释了为什么 `application/` 的编排文件会膨胀——编排层被迫了解过多 services 内部细节。

**建议（渐进，不要求一次重写）**

1. **先立规**：在 `AGENTS.md` 补一条「`services/<domain>` 不得直接 import 其他 `services/<other_domain>` 的内部模块，只能经该域的 `port.py`/`contracts.py`」。项目已有 `services/action/port.py`、`services/autonomy/port.py`、`services/world/engine_port.py`、`services/observability/port.py` 四例先例，风格是现成的。
2. **再补守卫**：仿照已有 `tests/unit/test_feishu_boundary.py`（fail-closed allowlist）写「services 域间边界测试」，把规则变成红/绿。
3. **后收敛**：优先处理调用关系最密的域（`tool` ↔ `action` ↔ `world`），因为它们同时是最大子包。
4. **`services → chains` 收口**：明确「链只能由 `application/` 或经 `llm_gateway` 调用」，把 services 里的 10 处改为经编排层注入。

---

### P1 — `application/` 编排层 3 个上帝文件 + 职责混杂

**问题**

| 文件 | 行数 | 混杂职责 |
|---|---:|---|
| `world_engine.py` | 1561 | 世界 tick + 事件解释 + 实体演化 + 一致性校验 |
| `action_engine.py` | 1076 | 行动检测 + 分派 + 能力调用 + 结果回写 |
| `chat_pipeline.py` | 922 | **前台**编排（上下文→四链并行→流式回答→落库）**和「后台」入口**（`schedule_post_process`） |
| `post_process.py` | 894 | 15+ 个后处理步骤（scene/state/goal/summary/memory/ledger/action/tool/world/evaluation…） |
| `life_loop.py` | 811 | 周期调度 + 维护步 + 目标推进 + 计划执行 + 记忆检索 |

`chat_pipeline.py` 的模块 docstring 自己写着「前台关键路径与后台任务编排」，这是**两类生命周期耦合在一个模块**的显式自白。

**为什么是 P1**：`AGENTS.md` 明确定位「`application/` 只做调度与容错，不做状态计算；新增能力以注册新 post-process 步骤 / 新 context 段的方式接入」。当前 `world_engine` / `action_engine` 已明显越过「只做调度」——它们含实质状态计算逻辑，本应下沉 `engines/`（纯函数）或 `services/`。

**建议**

1. `chat_pipeline.py` 拆 `foreground.py`（前台管线）与 `handoff.py`（后台触发/委派），后台步骤本就在 `post_process.py`，只需切断同文件耦合。
2. `world_engine.py` / `action_engine.py`：把纯计算部分（可无 IO 化）下沉 `engines/`，`application` 保留「驱动 + 容错 + 事务边界」。这与既有 `engines/` 的定位完全一致，是**回归设计意图**而非新架构。
3. `post_process.py`：步骤已经函数化（`run_scene_update` / `run_goal_review` …），可考虑改造成**显式注册表**（`PostProcessStep` 列表 + 顺序 + 是否 critical），把「有多少步、什么顺序」变成数据而非代码，直接对齐 `AGENTS.md` 的「注册新步骤」表述。

---

### P2 — 契约与配置的「静默退化」面

1. **settings 动态读取形态**（基线 §7.1 已登记）：存在 `getattr(settings, f"evaluation_{dim}_enabled", True)` 形态，**字段缺失时静默退化为「永远开启」**。新增/删除 settings 字段时若只按字段名 grep，会漏掉这些动态点。
   → 建议：把动态 key 构造改为显式白名单映射（`_DIMENSION_FLAGS: dict[str, str]`），触发 `AttributeError` 而非静默 True。
2. **零启动期 env↔settings 一致性检查**（2026-09-28 删除 `unknown_versioned_env_keys()` 的代价）：部署侧写错的 env 键完全静默。当前 settings 字段已达 **430** 个。
   → 建议：以「一次性运维脚本」形式恢复检查（不放在启动路径，避免启动耦合）：读取 settings 全部字段名，与 `.env` 键做差集告警。
3. **`extra="ignore"`**：Pydantic Settings 对未知 env 静默忽略，与上一条叠加 → 死键完全无声。

### P2 — 兼容壳与迁移期残留

1. **`services/agent_service.py`（40 行）**：编排已迁 `chat_pipeline`，壳仍保留供 api/测试依赖（基线 §9 已登记 P2）。建议：把 api 侧 import 改到 `chat_pipeline`，测试用 `conftest` 别名过渡，一次性删除。
2. **`services/__init__.py` 的 PEP 562 `_LEGACY` 映射（76 行）**：旧顶层模块名 → 新路径的惰性兼容层。这是重构期的合理过渡，但**没有退出条件**就没有终点。建议在文件头加「删除条件：全仓 `from app.services import <旧名>` 归零（当前 N 处）」，并把 N 写进一个守卫测试。
3. **`runtime_foreground_loop_enabled` / `runtime_autonomous_cycle_enabled`**：已转常开但字段与代码级回退位仍在（基线 §9 已登记 P3）。
4. **`ActionExecutor.execute_external` 返回 `external_adapter_reserved` 占位**：`external` ExecutionKind 是保留桩，分派面与实现面语义错位（基线 §9 P2）。

### P2 / P3 — 工程卫生

1. **22 个跨版本钉测的强耦合**：任何加迁移（bump `MIGRATION_HEAD`）或改冻结文件都会打破一批钉测。虽已收敛到 `schema_pins.py` 单点（+ `test_runtime_contracts` / `test_tool0xx` 若干常量），但仍是**结构变更的隐性税**。建议把「钉测失败」的标准处置流程写进 `docs/TESTING.md`（改哪些常量、如何重算 digest），降低误判成本。
2. **冻结文件摘要会静默 stale**：`test_tool008_integration.py::FROZEN_SOURCES` 等摘要曾出现「改动前就是红的」。建议：把摘要校验改为**先打印实际摘要再比对**（诊断友好），或提供 `REFRESH_PINS=1` 重算模式。
3. **基线非绿**：26 failed 是既定基线（判据 = 失败集 diff）。对新同学是认知负担，建议在 `README`/`TESTING.md` 顶部显著标注「known-failing set（附清单）」，并定期收敛。
4. **`models/` 与 `core/db/` 命名不统一**：`Memory`（Pydantic）vs `*Row`（ORM），历史遗留。

---

## 4. 后续如何拓展

### 4.1 分阶段路线图

**阶段 A — 多实例就绪（P0，最高优先，与业务无关）**

```
1. 抽 RuntimeStateStore 协议（core/runtime_state.py）
   ├─ MemoryRuntimeStateStore（现状，单实例）
   └─ RedisRuntimeStateStore（写锁 / active_generations / 节流时间戳）
2. 限流窗口外置（Redis 滑动窗）或明确「限流为单实例近似」
3. 启动期断言：若 instance_count > 1 且 store 为内存实现 → 拒绝启动（fail-closed）
4. 内存 dict 加 LRU 上限 + 空闲回收
```
交付判据：两台实例同时处理同一 `user_id` 的并发写不产生重复/丢失；飞书同会话乱序消息被正确串行化。

**阶段 B — services 领域化（P1，与阶段 A 可并行）**

```
1. 立规：补 AGENTS.md「services 域间只经 port 通信」
2. 补守卫测试（仿 test_feishu_boundary.py）
3. 逐域抽取 port/contracts，优先 tool ↔ action ↔ world 三域
4. services → chains 的 10 处收口到 application 或 llm_gateway
```
交付判据：域间边界测试从「不存在」→「全绿」；新增一个 domain 时的推荐动作有文档可循。

**阶段 C — 编排层瘦身（P1）**

```
1. chat_pipeline → foreground.py + handoff.py
2. world_engine / action_engine 纯计算下沉 engines/
3. post_process 步骤改为显式注册表（顺序/关键性数据化）
```
交付判据：`application/` 无单文件 > 700 行；`world_engine` / `action_engine` 中不含纯计算逻辑。

**阶段 D — 收敛与卫生（P2/P3）**

```
1. 删 agent_service 兼容壳 + PEP 562 _LEGACY 退出条件守卫
2. settings 动态 key 构造改显式白名单；恢复离线 env 一致性检查脚本
3. action_outbox_enabled 架构裁决（基线 §9 挂账）
4. 钉测处置流程文档化 + FROZEN 摘要诊断改良
```

### 4.2 拓展能力的推荐落点（沿用既有扩展点，避免新开管线）

| 想加的能力 | 推荐落点 | 依据 |
|---|---|---|
| 新 Run 类型（如定时摘要 Run） | `agent_runtime/profiles.py` 加 `ProfileSpec` | AGENT-001「Profile 唯一声明处」 |
| 对话后新处理（如情绪归档） | `post_process.py` 新步骤函数 | ADR-5「注册新 post-process 步骤」 |
| 新 LLM 调用点 | `core/settings` 加字段 + `llm_gateway._CAPABILITY_DEFAULTS` 登记 | §2.6「调用权收归 Gateway」 |
| 新外部动作（如订机票） | `services/action/capabilities/` 新 Capability + Registry 注册 | ADR-10「能力是手脚不是逻辑」 |
| 新通道（如微信） | `channels/<impl>/` + `channels/base.py` 契约，组合根注入 | ADR-1「Channel Adapter 独立」 |
| 新记忆类型 | `services/memory2/` + `memory_candidates` 摄取 | §11.2 Memory Evolution |
| 新世界实体/事件 | `world_events` 新类型 + `world_engine` 解释器 | ADR-4「World 独立状态系统」 |
| 新评估维度 | `services/evaluation/rules/` + `evaluation_judge_chain` | §11.3 Evaluation System |

**关键提醒**：`world_events` 是唯一事件 SoT，**任何新领域状态变化都应经事件写入**，不得直写 Character 域。这是本仓库最硬的一条纪律，拓展时必须守住。

### 4.3 基线文档中已规划、尚未落地的方向（供参考，非本次审查结论）

- **六段认知循环**（`agent_runtime/stages/*`）目前是**影子实现**，生产路径仍走 `controller.run_autonomous_cycle` / `chat_pipeline`（`loop.py` D5 明示）。推进六段方案前需先做基线 §9 批次 3 的决策。
- **Episodic / Semantic 双通道记忆**（§11.2）：可复用现有 `memory_candidates` / `embeddings` / `retriever` 底座。
- **评估闭环统一**（§11.3）：把离线评估与在线评估合并为持续回归 + 门槛门控。

---

## 5. 附：审查方法与可复现命令

```bash
# 规模量化
for d in api application chains channels character core engines models prompts repositories services; do
  echo -n "$d: "; find app/$d -name "*.py" -exec cat {} + | wc -l
done

# 分层依赖矩阵（谁 import 谁）
for src in api application services repositories chains engines; do
  for dst in api application services repositories chains engines; do
    n=$(grep -rl "from app\.$dst\|import app\.$dst" app/$src --include=*.py 2>/dev/null | wc -l)
    [ "$n" -gt 0 ] && [ "$src" != "$dst" ] && echo "$src -> $dst : $n"
  done
done

# 反向依赖（应为空）
grep -rn "from app.services\|from app.application" app/repositories --include=*.py
grep -rn "^from app\.\(repositories\|services\|application\|chains\)" app/engines --include=*.py

# API 层越界（应仅剩 base 契约与组合根豁免）
grep -rn "from app.repositories" app/api --include=*.py

# 最大文件
find app -name "*.py" -exec wc -l {} + | sort -rn | head -20
```

**已核查为「无问题」的项**（可直接采信）：repositories 反向依赖 0、engines 越界 1 处（延迟 import）、api 层 langchain 依赖 0、channels 层 repositories 依赖 0、硬编码密钥 0、裸 `except:` 0。
