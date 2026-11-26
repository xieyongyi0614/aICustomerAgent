# 后端架构改进任务列表（Backlog）

> 生成日期：2026-10-09 ｜ 更新：2026-10-09 17:50（批次 3+4 已落地）
> 依据：`docs/refactor/backend-architecture-review-2026-10-09.md`
> 基线 HEAD：`dda3f7e2` → 当前 HEAD：`151deef8`
> 用途：**供决策的候选任务池**，非执行计划。每条含「改动面 / 风险 / 收益 / 判据」，你选定后再展开为 `tasks.md`。

---

## 进度总览（截至 2026-10-09 17:50）

已落地 **9 项**（+1 项测试基建优化），分四批提交：

| 批次 | commit | 内容 |
|---|---|---|
| 1 | `3b64713d` | T-34（删 `_LEGACY` 死映射）· T-12（修异步越界）· T-21（env 一致性脚本）· T-30（单实例启动守卫） |
| 2 | `7cdf7a45` | T-20（评估维开关显式白名单）· T-22（运行态容量上限 + 限流窗口清扫） |
| 3 | `778d6c27` | T-33（删 `agent_service` 兼容壳，入口收敛至 `chat_pipeline` + `channel_gateway` 门面） |
| 4 | `66a909c7` | T-10（AGENTS.md 立规 services 域间边界） |
| 4 | `151deef8` | 测试基建：conftest 惰性加载 `app.main`（全量 -15%，零回归） |
| 5 | `7f7fb3c0` | T-24（冻结摘要诊断 `tests/support/frozen_surface.py`）· T-25（TESTING.md §10 判据 + 基线重采）· T-23（TESTING.md §11 钉测处置流程） |

**T-32 已评估·不采用（2026-10-10）**：曾实现并提交域间边界守卫（`e11762f6`），随后经评估**回退删除**。理由：① 净拦截为 0——232 条既有违规全部进基线，守卫不减少任何耦合；② 逃生门过宽——「往基线加一行」远比「建契约面」便宜，强制力接近 0；③ 规则与现实不符——26 个域里只有 4 个有契约面，要求跨域走契约面等于要求重写整个 services；④ 最大耦合（`planning`→`tool`、`tool`↔`action`）是设计而非缺陷，标注为「违规」属标签错误。**测量数据保留**（供将来真正做收敛时参考）：232 条跨域内部依赖 / 58 个域对 / 21.3% 域对密度；7 对**双向耦合**（`action`↔`tool`、`action`↔`memory`、`conversation`↔`goal`、`conversation`↔`relationship`、`development`↔`evaluation`、`evaluation`↔`relationship`、`memory`↔`relationship`）占 69 行 / 30%；最重 `planning`→`tool` 40 条。T-10 的规则条目本身保留在 `AGENTS.md`（作为方向，不再配机器守卫）。

**T-25 关键结论（2026-10-09 重采）**：**当前真实已知失败集为空（0 条）**。两次默认全量失败集几乎不重叠（21 vs 7，交集仅 1 条），交集那条隔离重跑亦通过 → 全部为 `safe-delete` 环境噪声。**旧的「26 failed 基线」清单正式作废**，判据固化为「改动前后失败集 diff，不是计数」。

**回归结论**：各批改动前后均跑全量 → 失败集无 diff。批次 3 实测 **unit 1591 passed / integration 428 passed + 7 skipped / e2e 182 passed / v24+v30+v50 689 passed**，全部 exit=0。批次 4 实测全量 `unit+integration+e2e` **2201 passed + 7 skipped** 连跑 4 次，与基线逐字一致。


**T-20 追加核验（2026-10-09 16:00）**：确认 `evaluation_*_enabled` 10 个字段是**活代码**（`post_process.run_evaluation` → `evaluation/engine.py` → `rules.run_rules` → `_dimension_enabled` → 白名单，每轮必跑；并由 `tests/unit/test_evaluation_rule_engine.py` 实测 setenv 翻转生效）。白名单**保留**——它把原来的 `getattr(..., True)` 静默 fail-open 收敛为 `KeyError` fail-closed，不可删。结论：**保留现状**（用户 2026-10-09 决定）。

**T-33 复盘**：一度判定「跳过」（触 5 处守卫契约），后经用户指示实做。关键设计决策：飞书 adapter **不直连 `chat_pipeline`**（通道边界 allowlist 明禁），改为 `channel_gateway` 新增叶子门面转发，延续 R-7' 原则；`chat_pipeline.py` 在 `ZERO_DIFF_HASHES` 冻结面内 → 摘要已同步（`e119d89b` → `d7be7201`）并加声明注释。详见 `docs/version/v3.0.0/entry-convergence.md` §0。

---

## 选型速览

| ID | 任务 | 优先级 | 工作量 | 风险 | 可独立 | 状态 |
|---|---|---|:--:|:--:|:--:|:--:|
| T-34 | 删除 `services/__init__.py` 的 `_LEGACY` 死映射 | P3 | S | 极低 | ✅ | ✅ 已完成 |
| T-12 | 修 active 路由中唯一的同步仓储调用 | P2 | XS | 极低 | ✅ | ✅ 已完成 |
| T-21 | 离线 env↔settings 一致性检查脚本 | P2 | S | 极低 | ✅ | ✅ 已完成 |
| T-30 | 单实例约束显式化（startup fail-closed） | P1 | S | 低 | ✅ | ✅ 已完成 |
| T-20 | settings 动态 key 构造改显式白名单 | P2 | S | 低 | ✅ | ✅ 已完成 |
| T-22 | `_user_write_locks` / `active_generations` 加容量上限 | P2 | S | 低 | ✅ | ✅ 已完成 |
| T-33 | 删 `agent_service` 兼容壳（31 文件引用点） | P2 | M | 低 | ✅ | ✅ 已完成 |
| T-11 | `chat_pipeline` 拆前台/后台 | P1 | M | 中 | ✅ | ❌ 已评估·不采用 |
| T-13 | `post_process` 步骤改显式注册表 | P1 | M | 中 | ✅ | ❌ 已评估·不采用 |
| T-10 | services 域间边界立规（文档） | P1 | XS | 极低 | ✅ | ✅ 已完成 |
| T-32 | services 域间边界守卫测试 | P1 | M | 低 | ✅ T-10 已满足 | ❌ 已评估·不采用 |
| T-31 | 抽 `RuntimeStateStore` 协议 + Redis 实现 | **P0** | L | **高** | ✅ | ⬜ 待做 |
| T-14 | `world_engine` 纯计算下沉 `engines/` | P1 | XL | **高** | ✅ | ⬜ 待做 |
| T-15 | `action_engine` 纯计算下沉 | P1 | L | **高** | ⚠️ 建议 T-14 后 | ⬜ 待做 |
| T-23 | 钉测处置流程文档化 | P3 | S | 极低 | ✅ | ✅ 已完成 |
| T-24 | 冻结摘要诊断改良（先打印后比对） | P3 | S | 低 | ✅ | ✅ 已完成 |
| T-25 | known-failing set 登记入 TESTING.md | P3 | S | 极低 | ✅ | ✅ 已完成 |
| T-26 | `models/` 与 `core/db/` 命名统一 | P3 | M | 低 | ✅ | ⬜ 待做 |
| D-1 | `action_outbox_enabled` 收口 | P2 | S | 极低 | ✅ | 🔧 部分完成 |
| D-2 | 六段循环是否推进（需真实模型回归） | P2 | 决策 | — | ✅ | ⬜ 待决策 |

**工作量口径**：XS ≤2h ｜ S ≤1d ｜ M 2~3d ｜ L 4~6d ｜ XL ≥1w

---

## 🚀 建议先做（最高性价比）· ✅ 全部已完成

### ✅ 快速清理三连：T-34 → T-12 → T-21（已于 `3b64713d` 落地，零风险）

**T-34 · 删除 `services/__init__.py` 的 `_LEGACY` 死映射**

- **实测证据**：53 个旧名映射，全仓 `app/` + `tests/` 中**零引用**（已用脚本逐名扫描确认）。
- **改动**：`app/services/__init__.py` 由 76 行的 PEP 562 惰性映射缩为空的包声明；同步检查 `app/agents/` 无同类残留。
- **收益**：消除「双重命名空间」认知负担；避免新同学误用旧名。
- **判据**：`grep -rn "from app.services import \(agent_evaluation\|conversation_service\|...\)"` 为空；全套测试失败集无 diff。

**T-12 · 修唯一的异步越界**

- **位置**：`app/api/v1/debug/plans.py:332`，`get_plan_context`（async 路由）内裸调 `goal_repository.get_goal(goal_id)`。
- **改动**：包 `await asyncio.to_thread(goal_repository.get_goal, goal_id)`。
- **收益**：消除调试面在事件循环上的同步阻塞（当前是唯一漏网点，顺手清零）。
- **判据**：该文件 async 体内不再有裸同步仓储调用。

**T-21 · 恢复离线 env↔settings 一致性检查**

- **背景**：`unknown_versioned_env_keys()` 已于 2026-09-28 删除（连带启动告警），叠加 `extra="ignore"` → 部署侧死键**完全静默**；settings 字段已达 430 个。
- **改动**：新增 `scripts/check_env_consistency.py`（**不进启动路径**），读 settings 全部字段名，与 `.env` / `.env.example` 键做双向差集并输出报告。
- **收益**：把「启动期检查」降级为「按需离线检查」，既恢复能力又不重新引入启动耦合。
- **判据**：脚本对当前 `.env` 输出「无死键 / 无缺失键」，或在文档中登记既存差异。

---

## 🥇 P0 — 多实例就绪

### ⚠️ T-31 · 抽 `RuntimeStateStore` 协议 + Redis 实现

| 项 | 内容 |
|---|---|
| **问题** | 7 处进程内内存态在多实例下语义错误（详见下表） |
| **改动面** | `core/runtime_state.py`（新增协议）、`core/redis_client.py`、`api/rate_limit.py`、`channels/feishu/{adapter,events}.py`、`application/life_loop.py`、`application/agent_runtime/events.py` |
| **风险** | **高** —— 触及聊天关键路径与飞书入站，且涉及约 22 个跨版本钉测 |
| **收益** | 多实例正确性；解除横向扩容阻塞 |

受影响状态清单：

| 状态 | 位置 | 多实例后果 |
|---|---|---|
| `_user_write_locks` | `core/runtime_state.py:14` | 并发写同一用户 → 账本/关系竞态 |
| `active_generations` | `core/runtime_state.py:26` | 实例 B 判「空闲」→ 主动消息打断 |
| `_session_locks` / `_session_refs` | `channels/feishu/adapter.py:60-61` | 同会话并发处理，顺序/去重失效 |
| 限流 `_windows` | `api/rate_limit.py:17` | 阈值 ×N 实例数失效 |
| `_seen_events` | `channels/feishu/events.py:44` | 内存 LRU，跨实例丢去重 |
| `_maintenance_last` / `_reflection_check_last` / `_supply_last` | `application/life_loop.py:60-62` | 每实例重复跑维护步 |
| `_SUBSCRIBERS` | `application/agent_runtime/events.py:33` | 事件不跨实例传播 |

**实施路径（建议拆 4 个子任务，逐个可独立验收）**

1. **T-31a** 只抽协议 + 内存实现（**零行为变化**，纯重构）——先把 `get_user_write_lock` 等调用点改为经协议，测试应全绿。
2. **T-31b** 写锁 + `active_generations` 加 Redis 实现（`SET NX PX` + 续约；生成态用带 TTL 的 `SET`）。
3. **T-31c** 限流窗口外置，或**明确裁决**「限流为单实例近似」并写进基线。
4. **T-31d** 飞书去重 / 会话锁对齐分片语义（此域另有 `docs/integrations/feishu/architecture.md` 阶段 2 硬前置，需先读该文档）。

**判据**：两台实例同时处理同一 `user_id` 并发写不产生重复/丢失；飞书同会话乱序消息被正确串行化。

**前置建议**：先做 T-30（单实例约束显式化），把「当前只支持单实例」这个事实固化成断言，再做 T-31 才有安全的过渡带。

### ✅ T-30 · 单实例约束显式化

- **改动**：`main.py` lifespan 中，若 `feishu_instance_count > 1` 且 runtime state store 为内存实现 → 启动**拒绝**（fail-closed）并打印明确指引。
- **收益**：把「静默错误」变成「启动即失败」，是 T-31 的安全前置；也是 P0 的最小可用缓解。
- **判据**：设 `FEISHU_INSTANCE_COUNT=2` 启动即报错退出。

---

## 🥈 P1 — 结构与纪律

### ✅ T-10 · services 域间边界立规（文档）—— **已完成（2026-10-09 批次 4 · `66a909c7`）**

- **改动**：`apps/backend/AGENTS.md` 补一条：`services/<domain>` 不得直接 import 其他 `services/<other_domain>` 内部模块，只能经该域 `port.py` / `contracts.py`。
- **现成先例**：`services/{action,autonomy,observability}/port.py` + `services/world/engine_port.py`。
- **收益**：零成本立规（作为方向指引；**不配机器守卫**，见 T-32 评估结论）。
- **判据**：文档条目落地。

### ❌ T-32 · services 域间边界守卫测试（已评估·不采用）

- **结论**：曾实现并提交（`e11762f6`），2026-10-10 经评估后**回退删除**（文件与文档引用一并清理）。
- **不采用理由**：
  1. **净拦截为 0** —— 232 条既有违规全部进基线，守卫不减少任何耦合；「守卫上线」≠「耦合改善」。
  2. **逃生门过宽** —— 「往基线加一行」远比「建契约面」便宜，实际会拦一次、静默一次，强制力≈0。
  3. **规则与现实不符** —— 26 个域里只有 4 个有契约面，要求跨域走契约面 = 要求重写整个 services。
  4. **最大耦合是设计而非缺陷** —— `planning`→`tool` 40 条（planner 用工具注册表）、`tool`↔`action` 35 条（工具执行用 action registry）是系统工作方式，标为「违规」属标签错误。
- **保留的测量数据**（将来若真做收敛可复用，无需重跑扫描）：
  - 总量 **232 条**跨域内部依赖 / **58 个域对** / 21.3% 域对密度。
  - **7 对双向耦合**占 69 行 / 30%：`action`↔`tool`、`action`↔`memory`、`conversation`↔`goal`、`conversation`↔`relationship`、`development`↔`evaluation`、`evaluation`↔`relationship`、`memory`↔`relationship`。
  - 最重域对：`planning`→`tool` 40、`tool`→`action` 19、`action`→`tool` 16。
  - 若将来只做一件事，**应优先解双向耦合**（循环依赖是唯一无歧义的缺陷：拆不开、没法独立测、初始化顺序隐式）。
- **T-10 规则本身保留**在 `AGENTS.md`（作为方向指引，不再配机器守卫）。

### ❌ T-11 · `chat_pipeline` 拆前台/后台 —— **已评估·不采用（2026-10-10）**

- **现状（2026-10-10 校正）**：950 行。**「后台」那一半早已不在本文件**——后台步骤在 `post_process.py::STEP_HANDLERS`，本文件只在 `record_handoff` 段调 `schedule_post_process`（`chat_pipeline.py:821`）触发，仅此一处。**前台也已半结构化**：已有 `_foreground_registry`（第 343 行）+ Profile 驱动段序（`agent_runtime/profiles.py::ProfileSpec.stages/critical`），9 个 runner 已注册（第 869-881 行）。原文 docstring「与后台任务编排」**名不副实**。
- **不采用理由**：任务**前提已被现状满足**——「前台/后台」这条分界线本来就在文件边界上（后台在 `post_process.py`），无需拆。曾实做（把前台管线整体搬到 `application/foreground.py`）并全量验证通过，但**净收益为负**：0 功能变化，仅 `+1 文件 / +1 层间接`，且 `chat_pipeline.py` 退化为**纯 re-export 空壳**（无存在理由的转发层，本身是坏味道）→ 遂**回退**（`chat_pipeline.py` 保持原样，`foreground.py` 已删除）。
- **真正的痛点（未解决）**：`chat_pipeline.py` 950 行是**上帝文件**，值得拆的是它**内部**（helpers / 段实现 / 驱动）；但 9 个段 runner 是**闭包**、捕获 25+ `nonlocal` 变量，不 class 化就拆不动。若将来要做须单独立项，并预算 `ZERO_DIFF_HASHES` 冻结面同步成本。

### ❌ T-13 · `post_process` 步骤改显式注册表 —— **已评估·不采用（2026-10-10）**

- **现状（2026-10-10 校正）**：894 行。**「显式注册表」已是现状**——`STEP_HANDLERS` 元组已存在（`post_process.py:830`），`run_post_process` 即 `for handler in STEP_HANDLERS`（第 853 行）；模块 docstring 第 1 行自称「步骤注册表 + 调度」、第 4 行「新增能力只需实现 `run_*` 并加入 `STEP_HANDLERS`」；`AGENTS.md:32` 亦把「post_process 步骤注册」列为既有模式。原文「步骤清单 / 顺序 / 关键性藏在代码里」**前两项不成立**。
- **不采用理由**：① 清单与顺序**早已是显式数据**，「新增步骤无需改编排代码」也已成立 → 原任务主体已完成；② 唯一真正缺的 `critical` 标志**本来就不该有**——docstring 第 3 行明确「每个步骤独立容错（失败仅 trace/log，不影响其余步骤）」，即**所有步骤设计上都是非关键的**，加 `critical` 等于为「全 false」的概念建模。属**为不需要的抽象买单**（同 T-11 模式）。
- **残余真问题（不是 T-13，另议）**：`run_post_process` 循环**无结构化逐步骤兜底**（`for handler: await handler(ctx)`，无 try/except），「独立容错」靠**约定**而非结构强制。实测 13 个步骤均自觉 try 住（`run_action_planning` 的 try 外 preamble 亦安全：`_run_confirmation_round` 内部有 try、`_defer_to_ledger_pending` 纯逻辑）→ 属**防御性加固，非修 bug**；若要做是 XS 级 ~5 行小改，须同步 `post_process.py` 冻结摘要。

### ⚠️ T-14 · `world_engine` 纯计算下沉 `engines/`

- **现状**：1561 行，混「世界 tick 驱动」+「事件解释」+「实体演化」+「一致性校验」。
- **改动**：把可无 IO 化的计算部分下沉 `engines/`（与既有 `engines/` 定位一致 = **回归设计意图**），`application` 只留驱动 + 容错 + 事务边界。
- **风险**：**高** —— `world_engine.py` 同时在 `test_tool007_integration.py::FROZEN_SOURCES` 冻结面内，且是世界域唯一写面落点；改动面大、回归面广。
- **判据**：`application/world_engine.py` 行数显著下降；纯函数部分可单测（无 mock DB）。

### ⚠️ T-15 · `action_engine` 纯计算下沉

- **现状**：1076 行，混「行动检测 / 分派 / 能力调用 / 结果回写」。
- **注意**：与 T-14 同构，**建议 T-14 完成并验证后再做**，复用同批经验与冻结面处理流程。
- **判据**：同 T-14。

---

## 🥉 P2 — 静默退化面与残留

### ✅ T-20 · settings 动态 key 构造改显式白名单

- **问题**：`getattr(settings, f"evaluation_{dim}_enabled", True)` 形态在字段缺失时**静默退化为「永远开启」**。
- **改动**：改为 `_DIMENSION_FLAGS: dict[str, str]` 显式映射，触发 `AttributeError` 而非静默 True。
- **判据**：全仓无 `getattr(settings, f"..."` 形态。

### ✅ T-22 · 内存 dict 加容量上限

- **问题**：`_user_write_locks` / `active_generations` 按 `user_id` 无界累积，仅测试里 `clear()` → 长跑 OOM。
- **改动**：统一 LRU / 上限 + 空闲回收（可在 T-30/T-31 同批做）。
- **判据**：dict 有显式上限常量，超限有回收路径。

### ✅ T-33 · 删 `agent_service` 兼容壳 —— **已完成（2026-10-09 批次 3）**

> 落地方式：壳逻辑（trace 兜底 + observability context set/reset）迁入 `chat_pipeline.stream_chat`；Web 直连 `chat_pipeline`，飞书经新增的 `channel_gateway.stream_chat` 叶子门面转发（**不直连 `chat_pipeline`**，否则破通道边界 allowlist）。5 处守卫契约同步更新，`entry-convergence.md` §0 显式登记。
>
> 原判「跳过」理由（供参考）：触 5 处守卫测试契约（`test_feishu_boundary.py:20` allowlist、`test_runtime_inbound_gateway.py:22` / `test_runtime_outbound_gateway.py:26` FORBIDDEN_IMPORTS、`test_runtime_foreground_cutover.py:38` CALL_PATTERN + `assert found`、`tests/unit/test_chat_pipeline_split.py`），非「简单任务」。

- **现状**：40 行壳，**31 个文件**引用（`api/v1/chat.py`、`channels/feishu/adapter.py`、`tests/conftest.py`、6 个 e2e 测试）。
- **改动**：调用点改为 `chat_pipeline`；27 个测试文件统一改别名/打桩点。
- **冻结面**：`chat_pipeline.py` 在 `tests/v24/test_tool010_e2e.py::ZERO_DIFF_HASHES` 内 → 摘要同步 `e119d89b` → `d7be7201` + 声明注释。
- **判据**：`app/services/agent_service.py` 不存在（新增守门测试）；全量测试失败集无 diff。**✅ 达成**。

### 🔧 D-1 · `action_outbox_enabled` 收口 —— **消费器断链已修（2026-10-10）；action 侧投递待决策**

- **性质（2026-10-10 校正）**：**不是策略位，是迁移位**——`False`=action 结果**同步直写**世界；`True`=写 outbox 同事务、由消费器**幂等落库**（幂等键 + 崩溃重放 + 退避 + 死信）。两条路径都完整实现、都有测试（`tests/v26/test_v26_outbox_world_write.py` 两用例分别覆盖）。基线 §9 原把它与 `foreground_gateway_enforced` 并列称「不是未收敛的门控」，属**分类错误**；其理由「关闭会破坏唯一写面纪律」是**循环论证**。
- 🚨 **已确认的断链**：`outbox_events` 有第二个**无条件**写入方 `services/world/event_bridge.py`（角色→世界事件 `goal_completed` / `interest_emerged`，由 `main.py` 注册、goal/planning 域调用，**不检查开关**），但**唯一消费者** `outbox_consumer.consume_pending` 只在被 `action_outbox_enabled` 门控的 life_loop 维护步里调用 → **默认配置下这些行永久滞留、世界事件不生成**。**实测**：`flag=off` → 维护步跑完 `pending 1→1`、`goal_events 0`；`flag=on` → `pending 1→0`、`goal_events 1`。
- ✅ **第 1 步（已做，2026-10-10）**：**解绑消费器**——`_run_maintenance` / `_maintenance_pending` 去掉 `action_outbox_enabled` 门控，`outbox_consume` 常开。消费器是**共享**机制，不该被 action 的策略位门控。复验：默认配置下 `pending 1→0`、`goal_events 1`（断链修复）。基线 §9 与维护步描述已同步。
- ⬜ **第 2 步（待决策）**：action 侧投递固化哪条 —— ① **固化 outbox**（对齐基线 §10 决策 9，保留幂等/重放/死信；代价 = 世界写变最终一致、工具结果**丢失同步 `world_event_id`**，见 `services/tool/normalizer.py:181`）；② **固化直写**（保留同步 `world_event_id`；须**同时**改 `event_bridge` 不再走 outbox）。**前置**：确认「工具结果无 world 效果」对模型是否可接受。
- **判据**：第 2 步结论写入基线 §9/§10。

---

## 📌 P3 — 工程卫生

| ID | 任务 | 说明 |
|---|---|---|
| T-23 | 钉测处置流程文档化 | 把「钉测失败 → 改哪些常量 → 如何重算 digest」写进 `docs/TESTING.md`，降低误判成本 |
| T-24 | 冻结摘要诊断改良 | `FROZEN_SOURCES` 校验改为**先打印实际摘要再比对**（当前摘要会静默 stale，实测出现过「改动前就是红的」） |
| T-25 | known-failing set 登记 | 26 个既存失败在 `TESTING.md` 顶部显著标注 + 附清单；判据始终是**失败集 diff 而非计数** |
| T-26 | `models/` 与 `core/db/` 命名统一 | `Memory`(Pydantic) vs `*Row`(ORM) 历史遗留，低收益长尾 |
| D-2 | 六段循环是否推进 | 基线 §9 批次 3 前置：**必须先做真实模型人工回归**（V4/V7/V7.5/V7.8/V8/V2.0.0/V2.1.0~V2.6.1），未回归前不得开工 |

---

## 🧭 三条可选的整体路线

> **进度（2026-10-09 16:00）**：路线甲的 4 项（T-34/T-12/T-21/T-30）**已全部落地**并推送；T-20、T-22 亦随手完成。乙 / 丙 尚未开工。

**路线 甲 · 先止血（1~2 天）· ✅ 已完成**
`T-34 → T-12 → T-21 → T-30` —— 全是 XS/S 低风险项，清掉死代码 + 把「只支持单实例」这个隐患变成显式断言。适合你想先看到干净快赢。

**路线 乙 · 直接啃 P0（1~2 周）· ⬜ 未开工**
`T-30 ✅ → T-31a/b/c/d` —— 解决真正的多实例正确性。适合你近期有多实例 / 横向扩容计划。**风险集中，建议单独一个迭代，不夹带其他改动。**

**路线 丙 · 结构治理（2~3 周）· ⬜ 未开工（已缩水：T-11 / T-13 判不采用）**
`T-10 → T-14 → T-15` —— 解决 `services` 单体化与 `application` 上帝文件。适合你近期要密集新增领域能力。**注意 T-14/T-15 会碰两个冻结面，需预算钉测同步成本。**（原含 T-11 / T-13，均已于 2026-10-10 评估为不采用。）

> 三条路线可串行，无硬冲突。唯一强依赖：**T-31 之前先做 T-30（✅ 已满足）**；**T-15 之前建议先做 T-14**。

---

## 🎯 剩余可选项按「性价比」重排（2026-10-10）

> T-32（域间边界守卫）已于 2026-10-10 **评估为不采用并回退**（见上文结论）。T-10 的规则条目保留为方向指引，但不配机器守卫——services 耦合的收敛改由 T-13/T-14 等实际重构承担，而非靠测试拦截。

| 推荐序 | ID | 一句话 | 工作量 | 风险 | 备注 |
|:--:|---|---|:--:|:--:|---|
| 1 | **D-1** | `action_outbox_enabled` 收口 | S | 极低 | 消费器断链**已修**（解绑门控）；残余 = action 侧投递二选一（写进基线 §9/§10） |
| 2 | **T-31** | `RuntimeStateStore` 协议 + Redis（P0） | L | **高** | 多实例正确性；体检建议只做 T-31a、Redis 押后 |
| 3 | **T-14** | `world_engine` 纯计算下沉 | XL | **高** | 碰 `FROZEN_SOURCES`；改动面最大 |
| 4 | **T-15** | `action_engine` 纯计算下沉 | L | **高** | 建议 T-14 后复用经验 |
| 5 | **T-26** | `models/` 与 `core/db/` 命名统一 | M | 低 | 低收益长尾（体检建议不采用） |
| — | **D-2** | 六段循环是否推进（决策） | 决策 | — | **前置：必须先做真实模型人工回归** |

> **T-11 / T-13 已于 2026-10-10 评估为不采用**——两者的前提均已被现状满足：T-11 的「前台/后台」分界线本就在文件边界上；T-13 的「显式注册表」早已是 `STEP_HANDLERS` 现状。实做 T-11 后确认净收益为负，已回退。

> 快赢档（T-23/T-24/T-25）已于批次 5 清空；**T-32 / T-11 / T-13 已评估为不采用**。
> 建议下一步：**D-1（纯决策、定方向）**——T-13 已判不采用，D-1 是当前唯一零风险可推进项。

---

## 🔍 过度设计体检（2026-10-10）

> 触发：复查本列表「是否存在过度设计」。方法：**逐条对照代码实现**，不只看描述。
> 结论：列表整体纪律良好（判据 / 风险 / 改动面齐全，且已有 T-32 自我否决先例），但**两条任务的「现状描述」已与代码脱节**，导致难度与收益被高估；**一条属真正的过度设计**。

### 🔴 T-31 · 唯一真正的过度设计候选

- **问题**：系统当前**显式单实例**（`core/runtime_state.py::assert_single_instance_runtime()` 在 `FEISHU_INSTANCE_COUNT>1` 时 fail-closed 拒绝启动，T-30 已落地）。为 7 处进程内态建「协议 + Redis 实现」，等于为**尚未承诺的横向扩容**预付复杂度。
- **7 态可分两类**：
  - **真需跨实例**：`_user_write_locks`、飞书 `_session_locks` / `_seen_events`。
  - **可裁决为「单实例近似」**：`active_generations`、限流 `_windows`、Life Loop 的 3 个 `_*_last`、`_SUBSCRIBERS`。任务自己也留了这条退路（T-31c）。
- **建议**：**只做 T-31a（抽协议 + 内存实现，零行为变化）**，把 Redis 实现押后到真有扩容计划时。既保住「接口就位」的低成本收益，又不预付 Redis 复杂度与 ~22 个钉测的同步成本。
- **复用面**：`core/redis_client.py` 已存在（现用于身份验证码），若真做 Redis 实现无需从零搭客户端。

### 🔴 两条「前提已被现状满足」的伪任务 → 均判不采用

- **T-11（`chat_pipeline` 拆前台/后台）**：后台步骤早已独立在 `post_process.py`，「前台/后台」分界线本就在文件边界上 → 任务**前提已被现状满足**。曾实做（前台管线整体迁 `application/foreground.py`）并全量验证通过，但确认净收益为负（`+1 文件 / +1 层间接`、0 功能变化、`chat_pipeline.py` 沦为纯 re-export 空壳）→ **已回退并判「不采用」**。
- **T-13（`post_process` 步骤改显式注册表）**：`STEP_HANDLERS` 元组**早已是显式注册表**（`post_process.py:830`），清单 / 顺序早已是数据；docstring 与 `AGENTS.md` 亦以此为准 → 原任务主体**已完成**。唯一残余的 `critical` 标志**本不该有**（设计上所有步骤非关键）→ **判「不采用」**。
- 两条的条目标题原均误标 ✅（与「选型速览」的「⬜ 待做」矛盾），已改为 ❌ 并注明理由。
- **方法论**：判一个重构任务是否值得做，**先看它的「前提」是否已被现状满足**——前提已满足即为伪任务，描述再合理也不该做（T-32 / T-11 / T-13 同一模式）。

### 🟡 T-26 · 建议同 T-32 处理（不采用）

- 任务自称「低收益长尾」。改名 `models/` ↔ `core/db/` 会大面积碰测试夹具，收益≈0 → 与 T-32 一样**评估为不采用**，避免长期挂在池子里反复被评估。

### 🟢 非过度设计，但需知成本

- **T-14 / T-15**：`app/engines/` 已存在且是既有设计意图（`autonomy` / `decision` / `relationship_*` 等），下沉属**对齐模式**，不是过度抽象；但 XL / 高风险、碰 `FROZEN_SOURCES` 冻结面 → 是「昂贵重构」，不是「过度设计」。

### 📌 结论

本列表的真问题不是「想太多」，而是**任务与代码脱节**（`STEP_HANDLERS` / `_foreground_registry` / `assert_single_instance_runtime` 均已落地，描述仍停在改造前）。**T-11 / T-13 已据此判定「不采用」**（T-11 实做后验证净收益为负并回退）；剩余 **T-31** 建议同样先做「现状核对」再定优先级，否则会把已完成的活重做一遍。
