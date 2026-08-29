import pytest

from app.character.asuna.habits import HABIT_LIST
from app.models.behavior_strategy import ActionBudget, BehaviorStrategy
from app.models.conversation import ConversationState
from app.models.intention import ValidatedIntention
from app.models.scene import PendingAction, SceneContext, SceneState
from app.services.behavior_engine import (
    classify_activity,
    match_habits,
    resolve,
)
from app.services.behavior_engine import _apply_modifiers


def _intention(name="continue_topic", degraded=False):
    return ValidatedIntention(intention=name, degraded=degraded)


def _state(stage="friend", tension=0.0, mood="calm", energy=0.9, intensity=0.3):
    from app.models.character_state import CharacterState
    from app.models.relationship import RelationshipState

    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[],
        summary=None,
        memories=[],
        current_input="hi",
        character_state=CharacterState(mood=mood, energy=energy, intensity=intensity),
        relationship_state=RelationshipState(stage=stage, tension=tension),
    )


def _scene_ctx(state=None, intent="chat"):
    return SceneContext(
        state=state or SceneState(session_id="s1"), intent=intent
    )


def test_strategy_mapping_covers_reactive_intentions():
    from app.services.behavior_engine import INTENTION_STRATEGY_MAP
    from app.models.intention import IntentionType
    from typing import get_args

    reactive = {name for name in get_args(IntentionType) if name != "check_in"}
    assert set(INTENTION_STRATEGY_MAP) == reactive
    assert len(INTENTION_STRATEGY_MAP) == 12


def test_base_mapping_comfort_to_quiet_companion():
    directive = resolve(
        _intention("comfort_user"), _state(), _scene_ctx(), "default"
    )
    assert directive.strategy.strategy == "quiet_companion"
    assert directive.strategy.base_strategy == "quiet_companion"
    assert directive.strategy.degraded is False
    assert directive.fallback_v2 is None


def test_modifier_professional_overrides_all():
    strategy, rules = _apply_modifiers(
        "playful_tease", "tease_user", "professional",
        tension=0.0, energy=0.9, stage="partner", mood="happy",
        scene_pending=False, intensity=0.3,
    )
    assert strategy == "focused_assistance"
    assert rules == ["mode_professional"]


def test_modifier_tension_reserved_with_repair_exception():
    strategy, _ = _apply_modifiers(
        "affectionate_expression", "express_affection", "default",
        tension=0.6, energy=0.9, stage="partner", mood="calm",
        scene_pending=False, intensity=0.3,
    )
    assert strategy == "reserved_distance"
    strategy, _ = _apply_modifiers(
        "sincere_repair", "repair_rapport", "default",
        tension=0.6, energy=0.9, stage="partner", mood="calm",
        scene_pending=False, intensity=0.3,
    )
    assert strategy == "sincere_repair"


def test_modifier_comfort_upgrade():
    strategy, rules = _apply_modifiers(
        "quiet_companion", "comfort_user", "default",
        tension=0.0, energy=0.8, stage="partner", mood="calm",
        scene_pending=False, intensity=0.3,
    )
    assert strategy == "direct_support"
    assert "comfort_upgrade" in rules


def test_modifier_low_energy_no_tease():
    strategy, rules = _apply_modifiers(
        "playful_tease", "tease_user", "default",
        tension=0.0, energy=0.9, stage="partner", mood="tired",
        scene_pending=False, intensity=0.3,
    )
    assert strategy == "natural_continuation"
    assert "low_energy_calm" in rules


def test_modifier_scene_pending_collapses_strategy():
    pending = SceneState(
        session_id="s1",
        pending_action=PendingAction(action="拿西瓜", status="pending"),
    )
    directive = resolve(
        _intention("tease_user"), _state(), _scene_ctx(pending), "default"
    )
    assert directive.strategy.strategy == "natural_continuation"
    assert "scene_pending_collapse" in directive.strategy.applied_rules


def test_deterministic_same_input_same_output():
    a = resolve(_intention("comfort_user"), _state(), _scene_ctx(), "default")
    b = resolve(_intention("comfort_user"), _state(), _scene_ctx(), "default")
    assert a == b


def test_degraded_intention_falls_back_v2():
    from app.models.emotion import TurnAnalysis

    turn = TurnAnalysis()
    directive = resolve(
        _intention(degraded=True), _state(), _scene_ctx(), "default", turn
    )
    assert directive.degraded is True
    assert directive.fallback_v2 is not None


def test_resolve_never_raises():
    directive = resolve(None, None, None, "weird-mode")
    assert directive.strategy.strategy == "natural_continuation"
    assert directive.degraded is True


def test_habit_match_priority_order_and_dedup():
    habits = match_habits("quiet_companion")
    assert 1 <= len(habits) <= 2
    ids = [h.id for h in habits]
    assert "habit_comfort_companion_first" not in ids
    indexes = [HABIT_LIST.index(h) for h in habits]
    assert indexes == sorted(indexes)


def test_habit_match_professional_empty():
    assert match_habits("focused_assistance") == []


def test_classify_activity_layers():
    assert classify_activity(None) == ("idle", None)
    assert classify_activity(SceneState(session_id="s")) == ("idle", None)
    ambient = SceneState(session_id="s", current_activity="切西瓜")
    assert classify_activity(ambient) == ("ambient_activity", "切西瓜")
    engaged = SceneState(session_id="s", current_action="切西瓜")
    assert classify_activity(engaged) == ("engaged_action", "切西瓜")
    pending = SceneState(
        session_id="s", pending_action=PendingAction(action="拿水", status="pending")
    )
    assert classify_activity(pending) == ("pending_obligation", "拿水")


def test_activity_continuity_rendered_on_question():
    scene = SceneState(session_id="s", current_activity="切西瓜")
    directive = resolve(
        _intention("continue_topic"), _state(), _scene_ctx(scene, "question"), "default"
    )
    assert directive.activity == "ambient_activity"
    assert directive.activity_text == "切西瓜"
    assert directive.strategy.strategy == "natural_continuation"


def test_activity_not_rendered_when_scene_advancing():
    scene = SceneState(session_id="s", current_activity="切西瓜")
    directive = resolve(
        _intention("continue_topic"), _state(), _scene_ctx(scene, "request_action"), "default"
    )
    assert directive.activity == "idle"
