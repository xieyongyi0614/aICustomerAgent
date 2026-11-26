"""PLAN-005 Step 1：`PlanScheduler` 搬运等价性 + 就绪 / 阻塞 / 矩阵（Task Detail §9.1 U1~U5）。

口径：期望值写死为字面量或与**搬运源**（`goal_observation` 私有函数）逐条对照；
本模块是 Step 1 的出口条件——**未通过前不得进入执行桥接与观测推进**（§10.3「先搬后改可举证」）。
"""

from app.services.goal import observation as goal_observation
from app.services.planning import scheduler
from app.services.planning.scheduler import (
    BLOCKED_COOLDOWN,
    BLOCKED_OFF_SURFACE,
    BLOCKED_PREDECESSOR_FAILED,
    PlanScheduler,
)

from . import plan005_support as support

PLAN_ID = support.PLAN_ID


def _nested_plan():
    """深层嵌套 + `depends_on` DAG：1 为父步（子步 2 / 3），4 依赖 3。"""
    return support.plan(
        [
            support.spec(1, kind="composite"),
            support.spec(2, parent_index=1),
            support.spec(3, parent_index=1),
            support.spec(4, depends_on=[3]),
        ]
    )


def _dag_plan():
    """纯 DAG（无父子）：1 → 2 → 4、1 → 3 → 4。"""
    return support.plan(
        [
            support.spec(1),
            support.spec(2, depends_on=[1]),
            support.spec(3, depends_on=[1]),
            support.spec(4, depends_on=[2, 3]),
        ]
    )


def _status_matrix_plan():
    """状态混合：done / in_progress / pending / failed 各态齐备（覆盖四条谓词的分支）。"""
    return support.plan(
        [
            support.spec(1, status="done"),
            support.spec(2, depends_on=[1], status="in_progress"),
            support.spec(3, depends_on=[1], status="pending"),
            support.spec(4, status="failed"),
            support.spec(5, kind="composite"),
            support.spec(6, parent_index=5, status="pending"),
            support.spec(7, parent_index=5, status="done"),
        ]
    )


def _plans():
    return (_nested_plan(), _dag_plan(), _status_matrix_plan(), support.plan([]))


class TestCarryOverEquivalence:
    """U1：公开纯函数与 `goal_observation` 私有实现对同一 plan 输出**逐条一致**。"""

    def test_order_matches_execution_order_element_by_element(self):
        for plan in _plans():
            specs = list(plan.sub_goals)
            expected = goal_observation._execution_order(specs)  # pylint: disable=protected-access
            actual = PlanScheduler.order(plan)
            assert [spec.index for spec in actual] == [
                spec.index for spec in expected
            ]
            assert all(
                left is right for left, right in zip(actual, expected)
            ), "搬运版必须返回同一批步骤对象（逐条等价）"

    def test_order_keeps_the_leaf_first_semantics(self):
        plan = _nested_plan()
        assert [spec.index for spec in PlanScheduler.order(plan)] == [2, 3, 1, 4]
        assert PlanScheduler.order_indexes(plan) == [2, 3, 1, 4]

    def test_order_accepts_the_deferred_goal_argument(self):
        plan = _nested_plan()
        assert [
            spec.index for spec in PlanScheduler.order(plan, support.goal())
        ] == [2, 3, 1, 4]

    def test_current_step_matches_the_private_implementation(self):
        for plan in _plans():
            specs = list(plan.sub_goals)
            expected = goal_observation._current_step(specs)  # pylint: disable=protected-access
            actual = PlanScheduler.current_step(plan)
            assert (None if actual is None else actual.index) == (
                None if expected is None else expected.index
            )

    def test_all_done_matches_the_private_implementation(self):
        for plan in _plans():
            assert PlanScheduler.all_done(plan) == goal_observation._all_done(
                list(plan.sub_goals)
            )

    def test_has_executable_matches_the_private_implementation(self):
        for plan in _plans():
            assert PlanScheduler.has_executable(
                plan
            ) == goal_observation._has_executable(list(plan.sub_goals))

    def test_private_functions_are_still_in_place_for_one_version_window(self):
        for name in (
            "_execution_order",
            "_current_step",
            "_all_done",
            "_has_executable",
        ):
            assert callable(getattr(goal_observation, name))


class TestDeterminism:
    """U2 / D1：同输入同输出；叶子优先；结构序（`index` 升序）。"""

    def test_repeated_calls_are_identical(self):
        plan = _dag_plan()
        first = PlanScheduler.order_indexes(plan)
        second = PlanScheduler.order_indexes(plan)
        assert first == second == [1, 2, 3, 4]

    def test_ready_steps_are_sorted_by_structural_index(self):
        plan = support.plan(
            [
                support.spec(1, status="done"),
                support.spec(3, depends_on=[1]),
                support.spec(2, depends_on=[1]),
            ]
        )
        assert [spec.index for spec in PlanScheduler.ready_steps(plan)] == [2, 3]

    def test_ready_steps_exclude_composite_parents(self):
        plan = _nested_plan()
        assert [spec.index for spec in PlanScheduler.ready_steps(plan)] == [2, 3]


class TestReadySteps:
    """U3：前驱全 `done` 且自身未终态；前驱未完成时不在集内。"""

    def test_predecessor_must_be_done(self):
        plan = _dag_plan()
        assert [spec.index for spec in PlanScheduler.ready_steps(plan)] == [1]

    def test_in_progress_still_counts_as_ready(self):
        plan = _status_matrix_plan()
        ready = [spec.index for spec in PlanScheduler.ready_steps(plan)]
        assert ready == [2, 3, 6]

    def test_unmet_predecessor_keeps_the_step_out_of_the_ready_set(self):
        plan = support.plan(
            [
                support.spec(1, status="in_progress"),
                support.spec(2, depends_on=[1]),
            ]
        )
        assert [spec.index for spec in PlanScheduler.ready_steps(plan)] == [1]

    def test_done_and_failed_steps_never_enter_the_ready_set(self):
        plan = support.plan(
            [support.spec(1, status="done"), support.spec(2, status="failed")]
        )
        assert PlanScheduler.ready_steps(plan) == []


class TestBlockedReason:
    """U4：三类阻塞原因 + 有可执行步时为 `None`。"""

    def test_none_when_an_executable_step_exists(self):
        plan = support.plan([support.spec(1, tool_id=support.REMINDER_CREATE)])
        assert (
            PlanScheduler.blocked_reason(
                plan, support.ctx(support.REMINDER_CREATE)
            )
            is None
        )

    def test_off_surface_when_the_bound_tool_left_the_surface(self):
        plan = support.plan([support.spec(1, tool_id=support.CHANNEL_SEND)])
        assert (
            PlanScheduler.blocked_reason(plan, support.ctx(support.REMINDER_CREATE))
            == BLOCKED_OFF_SURFACE
        )

    def test_cooldown_when_the_ready_step_is_still_cooling(self):
        plan = support.plan(
            [
                support.spec(
                    1,
                    tool_id=support.REMINDER_CREATE,
                    last_attempt_at=support.last_attempt_at(1),
                )
            ]
        )
        assert (
            PlanScheduler.blocked_reason(
                plan, support.ctx(support.REMINDER_CREATE, cooldown=30)
            )
            == BLOCKED_COOLDOWN
        )

    def test_cooldown_expires_after_the_window(self):
        plan = support.plan(
            [
                support.spec(
                    1,
                    tool_id=support.REMINDER_CREATE,
                    last_attempt_at=support.last_attempt_at(31),
                )
            ]
        )
        assert (
            PlanScheduler.blocked_reason(
                plan, support.ctx(support.REMINDER_CREATE, cooldown=30)
            )
            is None
        )

    def test_predecessor_failed_when_nothing_is_ready_any_more(self):
        plan = support.plan(
            [
                support.spec(1, status="failed"),
                support.spec(2, depends_on=[1]),
            ]
        )
        assert (
            PlanScheduler.blocked_reason(plan, support.ctx())
            == BLOCKED_PREDECESSOR_FAILED
        )

    def test_continue_explicitly_relaxes_the_predecessor_failure(self):
        plan = support.plan(
            [
                support.spec(1, status="failed"),
                support.spec(2, depends_on=[1], on_failure="continue"),
            ]
        )
        assert PlanScheduler.blocked_reason(plan, support.ctx()) is None

    def test_no_surface_in_context_means_no_off_surface_judgement(self):
        plan = support.plan([support.spec(1, tool_id=support.CHANNEL_SEND)])
        assert PlanScheduler.blocked_reason(plan, support.bare_ctx()) is None

    def test_reason_value_set_is_the_declared_three(self):
        assert scheduler.BLOCKED_REASONS == (
            "off_surface",
            "cooldown",
            "predecessor_failed",
        )


class TestOnFailureMatrix:
    """U5：四值 × 后继矩阵逐条与 §4.3.2 一致。"""

    @staticmethod
    def _fan_out(mode: str):
        """1 失败 → 直接后继 2、旁支 3；4 依赖 3（用于分辨「直接后继」与「全部」）。"""
        return support.plan(
            [
                support.spec(1, on_failure=mode, status="failed"),
                support.spec(2, depends_on=[1]),
                support.spec(3),
                support.spec(4, depends_on=[3]),
            ]
        )

    def test_abort_fails_every_remaining_step(self):
        result = PlanScheduler.propagate_failure(self._fan_out("abort"), 1)
        assert result.mode == "abort"
        assert result.plan_failed is True
        assert result.failed_indexes == (2, 3, 4)
        assert [spec.status for spec in result.specs] == [
            "failed",
            "failed",
            "failed",
            "failed",
        ]

    def test_skip_fails_only_the_direct_successor(self):
        result = PlanScheduler.propagate_failure(self._fan_out("skip"), 1)
        assert result.mode == "skip"
        assert result.plan_failed is False
        assert result.failed_indexes == (2,)
        assert [spec.status for spec in result.specs] == [
            "failed",
            "failed",
            "pending",
            "pending",
        ]

    def test_replan_pauses_the_successors(self):
        result = PlanScheduler.propagate_failure(self._fan_out("replan"), 1)
        assert result.mode == "replan"
        assert result.paused is True
        assert result.plan_failed is False
        assert result.failed_indexes == ()
        assert [spec.status for spec in result.specs] == [
            "failed",
            "pending",
            "pending",
            "pending",
        ]

    def test_continue_relaxes_the_dependency_explicitly(self):
        result = PlanScheduler.propagate_failure(self._fan_out("continue"), 1)
        assert result.mode == "continue"
        assert result.relaxed is True
        assert result.failed_indexes == ()
        assert [spec.status for spec in result.specs] == [
            "failed",
            "pending",
            "pending",
            "pending",
        ]

    def test_matrix_does_not_mutate_the_source_steps(self):
        plan = self._fan_out("abort")
        PlanScheduler.propagate_failure(plan, 1)
        assert [spec.status for spec in plan.sub_goals] == [
            "failed",
            "pending",
            "pending",
            "pending",
        ]

    def test_propagation_notes_carry_the_origin(self):
        result = PlanScheduler.propagate_failure(self._fan_out("skip"), 1)
        note = next(spec for spec in result.specs if spec.index == 2).failure_note
        assert note == "前置步骤 1 失败（on_failure=skip）"

    def test_unknown_step_index_is_an_implementation_defect(self):
        plan = self._fan_out("skip")
        try:
            PlanScheduler.propagate_failure(plan, 99)
        except ValueError as exc:
            assert "99" in str(exc)
        else:  # pragma: no cover - 断言分支
            raise AssertionError("缺失步骤必须抛实现缺陷异常")


class TestPureFunctionDiscipline:
    """D3：零 IO / 零 LLM / 零 `get_settings()` 直调 + 公开面冻结。"""

    def test_module_calls_no_settings_or_repository(self):
        from pathlib import Path

        from . import _plan_scan as scan

        path = Path(scheduler.__file__)
        called = {
            node.func.id
            for node in scan.call_nodes(path)
            if hasattr(node.func, "id")
        }
        assert "get_settings" not in called
        assert not [
            module
            for module in scan.imported_modules(path)
            if module.startswith("app.repositories")
            or module.startswith("app.application")
        ]

    def test_public_surface_is_the_six_declared_functions(self):
        for name in (
            "order",
            "order_indexes",
            "ready_steps",
            "current_step",
            "all_done",
            "has_executable",
            "blocked_reason",
            "propagate_failure",
        ):
            assert callable(getattr(PlanScheduler, name)), name
