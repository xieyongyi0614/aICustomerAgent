"""tests/v25 共享夹具：Flag 隔离（本任务零新增 Flag）+ Goal/Plan 构造器。"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.repositories import goal_repository
from app.services import goal_planning

V25_NOW = datetime(2026, 9, 8, 12, 0, 0)
V25_USER = "plan1-user"
V25_OFFLINE_USER = "plan1-off-user"

DEFAULT_PLANNED_STEP = {
    "index": 1,
    "description": "推送一条提醒",
    "capability": "create_reminder",
    "params": {"content": "该休息了"},
    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
}


@pytest.fixture(autouse=True)
def _pin_v25_planning_env(monkeypatch):
    """目录级隔离：既有自治通路取默认关闭（PLAN-001 零新增 Flag，V2.5.0 无 v25_* 项）。"""
    monkeypatch.setenv("V2_AUTONOMY_ADVANCED_ENABLED", "false")
    monkeypatch.setenv("V24_TOOL_SYSTEM_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def autonomy_on(override_settings):
    """需要既有 AUT-002 / AUT-003 通路时显式开闸（开的是 V2.0.0 既有 Flag，非本任务新增）。"""
    override_settings(
        v2_autonomy_advanced_enabled="true",
        action_enabled="true",
        world_enabled="false",
        v2_memory_enabled="false",
        observability_persist_enabled="false",
    )
    return True


@pytest.fixture
def make_goal():
    """顶层分层目标构造器（既有 create_hierarchical_goal，零改动）。"""

    def _make(
        user_id: str = V25_USER,
        layer: str = "long_term",
        domain: str = "personal",
        description: str = "契约目标",
        priority: int = 3,
    ):
        return goal_repository.create_hierarchical_goal(
            user_id, layer, domain, description, priority
        )

    return _make


@pytest.fixture
def make_spec():
    """Sub-Goal 构造器：默认 capability 与判据一致，可用 overrides 覆盖。"""

    def _spec(index: int = 1, capability: str = "create_reminder", **overrides):
        spec = {
            "index": index,
            "description": f"步骤{index}",
            "capability": capability,
            "params": {},
            "criteria": {"type": "action_succeeded", "capability": capability},
        }
        spec.update(overrides)
        return spec

    return _spec


@pytest.fixture
def planned_step():
    """默认单步计划步骤的一份可改副本。"""
    return dict(DEFAULT_PLANNED_STEP)


@pytest.fixture
def make_plan():
    """计划构造器（既有 create_plan，零改动）；`specs` 缺省为一步默认计划。"""

    def _plan(
        goal_id: str,
        specs: list[dict] | None = None,
        version: int = 1,
        status: str = "active",
    ):
        payload = specs if specs is not None else [dict(DEFAULT_PLANNED_STEP)]
        return goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal_id,
                version=version,
                status=status,
                sub_goals=[SubGoalSpec.model_validate(item) for item in payload],
                created_at=V25_NOW,
                updated_at=V25_NOW,
            )
        )

    return _plan


@pytest.fixture
def goal_facts():
    """既有判据求值的事实包；`succeeded` 直接给出应判定为成功的 capability 列表。"""

    def _facts(succeeded: list[str] | None = None, **overrides):
        facts = {
            "now": V25_NOW,
            "action_results": [
                {
                    "capability": capability,
                    "status": "succeeded",
                    "created_at": V25_NOW,
                }
                for capability in (succeeded or [])
            ],
            "world": {},
            "state": {},
            "memory": {},
        }
        facts.update(overrides)
        return facts

    return _facts


@pytest.fixture
def stub_planning_llm(monkeypatch):
    """把规划 LLM 换成确定性提案，可选把入参 prompt 记进 `recorder["messages"]`。"""

    def _apply(sub_goals=None, recorder=None):
        steps = sub_goals or [DEFAULT_PLANNED_STEP]
        proposal = goal_planning.PlanningProposal(
            sub_goals=[dict(item) for item in steps]
        )

        def _chain(messages, _schema, _llm):
            if recorder is not None:
                recorder["messages"] = messages
            return SimpleNamespace(invoke=lambda _payload: proposal)

        monkeypatch.setattr(goal_planning, "build_structured_chain", _chain)
        return proposal

    return _apply
