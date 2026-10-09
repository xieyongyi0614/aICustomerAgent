# 后端架构改进任务列表（Backlog）

> 生成日期：2026-10-09 ｜ 更新：2026-10-09 16:00（批次 1+2 已落地）
> 依据：`docs/refactor/backend-architecture-review-2026-10-09.md`
> 基线 HEAD：`dda3f7e2` → 当前 HEAD：`7cdf7a45`
> 用途：**供决策的候选任务池**，非执行计划。每条含「改动面 / 风险 / 收益 / 判据」，你选定后再展开为 `tasks.md`。

---

## 进度总览（截至 2026-10-09 16:20）

已落地 **7 项**，分三批提交：

| 批次 | commit | 内容 |
|---|---|---|
| 1 | `3b64713d` | T-34（删 `_LEGACY` 死映射）· T-12（修异步越界）· T-21（env 一致性脚本）· T-30（单实例启动守卫） |
| 2 | `7cdf7a45` | T-20（评估维开关显式白名单）· T-22（运行态容量上限 + 限流窗口清扫） |
| 3 | 待提交 | T-33（删 `agent_service` 兼容壳，入口收敛至 `chat_pipeline` + `channel_gateway` 门面） |

**回归结论**：三批改动前后均跑全量 → 失败集无 diff。批次 3 实测 **unit 1591 passed / integration 428 passed + 7 skipped / e2e 182 passed / v24+v30+v50 689 passed**，全部 exit=0。

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
| T-11 | `chat_pipeline` 拆前台/后台 | P1 | M | 中 | ✅ | ⬜ 待做 |
| T-13 | `post_process` 步骤改显式注册表 | P1 | M | 中 | ✅ | ⬜ 待做 |
| T-10 | services 域间边界立规（文档） | P1 | XS | 极低 | ✅ | ⬜ 待做 |
| T-32 | services 域间边界守卫测试 | P1 | M | 低 | ⚠️ 依赖 T-10 | ⬜ 待做 |
| T-31 | 抽 `RuntimeStateStore` 协议 + Redis 实现 | **P0** | L | **高** | ✅ | ⬜ 待做 |
| T-14 | `world_engine` 纯计算下沉 `engines/` | P1 | XL | **高** | ✅ | ⬜ 待做 |
| T-15 | `action_engine` 纯计算下沉 | P1 | L | **高** | ⚠️ 建议 T-14 后 | ⬜ 待做 |
| T-23 | 钉测处置流程文档化 | P3 | S | 极低 | ✅ | ⬜ 待做 |
| T-24 | 冻结摘要诊断改良（先打印后比对） | P3 | S | 低 | ✅ | ⬜ 待做 |
| T-25 | known-failing set 登记入 TESTING.md | P3 | S | 极低 | ✅ | ⬜ 待做 |
| T-26 | `models/` 与 `core/db/` 命名统一 | P3 | M | 低 | ✅ | ⬜ 待做 |
| D-1 | `action_outbox_enabled` 架构裁决 | P2 | S | 极低 | ✅ | ⬜ 待决策 |
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

### ✅ T-10 · services 域间边界立规（文档）

- **改动**：`apps/backend/AGENTS.md` 补一条：`services/<domain>` 不得直接 import 其他 `services/<other_domain>` 内部模块，只能经该域 `port.py` / `contracts.py`。
- **现成先例**：`services/{action,autonomy,observability}/port.py` + `services/world/engine_port.py`。
- **收益**：零成本立规，是 T-32 的验收依据。
- **判据**：文档条目落地。

### ⚠️ T-32 · services 域间边界守卫测试（依赖 T-10）

- **改动**：仿 `tests/unit/test_feishu_boundary.py`（fail-closed allowlist）写扫描式守卫测试，先只覆盖 **3 个最大域**（`tool` / `action` / `world`）以降低初始红灯面。
- **注意事项**：直接全量开启会有大量既有违规 → 建议「先记录基线违规集，再只拦新增」的渐进策略。
- **判据**：守卫测试存在且对新增违规 fail-closed。

### ✅ T-11 · `chat_pipeline` 拆前台/后台

- **现状**：922 行，docstring 自陈「前台关键路径与后台任务编排」。
- **改动**：拆 `application/foreground.py`（上下文→四链并行→流式回答→落库）与后台派发（`schedule_post_process` 委派，实际步骤本就在 `post_process.py`）。
- **风险**：中 —— `chat_pipeline.py` 在 `test_tool010_e2e.py::ZERO_DIFF_HASHES` 冻结面内，拆分会破钉测，需**显式声明 + 同步摘要**。
- **判据**：前台管线无后台步骤代码；冻结摘要已同步。

### ✅ T-13 · `post_process` 步骤改显式注册表

- **现状**：894 行，15+ 步骤已函数化但「步骤清单 / 顺序 / 关键性」藏在代码里。
- **改动**：改为 `PostProcessStep` 列表（函数 + 顺序 + `critical` 标志），把编排变成数据。直接对齐 `AGENTS.md`「注册新 post-process 步骤」的表述。
- **收益**：新增后处理步骤无需改编排代码；顺序与关键性可测。
- **判据**：`run_post_process` 中无硬编码步骤顺序。

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

### ⚠️ D-1 · `action_outbox_enabled` 架构裁决

- **背景**：基线 §9 挂账 —— 关闭它**会破坏** `deferred_world_op → outbox → world_engine` 唯一写面纪律，故不能走普通门控清理，须走架构裁决。当前默认 `False`、8 处读取。
- **动作**：**决策任务**（非编码）—— 决定「固化常开」还是「保留为特殊裁决位并补文档」。
- **判据**：裁决结论写入基线 §9/§10。

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

**路线 丙 · 结构治理（2~3 周）· ⬜ 未开工**
`T-10 → T-32（渐进）→ T-11 → T-13 → T-14 → T-15` —— 解决 `services` 单体化与 `application` 上帝文件。适合你近期要密集新增领域能力。**注意 T-14/T-15 会碰两个冻结面，需预算钉测同步成本。**

> 三条路线可串行，无硬冲突。唯一强依赖：**T-31 之前先做 T-30（✅ 已满足）**；**T-15 之前建议先做 T-14**；**T-32 之前必须先做 T-10**。

---

## 🎯 剩余可选项按「性价比」重排（2026-10-09 16:00）

| 推荐序 | ID | 一句话 | 工作量 | 风险 | 备注 |
|:--:|---|---|:--:|:--:|---|
| 1 | **T-10** | 在 `AGENTS.md` 补一条 services 域间边界铁律 | XS | 极低 | 零成本立规，且是 T-32 的验收依据 |
| 2 | **T-23** | 钉测处置流程写进 `TESTING.md` | S | 极低 | 纯文档，降低后续撞钉测的误判成本 |
| 3 | **T-25** | known-failing set 登记进 `TESTING.md` | S | 极低 | 纯文档，把「判据=失败集 diff」固化下来 |
| 4 | **T-24** | 冻结摘要校验改为先打印后比对 | S | 低 | 治「摘要静默 stale」这个真实踩过的坑 |
| 5 | **D-1** | `action_outbox_enabled` 架构裁决（决策） | S | 极低 | 纯决策，不改码，结论写进基线 |
| 6 | **T-13** | `post_process` 步骤改显式注册表 | M | 中 | 理顺 894 行的编排；对齐 AGENTS.md 表述 |
| 7 | **T-11** | `chat_pipeline` 拆前台/后台 | M | 中 | 922 行上帝文件；会碰 `ZERO_DIFF_HASHES` 冻结面 |
| 8 | **T-32** | services 域间边界守卫测试（渐进式） | M | 低 | 依赖 T-10；必须先记基线违规集再只拦新增 |
| 9 | **T-31** | `RuntimeStateStore` 协议 + Redis（P0） | L | **高** | 多实例正确性；建议单独迭代 |
| 10 | **T-14** | `world_engine` 纯计算下沉 | XL | **高** | 碰 `FROZEN_SOURCES`；改动面最大 |
| 11 | **T-15** | `action_engine` 纯计算下沉 | L | **高** | 建议 T-14 后复用经验 |
| 12 | **T-26** | `models/` 与 `core/db/` 命名统一 | M | 低 | 低收益长尾 |
| — | **D-2** | 六段循环是否推进（决策） | 决策 | — | **前置：必须先做真实模型人工回归** |
