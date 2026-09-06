# LIFE-001 Task Detail — 持久化 Trigger Registry（Foundation）

> 上游：[../tasks.md](../tasks.md) LIFE-001 ｜ [../../../architecture/overview.md](../../../architecture/overview.md) §4 ｜ [../../../architecture/risk.md](../../../architecture/risk.md) R14 ｜ 依赖：P1 MEM-001/009 background_jobs（已交付）

## Task 目标

用 `trigger_registry` 表替代 v1 内存 dict Trigger Registry，消灭「重启即丢 followup/action_due」的持久化缺口（v1 审计问题 6 实证）。具体交付四件事：

1. `trigger_registry` 表（迁移 0028）：due_at / priority / cooldown_until / attempt_count / payload 全列持久化，trigger_key 唯一防重复登记；
2. TriggerEvaluator 读写迁移：三类触发信号（conversation_inactivity / scheduled_followup / action_due）的登记与到期消费改为表通道（判定纯函数不动）；
3. 状态机 pending→due→fired→done|cancelled 落地，attempt_count + cooldown_until 防无限重试；
4. 迁移期双写（内存 dict + 表）一个版本后切表为准，DB 失败回退内存路径。

这是 Phase 5 的 M1 基座：LIFE-002 Controller 的 due 扫描、LIFE-003 的 Idle 判定（「无 due trigger」）、LIFE-006 的触发溯源（「为什么主动」第一环）全部以本表为数据源。表不落地，Controller 的「重启无状态丢失」不变量（architecture/character-runtime.md §4 不变量 5）无从谈起。

## 背景 / 为什么需要

v1 触发信号分三类，其中两类完全无持久化（`app/services/trigger_evaluator.py`）：

- **scheduled_followup**：模块级 `_followup_registry: dict[str, dict]` + `threading.Lock`（L26-27），登记点 `app/services/memory_service.py:102 _register_followups`（记忆内容命中「面试/考试/会议/答辩/体检」关键词 → 当天 18:00 提醒）。重启即丢——角色「答应明天问你面试结果」，进程一重启这件事凭空消失。文件头注释明确接受该丢失（L3「低频、重启丢失可接受」），V7.5 时代这是合理裁剪，v2 的「角色持续在场」不再成立。
- **action_due**：不注册，每 tick 现场扫 world_events（`poll_due_actions` L73-110），已汇报位置存 world 事件 payload.reported_by_autonomy（`mark_action_reported` L113-134）。扫描本身可恢复，但「这轮扫到了但静音期没发」的状态无记录，靠 payload 位间接兜底，且限 50 条窗口。
- **conversation_inactivity**：纯函数即时判定（`evaluate_inactivity` L137-177），dedupe_key=`inactivity:{user}:{last_user_message_id}`，引擎侧 `seen_keys` 恒为空 set（autonomy_engine 从不传入），实际幂等全靠 proactive_repository 的 dedupe_key 深度 1 队列——跨重启幂等是「碰巧成立」而非「结构保证」。

更深的结构问题：v1 无统一的触发状态生命周期。信号是「扫到即用、用完即弃」的一次性值，无法回答「这个 followup 现在什么状态、重试过几次、为什么没触发」。v2 裁决（overview.md §4）：Trigger Registry 持久化为 trigger_registry 表（P5），这是全部 P5 观测与预算控制的锚点。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| P1 MEM-009 background_jobs 表协议 | `BackgroundJobRow`（app/core/db.py:932-953，status/attempts/idempotency_key unique/指数退避）+ `background_job_repository`（enqueue/has_job） | **模式复用，非运行时依赖**：trigger_registry 的状态机列（status/attempts/idempotency）与退避参数对齐该协议风格；触发消费不走 background_jobs（trigger 由 Life Loop tick 扫描，见 LIFE-002） |
| P1 MEM-002 幂等键形状先例 | `memory_candidates` UNIQUE(source_table, source_id)（db.py:812）+ `_create_candidate` 先查后插 | trigger_key 唯一约束 + upsert 先查后插同款实现套路 |
| P1 per-user 写锁 | `get_user_write_lock`（post_process.py:383-388） | trigger 行级状态迁移在 claim 事务内完成（FOR UPDATE SKIP LOCKED），无需用户级锁；写锁仅复用在既有调用点 |
| P4 REL-003 PolicySnapshot 扩展先例 | autonomy_engine.py:142-149（`_snapshot_for` 内 patterns 读取，异常降级空） | 「Extend 不改纯函数本体」的 Flag 分叉先例——本 Task 对 trigger_evaluator 的改造遵循同款边界 |

不依赖 Memory/Reflection/Development/Relationship 的任何运行时行为（本 Task 只做存储与读写迁移）。

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/services/trigger_evaluator.py` L26-27 | `_followup_registry` 内存 dict + lock | Flag ON：写路径改表（+迁移期双写 dict）；OFF：逐字节 v1 |
| 同文件 `register_followup` L30-40 | 内存写 | Flag ON：upsert 表（trigger_key=既有 dedupe_key 形状）+ 双写 dict；DB 失败回退 dict |
| 同文件 `poll_due_followup` L52-70 | 内存扫描 + pop 出队 | Flag ON：表 claim（pending 且 due_at≤now 且 cooldown_until≤now → due，SKIP LOCKED）；无 due 返回 None |
| 同文件 `evaluate_inactivity` L137-177 | 纯函数即时判定，命中即返回信号 | **函数本体零改动**；命中后 Flag ON 追加一步 `register`（upsert，已存在非 pending 行 → 返回 None，跨重启幂等取代 seen_keys） |
| 同文件 `poll_due_actions` L73-110 / `mark_action_reported` L113-134 | 现场扫 world_events + payload 置位 | 轮询逻辑不变；Flag ON 命中后经 register 领取；`mark_action_reported` 追加 trigger done 推进（幂等） |
| 同文件 L109 / L134 | **缺陷：引用未定义的 `logger`**（模块无 `import logging`），异常路径二次 NameError | 本 Task 实施时顺手补 `logger = logging.getLogger(__name__)`（两行修复，零行为变化；详见 README 核对记录 6） |
| `app/services/memory_service.py` L99-102 `_register_followups` | 登记点（记忆保存后调用） | 零改动（`register_followup` 内部自迁移） |
| `app/application/autonomy_engine.py` L249-262 | 信号优先级：action_due → followup → inactivity | 零改动（poll 函数内部自迁移）；L361-364 delivered 后 `mark_action_reported` 调用点零改动 |
| 同文件 L50-51 `reset_seen_keys` | **缺陷：引用从未定义的 `_seen_dedupe_keys`**（调用即 NameError；当前无调用方，死代码） | 本 Task 不动（死代码清理另行确认；登记 README 核对记录 6） |
| `app/repositories/` | 无 trigger 仓储 | 新增 `trigger_registry_repository.py`（register/claim_due/complete/cancel/fail_for_retry/has_due/recover_stale） |
| `app/core/db.py` | 无 trigger_registry 模型 | 新增 `TriggerRegistryRow`（风格对齐 BackgroundJobRow） |
| `migrations/versions/` | head=0027 | 新增 `0028_trigger_registry.py` |
| `app/core/settings.py` | 无任何 v2_life_loop* 配置 | 新增 `v2_life_loop_enabled: bool = False`（autonomy 块后）+ `v2_life_loop_trigger_max_attempts: int = 3` + `v2_life_loop_trigger_backoff_seconds: int = 300` |
| `tests/unit/test_trigger_followup.py` / `test_trigger_evaluator.py` | v1 内存语义回归 | 保持全绿（OFF 路径）；新增 `tests/v2/test_life001_trigger_registry.py` |

## 设计方案

1. **表结构（迁移 0028）**：

   ```text
   trigger_registry
     id            varchar PK
     user_id       varchar NOT NULL
     character_id  varchar NOT NULL default 'asuna'
     trigger_type  varchar NOT NULL   CHECK in ('conversation_inactivity','scheduled_followup','action_due')
     trigger_key   varchar NOT NULL   UNIQUE          -- ≡ v1 dedupe_key 形状，天然幂等
     status        varchar NOT NULL   CHECK in ('pending','due','fired','done','cancelled')
     due_at        timestamptz NOT NULL
     priority      int NOT NULL       -- action_due=1 / followup=2 / inactivity=3（编码 v1 信号优先级）
     cooldown_until timestamptz NULL  -- 重试退避抑制
     attempt_count int NOT NULL default 0
     payload       JSON NULL          -- summary / event_id / context 等信号 context 原样
     last_error    varchar NULL
     created_at / updated_at timestamptz
     索引：(status, due_at)（due 扫描）、(user_id, status)
   ```

   trigger_key 与 v1 dedupe_key 完全同形：`action_due:{event_id}` / `followup:{user}:{summary[:20]}:{date}` / `inactivity:{user}:{last_user_message_id}`——v1 已验证的幂等语义直接升格为唯一约束。

2. **状态机**（tasks.md 口径 + 重试内边，登记见 README 核对记录 8）：

   ```text
   register (upsert)：key 已存在且 status∈(pending,due,fired) → 拦截返回已存在（重复登记）
                      key 已存在且 status∈(done,cancelled) → 复活为 pending（新 episode 同 key 重触发）
   pending ──claim(claim_due: due_at≤now ∧ cooldown_until≤now，FOR UPDATE SKIP LOCKED)──> due
   due ──信号进入判定/决策管线──> fired
   fired ──下游终态（proactive delivered ∨ mark_action_reported ∨ 判定为不行动）──> done
   fired ──处理异常──> pending（attempt_count+1，cooldown_until=now+backoff×2^n）
   任一态 ──cancel──> cancelled（reason: stale / max_attempts / shutdown）
   attempt_count ≥ v2_life_loop_trigger_max_attempts → cancelled(reason=max_attempts)（死信留痕）
   ```

   「判定为不行动」（AutonomyPolicy verdict≠act）也是 trigger 的正常消耗——信号被评估过即 done（评估记录在 decision_records，LIFE-006 溯源），不重试；重试只针对处理异常（DB/LLM 故障）。

3. **读写迁移（TriggerEvaluator 内部分叉，函数签名不变）**：
   - `register_followup`：Flag ON → 表 upsert + 迁移期双写内存 dict（OFF 回退窗口可读）；DB 异常 → log + 仅 dict（tasks.md Error/Failure：DB 失败回退内存路径）。
   - `poll_due_followup`：Flag ON → `claim_due(user_id, types=["scheduled_followup"])`，claimed 行转 due 并产出 TriggerSignal（context 从 payload 还原）；Flag OFF → v1 dict 路径逐字节。
   - `evaluate_inactivity`：纯判定不动。引擎拿到信号后（autonomy_engine `_process_user` 拿到 signal 处不做改动）——落在 `evaluate_inactivity` 内部返回信号前追加 register：Flag ON 时 upsert `inactivity:{user}:{message_id}`，若 key 已存在非 pending（跨重启重复评估同一 episode）→ 返回 None。该行 due_at=detected_at、立即 claim（register+claim 同事务原子完成，行为与 v1「扫到即用」一致）。
   - `poll_due_actions`：同上——命中到期未汇报事件后 register `action_due:{event_id}`（payload 含 event_id/title/due_at），重复命中被唯一键拦截；`mark_action_reported` Flag ON 追加 `complete_trigger(key, status=done)`（幂等，行不存在则忽略）。
   - **stale 校验（替代前台改动）**：inactivity trigger claim 时校验 payload.last_user_message_id 仍是该用户最新用户消息 id，否则 cancel(reason=stale)——用户新消息作废旧 inactivity 触发，与 v1 `reset_on_user_message` 语义等价但不触碰前台通知路径（Non-Scope）。

4. **迁移期双写与对账**：Flag ON 首版本内 dict+表双写（回退 OFF 时 dict 仍有全量登记），下一版本（v2.1）移除 dict 双写切表 only——登记遗留清单。对账任务 `recover_stale`（Life Loop 维护步骤调用，LIFE-002 接线；本 Task 交付函数）：due/fired 滞留超 `v2_job_running_timeout`（600s 复用）→ 重置 pending 或 cancelled（reason=stale_recovered），修复「表损坏/进程崩溃在 claim 后」的悬挂态（tasks.md Risk：以表为准对账）。

5. **时间基准**：due_at / cooldown_until 的比较在 SQL 内用数据库时间（`due_at <= NOW()`，沿 data-flow.md §3「周期任务一律用数据库时间」）；Python 侧 now 一律参数注入（可测试）。

6. **观测**：登记/领取/跳过/取消全路径 log（补齐 logger 后）；trace 侧本 Task 在既有 runtime_traces（kind=autonomy_tick）的 signal context 中附 trigger_key——完整 trigger trace 步骤名收口归 LIFE-006（trace_collector 为横切注册表，逐 Task 扩展先例）。

## 数据模型 / 状态变化

- 新表 `trigger_registry`（迁移 0028，唯一 DDL）；新模型 `TriggerRegistryRow`（db.py，对齐 BackgroundJobRow 风格：status CHECK、attempt_count、时间列）。
- 状态机五态 + 重试内边（见设计 2）；行只增改不物理删（cancelled 死信留痕供审计，物理清理归 observability retention 语义外未来决策）。
- 新增 settings：`v2_life_loop_enabled` / `v2_life_loop_trigger_max_attempts` / `v2_life_loop_trigger_backoff_seconds`（本 Task 三个；后续 Task 各自追加）。
- 零业务域表变更；memories/goals/world 全零接触。

## 核心处理流程

```text
Flag OFF（现状逐字节）:
  followup: memory_service._register_followups → register_followup → 内存 dict
  tick: poll_due_actions（现场扫 world_events）→ poll_due_followup（dict 扫描 pop）
        → evaluate_inactivity（纯函数）→ AutonomyPolicy

Flag ON:
  登记: 信号命中（followup 登记 / inactivity·action_due 判定命中）
        → trigger_registry_repository.register（upsert by trigger_key，唯一键拦截重复）
        → 迁移期双写内存 dict（回退窗口）
  消费: claim_due（SQL: pending ∧ due_at≤DB now ∧ cooldown_until≤now，ORDER BY priority,due_at，
        FOR UPDATE SKIP LOCKED）→ pending→due → 产出 TriggerSignal（payload 还原 context）
        → 既有管线（AutonomyPolicy 纯函数 / proactive enqueue+execute）
        → delivered/mark_reported/非 act → fired→done
  重试: 处理异常 → pending（attempt+1，cooldown 退避）；≥max_attempts → cancelled 死信
  对账: recover_stale —— due/fired 滞留 >600s → 重置 pending / cancelled(stale_recovered)

kill -9 演练: register 落表 → kill -9 → 重启 → claim_due 命中同一行 → 触发一次不重复
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：followup 登记源在 memory_service（记忆保存后钩子，L99-102）——本 Task 只迁移其下游存储，登记触发条件（关键词表 FOLLOWUP_EVENT_KEYWORDS）零改动；Memory 域不读 trigger_registry（依赖矩阵方向：Life Loop 编排域调用一切、不被业务域调用）。
- **Reflection**：无直接交互（REF-003 触发器是独立的反思触发面，走 background_jobs 日桶，不经 trigger_registry——两套触发语义刻意不合并，见 README 核对记录 14）。
- **Development**：无直接交互。
- **Relationship**：无直接交互（亲密度调制间隔仍活在 AutonomyPolicy 纯函数内，`effective_interval_minutes` autonomy_policy.py:80——registry 的 cooldown_until 只承载重试退避，不承载策略冷却，两值语义分离）。

## 异常与边界情况

- **DB 失败（双写期）**：register/poll 异常 → log + 回退内存 dict 路径（行为退化为 v1，可接受）；无 dict 可回退的操作（inactivity register）失败 → 放过本次信号（下轮 tick 重新评估，天然自愈）。
- **kill -9 在 claim 后 done 前**：行滞留 due/fired → 重启后 `recover_stale` 重置 pending → 重新 claim 触发；attempts 已 +1，退避冷却保证不会瞬时风暴。
- **重复登记**：唯一键 + upsert 拦截（同 episode 重复评估、多进程同时 register）；「复活」语义处理同 key 重触发（昨日 followup done 后明日同摘要新 key——date 进 key，天然新行）。
- **claim 与 tick 并发**：SKIP LOCKED 保证多执行器（单进程多 tick 或未来 Worker 抽离）下一条 trigger 只被一个执行器领取（对齐 P1 job_worker `_claim` 模式 job_worker.py:89-107）。
- **inactivity 的 message 已非最新**：claim 时 stale 校验 → cancelled(reason=stale)，本轮不产出信号。
- **world 事件在 claim 前被用户手动完结**：poll_due_actions 既有 payload 检查天然过滤；已 claim 行随处理流程走 done。
- **Flag ON 但迁移未跑**：表不存在 → 首次查询抛异常 → 回退 dict + 启动告警（settings 校验器模式对齐 `validate_rel_config` settings.py:532-548 加一条提示：启用前先跑迁移）。
- **SQLite 测试环境**：SKIP LOCKED 在 SQLite 退化为普通锁（P1 job_worker 已验证该方言差异可接受，job_worker.py:89-107 注释口径）。

## 测试要求

- Unit：状态机全迁移路径（含非法迁移拒绝、复活语义、max_attempts 死信）；trigger_key 幂等（重复登记拦截）；priority 排序；stale 校验；backoff 计算。
- Integration：①kill -9 演练——register → 模拟进程重启（新 SessionLocal）→ claim 命中同一行且只触发一次；②三类信号端到端——followup 到期触发、inactivity 跨重启幂等、action_due delivered 后 done；③对账——人为制造 due 滞留 → recover_stale 修复；④DB 故障注入——表查询异常回退 dict（双写期行为）。
- Idempotency：同 trigger_key 并发 register ×N → 仅 1 行；claim 并发 ×N → 仅 1 个执行器拿到。
- Regression：**Flag OFF 全量 golden**（trigger_evaluator 内存路径逐字节）+ V7 autonomy checklist（tests/unit/test_trigger_*、tests/integration/test_autonomy_matrix.py、test_proactive_* 全绿）。
- 性能：claim 扫描走 (status, due_at) 索引，单次扫描 <10ms 量级（P0 用户规模无压力断言即可）。

## 验收标准

- 给定 pending followup trigger，当进程 kill -9 后重启，那么 trigger 保留且到期正常触发不重复（E-LIFE-01）。
- 给定同一触发信号重复登记（跨轮/跨进程），那么 trigger_registry 恒为 1 行且只触发一次。
- 给定处理连续异常的 trigger，那么 attempt_count 递增 + cooldown 退避，达上限转 cancelled 且留 reason（死信可查）。
- 给定 Flag OFF，那么三类触发信号行为与 v1 逐字节一致（V7 checklist 全绿）。
- 给定任一触发信号，当查询 trigger_registry，那么其状态、次数、payload 可回答「登记于何时/为何触发/为何没触发」。

## Implementation Constraints

- **AutonomyPolicy 纯函数本体零改动**（evaluate / effective_interval_minutes / in_quiet_hours——tasks.md 红线）；本 Task 只动 TriggerEvaluator 的存储通道，三类信号的判定条件、context 字段、dedupe_key 形状全部保持 v1。
- autonomy_engine / autonomy_worker / proactive_executor 本体零改动（LIFE-002 才归并调度）；`mark_action_reported` 内追加一行 done 推进是唯一引擎文件触点（幂等、Flag 门控、OFF 逐字节）。
- trigger_evaluator 的 `logger` 缺失修复（L109/L134）随本 Task 实施（两行）；`autonomy_engine.reset_seen_keys` 死代码不动。
- 迁移 0028 只增表，零列变更零数据迁移（纯新表，downgrade drop）。
- LLM Usage = NONE（全程规则与 SQL）。
- 周期任务时间基准用数据库时间（data-flow.md §3）；不新增 `datetime.now()` 散点。
- 不提前实现 Controller 的 due 扫描消费（LIFE-002）与 Idle 判定（LIFE-003）——本 Task 交付的 `has_due`（只读 EXISTS）是给它们的基础件，本 Task 自身不消费。
- 不合并 Reflection 触发器入 trigger_registry（两套触发语义职责不同，见 README 核对记录 14）。
