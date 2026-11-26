"""PLAN-011 Step 1 单测：`goal_repository` 三个只读扩展（§6.1 U2~U5）。

- U2 `list_plans_by_status`：状态过滤正确；`statuses` 越出 `PLAN_STATUS_VALUES` 即拒。
- U3 `count_plan_versions`：版本数正确（含 `superseded` / `rejected`）。
- U4 `list_terminal_plans_since`：只返回终态；`since` 边界正确。
- U5 三函数零写库：会话级写探针（零 `add` / `commit` / `delete` / `merge` / `flush`）。

零迁移口径：终态 = `rejected` / `superseded`（`ck_goal_plans_status` 五值中的两个）。
计划级**没有** `completed`：该值不在 `GoalPlanStatus` / CHECK 内，加值需迁移（红线）。
"""

from datetime import timedelta

import pytest

from app.models.goal import PLAN_STATUS_VALUES, GoalPlanRecord, SubGoalSpec
from app.repositories import goal_repository

from . import plan011_support as support


def _plan(goal_id: str, version: int, status: str, *, step_count: int = 1) -> GoalPlanRecord:
    return goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=[
                SubGoalSpec.model_validate(support.step_spec(index))
                for index in range(1, step_count + 1)
            ],
            created_at=support.NOW,
            updated_at=support.NOW,
        )
    )


class TestStatusValueContract:
    """D3：`statuses` 取值 ⊆ `PLAN_STATUS_VALUES`（五值，零新增值）。"""

    def test_status_value_set_is_still_five(self):
        assert PLAN_STATUS_VALUES == (
            "draft",
            "validated",
            "active",
            "rejected",
            "superseded",
        )
        assert goal_repository.PLAN_TERMINAL_STATUSES == ("rejected", "superseded")
        assert set(goal_repository.PLAN_TERMINAL_STATUSES) <= set(PLAN_STATUS_VALUES)

    def test_illegal_status_is_rejected(self, db_session_factory, make_goal):
        goal = make_goal(user_id=support.USER, description="非法状态")
        _plan(goal.id, 1, "active")
        for statuses in (("completed",), ("active", "bogus"), ("Done",)):
            with pytest.raises(ValueError):
                goal_repository.list_plans_by_status(support.USER, statuses)

    def test_empty_status_set_returns_empty_without_query(self, db_session_factory, make_goal):
        goal = make_goal(user_id=support.USER, description="空状态集")
        _plan(goal.id, 1, "active")
        assert goal_repository.list_plans_by_status(support.USER, ()) == []


class TestListPlansByStatus:
    """U2：按状态批量取计划（`goal_plans` 无 `user_id` 列，归属经 `character_goals`）。"""

    def test_filters_by_status_and_user(self, db_session_factory, make_goal):
        mine = make_goal(user_id=support.USER, description="我的目标")
        theirs = make_goal(user_id=support.OTHER_USER, description="别人的目标")
        _plan(mine.id, 1, "active")
        _plan(mine.id, 2, "superseded")
        _plan(mine.id, 3, "rejected")
        _plan(theirs.id, 1, "active")

        active = goal_repository.list_plans_by_status(support.USER, ("active",))
        assert [(plan.goal_id, plan.version, plan.status) for plan in active] == [
            (mine.id, 1, "active")
        ]
        terminal = goal_repository.list_plans_by_status(
            support.USER, goal_repository.PLAN_TERMINAL_STATUSES
        )
        assert {plan.status for plan in terminal} == {"superseded", "rejected"}
        assert {plan.goal_id for plan in terminal} == {mine.id}
        assert len(
            goal_repository.list_plans_by_status(support.USER, PLAN_STATUS_VALUES)
        ) == 3
        assert goal_repository.list_plans_by_status(support.OTHER_USER, ("active",)) != []
        assert [
            plan.goal_id
            for plan in goal_repository.list_plans_by_status(
                support.OTHER_USER, ("active",)
            )
        ] == [theirs.id]

    def test_unknown_user_returns_empty(self, db_session_factory):
        assert goal_repository.list_plans_by_status("plan11-nobody", PLAN_STATUS_VALUES) == []


class TestCountPlanVersions:
    """U3：版本链长度（`rejected` / `superseded` 一并计入）。"""

    def test_counts_every_version_row(self, db_session_factory, make_goal):
        goal = make_goal(user_id=support.USER, description="版本链")
        assert goal_repository.count_plan_versions(goal.id) == 0
        _plan(goal.id, 1, "superseded")
        _plan(goal.id, 2, "rejected")
        _plan(goal.id, 3, "active")
        assert goal_repository.count_plan_versions(goal.id) == 3
        assert goal_repository.count_plan_versions(goal.id) == goal_repository.count_plans(
            goal.id
        )

    def test_unknown_goal_returns_zero(self, db_session_factory):
        assert goal_repository.count_plan_versions("plan11-no-goal") == 0


class TestListTerminalPlansSince:
    """U4 / D4：只返回终态（`rejected` / `superseded`），`since` 按 `updated_at` 含边界。"""

    def test_returns_terminal_plans_of_the_user_only(self, db_session_factory, make_goal):
        mine = make_goal(user_id=support.USER, description="终态窗口")
        theirs = make_goal(user_id=support.OTHER_USER, description="终态窗口-他人")
        _plan(mine.id, 1, "superseded")
        _plan(mine.id, 2, "active")
        _plan(mine.id, 3, "validated")
        _plan(theirs.id, 1, "rejected")

        window = support.NOW - timedelta(hours=1)
        terminal = goal_repository.list_terminal_plans_since(support.USER, window)
        assert [plan.status for plan in terminal] == ["superseded"]
        assert {plan.goal_id for plan in terminal} == {mine.id}
        assert goal_repository.list_terminal_plans_since(support.OTHER_USER, window)

    def test_since_boundary_is_inclusive(self, db_session_factory, make_goal):
        goal = make_goal(user_id=support.USER, description="窗口边界")
        plan = _plan(goal.id, 1, "active")
        goal_repository.set_plan_status(plan.id, "rejected")
        written = goal_repository.get_plan(plan.id).updated_at

        assert goal_repository.list_terminal_plans_since(support.USER, written)
        assert (
            goal_repository.list_terminal_plans_since(
                support.USER, written + timedelta(seconds=1)
            )
            == []
        )


class TestZeroWriteDiscipline:
    """U5 / D2：三个只读扩展**零写库**（会话级探针记录全部写方法调用名）。"""

    def test_three_read_functions_never_write(
        self, db_session_factory, make_goal, monkeypatch
    ):
        goal = make_goal(user_id=support.USER, description="只读探针")
        plan = _plan(goal.id, 1, "active")
        goal_repository.set_plan_status(plan.id, "rejected")
        probes = support.readonly_sessions(monkeypatch, goal_repository, db_session_factory)

        listed = goal_repository.list_plans_by_status(support.USER, PLAN_STATUS_VALUES)
        versions = goal_repository.count_plan_versions(goal.id)
        terminal = goal_repository.list_terminal_plans_since(
            support.USER, support.NOW - timedelta(days=1)
        )

        assert len(listed) == 1 and versions == 1 and len(terminal) == 1
        assert probes
        assert [probe.writes for probe in probes] == [[] for _ in probes]
