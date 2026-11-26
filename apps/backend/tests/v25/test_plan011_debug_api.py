"""PLAN-011 Step 5 单测：管理面 6 端点（§4.2.6 / §6.3 D8~D13；§9.1 U6~U8）。

- D8 / I9 语义反转（v25 去门控）：端点不再有 Flag 门控（两闸已删），恒可见；D9 只读纪律不变。
- D9 / I10：六端点全部只读（会话级写探针零写）。
- D10：投影只读四张既有表（`goal_plans` / `action_records` / `decision_records` / `loop_runs`）。
- D11：上下文投影含**六源**与 `degraded` 清单。
- D12：步骤视图含 `tool_id` 绑定与 `blocked_reason`。
- D13 / U8：不回显记忆正文（只计数与 id）。

「端点不可见」的落地形态：路由在 `debug_router` 上**静态注册**（FastAPI 无法按 Flag 摘除路由），
故 Flag off 时以 **404** 兑现「未注册 / 不可见」语义（§6.5）；六个输出模型按 §6.3 字段契约不含
`enabled`，与既有面板的 `{"enabled": false}` 形态由此分野。
"""

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.api.v1.debug import plans as debug_api
from app.api.v1.debug import tools as debug_tools
from app.api.v1.schemas import (
    PlanContextOut,
    PlanDetailOut,
    PlanPendingOut,
    PlanPendingRowOut,
    PlanRevisionRowOut,
    PlanRevisionsOut,
    PlansOut,
    PlanStepRowOut,
    PlanStepsOut,
    PlanSummaryOut,
)
from app.core.settings import get_settings
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import (
    action_repository,
    decision_repository,
    goal_repository,
    loop_run_repository,
)
from app.services.life import budget as life_loop_budget
from app.services.planning import observer as plan_observer
from app.services.planning import scheduler as plan_scheduler
from app.services.tool import registry as tool_registry_module

from . import plan011_support as support

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _auth_override():
    """调试面自身份收口（v5.0.0 §14）起一律经 `require_user`。

    本模块经 `plan011_support` 走真实路由，但模块源码不含 `app.main` 字面量，
    命中不了 `tests/conftest.py::_mark_app_based` 的自动识别，故就地显式装 override。
    """
    from app.api.v1 import auth as auth_api
    from app.main import app as server_app

    server_app.dependency_overrides[auth_api.require_user] = lambda: support.USER
    yield
    server_app.dependency_overrides.pop(auth_api.require_user, None)


@pytest.fixture
def plan_panel_on(override_settings, monkeypatch):
    monkeypatch.setattr(tool_registry_module, "_registry", None)
    override_settings()
    life_loop_budget.reset_cache()
    return True


@pytest.fixture
def plan_panel_tools_on(plan_panel_on, override_settings):
    override_settings(
        plan_tool_required="true",
    )
    return True


@pytest.fixture
def persisted_audit(monkeypatch):
    support.persist_decisions(monkeypatch)
    return decision_repository


def _plan(goal_id: str, version: int, status: str, specs: list[dict] | None = None):
    payload = specs if specs is not None else [support.step_spec(1)]
    return goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=[SubGoalSpec.model_validate(item) for item in payload],
            created_at=support.NOW,
            updated_at=support.NOW,
        )
    )


class TestGating:
    """D8 / I9 语义反转（v25 去门控）：门控已删，六端点恒可见（仍全只读）。"""

    @staticmethod
    async def _probe_all(goal_id: str, plan_id: str) -> list[tuple[str, int]]:
        calls = (
            (support.plan_url(""), {"user_id": support.USER}),
            (support.plan_url(f"/{plan_id}"), {}),
            (support.plan_url(f"/{plan_id}/steps"), {}),
            (support.plan_url("/context"), {"user_id": support.USER, "goal_id": goal_id}),
            (support.plan_url("/revisions"), {"goal_id": goal_id}),
            (support.plan_url("/pending"), {"user_id": support.USER}),
        )
        return [
            (path, (await support.plan_get(path, **params)).status_code)
            for path, params in calls
        ]

    @pytest.mark.asyncio
    async def test_panel_is_always_served(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="面板常开")
        plan = _plan(goal.id, 1, "active")
        for path, status in await self._probe_all(goal.id, plan.id):
            assert status == 200, path


class TestPlansListEndpoint:
    """`/debug/plans`：版本链与状态；状态过滤取值越界 → 400。"""

    @pytest.mark.asyncio
    async def test_lists_the_version_chain_of_the_user(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="版本链清单")
        _plan(goal.id, 1, "superseded")
        _plan(goal.id, 2, "active")
        _plan(goal.id, 3, "rejected")

        response = await support.plan_get(support.plan_url(""), user_id=support.USER)
        body = response.json()
        assert response.status_code == 200
        assert {row["version"] for row in body["plans"]} == {1, 2, 3}
        assert {row["plan_id"] for row in body["plans"]} == {
            plan.id for plan in goal_repository.list_plans(goal.id)
        }
        assert all(row["goal_id"] == goal.id for row in body["plans"])
        assert all(row["step_count"] == 1 for row in body["plans"])
        assert all(row["updated_at"] for row in body["plans"])

    @pytest.mark.asyncio
    async def test_status_filter_and_illegal_value(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="状态过滤")
        _plan(goal.id, 1, "superseded")
        _plan(goal.id, 2, "active")

        filtered = await support.plan_get(
            support.plan_url(""), user_id=support.USER, status="active"
        )
        assert [row["status"] for row in filtered.json()["plans"]] == ["active"]

        illegal = await support.plan_get(
            support.plan_url(""), user_id=support.USER, status="completed"
        )
        assert illegal.status_code == 400
        assert "计划状态取值非法" in illegal.json()["detail"]

    @pytest.mark.asyncio
    async def test_unknown_user_returns_empty_list(self, db_session_factory, plan_panel_on):
        response = await support.plan_get(
            support.plan_url(""), user_id="plan11-nobody"
        )
        assert response.json() == {"plans": []}


class TestPlanDetailEndpoint:
    """`/debug/plans/{plan_id}`：本体 + 步骤 + 绑定 + 判据 + 推进历史；未找到 → 404。"""

    @pytest.mark.asyncio
    async def test_detail_projects_steps_bindings_criteria_and_history(
        self, db_session_factory, make_goal, plan_panel_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="计划详情")
        specs = [
            support.step_spec(
                1,
                tool_id=support.REMINDER_CREATE,
                binding_reason="capability_map",
                observation_keys=("temperature",),
                expected_effects=("external",),
            ),
            support.step_spec(2, depends_on=[1], status="done"),
        ]
        plan = _plan(goal.id, 1, "active", specs)
        plan_observer.record_plan_advance(
            support.advance(
                goal.id, plan.id, decision="advanced", step_index=1, at=support.NOW
            )
        )
        plan_observer.record_plan_advance(
            support.advance(
                goal.id,
                plan.id,
                decision="hold",
                reason="plan_step_hold",
                step_index=2,
                at=support.NOW + timedelta(minutes=5),
            )
        )

        response = await support.plan_get(support.plan_url(f"/{plan.id}"))
        body = response.json()
        assert response.status_code == 200
        assert body["plan"]["plan_id"] == plan.id
        assert body["plan"]["status"] == "active"
        assert [row["index"] for row in body["steps"]] == [1, 2]
        assert body["bindings"][0]["tool_id"] == support.REMINDER_CREATE
        assert body["bindings"][0]["binding_reason"] == "capability_map"
        assert body["criteria"][0]["observation_keys"] == ["temperature"]
        assert body["criteria"][0]["expected_effects"] == ["external"]
        assert [row["decision"] for row in body["advance_history"]] == [
            "advanced",
            "hold",
        ]

    @pytest.mark.asyncio
    async def test_unknown_plan_returns_404(self, db_session_factory, plan_panel_on):
        response = await support.plan_get(support.plan_url("/plan11-no-plan"))
        assert response.status_code == 404
        assert response.json()["detail"] == "计划不存在"


class TestPlanStepsEndpoint:
    """D12：步骤视图含 `tool_id` 绑定与 `blocked_reason`。"""

    @pytest.mark.asyncio
    async def test_steps_expose_binding_and_cooldown(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="步骤视图冷却")
        plan = _plan(
            goal.id,
            1,
            "active",
            [
                support.step_spec(
                    1,
                    tool_id=None,
                    last_attempt_at=timeutil.now(),
                    binding_reason="fallback",
                )
            ],
        )

        body = (await support.plan_get(support.plan_url(f"/{plan.id}/steps"))).json()
        assert body["steps"] == [
            {
                "index": 1,
                "description": "步骤1",
                "kind": "tool",
                "tool_id": None,
                "binding_reason": "fallback",
                "status": "pending",
                "attempt_count": 0,
                "blocked_reason": "cooldown",
            }
        ]

    @pytest.mark.asyncio
    async def test_steps_expose_off_surface(
        self, db_session_factory, make_goal, plan_panel_tools_on
    ):
        goal = make_goal(user_id=support.USER, description="步骤视图无面")
        plan = _plan(
            goal.id,
            1,
            "active",
            [support.step_spec(1, tool_id=support.OFF_SURFACE_TOOL)],
        )

        body = (await support.plan_get(support.plan_url(f"/{plan.id}/steps"))).json()
        assert body["steps"][0]["tool_id"] == support.OFF_SURFACE_TOOL
        assert body["steps"][0]["blocked_reason"] == "off_surface"

    @pytest.mark.asyncio
    async def test_steps_expose_predecessor_failed(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="步骤视图前置失败")
        plan = _plan(
            goal.id,
            1,
            "active",
            [
                support.step_spec(1, status="failed"),
                support.step_spec(2, depends_on=[1]),
            ],
        )

        rows = (await support.plan_get(support.plan_url(f"/{plan.id}/steps"))).json()[
            "steps"
        ]
        assert [row["blocked_reason"] for row in rows] == [None, "predecessor_failed"]


class TestPlanContextEndpoint:
    """D11：上下文投影含六源与 `degraded`；硬依赖缺失 → 降级结构；未找到 → 404。"""

    @pytest.mark.asyncio
    async def test_six_sources_with_degraded_list(
        self, db_session_factory, make_goal, plan_panel_tools_on
    ):
        goal = make_goal(user_id=support.USER, description="六源装配")

        response = await support.plan_get(
            support.plan_url("/context"),
            user_id=support.USER,
            goal_id=goal.id,
        )
        body = response.json()
        assert response.status_code == 200
        assert tuple(body["sources"]) == debug_api.PLAN_SOURCE_NAMES
        assert "world_disabled" in body["degraded"]

    @pytest.mark.asyncio
    async def test_unknown_or_mismatched_goal_returns_404(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="归属不符")
        assert (
            await support.plan_get(
                support.plan_url("/context"),
                user_id=support.USER,
                goal_id="plan11-no-goal",
            )
        ).status_code == 404
        assert (
            await support.plan_get(
                support.plan_url("/context"),
                user_id=support.OTHER_USER,
                goal_id=goal.id,
            )
        ).status_code == 404


class TestPlanRevisionsEndpoint:
    """修订链端点：`goal_id` 过滤 + 未找到 → 404。"""

    @pytest.mark.asyncio
    async def test_chain_is_served_over_http(
        self, db_session_factory, make_goal, plan_panel_on, persisted_audit
    ):
        goal = make_goal(user_id=support.USER, description="修订链 HTTP")
        _plan(goal.id, 1, "superseded")
        plan_2 = _plan(goal.id, 2, "active")
        plan_observer.record_plan_revision(
            support.revision(1, 2, evidence_refs=["insight-1"], kept_steps=[1]),
            plan=plan_2,
        )

        body = (
            await support.plan_get(support.plan_url("/revisions"), goal_id=goal.id)
        ).json()
        assert body["revisions"] == [
            {
                "from_version": 1,
                "to_version": 2,
                "reason": "step_attempt_exhausted",
                "trigger_source": "step_attempt_exhausted",
                "evidence_refs": ["insight-1"],
                "kept_steps": [1],
                "at": support.NOW.isoformat(),
            }
        ]

    @pytest.mark.asyncio
    async def test_unknown_goal_returns_404(self, db_session_factory, plan_panel_on):
        response = await support.plan_get(
            support.plan_url("/revisions"), goal_id="plan11-no-goal"
        )
        assert response.status_code == 404


class TestPlanPendingEndpoint:
    """§4.2.6 #6：待推进步骤（`off_surface` / 冷却中 / 前置失败）。"""

    @pytest.mark.asyncio
    async def test_pending_reports_cooldown(
        self, db_session_factory, make_goal, plan_panel_on, make_plan
    ):
        goal = make_goal(user_id=support.USER, description="待推进冷却")
        plan = _plan(
            goal.id,
            1,
            "active",
            [support.step_spec(1, last_attempt_at=timeutil.now())],
        )

        body = (await support.plan_get(support.plan_url("/pending"), user_id=support.USER)).json()
        assert body["pending"] == [
            {
                "goal_id": goal.id,
                "plan_id": plan.id,
                "step_index": 1,
                "tool_id": None,
                "reason": "cooldown",
            }
        ]

    @pytest.mark.asyncio
    async def test_pending_reports_off_surface(
        self, db_session_factory, make_goal, plan_panel_tools_on
    ):
        goal = make_goal(user_id=support.USER, description="待推进无面")
        plan = _plan(
            goal.id, 1, "active", [support.step_spec(1, tool_id=support.OFF_SURFACE_TOOL)]
        )
        body = (await support.plan_get(support.plan_url("/pending"), user_id=support.USER)).json()
        assert body["pending"][0]["reason"] == "off_surface"
        assert body["pending"][0]["tool_id"] == support.OFF_SURFACE_TOOL
        assert body["pending"][0]["plan_id"] == plan.id

    @pytest.mark.asyncio
    async def test_pending_reports_predecessor_failed(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="待推进前置失败")
        _plan(
            goal.id,
            1,
            "active",
            [
                support.step_spec(1, status="failed"),
                support.step_spec(2, depends_on=[1]),
            ],
        )
        body = (await support.plan_get(support.plan_url("/pending"), user_id=support.USER)).json()
        assert body["pending"] == [
            {
                "goal_id": goal.id,
                "plan_id": body["pending"][0]["plan_id"],
                "step_index": 2,
                "tool_id": None,
                "reason": "predecessor_failed",
            }
        ]

    @pytest.mark.asyncio
    async def test_executable_plan_is_not_pending(
        self, db_session_factory, make_goal, plan_panel_on
    ):
        goal = make_goal(user_id=support.USER, description="可执行即不待推进")
        _plan(goal.id, 1, "active", [support.step_spec(1)])
        body = (await support.plan_get(support.plan_url("/pending"), user_id=support.USER)).json()
        assert body == {"pending": []}


class TestOutputModelContracts:
    """U6 / U7：六模型字段与 §6.3 契约一致；`reason` 值域三值。"""

    def test_main_models_have_exactly_the_contract_fields(self):
        assert tuple(PlansOut.model_fields) == ("plans",)
        assert tuple(PlanDetailOut.model_fields) == (
            "plan",
            "steps",
            "bindings",
            "criteria",
            "advance_history",
        )
        assert tuple(PlanStepsOut.model_fields) == ("steps",)
        assert tuple(PlanContextOut.model_fields) == ("sources", "degraded")
        assert tuple(PlanRevisionsOut.model_fields) == ("revisions",)
        assert tuple(PlanPendingOut.model_fields) == ("pending",)

    def test_row_models_have_exactly_the_contract_fields(self):
        assert tuple(PlanSummaryOut.model_fields) == (
            "plan_id",
            "goal_id",
            "version",
            "status",
            "step_count",
            "updated_at",
        )
        assert tuple(PlanStepRowOut.model_fields) == (
            "index",
            "description",
            "kind",
            "tool_id",
            "binding_reason",
            "status",
            "attempt_count",
            "blocked_reason",
        )
        assert tuple(PlanRevisionRowOut.model_fields) == (
            "from_version",
            "to_version",
            "reason",
            "trigger_source",
            "evidence_refs",
            "kept_steps",
            "at",
        )
        assert tuple(PlanPendingRowOut.model_fields) == (
            "goal_id",
            "plan_id",
            "step_index",
            "tool_id",
            "reason",
        )

    def test_no_model_exposes_an_enabled_switch(self):
        """门控形态的直接后果：输出模型无 `enabled`（Flag off 以 404 兑现）。"""
        for model in (
            PlansOut,
            PlanDetailOut,
            PlanStepsOut,
            PlanContextOut,
            PlanRevisionsOut,
            PlanPendingOut,
        ):
            assert "enabled" not in model.model_fields, model.__name__

    def test_pending_reason_domain_is_the_three_scheduler_reasons(self):
        assert plan_scheduler.BLOCKED_REASONS == (
            "off_surface",
            "cooldown",
            "predecessor_failed",
        )
        assert PlanPendingRowOut.model_fields["reason"].annotation is str

    @pytest.mark.asyncio
    async def test_pending_reasons_stay_within_the_scheduler_value_set(
        self, db_session_factory, make_goal, plan_panel_tools_on
    ):
        """U7：端点的 `reason` 全部落 `PlanScheduler.BLOCKED_REASONS`（值域单一来源在调度器）。"""
        cooldown = make_goal(user_id=support.USER, description="值域-冷却")
        _plan(
            cooldown.id,
            1,
            "active",
            [support.step_spec(1, last_attempt_at=timeutil.now())],
        )
        off_surface = make_goal(user_id=support.USER, description="值域-无面")
        _plan(
            off_surface.id,
            1,
            "active",
            [support.step_spec(1, tool_id=support.OFF_SURFACE_TOOL)],
        )
        predecessor = make_goal(user_id=support.USER, description="值域-前置失败")
        _plan(
            predecessor.id,
            1,
            "active",
            [
                support.step_spec(1, status="failed"),
                support.step_spec(2, depends_on=[1]),
            ],
        )

        pending = (
            await support.plan_get(support.plan_url("/pending"), user_id=support.USER)
        ).json()["pending"]
        reasons = [row["reason"] for row in pending]
        assert len(pending) == 3
        assert set(reasons) <= set(plan_scheduler.BLOCKED_REASONS)
        assert set(reasons) == set(plan_scheduler.BLOCKED_REASONS)


class TestDesensitization:
    """D13 / U8：上下文投影不回显记忆正文与洞察陈述（只计数与 id）。"""

    def test_memory_content_and_insight_statement_are_not_projected(self, db_session_factory):
        from app.models.plan import MemoryRef
        from app.models.reflection import InsightSummary

        goal = goal_repository.create_hierarchical_goal(
            support.USER, "long_term", "personal", "脱敏目标", 3
        )
        context = PlanContext(
            goal=goal,
            tool_surface=ToolSurface(run_kind="autonomous_tick", tool_ids=()),
            budget={},
            memories=[
                MemoryRef(id="m-1", type="important_event", content="秘密正文", importance=0.9)
            ],
            insights=[
                InsightSummary(
                    insight_id="i-1", statement="洞察陈述", type="pattern", confidence=0.8
                )
            ],
        )

        sources = debug_api._plan_context_sources(context)
        serialized = str(sources)

        assert sources["memory"] == {
            "count": 1,
            "memory_ids": ["m-1"],
            "types": ["important_event"],
        }
        assert sources["reflection"]["count"] == 1
        assert sources["reflection"]["insight_ids"] == ["i-1"]
        assert "秘密正文" not in serialized
        assert "洞察陈述" not in serialized


class TestReadOnlyEndpoints:
    """D9 / I10：六端点零写库（会话级写探针）。"""

    @pytest.mark.asyncio
    async def test_every_endpoint_writes_nothing(
        self, db_session_factory, make_goal, plan_panel_on, persisted_audit, monkeypatch
    ):
        goal = make_goal(user_id=support.USER, description="只读端点")
        plan = _plan(goal.id, 1, "active")
        plan_observer.record_plan_advance(support.advance(goal.id, plan.id))

        probe_lists = [
            support.readonly_sessions(monkeypatch, module, db_session_factory)
            for module in (
                goal_repository,
                decision_repository,
                action_repository,
                loop_run_repository,
            )
        ]

        responses = [
            await support.plan_get(support.plan_url(""), user_id=support.USER),
            await support.plan_get(support.plan_url(f"/{plan.id}")),
            await support.plan_get(support.plan_url(f"/{plan.id}/steps")),
            await support.plan_get(
                support.plan_url("/context"), user_id=support.USER, goal_id=goal.id
            ),
            await support.plan_get(support.plan_url("/revisions"), goal_id=goal.id),
            await support.plan_get(support.plan_url("/pending"), user_id=support.USER),
        ]

        probes = [probe for probes_ in probe_lists for probe in probes_]
        assert [response.status_code for response in responses] == [200] * 6
        assert len(probes) >= 2
        assert [probe.writes for probe in probes] == [[] for _ in probes]


class TestToolPanelIsUnchanged:
    """I11：既有 `/debug/tools*` 面板零改动（端点集与输出模型未变）。"""

    def test_tool_panel_paths_are_untouched(self):
        paths = {
            route.path
            for route in debug_tools.tools_router.routes
            if route.path.startswith("/debug/tools")
        }
        assert paths == {
            "/debug/tools",
            "/debug/tools/surface",
            "/debug/tools/executions",
            "/debug/tools/permissions",
            "/debug/tools/confirmations",
            "/debug/tools/confirmations/{request_id}/revoke",
            "/debug/tools/permissions/revoke",
            "/debug/tools/{tool_id}/disable",
            "/debug/tools/{tool_id}/enable",
            "/debug/tools/manifests",
            "/debug/tools/external",
            "/debug/tools/user-defined",
            "/debug/tools/user-defined/{tool_id}/revoke",
            "/debug/tools/{tool_id}",
        }

    def test_tools_out_model_is_untouched(self):
        from app.api.v1.schemas import ToolsOut

        assert tuple(ToolsOut.model_fields) == (
            "enabled",
            "tools",
            "runtime_disabled",
            "world_intent",
            "capability_registry_flags",
            "capability_names",
            "tool_surface_degrade_count",
        )

    def test_plan_routes_do_not_shadow_tool_routes(self):
        plan_routes = [
            route.path
            for route in debug_api.plans_router.routes
            if route.path.startswith(support.PLAN_ROUTER_BASE)
        ]
        assert sorted(plan_routes) == sorted(support.PLAN_ROUTER_PATHS)
        literal_routes = [
            index
            for index, path in enumerate(plan_routes)
            if path.rsplit("/", 1)[-1] in {"context", "revisions", "pending"}
        ]
        dynamic_route = plan_routes.index(f"{support.PLAN_ROUTER_BASE}/{{plan_id}}")
        assert max(literal_routes) < dynamic_route
