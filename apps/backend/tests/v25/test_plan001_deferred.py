"""PLAN-001 deferred 断言台账：依赖后续任务产物的断言，本任务**不编造实现**。

Task Detail §8 Step 5.2 引用了 PLAN-005 的 `PlanScheduler.order`、§9.2 I4 引用了
`PlanObserver.settle` 把计划置 `superseded` 的形态；这些产物在 PLAN-001 阶段不存在，
因此本模块用 `pytest.mark.skip` 显式登记「待某任务落地」的断言，并写明未来的判定方式
与依据（而非留空或伪造通过）。落地时去掉对应 `skip` 标记，断言代码即成为该任务证据。

已核对差异台账（Task Detail ↔ 真实源码，均已按源码冻结并在用例中断言）：

1. §6.2 写面表列的 `finish_goal(goal_id, status, failure_reason=None, arbitration_state=None)`
   多了一个 `arbitration_state`：真实签名只到 `failure_reason`（`arbitration_state` 仅
   `set_status` 有）。本任务按源码冻结，**不新增参数**（见 `test_plan001_goal_contract.py`
   的 `test_goal_repository_state_write_face_signatures_are_frozen`）。
2. §4.3.1 / §6.5 称非法迁移抛 `IllegalGoalTransition`：真实写面抛的是 `ValueError` 本身
   （`IllegalGoalTransition` 是 `ValueError` 子类但从未被 `goal_repository` 抛出）。本任务按
   「可观察契约 = `ValueError`」冻结，并断言子类关系，使两种写法都兼容。
3. §4.4 I2 的「计划同时进终态（`superseded`）」形态今日不成立（既有 `_complete` 只改目标状态）；
   今日成立的是「冻结」形态——目标终态即退出推进候选集（断言见
   `test_plan001_invariants.py::test_i2_terminal_goal_stops_advancing_its_plan`）。
4. §7 称 `GoalRecord` 20 个字段、`GoalPlanRow` 8 个列：真实为 19 个字段（列数与 8 一致）。
5. §10.3 的白名单为 §6.1 ∪ §6.2（12 项），不含计划面四函数（`create_plan` /
   `set_plan_status` / `set_plan_rejection` / `update_plan_progress`）；PLAN-003 落地时已
   **显式扩白名单**（12 → 16），见 `test_plan_face_writes_are_whitelisted_after_plan_003`
   与 `goal_contract` 模块文档 §9。

PLAN-003 落地时的改动仅限本模块的「待落地」清单与对应断言翻转为「已落地」：`context` /
`engine` 移出 `PLANNING_MODULES_FOR_LATER_TASKS`，白名单断言去 `skip`；PLAN-004 ~ PLAN-011
的产物仍保持「今日不存在」。

PLAN-004 落地时按同一纪律改动：`decompose` 移出「待落地」清单并进 `PLAN_004_LANDED_MODULES`；
PLAN-005 的五个模块（`scheduler` / `executor_bridge` / `observer` / `revision` /
`revision_listener`）**仍在「待落地」清单内**——拆解不调度、不执行、不观测、不修订。

PLAN-005 落地时按同一纪律改动本模块：

1. `scheduler` / `executor_bridge` / `observer` / `revision` 四者移出「待落地」清单并进
   `PLAN_005_LANDED_MODULES`；`revision_listener` **留在「待落地」清单**（PLAN-010 的反思接线，
   本任务只定义 `insight_driven` 理由码与判定入口，见 Task Detail §5.5 边界）。
2. 两条 PLAN-005 归属的 deferred 断言处理如下（**不编造实现**原则不变）：
   - `test_deferred_structural_order_via_plan_scheduler`：**去 `skip`**，`PlanScheduler.order`
     已落地（本任务 Step 1 的搬运出口）；该断言按 `order(plan, goal)` 调用，本实现的签名是
     `order(plan, goal=None)`——第二形参是这条 deferred 断言的既有调用形态，冻结接口
     `order(plan)` 仍成立（§8.4 的单参调用不变）。
   - `test_deferred_goal_terminal_moves_latest_plan_out_of_active`：**保持 `skip`** 并更新理由。
     它要求 `goal_observation.advance_goal` 在目标转终态时把最新计划置 `superseded`（§4.4 I2 的
     「进终态」形态）。PLAN-005 的实现选择是 I2 的**另一种允许形态**——「冻结」：`settle` 只做
     `GoalStatus` 的唯一写面迁移与归因，不改计划状态；且**目标终态一旦成立，其计划即刻退出
     推进候选集**（`list_active_plans` 的查询条件含 `GoalRow.status == "active"`）。把计划置
     `superseded` 需要改动既有 `_complete`（既有运行时语义），属本任务红线外，故不在本任务落。
"""

import importlib

import pytest

from app.repositories import goal_repository
from app.services import goal_observation
from app.services.planning import goal_contract

from .conftest import V25_NOW, V25_USER

PLANNING_MODULES_FOR_LATER_TASKS = (
    "app.services.planning.revision_listener",
)

PLAN_003_LANDED_MODULES = (
    "app.services.planning.context",
    "app.services.planning.engine",
)

PLAN_004_LANDED_MODULES = ("app.services.planning.decompose",)

PLAN_005_LANDED_MODULES = (
    "app.services.planning.scheduler",
    "app.services.planning.executor_bridge",
    "app.services.planning.observer",
    "app.services.planning.revision",
)


def _import_later_module(module_path: str):
    return importlib.import_module(module_path)


def test_deferred_targets_are_absent_today():
    for module_path in PLANNING_MODULES_FOR_LATER_TASKS:
        with pytest.raises(ImportError):
            _import_later_module(module_path)
    assert goal_repository.list_active_plans(V25_USER) == []


def test_plan_003_modules_are_landed():
    for module_path in PLAN_003_LANDED_MODULES:
        assert _import_later_module(module_path) is not None


def test_plan_004_decompose_module_is_landed():
    assert _import_later_module("app.services.planning.decompose") is not None


def test_plan_005_execution_modules_are_landed():
    for module_path in PLAN_005_LANDED_MODULES:
        assert _import_later_module(module_path) is not None


def test_deferred_structural_order_via_plan_scheduler(make_goal, make_plan, make_spec):
    scheduler = _import_later_module("app.services.planning.scheduler")
    goal = make_goal(description="结构序目标", priority=5, domain="world")
    plan = make_plan(
        goal.id,
        [
            make_spec(index=1, capability="query_environment"),
            make_spec(index=2, depends_on=[1]),
        ],
    )
    indexes = [spec.index for spec in scheduler.PlanScheduler.order(plan, goal)]
    assert indexes.index(1) < indexes.index(2)


@pytest.mark.skip(
    reason=(
        "待 PLAN-010 或专项任务：把计划置 superseded 需改动既有 `_complete` 运行时语义；"
        "PLAN-005 采用 I2 的「冻结」形态（目标终态即退出推进候选集），settle 不改计划状态"
    )
)
def test_deferred_goal_terminal_moves_latest_plan_out_of_active(
    make_goal, make_plan, goal_facts
):
    goal = make_goal(description="终态结算目标")
    plan = make_plan(goal.id)
    goal_observation.advance_goal(
        goal, plan, goal_facts(succeeded=["create_reminder"]), V25_NOW
    )
    assert goal_repository.get_goal(goal.id).status == "completed"
    assert goal_repository.get_latest_plan(goal.id).status == "superseded"


def test_plan_face_writes_are_whitelisted_after_plan_003():
    """PLAN-003 契约演进（原 deferred，现落地）：计划面四函数进入调用白名单。"""
    plan_face_writes = (
        "create_plan",
        "set_plan_status",
        "set_plan_rejection",
        "update_plan_progress",
    )
    assert [
        name
        for name in plan_face_writes
        if name not in goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS
    ] == []
    assert len(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS) == 16
    assert goal_contract.PLANNING_WRITE_FUNCTION_NAMES == (
        "set_status",
        "finish_goal",
        "complete_goal",
        "fail_goal",
        "reactivate_goal",
    )


@pytest.mark.skip(reason="待 PLAN-006 落地：G-EXEC 执行唯一入口断言")
def test_deferred_execution_single_entry_point():
    bridge = _import_later_module("app.services.planning.executor_bridge")
    assert bridge.PlanExecutorBridge is not None
    assert "ToolExecutor" not in dir(bridge)


@pytest.mark.skip(reason="待 PLAN-010 落地：PlanningRevisionListener 唯一反思接线")
def test_deferred_reflection_listener_registration():
    listener = _import_later_module("app.services.planning.revision_listener")
    assert listener.PlanningRevisionListener is not None
