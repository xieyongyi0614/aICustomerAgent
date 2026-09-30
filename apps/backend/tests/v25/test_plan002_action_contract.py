"""PLAN-002 §4.2.9 / §4.3.3 / §6.3：ActionItem 契约（步级执行映射）的可判定形式。

契约表在 Task Detail §6.3，本模块逐条把它钉到**真实 Action 域取值**上：映射目标必须真的
存在（`ACTION_STATUSES` / `GATE_REASONS`），投影取值必须真的合法
（`ActionIntent.confidence` / `ActionSource`），Action 层幂等键公式必须与既有实现一致。
PLAN-005 按本契约实现执行桥，不得再自建第二份。
"""

import inspect
from pathlib import Path
from typing import get_args

from app.models.action import (
    ACTION_STATUSES,
    GATE_REASONS,
    ActionIntent,
    ActionSource,
)
from app.models.plan import (
    PLAN_ACTION_DEDUPE_KEY_TEMPLATE,
    PLAN_STEP_ACTION_CONFIDENCE,
    PLAN_STEP_ACTION_SOURCE,
    PLAN_STEP_ATTEMPT_INCREMENT_STATUSES,
    PLAN_STEP_BLOCKED_GATE_REASONS,
    PLAN_STEP_DEDUPE_KEY_TEMPLATE,
    PLAN_STEP_OUTCOMES,
    PLAN_STEP_OUTCOME_ACTION_STATUS,
)
from app.services.goal import execution as goal_execution
from app.services.planning import goal_contract

STATUS_MAP_SNAPSHOT = {
    "succeeded": "succeeded",
    "failed": "failed",
    "timeout": "failed",
    "blocked": "cancelled",
    "skipped": None,
    "hold": "planned",
}

BACKEND_ROOT = Path(goal_contract.__file__).parents[3]


def test_status_map_covers_exactly_the_six_step_outcomes():
    assert PLAN_STEP_OUTCOME_ACTION_STATUS == STATUS_MAP_SNAPSHOT
    assert tuple(PLAN_STEP_OUTCOME_ACTION_STATUS) == PLAN_STEP_OUTCOMES
    assert len(PLAN_STEP_OUTCOME_ACTION_STATUS) == 6


def test_status_map_targets_exist_in_the_action_domain():
    for outcome, action_status in PLAN_STEP_OUTCOME_ACTION_STATUS.items():
        if action_status is None:
            assert outcome == "skipped"
            continue
        assert action_status in ACTION_STATUSES, (outcome, action_status)


def test_status_map_adds_no_action_status_value():
    assert ACTION_STATUSES == (
        "created",
        "planned",
        "executing",
        "succeeded",
        "failed",
        "cancelled",
    )
    assert PLAN_STEP_OUTCOME_ACTION_STATUS["skipped"] is None
    assert PLAN_STEP_OUTCOME_ACTION_STATUS["hold"] == "planned"
    assert PLAN_STEP_OUTCOME_ACTION_STATUS["blocked"] == "cancelled"


def test_blocked_gate_reasons_are_a_subset_of_the_existing_value_set():
    assert PLAN_STEP_BLOCKED_GATE_REASONS == (
        "capability_unavailable",
        "permission_denied",
        "invalid_params",
        "pending_confirmation",
    )
    assert len(GATE_REASONS) == 10
    assert set(PLAN_STEP_BLOCKED_GATE_REASONS) <= set(GATE_REASONS)


def test_action_intent_projection_values_are_legal_in_the_action_domain():
    confidence_values = get_args(ActionIntent.model_fields["confidence"].annotation)
    assert PLAN_STEP_ACTION_CONFIDENCE == "confident"
    assert PLAN_STEP_ACTION_CONFIDENCE in confidence_values
    assert PLAN_STEP_ACTION_SOURCE == "autonomy"
    assert PLAN_STEP_ACTION_SOURCE in get_args(ActionSource)


def test_attempt_count_increment_happens_only_on_action_terminal_statuses():
    assert PLAN_STEP_ATTEMPT_INCREMENT_STATUSES == ("succeeded", "failed")
    assert set(PLAN_STEP_ATTEMPT_INCREMENT_STATUSES) <= set(ACTION_STATUSES)
    for intermediate in ("created", "planned", "executing"):
        assert intermediate not in PLAN_STEP_ATTEMPT_INCREMENT_STATUSES
    assert "cancelled" not in PLAN_STEP_ATTEMPT_INCREMENT_STATUSES


def test_step_dedupe_key_shape_carries_the_plan_version():
    assert PLAN_STEP_DEDUPE_KEY_TEMPLATE == "plan:{goal_id}:{version}:{index}"
    key = PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(goal_id="goal-1", version=2, index=3)
    assert key == "plan:goal-1:2:3"
    assert PLAN_STEP_DEDUPE_KEY_TEMPLATE != PLAN_ACTION_DEDUPE_KEY_TEMPLATE


def test_action_layer_dedupe_key_template_matches_the_existing_implementation():
    assert PLAN_ACTION_DEDUPE_KEY_TEMPLATE == "goal:{goal_id}:{version}:{index}"
    source = inspect.getsource(goal_execution)
    assert 'dedupe_key=f"goal:{goal.id}:{plan.version}:{current.index}"' in source
    assert source.count("dedupe_key=f\"goal:") == 1


def test_plan_step_dedupe_key_is_declared_at_exactly_one_site():
    declarations = [
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in (BACKEND_ROOT / "app").rglob("*.py")
        if "plan:{goal_id}:{version}:{index}" in path.read_text(encoding="utf-8")
    ]
    assert declarations == ["app/models/plan.py"]
    assert PLAN_STEP_DEDUPE_KEY_TEMPLATE.startswith("plan:")
    assert PLAN_ACTION_DEDUPE_KEY_TEMPLATE.startswith("goal:")
