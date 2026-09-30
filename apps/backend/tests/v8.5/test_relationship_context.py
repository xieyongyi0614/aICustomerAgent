"""V8.5 M7 行为集成套件（behavior-integration.md §4：B1~B5 + 默认态逐位一致）。"""

import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.intention import ValidatedIntention
from app.models.relationship import RelationshipState
from app.models.scene import SceneContext, SceneState
from app.engines.behavior import (
    RelationshipBehaviorContext,
    resolve,
)


def _intention(name="express_affection"):
    return ValidatedIntention(intention=name)


def _state(stage="friend", tension=0.0):
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[],
        summary=None,
        memories=[],
        current_input="hi",
        character_state=CharacterState(mood="calm", energy=0.9, intensity=0.3),
        relationship_state=RelationshipState(stage=stage, tension=tension),
    )


def _scene_ctx():
    return SceneContext(state=SceneState(session_id="s1"), intent="chat")


def _ctx(**overrides) -> RelationshipBehaviorContext:
    values = dict(
        stage="friend",
        comfort=0.6,
        respect=0.6,
        conflict_status="none",
        unlocks=(),
    )
    values.update(overrides)
    return RelationshipBehaviorContext(**values)


def _directive(ctx):
    return resolve(_intention(), _state(), _scene_ctx(), "default", relationship_ctx=ctx)


def test_relationship_ctx_none_is_identity():
    baseline = resolve(_intention(), _state(), _scene_ctx(), "default")
    explicit = resolve(
        _intention(), _state(), _scene_ctx(), "default", relationship_ctx=None
    )
    assert explicit == baseline
    assert explicit.strategy.applied_rules == baseline.strategy.applied_rules


def test_b1_conflict_restrains_social_comfort():
    directive = _directive(_ctx(conflict_status="conflict"))
    assert directive.strategy.strategy == "reserved_distance"
    assert "B1_conflict_restrained" in directive.strategy.applied_rules


def test_b1_not_triggered_outside_conflict():
    directive = _directive(_ctx(conflict_status="none"))
    assert directive.strategy.strategy == "affectionate_expression"
    assert "B1_conflict_restrained" not in directive.strategy.applied_rules


def test_b1_halves_action_budget():
    warm = _directive(_ctx())
    restrained = _directive(_ctx(conflict_status="cold"))
    assert (
        restrained.budget.max_action_desc == warm.budget.max_action_desc // 2
    )


def test_b2_low_comfort_reduces_budget():
    baseline = _directive(_ctx(comfort=0.6))
    low = _directive(_ctx(comfort=0.30))
    assert "B2_low_comfort" in low.strategy.applied_rules
    assert low.budget.max_action_desc == baseline.budget.max_action_desc - 1


def test_b2_not_triggered_at_normal_comfort():
    directive = _directive(_ctx(comfort=0.5))
    assert "B2_low_comfort" not in directive.strategy.applied_rules


def test_b3_low_respect_downgrades_affection():
    directive = _directive(_ctx(respect=0.30))
    assert directive.strategy.strategy == "natural_continuation"
    assert "B3_low_respect" in directive.strategy.applied_rules


def test_b3_not_triggered_at_normal_respect():
    directive = _directive(_ctx(respect=0.6))
    assert directive.strategy.strategy == "affectionate_expression"
    assert "B3_low_respect" not in directive.strategy.applied_rules


def test_b4_high_comfort_deep_stage_enriches():
    directive = _directive(_ctx(stage="close_friend", comfort=0.8))
    assert "B4_high_comfort" in directive.strategy.applied_rules


def test_b4_not_triggered_in_shallow_stage():
    directive = _directive(_ctx(stage="friend", comfort=0.8))
    assert "B4_high_comfort" not in directive.strategy.applied_rules


def test_b5_locked_commitment_in_partner_stage():
    locked = _directive(_ctx(stage="partner"))
    assert locked.strategy.strategy == "natural_continuation"
    assert "B5_locked_commitment" in locked.strategy.applied_rules


def test_b5_unlock_allows_commitment_language():
    unlocked = _directive(
        _ctx(stage="partner", unlocks=("deep_commitment_language",))
    )
    assert unlocked.strategy.strategy == "affectionate_expression"
    assert "B5_locked_commitment" not in unlocked.strategy.applied_rules


def test_rules_compose_deterministically():
    first = _directive(_ctx(conflict_status="conflict", comfort=0.3))
    second = _directive(_ctx(conflict_status="conflict", comfort=0.3))
    assert first == second
    assert "B1_conflict_restrained" in first.strategy.applied_rules
    assert "B2_low_comfort" in first.strategy.applied_rules


@pytest.mark.parametrize(
    "ctx",
    [
        _ctx(),
        _ctx(conflict_status="cold", comfort=0.3, respect=0.3),
        _ctx(stage="partner", comfort=0.8, unlocks=("deep_commitment_language",)),
    ],
)
def test_same_ctx_same_directive(ctx):
    assert _directive(ctx) == _directive(ctx)