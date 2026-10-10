# 交互式 Plan 模式改造评估

> 评估日期：2026-10-10 ｜ 分支：`feat/feishu_bot` ｜ 性质：**只评估，不动代码**
> 目标形态：WorkBuddy 式「Agent 先出整份方案 → 人工确认 → 再执行」的计划级审批闸门
> 依据：`docs/current-system-architecture-baseline.md`（当前唯一可信基线）、`docs/version/v2.5.0/planning-system/architecture.md`

---

## 一、结论

**可以做，而且比预期便宜得多——后端核心改动可做到「零迁移 + 零新状态值」。**

原因是一个现成的语义巧合：计划状态机里已有的 `validated` 值，**从不被任何执行路径拾取**。把它作为「待批准」停靠点，等于系统天然支持「计划已生成但不执行」。当前 `plan_goal()` 之所以一生成就执行，仅仅是因为它在同一函数里把 `validated` **立刻**改成了 `active`。

| 维度 | 结论 |
|---|---|
| 是否伪任务 | **否**。计划级审批闸门今日确实不存在（只有工具/动作级确认） |
| 需要数据库迁移 | **不需要**（复用 `validated`，CHECK 已含该值） |
| 需要新增状态值 | **不需要**（`GoalPlanStatus` 五值够用） |
| 是否触碰冻结哈希面 | **不触碰**（`services/goal/planning.py` 不在任何 `FROZEN_SOURCES` / `ZERO_DIFF_HASHES`） |
| 最小可用改动量 | **S 级**：1 设置项 + 1 分支 + 1 审批服务 + 1 路由文件 + 测试 |
| 默认行为 | **建议默认 OFF**，保持现状 → 既有 2201 用例零回归 |

---

## 二、需求定性

要的不是「让 Agent 会规划」——项目早就会（V2.5.0 Planning System）。要的是**在计划与执行之间插一个人类闸门**：

```text
现状：  Goal → 规划 → validated →（同一函数内立刻）→ active → 调度执行
目标：  Goal → 规划 → validated →  ⏸ 等人工批准  → active → 调度执行
                                   ↘ 驳回 → rejected
```

本质差异：现状是**全自主**（计划一过结构闸就跑），目标引入**人在环**（human-in-the-loop）的**计划级**审批。注意它不同于已有的**工具级**确认（见 §3.2）。

---

## 三、现状盘点

### 3.1 已有且可直接复用

| 能力 | 落点 | 复用方式 |
|---|---|---|
| 计划状态机（五态） | `models/goal.py:29`、`repositories/goal_repository.py:23` | `validated` 直接当「待批准」 |
| 计划落库 / 版本链 / 修订链 | `repositories/goal_repository.py` 计划面四函数 | 原样用 |
| 列待批计划 | `goal_repository.list_plans_by_status(user_id, ("validated",))`（`:528`） | **已存在**，直接调 |
| 批准 / 驳回写面 | `goal_repository.set_plan_status`（`:487`）、`set_plan_rejection`（`:499`） | **已存在**，直接调 |
| 「停住即不执行」语义 | `goal_repository.list_active_plans`（`:512`）查询条件 `GoalPlanRow.status == "active"` | 停 `validated` 天然不被调度 |
| 批准后自动续跑 | Life Loop 每 tick 拉 `list_active_plans` 推进 | **无需额外触发**，改状态即续跑 |
| 审计留痕 | `decision_records`（`kind=goal_lifecycle`） | 复用，**不新增 kind**（新增需改 CHECK） |
| 确认流基础设施 | `services/tool/confirmation.py`（`trigger_registry` 零 DDL） | 可复用做「通知用户有待批」 |
| 只读调试端点体例 | `api/v1/debug/plans.py`（6 端点） | 新对外端点照此体例写 |

### 3.2 已有的「确认」≠ 本次要的「审批」

项目已有一套完整的**确认流**，但作用层级不同：

- `services/tool/confirmation.py::ConfirmationService` — **工具/动作级**确认。某工具按权限策略需要确认时，登记 `pending_confirmation`，等用户在对话里说「可以」→ `ConfirmationIntentDetector` 词表识别 → 放行**单次工具调用**。
- `services/planning/executor_bridge.py:130,502` — 计划步骤遇到 `pending_confirmation` 时，步骤记 `blocked`、留在 `in_progress`，等既有确认流。
- `models/plan.py:124-129` — `PLAN_STEP_BLOCKED_GATE_REASONS` 已含 `"pending_confirmation"`。

**缺口**：这套是**逐次、逐步、事后**的确认；没有「**整份计划**生成后、执行前**一次性**审批」的闸门。这正是 WorkBuddy Plan 模式的核心，也是本次要补的。

### 3.3 缺口清单

1. **计划级审批闸门**——`plan_goal()` 里 `validated → active` 之间没有「暂停」分支。
2. **对外 API**——只有 debug 只读面，无「列待批 / 批准 / 驳回」的正式端点（`api/v1/` 下无 plans 路由）。
3. **配置开关**——无 `plan_require_approval` 之类策略位。
4. **审批审计**——批准/驳回的归因行未落。
5. **前端**——`apps/frontend/src/features/` 无 plans 页面。
6. **通知与超时**——待批计划如何触达用户、超时怎么办，均未定义。

---

## 四、关键发现：为什么能「零迁移」

`services/goal/planning.py::plan_goal()` 第 466~481 行：

```python
plan = goal_repository.create_plan(GoalPlanRecord(..., status="validated", ...))
for existing in goal_repository.list_plans(goal_id):
    if existing.id != plan.id and existing.status == "active":
        goal_repository.set_plan_status(existing.id, "superseded")
goal_repository.set_plan_status(plan.id, "active")   # ← 就是这一行，把「待批准」变成了「立即执行」
```

- `validated` 与 `active` 是**同一函数内相邻两行**，`validated` 存活时间为零。
- 全仓无任何执行路径消费 `validated`（`list_active_plans` 只认 `active`）。
- `ck_goal_plans_status` CHECK 已允许 `validated`。

**推论**：把第 481 行改成「按开关决定是否立刻 `active`」，即可得到一个**不需要迁移、不需要新状态值**的审批停靠点。这是整个评估里成本最低、风险最小的路径。

---

## 五、改动落点（最小可用版）

| # | 文件 | 改动 | 量级 |
|---|---|---|---|
| 1 | `app/core/settings/plan.py` | 加策略位 `plan_require_approval: bool = False` | 1 行 |
| 2 | `app/services/goal/planning.py::plan_goal()` | 第 481 行改条件：开关 ON → 停在 `validated`；OFF → 维持现状 | ~5 行 |
| 3 | `app/services/goal/approval.py`（新） | 审批服务：`list_pending` / `approve` / `reject`，复用 `list_plans_by_status` + `set_plan_status` + `set_plan_rejection` | 新文件 ~80 行 |
| 4 | `app/api/v1/plans.py`（新） | 3 端点：`GET /plans/pending`、`POST /plans/{id}/approve`、`POST /plans/{id}/reject`，挂 `require_user` | 新文件 ~90 行 |
| 5 | `app/api/v1/router.py` | `include_router(plans.plans_router)` | 1 行 |
| 6 | `tests/v25/…`（新） | 闸门 ON/OFF 两态 + 批准续跑 + 驳回 + 幂等 | 新增 |

**为什么审批服务放 `services/goal/` 而不是 `services/planning/`**：
`services/planning/` 有**包模块数量负向断言**（`test_plan010_static_scan.py`，包清单固定 11 个文件），且 `PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS`（`goal_contract.py:197`）是 19 项白名单。在 `services/planning/` 新增模块会同时踩这两条。`services/goal/` 是 `plan_goal()` 所在域，放这里既同域又避开约束。

---

## 六、必须同步处理的冻结面与钉测

**好消息**：`services/goal/planning.py` **不在**任何冻结哈希面（`FROZEN_SOURCES` / `ZERO_DIFF_HASHES` 均未覆盖）。但仍需处理以下 v25 钉测：

| 测试 | 钉的是什么 | 处理 |
|---|---|---|
| `tests/v25/test_plan003_mount.py:175` | `assert plan.status == "active"`（规划后即 active） | **开关默认 OFF 即可不破**；补 OFF 态用例显式钉住 |
| `tests/v25/test_plan001_invariants.py:129` | `[plan.status for plan in plans] == ["active", "superseded"]` | 同上 |
| `tests/v25/test_plan010_evidence.py:206` | `plan_status_counts == {"active": 4}` | 同上 |
| `tests/v25/test_plan003_engine.py:198` | `outcome.plan.status == "validated"` | 已符合，无需改 |
| `tests/v25/test_plan010_static_scan.py:85` | 计划写面白名单恰为 4 函数 | 复用 `set_plan_status`/`set_plan_rejection`，**不新增写函数** |
| `tests/v25/test_plan010_listener.py:343` | 某模块禁含 `set_plan_status` | 新代码不得落在该模块 |
| `app/services/planning/goal_contract.py:197` | 19 项调用白名单 | 新代码若进 `services/planning/` 需同步；放 `services/goal/` 则无关 |

**风险排序**：最大风险是「默认 ON 导致既有钉测红」。**对策 = 默认 OFF**，把新行为变成显式开关，实现「零回归 + 可灰度」。

**另需注意**：新增设置字段无版本前缀（`plan_require_approval`，env = `PLAN_REQUIRE_APPROVAL`），符合 2026-09-19 收官后的命名约定。

---

## 七、待决策的三个设计点

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| D1 | 审批超时行为 | ①永久等待 ②超时自动批准 ③超时自动驳回（复用 `plan_ttl_hours`=168h） | **③自动驳回**：与「不确认即不执行」的安全默认一致 |
| D2 | 触达方式 | ①仅 API（前端轮询）②飞书消息推送 ③复用确认流 `trigger_registry` | **②+①**：飞书是当前已验证的真实通道（`feat/feishu_bot`） |
| D3 | 审批粒度 | ①整份计划一次性 ②按步骤逐条 | **①**：这才是 WorkBuddy Plan 模式；逐条审批等于放大版工具确认 |

---

## 八、工作量分级与建议路径

| 阶段 | 内容 | 量级 |
|---|---|---|
| **P0 最小可用** | §5 的 6 项（后端闸门 + 3 端点 + 测试），默认 OFF | **S**（约 1 个工作日量级） |
| **P1 可用性** | D1 超时策略 + D2 飞书触达 + 审批审计归因 | **M** |
| **P2 可观测** | 前端 plans 页面（列待批 / 批准 / 驳回 / 看步骤） | **M~L** |
| **P3 收敛** | 计划级 `pending_confirmation` 与工具级确认流语义统一 | **L**（可选，非必需） |

**建议路径**：先做 P0 并**默认 OFF** 验证零回归 → 再用开关灰度跑通 P1 → 前端 P2 视需要。

---

## 九、与既有决策的关系

- 与 T-32 / T-11 / T-13 的「评估后不采用」**不同**：那三者的前提均已被现状满足（属伪任务）；本需求的前提（计划级审批闸门）**今日确实不成立**，是真需求。
- 与 `plan_goal()` 现有语义**不冲突**：开关 OFF 时行为逐字节不变。
- **前置纪律**：按 `AGENTS.md`，任何架构演进须**先更新 `docs/current-system-architecture-baseline.md`** 再进入开发。P0 动工前应先补基线章节（Planning 域新增「计划审批闸门」扩展点）。

---

## 附：本次评估的核实证据（可复现）

```text
services/goal/planning.py:466-481      计划创建 validated 后立刻置 active
repositories/goal_repository.py:512     list_active_plans 过滤 status == "active"
repositories/goal_repository.py:528     list_plans_by_status（已存在）
repositories/goal_repository.py:487/499 set_plan_status / set_plan_rejection（已存在）
models/goal.py:29,100-106               GoalPlanStatus 五值 + CHECK
models/plan.py:124-129                  PLAN_STEP_BLOCKED_GATE_REASONS 含 pending_confirmation
services/tool/confirmation.py           工具级确认流（ConfirmationService）
services/planning/executor_bridge.py:130,502  pending_confirmation → 步骤 blocked
api/v1/debug/plans.py                   6 个只读调试端点（无对外写端点）
services/planning/goal_contract.py:197  19 项调用白名单
tests/v25/test_plan010_static_scan.py   包模块数量 + 写面白名单负向断言
```
