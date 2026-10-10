"""计划审批闸门（baseline §8.6 / ADR-21）：闸门 ON/OFF 两态 + 批准 / 驳回 / 守卫。

覆盖四组面：

- **闸门两态**：OFF（默认）维持「生成即 `active` 自动执行」；ON 时计划停在 `validated`，
  执行候选集（`list_active_plans`）看不到它。
- **人工裁决**：批准转 `active` 并撤下同目标旧 `active` 计划；驳回转 `rejected` 并留理由。
- **守卫 fail-closed**：非待批态不改库（`not_pending`）；不存在或非本人一律 `not_found`。
- **不误伤**：闸门 ON 时新计划停 `validated`，旧 `active` 计划**不被撤下**（驳回后原状保持）。
"""

from app.repositories import goal_repository
from app.services.goal import approval as plan_approval
from app.services.goal import planning as goal_planning

from .conftest import V25_USER

OTHER_USER = "plan-approval-other-user"


def test_gate_off_keeps_auto_activation(make_goal, stub_planning_llm):
    goal = make_goal(description="默认自动激活")
    stub_planning_llm()
    result = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)
    assert result["status"] == "ok"
    plan = goal_repository.get_plan(result["plan_id"])
    assert plan.status == "active"
    assert [pair[1].id for pair in goal_repository.list_active_plans(V25_USER)] == [plan.id]


def test_gate_on_holds_plan_in_validated(make_goal, stub_planning_llm, override_settings):
    override_settings(plan_require_approval="true")
    goal = make_goal(description="待批停靠")
    stub_planning_llm()
    result = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)
    assert result["status"] == "ok"
    plan = goal_repository.get_plan(result["plan_id"])
    assert plan.status == "validated"
    assert goal_repository.list_active_plans(V25_USER) == []
    assert [item.id for item in plan_approval.list_pending(V25_USER)] == [plan.id]


def test_gate_on_replan_keeps_previous_active_plan(
    make_goal, make_plan, stub_planning_llm, override_settings
):
    override_settings(plan_require_approval="true")
    goal = make_goal(description="驳回不误伤旧计划")
    old = make_plan(goal.id, version=1, status="active")
    stub_planning_llm()
    result = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_REPLAN)
    assert goal_repository.get_plan(old.id).status == "active"
    assert goal_repository.get_plan(result["plan_id"]).status == "validated"


def test_approve_activates_pending_plan(make_goal, make_plan):
    goal = make_goal(description="批准激活")
    pending = make_plan(goal.id, version=1, status="validated")
    result = plan_approval.approve(V25_USER, pending.id)
    assert result["outcome"] == plan_approval.OUTCOME_APPROVED
    assert result["goal_id"] == goal.id
    assert result["status"] == "active"
    assert goal_repository.get_plan(pending.id).status == "active"
    assert plan_approval.list_pending(V25_USER) == []


def test_approve_supersedes_previous_active_plan(make_goal, make_plan):
    goal = make_goal(description="批准撤旧")
    older = make_plan(goal.id, version=1, status="active")
    pending = make_plan(goal.id, version=2, status="validated")
    plan_approval.approve(V25_USER, pending.id)
    assert goal_repository.get_plan(older.id).status == "superseded"
    assert goal_repository.get_plan(pending.id).status == "active"
    active = [pair[1].id for pair in goal_repository.list_active_plans(V25_USER)]
    assert active == [pending.id]


def test_reject_marks_plan_rejected_with_reason(make_goal, make_plan):
    goal = make_goal(description="驳回留痕")
    pending = make_plan(goal.id, version=1, status="validated")
    result = plan_approval.reject(V25_USER, pending.id, "方案风险过高")
    assert result["outcome"] == plan_approval.OUTCOME_REJECTED
    reloaded = goal_repository.get_plan(pending.id)
    assert reloaded.status == "rejected"
    assert reloaded.rejection_reason == "方案风险过高"
    assert goal_repository.get_goal(goal.id).status == "active"


def test_reject_defaults_reason_when_blank(make_goal, make_plan):
    goal = make_goal(description="驳回空理由")
    pending = make_plan(goal.id, version=1, status="validated")
    plan_approval.reject(V25_USER, pending.id, "   ")
    assert (
        goal_repository.get_plan(pending.id).rejection_reason
        == plan_approval.DEFAULT_REJECTION_REASON
    )


def test_approve_refuses_non_pending_without_write(make_goal, make_plan):
    goal = make_goal(description="非待批拒绝批准")
    active = make_plan(goal.id, version=1, status="active")
    result = plan_approval.approve(V25_USER, active.id)
    assert result["outcome"] == plan_approval.OUTCOME_NOT_PENDING
    assert result["status"] == "active"
    assert goal_repository.get_plan(active.id).status == "active"


def test_reject_refuses_non_pending_without_write(make_goal, make_plan):
    goal = make_goal(description="非待批拒绝驳回")
    rejected = make_plan(goal.id, version=1, status="rejected")
    result = plan_approval.reject(V25_USER, rejected.id, "再次驳回")
    assert result["outcome"] == plan_approval.OUTCOME_NOT_PENDING
    assert goal_repository.get_plan(rejected.id).status == "rejected"


def test_approve_missing_plan_is_not_found():
    result = plan_approval.approve(V25_USER, "no-such-plan")
    assert result["outcome"] == plan_approval.OUTCOME_NOT_FOUND


def test_foreign_plan_is_not_found_and_untouched(make_goal, make_plan):
    foreign_goal = make_goal(user_id=OTHER_USER, description="他人目标")
    pending = make_plan(foreign_goal.id, version=1, status="validated")
    assert plan_approval.approve(V25_USER, pending.id)["outcome"] == plan_approval.OUTCOME_NOT_FOUND
    assert plan_approval.reject(V25_USER, pending.id, "越权")["outcome"] == plan_approval.OUTCOME_NOT_FOUND
    assert goal_repository.get_plan(pending.id).status == "validated"


def test_list_pending_scopes_to_user_and_pending_status(make_goal, make_plan):
    goal = make_goal(description="清单口径")
    pending = make_plan(goal.id, version=1, status="validated")
    make_plan(goal.id, version=2, status="active")
    foreign_goal = make_goal(user_id=OTHER_USER, description="他人待批")
    make_plan(foreign_goal.id, version=1, status="validated")
    assert [item.id for item in plan_approval.list_pending(V25_USER)] == [pending.id]


def test_plans_endpoints_require_token():
    """三个产品端点一律经 `require_user`：无 token 即 401（写面不得裸奔）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/v1/plans/pending").status_code == 401
    assert client.post("/api/v1/plans/any/approve").status_code == 401
    assert client.post("/api/v1/plans/any/reject").status_code == 401
