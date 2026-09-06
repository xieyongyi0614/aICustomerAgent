# LIFE-005 Task Detail — 周期记忆检索与反思检查（Integration）

> 上游：[../tasks.md](../tasks.md) LIFE-005 ｜ [../../../architecture/character-runtime.md](../../../architecture/character-runtime.md) §2.2 ｜ 依赖：LIFE-002, P1 MEM-006（已交付）, P2 REF-003/REF-004（已交付）

## Task 目标

让生活时刻「想得起、会反思」——把 §九/§十三要求的 Memory Retrieval 与 Reflection Check 两步接进 Life Loop 周期（LIFE-002 留出的步骤 4/5 位）：

1. **Memory Retrieval（高显著度快查）**：周期内按显著度门槛快查 top 记忆，结果进入 Decision 输入的**可见面**（trace + proactive 生成上下文），不进 AutonomyPolicy 闸门；
2. **Reflection Check**：复用 REF-003 触发器全链（证据门槛→日额度→日桶幂等入队），Life Loop 只做「按频控调用」这一件事；
3. 全程**只读 + 入队**，不写任何域（tasks.md Non-Scope）；检索 0 LLM，反思 LLM 经 REF-003 既有额度。

缺了这两步，用户不说话时角色失忆且不反思——「想起与当前状态相关的记忆」「证据是否达到反思门槛」是 character-runtime.md §2.2 生活时刻管线的既定环节，闭环（memory→decision、evidence→insight）在生活时刻断裂。

## 背景 / 为什么需要

v1 的 60s tick 决策（`_snapshot_for`，autonomy_engine.py:113-174）组装 PolicySnapshot 时读状态/关系/goal/world/action 六类事实，**唯独没有任何记忆输入**——主动消息的生成上下文只有 goal_description 与空 recent_context（proactive_executor.py:141 → proactive_chain.generate(recent_context="")）。后果：角色主动发起的对话不知道「上周用户说过什么、两人共同经历过什么」——主动性有形式无内容。

反思侧，REF-003 的周期触发（`run_reflection_trigger_tick`）只在天级 schedule（`v2_reflection_schedule_hour=4`）+ 事件路径（reinforce 计数，进程内存桶）两个入口；生活时刻没有反思检查点——证据窗口达标后要等到次日 4 点才被处理（或进程重启后事件桶清零漏掉）。生活时刻的 reflection_check 是证据→洞见闭环在「用户不在场」时段的补位。

同时必须守住成本红线：生活时刻每一环默认纯规则，LLM 只在 Decision 命中且预算允许时发生（character-runtime.md §2.2 成本铁律）——检索必须是无 LLM 的快查，反思必须复用既有门槛与额度，不得新开 LLM 面。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| P1 MEM-006 检索体系 | `memory2/retriever.retrieve`（retriever.py:257，混合打分）+ `memories.salience` 列（db.py:125） | 周期快查**不用** retriever 全链（语义向量/embedding 依赖重）——按 salience 列直接 SQL 快查（新仓储函数，见设计 1）；salience 值域与转正口径复用 P1（evaluator `_promote` 0~1 封顶） |
| P1 MEM-003 转正口径 | salience 语义（explicit_remember=1.0 / 里程碑 0.85~0.90 / world high=0.8） | 门槛默认 0.8 与 P1 高显著度分档对齐（重要事实/里程碑/显式记忆） |
| P2 REF-003 触发器 | `trigger_for_user(user_id, trigger, now, trace)`（triggers.py:52-145，返回 queued|skipped|quota|off；内含证据门槛 evidence.aggregate_evidence_windows + `_quota_used` 日额度 + `has_job(_day_bucket_key)` 幂等） | **原样复用**：reflection_check 步骤调用它，trigger="event"；同日不重复入队由其日桶键（`reflect:{user}:{date}`，triggers.py:279-280）保证 |
| P2 REF-004 执行器 | `run_queued_reflections` handler（reflector.py:66） | 零改动（入队后执行链既有） |
| LIFE-002 步骤位 | 步骤 4 memory_retrieval / 步骤 5 reflection_check（skip 条件已留） | 实装步骤体 + 频控 |
| V7 决策管线 | `proactive_executor.execute(action, llm, trace, now)`（proactive_executor.py:103）→ `proactive_chain.generate(goal_description, intention, recent_context="", ...)`（proactive_chain.py:53） | 执行器签名**扩展**可选 `recent_context` 参数（默认 "" 逐字节回退）透传给 chain——chain 本体零改动（形参已存在） |

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/repositories/memory_repository.py` | 仅有 list_active（created_at 排序）/ search_by_vector；**无 salience 排序查询**（Python 侧打分在 retriever） | 新增 `list_top_salience(user_id, character_id, min_salience, limit)`：`WHERE status='active' AND visibility!='hypothetical' AND salience>=:min ORDER BY salience DESC, created_at DESC LIMIT :n`（既有索引 idx_memories_user_character_status 过滤后小集合排序，暂不加索引——规模触发再补，核对记录 5） |
| `app/application/life_loop.py` 步骤 4/5 | LIFE-002 留位 | 实装：步骤 4 调快查 → 结果进 trace 与 recent_context；步骤 5 频控调 trigger_for_user |
| `app/application/autonomy_engine.py` | `_process_user` / `_snapshot_for` 决策管线 | **零改动**（检索结果不经 PolicySnapshot——红线：AutonomyPolicy 纯函数本体零改动） |
| `app/application/proactive_executor.py` `execute` L103 与 `proactive_chain.generate` 调用点 L141 | recent_context 恒空串 | execute 扩展可选参 `recent_context: str = ""` 透传（编排层 Extend；chain 签名已含该形参，本体零改动） |
| `app/services/reflection/triggers.py` | REF-003 全链 | **零改动**（调用方视角复用） |
| `app/application/life_loop.py` trace | — | 注册 TRACE_STEP_NAMES：`life_loop_memory_retrieval` / `life_loop_reflection_check`（连同 LIFE-003 的 `life_loop_budget`） |
| `app/core/settings.py` | — | 新增 `v2_life_loop_memory_min_salience: float = 0.8`、`v2_life_loop_memory_limit: int = 5`、`v2_life_loop_memory_digest_chars: int = 600`（recent_context 摘要预算）、`v2_life_loop_reflection_check_interval_minutes: int = 240` |
| `tests/v2/test_life005_cycle_retrieval.py` | — | 新增 |

## 设计方案

1. **Memory Retrieval（步骤 4，0 LLM）**：
   - 快查：`list_top_salience(min_salience=v2_life_loop_memory_min_salience, limit=v2_life_loop_memory_limit)`——高显著度记忆是「必须想起的事」（显式嘱托、里程碑、重要事实），无需语义检索的模糊召回；显式记住（salience=1.0）与里程碑（0.85+）天然命中。
   - 快照进 Decision 可见面（两处，均不触碰闸门）：
     a. **trace**：`life_loop_memory_retrieval` 步骤记录条数 + memory_id 列表 + 摘要（「为什么主动提到这件事」可溯源到记忆行，E-LIFE-05 trace 面）；
     b. **proactive 生成上下文**：检索结果组装为有界摘要（title/content 截断，合计 ≤ `v2_life_loop_memory_digest_chars`），存入本 run 的 run-scoped 上下文（life_loop run 上下文对象，随 run 生命周期），在步骤 6 内经扩展后的 `proactive_executor.execute(..., recent_context=digest)` 传入生成链。
   - **不进 AutonomyPolicy**：PolicySnapshot 零改动——检索结果不新增任何闸门条件（命中/不命中不改变「是否行动」的判定），只改变「行动时的谈资」。这是红线（纯函数本体零改动）与 Extend 边界的直接推论；若评审认为记忆应当参与触发判定，属架构变更另行裁决（核对记录 17）。
   - 降级：检索异常 → 步骤 skip(reason=retrieval_error)，digest 置空——decision 照常运行（无记忆上下文降级，tasks.md Error/Failure 口径）。

2. **Reflection Check（步骤 5，频控入队）**：
   - 频控：距上次检查 ≥ `v2_life_loop_reflection_check_interval_minutes`（默认 240，进程内时间戳）才调用——`trigger_for_user` 的证据聚合（窗口聚类）虽是纯规则但非零成本，且其 skipped 落行（reflection_runs status=skipped）需限频防写放大。
   - 调用：`trigger_for_user(user_id, trigger="event", now=..., trace=...)`——全链复用：`v2_reflection_enabled` OFF 返回 off（步骤记账 skipped）→ 证据门槛未过返回 skipped（reflection_runs 留痕，既有语义）→ 额度满返回 quota（步骤记账 skipped，不再入队——验收口径）→ 达标入队返回 queued。
   - 同周期不重复入队：日桶键 `reflect:{user}:{date}` 唯一（triggers.py:279-280）保证每日至多 1 个排队 job（scheduled 与 event 共享桶）——Life Loop 即使每 4h 检查一次，当日已入队则 quota/already_enqueued 返回，幂等成立。
   - 检查时间戳为进程内存态：重启即重置，下次周期重新检查一次（幂等由日桶兜底，无害）。

3. **两步与步骤 6 的衔接（run 上下文流）**：

   ```text
   步骤 4（检索）→ digest → run.context["memory_digest"]
   步骤 5（反思检查）→ outcome → run.context["reflection_check"]（记账）
   步骤 6（decision）: autonomy_engine.tick([user])
     └─ tick 内部 proactive_executor.execute —— recent_context 注入点在 Controller 侧？
   ```

   **裁决**：`autonomy_engine` 本体零改动，Controller 不能向 tick 内部的 execute 传参——注入改走**上下文载体**：`proactive_executor.execute` 扩展的 recent_context 参数由其内部从显式入参获得；Controller 侧不 hack tick。诚实口径：**步骤 4 的 digest 通过模块级传递会被 tick 的多层调用稀释，因此 P5 的注入点收敛为「Life Loop 直接编排 proactive 路径时的参数传递 + autonomous tick 内保持空串」**——具体落地：Controller 在步骤 6 调用 `autonomy_engine.tick` 前将 digest 写入 `life_loop` 模块的 run-scoped contextvar（`life_loop_context.memory_digest`，contextvar 实现，asyncio 任务隔离），`proactive_executor.execute` 内读取该 contextvar（默认 None 即空串回退）作为 recent_context——proactive_executor 是编排层（非引擎本体，不在红线内），contextvar 采集模式与 V7.8 trace 采集先例（contextvar 采集）一致。contextvar 默认 None 保证前台/独立调用零漂移。
   （核对记录 18 登记：contextvar 注入 vs 参数传递的取舍与回退面。）

4. **观测**：两个步骤各落 trace 步骤（条数/ids/outcome/频控状态）；E-LIFE-05 的「主动消息引用相关记忆」人评抽样以 trace 中 memory_id ↔ 消息文本对照为底稿。

## 数据模型 / 状态变化

- **零 DDL、零新表**（tasks.md Data Changes: 无）。
- 只读面：memories（快查）；写入面：仅经 REF-003 既有链（reflection_runs + background_jobs 入队）——本 Task 自身不写任何域。
- contextvar：`life_loop_context`（模块级，asyncio 任务隔离，默认 None）——运行时态，非持久化。
- 新增 settings 四项（见涉及位置表）。

## 核心处理流程

```text
Life Loop 单用户周期（LIFE-002 管线内）

步骤 4 memory_retrieval（0 LLM）:
  list_top_salience(min_salience≥0.8, limit 5)
    → trace（ids+摘要）
    → digest（≤600 字符）→ life_loop_context.memory_digest（contextvar）
    [异常 → skip + digest=None → 决策无记忆上下文降级]

步骤 5 reflection_check（频控 240min）:
  未到频控 → skip(reason=throttled)
  到频控 → trigger_for_user(trigger="event")
    [queued → 已入队（日桶幂等）｜skipped/quota/off → 记账跳过]

步骤 6 decision（LIFE-002）:
  autonomy_engine.tick([user])
    └─ 命中 proactive → proactive_executor.execute
         └─ recent_context = contextvar.digest（默认 None → "" 逐字节回退）
              → proactive_chain.generate（本体零改动，上下文自然进入生成）

Flag OFF: 步骤 4/5 整体 skip（LIFE-002 skip 条件），全链 v1 逐字节
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：本 Task 是 Memory 域在生活时刻的**读**接口消费方（salience 快查）；同时是闭环「Memory → Decision」的落点——被想起的记忆经生成上下文影响主动消息内容，主动消息引发的对话再经 post_process 摄取为新 Candidate（闭环回到记忆，Dev 不自证同理）。检索零写入（reinforce 直写已取消——retriever 记录 reinforce 的写回缓冲语义不适用于本快查，快查不触碰 reinforce，核对记录 19）。
- **Reflection**：本 Task 是 REF-003 触发器的**调用方**（生活时刻检查点），不新增触发条件、不改门槛/额度/幂等；反思产出链（REF-004 执行→Insight→DEV/REL 监听）零改动。
- **Development**：无直接交互（digest 不经 DevPolicy；调制仍经 BehaviorEngine 既有接线）。
- **Relationship**：无直接交互——共同经历/关系模式不在此步注入（proactive 上下文的关系面由 `_snapshot_for` 既有 patterns 参考与 goal_description 承载）；避免上下文段重复注入（R12 写放大防护）。

## 异常与边界情况

- **检索异常/超时**：skip + digest=None，决策照常（无记忆上下文降级；不阻塞周期）。
- **检索结果为空**（无高显著度记忆）：合法空——digest=None，trace 记 0 条；不降级不告警（新用户常态）。
- **反思额度满**：outcome=quota，步骤记账 skipped(reason=quota)，当日不再尝试（日桶已占位）。
- **证据门槛未过**：outcome=skipped（REF-003 留 reflection_runs 行）——频控保证该行最多 6 行/日/用户（240min 频控），写放大可控。
- **contextvar 跨任务污染**：asyncio contextvar 随任务复制——Controller 在每轮周期开始 reset，tick 内部 create_task 的后台步骤不继承（默认 None 回退）；测试覆盖前台路径零漂移（不设 contextvar 时 recent_context 恒空串）。
- **digest 超预算**：组装时截断（per 条 + 总额双截断），杜绝 prompt 膨胀（R2 写放大防护）。
- **Flag ON 但 v2_memory_enabled OFF**：快查表仍是 memories（v1 也写该表）——快查可用但语义上 v2 转正行才带结构化 salience 值域；Enablement 串行链保证 v2_life_loop 在 v2_memory 之后开启，该组合不出现，settings 校验器加启动告警兜底。
- **反思入队后执行面失败**：REF-004 既有重试/超时回收兜底，与本 Task 无关（调用方职责止于入队）。

## 测试要求

- Unit：list_top_salience（排序/门槛/limit/hypothetical 排除）；digest 组装截断；频控判定；contextvar 注入与默认回退。
- Integration：①端到端——构造高显著度记忆（显式 remember salience=1.0）→ 周期运行 → trace 含该记忆 id 且 proactive 生成请求含 digest（stub LLM 断言入参）；②反思链路——构造达标证据窗口 → reflection_check 入队 → 日桶幂等（同日二次检查 quota）→ 额度满不再入队；③降级——检索异常时决策照常、digest 空；④前台零漂移——不设 contextvar 的 chat_pipeline 回归 golden。
- 抽样人评（E-LIFE-05）：主动消息引用相关记忆——trace memory_id 与消息文本对照抽检清单（regression-checklist 执行步骤 2）。
- Regression：Flag OFF 无行为；V7 checklist 全量（决策管线零改动证明）；P1/P2 既有测试全绿（REF-003 零改动证明）。
- 性能：快查走既有索引 <10ms；频控内 0 查询。

## 验收标准

- 给定高显著度记忆存在，当周期运行，那么主动决策输入含该记忆且 trace 可见（memory_id 可溯）。
- 给定反思额度已满，那么不再入队（outcome=quota 且 background_jobs 无新行）。
- 给定证据窗口达标且到频控，当周期运行，那么反思任务按 REF-003 既有链入队（≤1 次/日/用户）。
- 给定检索失败，那么决策无记忆上下文照常运行（降级不阻塞）。
- 给定前台普通对话（无 Life Loop），那么 proactive/recent_context 行为与 v1 逐字节一致（contextvar 默认回退证明）。

## Implementation Constraints

- **红线**：AutonomyPolicy 纯函数本体零改动——检索结果不得成为触发/闸门条件；proactive_chain 本体零改动（形参已存在）；REF-003/REF-004 全链零改动。
- 检索仅读、反思只入队：本 Task 不写 memories/insights/任何业务域表（reflection_runs/background_jobs 写入发生在 REF-003 函数内部，非本 Task 代码）。
- LLM Usage：检索 NONE；反思经 REF-003 既有额度（≤1 次/日/用户）；本 Task 不新增任何 LLM 调用点。
- 快查不走向量检索（embedding 依赖与成本）；不触 reinforce 写回（读路径零写）。
- digest 预算硬顶（600 字符）且挤占申报为零（不进 Context Architect 800 合并预算——它是 proactive 生成上下文，不是对话 Context 段；核对记录 20）。
- 不提前设计 Phase 6：检索不做 goal 相关性排序、不做 Planning 输入组装（AUT-002）；反思不接 goal 证据（P6 范围）。

## 缺口补充设计（评审决策材料，随登记缺口收口补充）

### 补 1：salience 查询索引备案 DDL（核对记录 5）

本 Task 取「既有索引过滤 + 小集合排序」口径的规模触发阈值与备好 DDL（**本期不建**）：

- 触发条件：单用户 active 记忆数 > 2000（P1 candidate pool 上限 500 的 4 倍冗余余量）或快查 P95 > 50ms（loop_memory trace 观测）；
- 备案 DDL：`CREATE INDEX CONCURRENTLY idx_memories_user_salience ON memories (user_id, character_id, status, salience DESC)`（含 character_id 与过滤列全对齐，排序零 filesort；`visibility != 'hypothetical'` 由回表过滤，不进索引键）；
- 迁移方式：独立小迁移（ alembic op.create_index，PG 专用 CONCURRENTLY 在 SQLite 测试环境退化为普通建索引）。

### 补 2：「记忆参与触发判定」的红线解锁决策材料（核对记录 17）

若评审认为高显著度记忆（如未兑现嘱托）应参与「是否主动」判定，所需的**最小架构变更形状**如下（供红线解除裁决用，本期不实施）：

- 变更点 1（Extend，无争议）：`PolicySnapshot` 追加可选字段 `salient_memory_keys: tuple[str, ...] = ()`（对齐 REL-003 relationship_patterns 先例），Controller 组装处注入快查结果；
- 变更点 2（**红线触碰点**）：`autonomy_policy.evaluate` 八步短路中新增一条规则（如「存在 commitment 类显著记忆且超期未兑现 → 覆盖 quiet hours/intimacy 闸门」）——纯函数本体改动，需 tasks.md 红线条款修订（AutonomyPolicy 零改动 → 允许白名单式扩展）；
- 配套：decision trace 附命中记忆 keys（溯源）；评估规则补「触发有依据」对记忆触发源的检查；V7 checklist 需确认新规则在 OFF 路径不生效（Flag 门控在组装处，OFF 时字段恒空 → 规则自然短路，golden 不变可行）；
- 影响估计：代码 ~30 行 + 红线条款修订 + V7 回归重跑；建议作为独立评审项与 P6 AUT 闸门调制一并裁决（P6 本就计划消费 Autonomy 阈值调制，避免两次触碰红线）。
