import pytest
from pydantic import ValidationError

from app.character.asuna.behavior_policy import BEHAVIOR_POLICY, STRATEGY_INSTRUCTIONS
from app.character.asuna.habits import HABIT_LIST
from app.models.behavior_strategy import (
    MOOD_KEYS,
    STAGE_KEYS,
    ActionBudget,
    BehaviorPolicy,
    BehaviorStrategy,
    BehaviorDirective,
    HabitRule,
    MoodModifier,
    StageBehaviorParams,
)


def _policy(stage_params=None, mood_modifiers=None):
    return BehaviorPolicy(
        stage_params=stage_params or {}, mood_modifiers=mood_modifiers or {}
    )


def test_strategy_type_12_values():
    from app.models.behavior_strategy import BEHAVIOR_STRATEGY_TYPES

    assert len(BEHAVIOR_STRATEGY_TYPES) == 12
    assert len(set(BEHAVIOR_STRATEGY_TYPES)) == 12


def test_policy_rejects_missing_stage():
    stage_params = {k: None for k in STAGE_KEYS if k != "partner"}
    with pytest.raises(ValidationError):
        _policy(stage_params=stage_params)


def test_policy_rejects_missing_mood():
    mood_modifiers = {m: MoodModifier() for m in MOOD_KEYS if m != "angry"}
    with pytest.raises(ValidationError):
        _policy(mood_modifiers=mood_modifiers)


def test_policy_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        _policy(stage_params={"unknown": None})
    with pytest.raises(ValidationError):
        _policy(mood_modifiers={"ecstatic": MoodModifier()})


def test_asuna_policy_asset_matches_docs():
    assert set(BEHAVIOR_POLICY.stage_params) == set(STAGE_KEYS)
    assert set(BEHAVIOR_POLICY.mood_modifiers) == set(MOOD_KEYS)
    partner = BEHAVIOR_POLICY.stage_params["partner"]
    assert partner.physical_contact == "light"
    assert partner.action_desc_max == 2
    stranger = BEHAVIOR_POLICY.stage_params["stranger"]
    assert stranger.physical_contact == "none"
    assert stranger.action_desc_max == 1
    assert BEHAVIOR_POLICY.mood_modifiers["angry"].action_desc_factor == 0.5
    assert BEHAVIOR_POLICY.mood_modifiers["excited"].action_desc_factor == 1.5


def test_strategy_instructions_cover_all_strategies():
    from app.models.behavior_strategy import BEHAVIOR_STRATEGY_TYPES

    assert set(STRATEGY_INSTRUCTIONS) == set(BEHAVIOR_STRATEGY_TYPES)
    for text in STRATEGY_INSTRUCTIONS.values():
        assert len(text) <= 40


def test_habit_list_rules_valid():
    ids = [h.id for h in HABIT_LIST]
    assert len(ids) == len(set(ids))
    for habit in HABIT_LIST:
        assert 1 <= habit.priority <= 5
        assert len(habit.instruction) <= 40
        assert habit.domain in ("relate", "express", "pace")


def test_habit_rule_rejects_bad_priority():
    with pytest.raises(ValidationError):
        HabitRule(id="x", domain="relate", priority=9, instruction="ok")


def test_action_budget_defaults():
    budget = ActionBudget()
    assert budget.max_action_desc == 1
    assert budget.allow_action_desc is True
    assert budget.physical_contact == "none"


def test_directive_degraded_property():
    directive = BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="natural_continuation",
            base_strategy="natural_continuation",
            degraded=True,
        ),
        budget=ActionBudget(),
    )
    assert directive.degraded is True


def test_stage_params_rejects_out_of_range_action_max():
    with pytest.raises(ValidationError):
        StageBehaviorParams(
            physical_contact="none",
            affection_verbosity="natural",
            teasing_tolerance="light",
            action_desc_max=5,
            initiative_level="responsive",
        )
