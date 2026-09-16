"""PLAN-011 Step 7 单测：Q10 记录与回归断言（§8 Step 7；§9.2 I1 / I12 / I13 / I14）。

- I1：`goal_repository` 既有九函数**零改动**（源码摘要冻结 + 签名冻结 + 行为抽查）。
- I12：`list_terminal_plans_since` 是 PLAN-010 证据窗的基础设施（只读、可复现、终态口径）。
- I13：零迁移断言（迁移链头 0046；两张表的 CHECK 值集未变；无新列 / 新索引）。
- I14：Flag 全 off 时端点不可见且 prompt 与 V2.4.0 逐字节一致。
- Q10：计划可观测面**不纳入** `apps/frontend/` 调试控制台（本版本不实现，推后续版本评估）。

Q10 记录（Step 7.1 的交付项，Task Detail §9.7 Q10）

| 项 | 结论 |
|---|---|
| 是否纳入前端调试控制台 | **否**——本版本只交付后端 6 个只读调试端点（`api/v1/debug.py`） |
| 依据 | 该子项即 architecture §9.2 中唯一的 P2 交付面（可延后）；前端控制台接入属新 UI 面，未在 PLAN-011 范围内 |
| 留痕方式 | 本模块文档 + `TestQ10FrontendIsNotImplemented` 的两条可判定断言（前端无计划视图、无 `/debug/plans` 调用） |
| 后续 | 推后续版本评估（与 architecture §9.2 的 P2 语义一致） |

`apps/frontend/` 现有 `features/world-sim`（V2.3.0 WS 面板）与 `components/debug/*` 等既有面，
本版本**不为计划域新增**任何前端模块或调用点。
"""

import hashlib
import inspect
import re
from pathlib import Path

import pytest

from app.core.db import DecisionRecordRow, GoalPlanRow
from app.models.observability import DecisionKind
from app.repositories import goal_repository
from app.services.planning import goal_contract

from . import plan011_support as support
from .test_plan001_flag_regression import FROZEN_PROMPT_DIGEST, _digest

PLAN_FACE_FUNCTIONS = (
    "create_plan",
    "get_plan",
    "get_latest_plan",
    "list_plans",
    "count_plans",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
    "list_active_plans",
)

FROZEN_PLAN_FACE_DIGEST = (
    "836a352c9e8587c469fdbe6904c1a483559fb9f1d4f5f8fe8e7238e77b7eea99"
)
"""既有九函数的源码摘要（PLAN-011 冻结值）：任何字节改动都会使本断言失败。

冻结口径：按上表顺序拼接 `inspect.getsource` 后取 sha256；摘要更新即「九函数被改动」的
显式留痕点（契约演进必须在此登记，不允许静默改动）。
"""

FROZEN_PLAN_FACE_SIGNATURES = {
    "create_plan": ("record",),
    "get_plan": ("plan_id",),
    "get_latest_plan": ("goal_id",),
    "list_plans": ("goal_id",),
    "count_plans": ("goal_id",),
    "set_plan_status": ("plan_id", "status"),
    "set_plan_rejection": ("plan_id", "reason"),
    "update_plan_progress": ("plan_id", "sub_goals"),
    "list_active_plans": ("user_id",),
}

MIGRATION_HEAD = "0047"

BACKEND_ROOT = Path(goal_repository.__file__).parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"

FRONTEND_SOURCE_PREFIXES = ("src", "e2e", "tests")

FORBIDDEN_FRONTEND_PLAN_REFERENCES = (
    "/debug/plans",
    "debug/plans",
    "PlanDebugPanel",
    "plan-observability",
)


class TestExistingNineFunctionsAreUntouched:
    """I1：既有九函数签名与行为零改动（差异对照为空）。"""

    def test_source_digest_is_frozen(self):
        payload = "\n\n".join(
            inspect.getsource(getattr(goal_repository, name))
            for name in PLAN_FACE_FUNCTIONS
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert digest == FROZEN_PLAN_FACE_DIGEST
        assert len(PLAN_FACE_FUNCTIONS) == 9

    def test_signatures_are_frozen(self):
        for name, declared in FROZEN_PLAN_FACE_SIGNATURES.items():
            parameters = inspect.signature(getattr(goal_repository, name)).parameters
            assert tuple(parameters) == declared, name
            assert all(
                parameter.default is inspect.Parameter.empty
                for parameter in parameters.values()
            ), name

    def test_new_read_extensions_are_added_without_touching_the_nine(
        self, db_session_factory, make_goal, make_plan
    ):
        goal = make_goal(user_id=support.USER, description="九函数行为抽查")
        plan = make_plan(goal.id)

        assert goal_repository.get_plan(plan.id).id == plan.id
        assert goal_repository.get_latest_plan(goal.id).version == plan.version
        assert [item.id for item in goal_repository.list_plans(goal.id)] == [plan.id]
        assert goal_repository.count_plans(goal.id) == 1
        assert goal_repository.count_plan_versions(goal.id) == 1
        assert goal_repository.set_plan_status(plan.id, "active").status == "active"
        rejected = goal_repository.set_plan_rejection(plan.id, "revision_exhausted")
        assert (rejected.status, rejected.rejection_reason) == (
            "rejected",
            "revision_exhausted",
        )
        assert goal_repository.list_active_plans(support.USER) == []
        goal_repository.set_plan_status(plan.id, "active")
        pairs = goal_repository.list_active_plans(support.USER)
        assert [(item.id, loaded.id) for item, loaded in pairs] == [(goal.id, plan.id)]
        from app.models.goal import GoalPlanRecord

        created = goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=2,
                status="active",
                created_at=support.NOW,
                updated_at=support.NOW,
            )
        )
        assert (created.goal_id, created.version) == (goal.id, 2)

    def test_whitelist_extension_is_recorded(self):
        allowed = goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS
        assert len(allowed) == 19
        assert allowed[16:] == (
            "list_plans_by_status",
            "count_plan_versions",
            "list_terminal_plans_since",
        )
        for name in ("expire_goal", "cancel_goal", "create_goal", "seed_goals"):
            assert name not in allowed
        assert goal_contract.PLANNING_WRITE_FUNCTION_NAMES == (
            "set_status",
            "finish_goal",
            "complete_goal",
            "fail_goal",
            "reactivate_goal",
        )


class TestZeroMigration:
    """I13：零迁移断言（迁移链头 + 两张表的 CHECK 值集 + 列集）。"""

    @staticmethod
    def _numbered_versions() -> list[int]:
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        return sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )

    def test_migration_chain_head_is_still_0047(self):
        numbered = self._numbered_versions()
        assert max(numbered) == 47
        assert f"{max(numbered):04d}" == MIGRATION_HEAD

    def test_goal_plans_status_check_keeps_its_five_values(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in GoalPlanRow.__table__.constraints
            if constraint.name == "ck_goal_plans_status"
        }
        assert list(checks) == ["ck_goal_plans_status"]
        for status in ("draft", "validated", "active", "rejected", "superseded"):
            assert status in checks["ck_goal_plans_status"]
        assert "completed" not in checks["ck_goal_plans_status"]
        assert goal_repository.PLAN_TERMINAL_STATUSES == ("rejected", "superseded")
        assert tuple(sorted(GoalPlanRow.__table__.c.keys())) == (
            "created_at",
            "goal_id",
            "id",
            "rejection_reason",
            "status",
            "sub_goals",
            "updated_at",
            "version",
        )
        assert {
            index.name for index in GoalPlanRow.__table__.indexes
        } == {"idx_goal_plans_goal_status"}

    def test_decision_records_kind_check_keeps_its_five_values(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in DecisionRecordRow.__table__.constraints
            if constraint.name == "ck_decision_records_kind"
        }
        assert list(checks) == ["ck_decision_records_kind"]
        for kind in DecisionKind:
            assert kind.value in checks["ck_decision_records_kind"]
        assert len(list(DecisionKind)) == 5
        assert {
            index.name for index in DecisionRecordRow.__table__.indexes
        } == {"idx_decision_records_action", "idx_decision_records_user_time"}


class TestTerminalPlansInfrastructure:
    """I12：`list_terminal_plans_since` 是计划证据窗的只读基础设施。"""

    def test_terminal_window_is_readable_and_reproducible(
        self, db_session_factory, make_goal, make_plan
    ):
        goal = make_goal(user_id=support.USER, description="证据窗基础设施")
        plan = make_plan(goal.id)
        goal_repository.set_plan_status(plan.id, "superseded")

        window = support.NOW.replace(year=support.NOW.year - 1)
        first = goal_repository.list_terminal_plans_since(support.USER, window)
        second = goal_repository.list_terminal_plans_since(support.USER, window)
        assert [row.id for row in first] == [row.id for row in second] == [plan.id]
        assert first[0].status in goal_repository.PLAN_TERMINAL_STATUSES

    def test_non_terminal_plans_are_never_in_the_window(
        self, db_session_factory, make_goal, make_plan
    ):
        goal = make_goal(user_id=support.USER, description="非终态不入窗")
        make_plan(goal.id)
        window = support.NOW.replace(year=support.NOW.year - 1)
        assert goal_repository.list_terminal_plans_since(support.USER, window) == []

    def test_plan_010_evidence_windows_remain_read_only(self):
        """I12 的调用点可追溯性说明（**偏差留痕**）。

        PLAN-010 在 PLAN-011 之前落地，其三个计划证据窗按 `list_active_plans` + `list_plans`
        取数（`reflection/evidence.py` 的两条只读投影），故今日**不存在**对
        `list_terminal_plans_since` 的调用点——本任务交付的是该窗口的**基础设施**（§5.5
        「消费方向为 PLAN-010 → 本任务交付的只读函数」）。为守住「零改动既有反射面」纪律，
        PLAN-011 不改 `reflection/evidence.py`（属 PLAN-010 的已落地语义），此处只断言：
        证据窗模块的取数面仍是只读仓储调用，未被本任务触碰。
        """
        from app.services.reflection import evidence as reflection_evidence

        source = Path(reflection_evidence.__file__).read_text(encoding="utf-8")
        assert "list_terminal_plans_since" not in source.split("def aggregate", 1)[0]
        assert "goal_repository.list_active_plans" in source
        assert "def aggregate_plan_success_rate" in source


class TestFlagOffRegression:
    """I14：Flag 全 off 时端点不可见、prompt 逐字节一致。"""

    @pytest.mark.asyncio
    async def test_flag_off_keeps_every_plan_endpoint_invisible(
        self, db_session_factory, make_goal, make_plan
    ):
        goal = make_goal(user_id=support.USER, description="Flag off 不可见")
        plan = make_plan(goal.id)
        calls = (
            (support.plan_url(""), {"user_id": support.USER}),
            (support.plan_url(f"/{plan.id}"), {}),
            (support.plan_url(f"/{plan.id}/steps"), {}),
            (support.plan_url("/context"), {"user_id": support.USER, "goal_id": goal.id}),
            (support.plan_url("/revisions"), {"goal_id": goal.id}),
            (support.plan_url("/pending"), {"user_id": support.USER}),
        )
        for path, params in calls:
            response = await support.plan_get(path, **params)
            assert response.status_code == 404, path
            assert response.json()["detail"].startswith("计划调试面未启用")

    def test_planning_prompt_is_byte_identical(
        self, stub_planning_llm, make_goal, autonomy_on
    ):
        """Flag 全 off 的规划 prompt 与 V2.4.0 逐字节一致（摘要冻结，同 PLAN-001 口径）。"""
        assert autonomy_on
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        from app.services import goal_planning

        goal = make_goal(description="prompt 快照目标", priority=4, domain="relationship")
        assert goal_planning.plan_goal(
            goal.id, goal_planning.TRIGGER_CREATED
        )["status"] == "ok"
        assert [pair[0] for pair in recorder["messages"]] == ["system", "human"]
        assert _digest(recorder["messages"]) == FROZEN_PROMPT_DIGEST


class TestQ10FrontendIsNotImplemented:
    """Q10：计划可观测面不纳入前端调试控制台（本版本不实现）。"""

    def test_frontend_has_no_plan_view(self):
        offenders = [
            path.as_posix()
            for path in FRONTEND_ROOT.rglob("*")
            if path.is_file()
            and any(part in FRONTEND_SOURCE_PREFIXES for part in path.parts)
            and "node_modules" not in path.parts
            and "plan" in path.name.lower()
            and path.suffix in {".ts", ".tsx"}
        ]
        assert offenders == []

    def test_frontend_never_calls_the_plan_debug_surface(self):
        hits: list[str] = []
        for path in FRONTEND_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
                continue
            if "node_modules" in path.parts or "dist" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in FORBIDDEN_FRONTEND_PLAN_REFERENCES):
                hits.append(path.as_posix())
        assert hits == []

    def test_backend_debug_surface_is_the_only_plan_observability_face(self):
        from app.api.v1 import debug as debug_api

        assert FRONTEND_ROOT.is_dir()
        assert FRONTEND_ROOT.joinpath("src", "features", "world-sim").is_dir()
        assert not FRONTEND_ROOT.joinpath("src", "features", "plans").exists()
        assert debug_api.PLAN_SOURCE_NAMES == (
            "goal",
            "context",
            "world",
            "memory",
            "reflection",
            "tool_surface",
        )
