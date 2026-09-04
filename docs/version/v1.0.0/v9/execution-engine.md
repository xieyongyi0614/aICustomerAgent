# V9 Execution Engine（执行编排与容错）

> ActionEngine 是行动域唯一的编排器：plan → execute → integrate 三段，全部发生在 post_process 第 9 步（per-user 写锁内）或重试维护循环中。本篇定义执行编排、超时/重试/幂等、失败分类与恢复。

## 1. ActionEngine 编排

落点 `app/application/action_engine.py`（模块级函数组织，与 world_engine 同惯例；所有失败只 log + 降级，永不冒泡到回复）：

```text
run_action_planning(ctx: PostProcessContext) -> None          # post_process 第 9 步入口
    ├─ 门控 action_enabled；intent 为 None → 返回
    ├─ create_record(intent, ctx)                             # created + audit 落库
    ├─ evaluate_gates(intent, snapshots)                      # 六闸门（planner.md §2）
    │     └─ 否决 → transition(cancelled, gate_reason) → 返回
    ├─ assemble_plan(intent, registry)                        # planned
    ├─ execute_plan(record, plan) -> ActionResult             # executing
    │     ├─ CapabilityExecutor.run(step, ctx)                # 超时包裹 + 结果归一
    │     └─ 逐步回填 steps / result
    └─ integrate_result(record, result)                       # 结果整合四通道
          ├─ world_bridge（tool-integration.md §2）
          ├─ memory_bridge（memory-policy.md §3）
          ├─ relationship_bridge（relationship-impact.md §3，默认关）
          └─ note_bridge（行动 note → 下轮上下文）
```

- 检出（H-A1，前台 turn 内）与执行（第 9 步，后台）**分离**：检出毫秒级纯函数，执行可能含 IO——回答流零阻塞。
- `run_action_retry_loop()`：lifespan 维护循环（与 `run_world_maintenance_loop` 同构），周期扫描 `status=executing and next_retry_at<=now` 的记录重新入执行；顺带执行 `expires_at` 过期检查（planned 超时 → cancelled）。间隔 `action_maintenance_interval_seconds`（默认 60）。
- 自治链路执行入口：`execute_autonomy_plan(source="autonomy")`——`autonomy_action_enabled=false` 时仅为接口预留（autonomy-integration.md §4）。

## 2. CapabilityExecutor

落点 `app/services/action/executor.py`：

```text
run(step: ActionStep, ctx: ExecutionContext) -> CapabilityResult
    1. registry.get(step.capability)          # G3 已过，防御性再查
    2. asyncio.wait_for(capability.execute(...), timeout=action_execution_timeout_seconds)
    3. CapabilityResult 归一：异常 → failed(error=摘要)；超时 → timeout
    4. usage 统计（duration_ms）回填 step
```

- 能力异常一律捕获归一为 `failed`，**不区分异常类型**（能力内部负责把可恢复状况表达为 unavailable/transient 语义字段）。
- 超时不取消已产生的半效果（如 WorldEvent 已建但超时返回）——能力实现必须**先写后返**或**先返后写二选一**并保证幂等；MVP 能力全部单写操作，天然无半效果。
- 单 step 失败不影响同 plan 其余 step（MVP 单步，预留多步语义：失败 step 后置 skipped）。

## 3. 失败分类与恢复

| FailureKind | 含义 | 恢复策略 |
|---|---|---|
| `transient` | 暂时性失败（锁竞争、临时 IO） | 自动重试：attempt+1，`next_retry_at = now + backoff_seconds × 2^(attempt-1)`；超 `action_retry_max_attempts` → failed 终态 |
| `timeout` | 执行超时 | 同 transient 重试；重试仍超时 → failed |
| `permanent` | 参数/前提不满足（G6 通过后前提又变，如物品已被 interpreter 移走） | **不重试**，failed 终态；进行动 note 待补救 |
| `unavailable` | 能力未接入（search/notification） | 不重试，failed 终态；评估降级 info（不扣分警告） |

- 重试**复用同一 ActionRecord**（attempt 递增），不新建——行动是幂等委托，不是多次独立行动。
- 重试决策纯代码（executor 层），能力与 planner 均无重试权——职责分离第二体现。

## 4. 幂等与并发

| 机制 | 位置 | 说明 |
|---|---|---|
| dedupe_key 去重 | G4 闸门 | 同 (user, action_type, key) 在 `action_dedupe_window_hours` 内已有 succeeded / 非终态记录 → duplicate 否决（planner.md §2） |
| per-user 写锁 | 第 9 步全程 | 复用 `post_process.get_user_write_lock`——与 save_turn / proactive_executor 落库互斥，行动创建的世界事件不与进行中 turn 交错 |
| 重入保护 | execute_plan 入口 | Record 状态非 planned/executing 拒绝执行（锁内重查，proactive_executor 同款 TOCTOU 防御） |
| 单进程假设 | lifespan 循环 | 单 worker 单写锁，无跨进程竞争；多实例部署留待未来（V7 action-queue 同预留位） |

## 5. trace 与观测

- 前台链路：第 9 步内 `trace.record("action_execute", ...)`（H-A4 新增规范名）；检出在 turn 内记 `action_detect`。
- 自治/重试链路：自建 TurnTraceSession 并 `collector.attach(trace, record_id)`（V7 自治同款）。
- 记录字段即观测面：gate_reason 分布（词表调优依据）、failure_kind 分布（能力健康度）、attempt 分布、capability × duration（usage）。
- /debug/actions 端点（H-A7）：GET 列表（按 user/status 过滤）/ GET 详情（含 steps/result/effects）/ POST 手动重试（failed → executing，运维用）/ POST 取消（非终态 → cancelled）。

## 6. 明确不做

- 不做分布式事务 / Saga：跨通道效果（世界+记忆）单写锁内顺序执行，单通道失败不回滚其他通道（效果清单记录实况，补录语义）。
- 不做执行队列 / 优先级：第 9 步同步执行 + 维护循环兜底，单用户单行动模型下无排队需求（V7 outbox 同款结论）。
- 不做能力沙箱 / 资源配额：能力全部内置 manual/simulated，无外部资源；接入真实 API 时再评估。
- 不做多步依赖编排 / 失败回滚：MVP 单步；多步（steps 间依赖、部分成功回滚）留待后续版本，模型已预留（ActionStep.status=skipped / ActionResult.partial）。
