# LIFE-003 Task Detail — Idle 与预算控制（Core）

> 上游：[../tasks.md](../tasks.md) LIFE-003 ｜ [../../../architecture/llm-orchestration.md](../../../architecture/llm-orchestration.md) §3 预算熔断 ｜ [../../../architecture/risk.md](../../../architecture/risk.md) R9 ｜ 依赖：LIFE-002（本 Phase 内）

## Task 目标

给 Life Loop 装上成本刹车的两个踏板，明确「角色什么时候什么都不做」：

1. **Idle 判定**（纯规则）：无 due trigger 且无到期 goal 且无维护到期且状态平稳 → 跳过整轮，0 LLM、0 记账行——空转模式只剩时钟检查；
2. **预算控制**：每周期步骤 LLM 预算 + 全局日 LLM 配额熔断——超限时周期内 LLM 步骤降级为跳过（不生成 proactive），前台路径永不熔断；
3. **记账闭环**：每轮 llm_call_count / token_total / budget_state 落 loop_runs，「为什么降级/为什么 Idle」可答。

任务书 §二十二禁 `while true: call LLM()`——没有这两个踏板，Life Loop 就是成本无底洞（R9）：5 循环归并后的单循环每 60s 醒一次，若无 Idle 短路，一个 7 天不说话的静止用户也会每天积累上千次空转；若无熔断，任何触发器 bug 或风暴都会直接烧穿预算。

## 背景 / 为什么需要

v1 的成本控制只有三处局部限额，没有全局视图：

- `autonomy_action_daily_limit=1`（autonomy_engine.py:87，仅限自治产行动）；
- `autonomy_max_attempts_per_episode=2` + cooldown（AutonomyPolicy，仅限单 episode 主动消息）；
- `quota_exceeded` 闸门（planner.py:104，`action_max_active_per_user=5`，仅限并发 action 数）。

全仓**没有** LLM token/cost 日配额、没有熔断逻辑（settings.py 无 quota/circuit/rate_limit 类配置；`run_budget_observer` 检查的是行为层动作描述句数，与 LLM 预算无关——post_process.py:279-305）。v1 之所以没有全局熔断还能活，是因为触发面窄（inactivity 30 分钟 + followup 关键词）且 LLM 只在命中后调用；v2 Life Loop 把感知/检索/反思/决策全部纳入周期，触发面扩大，没有全局配额与 Idle 短路等于裸奔。

架构裁决（llm-orchestration.md §3）：**预算熔断 = 全局每日 LLM Token/调用配额（settings 可调），超限后台任务降级；前台永不熔断**。本 Task 是该裁决在 Life Loop 的落地面（执行面范围登记见 README 核对记录 11）。

## 依赖的 Phase 1~4 能力

| 依赖 | 实现锚点 | 本 Task 消费方式 |
|---|---|---|
| LIFE-002 Controller 骨架 | `life_loop.py` tick 骨架 + loop_runs steps JSON + 记账列（建表即含） | Idle 判定与预算检查插在 tick 骨架的既定位置（work 发现后、步骤管线前）；记账写既有列，零 DDL |
| LIFE-001 `has_due` | trigger_registry_repository 只读 EXISTS | Idle 判定第一条件（有 pending due trigger 即不可 Idle） |
| V7.8 LLM 记账 | `llm_call_records`（db.py:485-513，input_tokens/output_tokens/cost_estimate/created_at，索引 idx_llm_calls_time）+ `llm_call_repository.list_since`（:135） | 日配额用量聚合的数据源；新增聚合查询函数（COUNT+SUM，走既有时间索引） |
| P1 MEM-009 退避协议 | `v2_job_retry_backoff_seconds × 2^(attempts-1)`（job_worker.py:152-169） | 预算不足时 trigger 重试退避对齐同款参数风格（实际退避由 LIFE-001 cooldown_until 承载） |
| P1/P2 既有额度机制（参照） | evaluator fallback rate cap（`v2_memory_llm_fallback_rate_cap`）、反思日额度（`_quota_used` triggers.py:234-247） | **不改其内部**——它们已是独立限额；本 Task 的全局熔断是其上层的横切闸（范围登记 README 核对记录 11） |

## 当前代码涉及位置

| 位置 | 现状 | 本 Task 动作 |
|---|---|---|
| `app/application/life_loop.py` | LIFE-002 交付的 tick 骨架（Idle 位与步骤位已留） | 实装 `_should_idle` / `_check_budget` / 降级分支 |
| `app/repositories/llm_call_repository.py` | 仅有 `list_since`（拉全量行，limit 20000——不适合每轮聚合） | 新增 `aggregate_usage_since(cutoff) -> dict`（SQL COUNT(*)+SUM(input_tokens+output_tokens)，GROUP BY 无需，走 idx_llm_calls_time） |
| `app/application/life_loop.py`（或新 `app/services/life_loop_budget.py`） | 无 | 新增日配额检查器：`check_daily_budget(now) -> BudgetState(ok|degraded, used_calls, token_total, call_limit, token_limit)`，带结果缓存 |
| `app/core/settings.py` | 无预算配置 | 新增 `v2_life_loop_daily_llm_call_budget: int = 200`、`v2_life_loop_daily_llm_token_budget: int = 0`（0=不按 token 熔断）、`v2_life_loop_budget_cache_seconds: int = 60`、`v2_life_loop_cycle_llm_budget: int = 1`、`v2_life_loop_degraded_usage_ratio: float = 0.8` |
| `app/core/db.py` loop_runs | LIFE-002 建表已含 llm_call_count/token_total/budget_state 列 | 零 DDL（README 核对记录 9） |
| `tests/v2/test_life002_controller.py` | LIFE-002 空转基础用例 | 新增 `tests/v2/test_life003_idle_budget.py`；`tests/e2e` 无需新增 |

## 设计方案

1. **Idle 判定（纯规则，tick 第一步）**：

   ```text
   should_idle = NOT has_due_trigger()            -- LIFE-001 只读 EXISTS
             AND NOT goal_catchup_due()           -- LIFE-002 work 发现项
             AND NOT outbox_pending()             -- LIFE-002（子闸关闭恒 False）
             AND NOT maintenance_due()            -- world/action/outbox/reconcile 间隔
   should_idle → 本轮直接返回：0 LLM、0 loop_runs 行、0 写路径
   ```

   「状态平稳」条件的裁决：**不引入独立的状态平稳检查**——状态非平稳的后果（情绪极端需要安抚等）在 v2 里由 due trigger（用户交互后遗留）与 goal（到期补扫）承载；没有 trigger 与 goal 的「状态平稳」用户恰是 Idle 的定义对象。额外发明状态波动检测会引入无依据的触发源（R8：触发器互相唤醒），违反「宁可不跑」原则。此裁决登记 README 核对记录 12（tasks.md Scope 列「状态平稳→跳过整轮」，落地口径=该条件由前三个 work 项联合承载）。
   判定异常（任一查询抛错）→ **默认 Idle**（tasks.md Error/Failure：宁可不跑）。

2. **每周期步骤预算**：`v2_life_loop_cycle_llm_budget`（默认 1）= 单用户周期内允许的 LLM 步骤数上限。执行点：步骤 6（decision，唯一 LLM 步骤）运行前检查本 run 已耗 LLM 步骤数（从 steps JSON 聚合）——超限 → decision 步骤 skip(reason=step_budget) + trigger 留 due 态（recover_stale 下轮重试）。正常态该预算恒为 1（decision 是唯一 LLM 步骤），其意义是**结构上限**：未来任何步骤新增 LLM 调用都被该闸兜住（防止步骤叠加悄悄突破「生活时刻 LLM 只在 Decision 命中」铁律——character-runtime.md §2.2 成本铁律的机械保障）。

3. **全局日配额熔断**：

   ```text
   check_daily_budget(now):
     cache 命中（≤v2_life_loop_budget_cache_seconds）→ 返回缓存 BudgetState
     try: usage = aggregate_usage_since(当日零点[DB 时间])
     except: → 保守模式：call_limit ×= v2_life_loop_degraded_usage_ratio(0.8)，used 未知按 limit 记
     degraded = (call_limit>0 AND used_calls ≥ call_limit)
             OR (token_limit>0 AND token_total ≥ token_limit)
   ```

   - **熔断执行面（Life Loop 步骤内）**：degraded 时步骤 6 skip(reason=quota_circuit_open)——不调 tick、不生成 proactive；已 claim 的 trigger 留 due 态经 recover_stale 重置后带退避重试；步骤 4（memory_retrieval）与 5（reflection_check）为 0 LLM 只读/入队步骤，不受熔断跳过（反思入队后的执行面 LLM 由 REF-003 既有日额度约束，天然双重保险）。
   - **前台永不熔断**：check_daily_budget 只被 life_loop 调用；chat_pipeline / answer 链不读该状态（tasks.md Non-Scope + llm-orchestration §3）。
   - **降级恢复**：无持久化状态机——BudgetState 每次现算（带缓存），次日零点聚合窗口自然滚动即恢复；degraded 期间的状态留痕在每轮 loop_runs.budget_state JSON（used/limit/decision），审计可查。
   - **记账口径**：loop_runs.llm_call_count/token_total 来自本 run trace 聚合（LIFE-002）；全局用量以 llm_call_records 为准（唯一记账真相，两套数字各司其职：run 级归因、表级配额）。

4. **熔断联动范围（Non-Scope 边界）**：P1 记忆评估兜底与 P2 反思执行面的 LLM 不接本熔断——它们已有独立限额（fallback rate cap / 日额度），且其执行面在 background_jobs handler 内，改动需触碰已交付域（P1/P4 灰度风险）。本 Task 交付 check_daily_budget 为公共基础件，P1/P2 接线留作灰度观察后的后续决策（登记 README 核对记录 11）。

5. **观测**：`life_loop_budget` trace 步骤（LIFE-005 一并注册步骤名或本 Task 注册）：每轮记录 BudgetState 快照；degraded 与 idle 决策均落 loop_runs（idle 不落行的例外：Idle 决策本身不建 run——「为什么没运行」由「无 loop_runs 行 + has_due=false」组合回答，六问口径登记 README 核对记录 13）。

## 数据模型 / 状态变化

- **零 DDL**（loop_runs 记账列由 LIFE-002 建表一次到位）。
- 状态机：`loop: running→idle(空转模式)|active`（tick 级判定，无持久化）；`预算: ok→degraded(后台降级)→恢复`（现算无状态机持久化，留痕在 budget_state JSON）。
- 新增 settings 五项（见涉及位置表）。
- 不写任何业务域表；trigger 留 due 态是唯一跨 Task 状态效应（LIFE-001 生命周期承载）。

## 核心处理流程

```text
周期开始（LIFE-002 tick 骨架内）
  → Idle 判定（纯规则四条件）
      [Idle → 直接返回：0 LLM、0 run 行、仅时钟检查]
      [运行 → 步骤管线（LIFE-002）]
  → 步骤 6 前：check_daily_budget（缓存 60s）
      [degraded → decision skip(reason=quota_circuit_open)
                  → trigger 留 due，recover_stale 带退避重试
                  → run done（budget_state 留痕）]
      [ok → decision 执行 → proactive 命中时 LLM 发生]
  → run 收口：llm_call_count/token_total/budget_state 落 loop_runs

故障注入:
  用量查询失败 → 保守 80% 预算运行（可能提前 degraded，宁紧勿松）
  判定异常     → 默认 Idle（宁可不跑）
```

## 与 Memory / Reflection / Development / Relationship 的关系

- **Memory**：步骤 4（memory_retrieval）不受熔断跳过（纯 DB 读）；P1 记忆评估的 LLM 兜底不在本熔断执行面（已有 fallback rate cap，联动留后续——核对记录 11）。
- **Reflection**：步骤 5 入队不受熔断跳过（0 LLM）；反思执行的 main 档 LLM 受 REF-003 日额度约束——两套额度叠加后反思日 LLM 上限不变（≤1 次/日/用户），熔断只是额外的全局刹车。
- **Development**：无直接交互（调制是纯函数，无 LLM）。
- **Relationship**：无直接交互（V8.5 数值数学无 LLM）。

## 异常与边界情况

- **用量聚合查询失败** → 保守模式（预算×0.8 后照常判定，used 未知按 limit 记 → 直接 degraded）——倾向熔断而非放行。
- **Idle 判定查询失败** → 默认 Idle（宁可不跑）。
- **缓存与熔断时滞**：budget_cache_seconds 内的用量增量不可见——最坏多放行 cache 窗口内的少量调用（60s 窗口 × 周期预算 1，可控）；cache 不得长于 tick 周期（校验器加提示）。
- **跨日竞态**：聚合 cutoff 用 DB 当日零点，跨零点瞬间缓存可能引用昨日窗口——窗口键（date）进缓存键，跨日自动失效。
- **llm_call_records 无 user_id 列**：配额只能是全局口径（架构 llm-orchestration §3 即全局日配额）；per-user 配额需 schema 扩展，非本 Phase 范围（登记 README 核对记录 1）。
- **token 预算为 0（默认）**：只按调用次数熔断（token 计量在部分 provider 不可靠，默认关闭，settings 可开）。
- **7 天空跑验收的时钟模拟**：测试用注入 now 的 fake clock 驱动 tick（Controller 已参数化 now），不真跑 7 天——长跑演练以小时级压缩时间轴执行（regression-checklist 执行步骤 2 的口径）。

## 测试要求

- Unit：Idle 四条件真值表（含查询异常默认 Idle）；BudgetState 计算（ok/degraded 边界、保守 0.8、跨日窗口）；周期步骤预算聚合。
- Integration：①7 天空转长跑（压缩时钟）——Idle 期间 LLM 调用为 0、总量 ≤ 日预算（E-LIFE-03）；②熔断注入——llm_call_records 预填超限用量 → degraded → decision skip + 前台 answer 链正常（前台不熔断证明）；③恢复——跨零点后自动恢复 active；④记账——degraded 轮的 budget_state 留痕完整。
- Regression：Flag OFF 无行为（本 Task 全部代码在 Flag ON 路径内）；LIFE-002 既有测试全绿；V7 checklist 全量（每 Task 合入硬门）。
- 性能：aggregate_usage_since 走时间索引，缓存命中后每轮 0 查询。

## 验收标准

- 给定 7 天无用户消息（压缩时钟模拟），当 Life Loop 运行，那么 Idle 期间 LLM 调用为 0 且总量在日预算内。
- 给定全局配额超限，那么周期内 LLM 步骤降级（不生成 proactive、trigger 带退避保留）、前台消息处理不受任何影响。
- 给定用量查询失败，那么系统按 80% 预算保守运行而非放行。
- 给定任意一轮（运行/空转/降级），「为什么 Idle / 为什么降级 / 花了多少」均可由 loop_runs.budget_state 与 trace 回答（E-LIFE-03 审计面）。
- 给定次日到来，那么熔断自动解除，无人工干预。

## Implementation Constraints

- **前台路径永不熔断**：check_daily_budget 的调用面仅限 life_loop 步骤；禁止在 chat_pipeline / answer_chain / proactive_executor（被前台共享的执行体）内读取 BudgetState——降级只能发生在 Controller 调用决策之前。
- Idle 判定是纯规则（0 LLM、0 embedding）；禁止引入「预测性触发」「智能调度」等智能 Idle（tasks.md Non-Scope：不做智能预测）。
- 熔断只降级后台：degraded 不取消 trigger、不清队列、不改业务状态——只推迟 LLM 步骤。
- 不修改 P1/P2 已交付域内部的额度逻辑（fallback rate cap / 反思日额度）；check_daily_budget 作为公共基础件交付，联动属后续灰度决策。
- 不新增 llm_call_records 列（无 user_id 的全局口径足够，核对记录 1）。
- LLM Usage：本 Task 自身 0 LLM；它约束的是其他步骤的 LLM。
- 不提前设计 Phase 6：预算不区分任务类型/模型档位的差异化配额（属 P6 若有需要另行设计）。
