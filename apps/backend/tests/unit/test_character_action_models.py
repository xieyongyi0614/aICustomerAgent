"""ACTION-001 WorldAction 模型 + 状态机 + 幂等键 单测。"""

import pytest
from pydantic import ValidationError

from app.models.character_action import (
    ACTION_TYPES,
    TERMINAL_ACTION_STATUSES,
    ActionTransitionEvent,
    TargetRef,
    TurnRef,
    WorldAction,
    WorldActionReason,
    WorldActionStatus,
    build_dedupe_key,
    make_action_id,
    make_world_action_dedupe_key,
    transition_world_action,
)
from app.character.asuna.narrative import (
    NARRATIVE_ACTION_VERBS,
    NARRATIVE_NOISE_PATTERNS,
    NARRATIVE_QUANTITY_WORDS,
)


def _make_action(**overrides) -> WorldAction:
    defaults = dict(
        action_type="CONSUME",
        target=TargetRef(name="鸡蛋"),
        turn_ref=TurnRef(session_id="s1", turn_id="t1", ordinal=0),
    )
    defaults.update(overrides)
    return WorldAction(**defaults)


class TestWorldActionModel:
    def test_consume_candidate(self):
        action = _make_action(quantity=2.0)
        assert action.status == WorldActionStatus.CANDIDATE
        assert action.action_type == "CONSUME"
        assert action.target.name == "鸡蛋"
        assert action.quantity == 2.0
        assert action.actor == "character"

    def test_create_candidate(self):
        action = _make_action(
            action_type="CREATE",
            target=TargetRef(name="面"),
            quantity=1.0,
        )
        assert action.action_type == "CREATE"
        assert action.target.name == "面"

    def test_move_candidate(self):
        action = _make_action(
            action_type="MOVE",
            target=TargetRef(name="牛奶", location_id="home.kitchen"),
        )
        assert action.action_type == "MOVE"
        assert action.target.location_id == "home.kitchen"

    def test_rejects_unknown_action_type(self):
        with pytest.raises(ValidationError):
            _make_action(action_type="INVALID")

    def test_rejects_empty_target_name(self):
        with pytest.raises(ValidationError):
            _make_action(target=TargetRef(name=""))

    def test_rejects_negative_quantity(self):
        with pytest.raises(ValidationError):
            _make_action(quantity=-1.0)

    def test_rejects_zero_quantity(self):
        with pytest.raises(ValidationError):
            _make_action(quantity=0.0)

    def test_rejects_unknown_actor(self):
        with pytest.raises(ValidationError):
            _make_action(actor="alien")

    def test_rejects_unknown_source(self):
        with pytest.raises(ValidationError):
            _make_action(source="unknown")

    def test_move_allows_null_quantity(self):
        action = _make_action(
            action_type="MOVE",
            target=TargetRef(name="牛奶"),
            quantity=None,
        )
        assert action.quantity is None

    def test_snapshot(self):
        action = _make_action(quantity=2.0)
        snap = action.snapshot()
        assert snap["action_type"] == "CONSUME"
        assert snap["target_name"] == "鸡蛋"
        assert snap["quantity"] == 2.0
        assert snap["status"] == "candidate"


class TestWorldActionTransition:
    def test_candidate_to_validated(self):
        action = _make_action()
        new = action.transition(ActionTransitionEvent.VALIDATE_PASS)
        assert new == WorldActionStatus.VALIDATED
        assert action.status == WorldActionStatus.VALIDATED

    def test_candidate_to_rejected(self):
        action = _make_action()
        new = action.transition(ActionTransitionEvent.VALIDATE_REJECT)
        assert new == WorldActionStatus.REJECTED
        assert action.status == WorldActionStatus.REJECTED

    def test_candidate_to_skipped(self):
        action = _make_action()
        new = action.transition(ActionTransitionEvent.SKIP)
        assert new == WorldActionStatus.SKIPPED

    def test_validated_to_applied(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_PASS)
        new = action.transition(ActionTransitionEvent.ENGINE_OK)
        assert new == WorldActionStatus.APPLIED

    def test_validated_to_failed(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_PASS)
        new = action.transition(ActionTransitionEvent.ENGINE_FAIL)
        assert new == WorldActionStatus.FAILED

    def test_rejected_is_terminal(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_REJECT)
        assert action.is_terminal()
        assert action.transition(ActionTransitionEvent.VALIDATE_PASS) is None

    def test_applied_is_terminal(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_PASS)
        action.transition(ActionTransitionEvent.ENGINE_OK)
        assert action.is_terminal()
        assert action.transition(ActionTransitionEvent.ENGINE_FAIL) is None

    def test_failed_is_terminal(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_PASS)
        action.transition(ActionTransitionEvent.ENGINE_FAIL)
        assert action.is_terminal()

    def test_skipped_is_terminal(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.SKIP)
        assert action.is_terminal()

    def test_illegal_forward_transition_rejected_to_validated(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_REJECT)
        assert action.transition(ActionTransitionEvent.VALIDATE_PASS) is None
        assert action.status == WorldActionStatus.REJECTED

    def test_illegal_applied_to_validated(self):
        action = _make_action()
        action.transition(ActionTransitionEvent.VALIDATE_PASS)
        action.transition(ActionTransitionEvent.ENGINE_OK)
        assert action.transition(ActionTransitionEvent.VALIDATE_PASS) is None

    def test_illegal_candidate_engine_ok(self):
        action = _make_action()
        assert action.transition(ActionTransitionEvent.ENGINE_OK) is None

    def test_pure_function_transition(self):
        result = transition_world_action(WorldActionStatus.CANDIDATE, ActionTransitionEvent.VALIDATE_PASS)
        assert result == WorldActionStatus.VALIDATED

    def test_pure_function_illegal(self):
        result = transition_world_action(WorldActionStatus.APPLIED, ActionTransitionEvent.VALIDATE_PASS)
        assert result is None

    def test_all_terminal_states_immutable(self):
        for status in TERMINAL_ACTION_STATUSES:
            for event in ActionTransitionEvent:
                result = transition_world_action(status, event)
                if status in (WorldActionStatus.REJECTED, WorldActionStatus.APPLIED,
                              WorldActionStatus.FAILED, WorldActionStatus.SKIPPED):
                    assert result is None, f"{status} + {event} should be None"


class TestDedupeKey:
    def test_word_order_irrelevant(self):
        key_a = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        key_b = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        assert key_a == key_b

    def test_content_sensitive_quantity(self):
        key_a = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        key_b = build_dedupe_key("CONSUME", "鸡蛋", 3.0, "s1", "t1", 0)
        assert key_a != key_b

    def test_content_sensitive_target(self):
        key_a = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        key_b = build_dedupe_key("CONSUME", "牛奶", 2.0, "s1", "t1", 0)
        assert key_a != key_b

    def test_content_sensitive_ordinal(self):
        key_a = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        key_b = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 1)
        assert key_a != key_b

    def test_type_sensitive(self):
        key_a = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        key_b = build_dedupe_key("CREATE", "鸡蛋", 2.0, "s1", "t1", 0)
        assert key_a != key_b

    def test_quantity_int_float_equal(self):
        key_a = make_world_action_dedupe_key("CONSUME", {"target_name": "鸡蛋", "quantity": 2})
        key_b = make_world_action_dedupe_key("CONSUME", {"target_name": "鸡蛋", "quantity": 2.0})
        assert key_a == key_b

    def test_key_length(self):
        key = build_dedupe_key("CONSUME", "鸡蛋", 2.0, "s1", "t1", 0)
        assert len(key) == 16

    def test_make_action_id(self):
        id1 = make_action_id()
        id2 = make_action_id()
        assert id1.startswith("wa_")
        assert id1 != id2


class TestNarrativeLexicon:
    def test_consume_verbs_count(self):
        assert len(NARRATIVE_ACTION_VERBS["CONSUME"]) >= 3

    def test_create_verbs_count(self):
        assert len(NARRATIVE_ACTION_VERBS["CREATE"]) >= 3

    def test_move_verbs_count(self):
        assert len(NARRATIVE_ACTION_VERBS["MOVE"]) >= 3

    def test_quantity_words_coverage(self):
        assert NARRATIVE_QUANTITY_WORDS["一"] == 1.0
        assert NARRATIVE_QUANTITY_WORDS["两"] == 2.0
        assert NARRATIVE_QUANTITY_WORDS["半"] == 0.5

    def test_noise_patterns_exist(self):
        assert len(NARRATIVE_NOISE_PATTERNS) >= 3
        assert "吗" in NARRATIVE_NOISE_PATTERNS
        assert "如果" in NARRATIVE_NOISE_PATTERNS

    def test_all_action_types_covered(self):
        assert set(NARRATIVE_ACTION_VERBS.keys()) == {"CONSUME", "CREATE", "MOVE"}
        assert set(ACTION_TYPES) == {"CREATE", "MOVE", "CONSUME"}
