"""CHAR-006：StyleContract 装配中枢单测（纯函数，无 IO / 无 LLM）。"""

from datetime import datetime

from app.character.asuna.emotion_expression import EMOTION_TONES
from app.character.asuna.personality_profile import PERSONA_PROFILE
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.memory import UserMemory
from app.models.relationship import RelationshipState
from app.models.style_contract import Addressing, PersonalityModulation
from app.services.experience import style_assembler
from app.services.experience.style_assembler import assemble_style_contract


def _memory() -> UserMemory:
    return UserMemory(
        id="m1",
        user_id="u1",
        character_id="asuna",
        type="user_fact",
        content="用户在准备马拉松",
        importance=0.8,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def _state(
    message: str = "最近工作很累",
    mood: str = "worried",
    intensity: float = 0.55,
    relationship: RelationshipState | None = None,
    with_memory: bool = False,
) -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[],
        summary=None,
        memories=[_memory()] if with_memory else [],
        current_input=message,
        character_state=CharacterState(mood=mood, intensity=intensity),
        relationship_state=relationship or RelationshipState(),
    )


def _analysis(emotion: str = "tired", event: str = "seek_help") -> TurnAnalysis:
    return TurnAnalysis(user_emotion=UserEmotion(emotion=emotion, event=event))


def test_normal_assembly_produces_complete_contract():
    contract = assemble_style_contract(_state(), _analysis())
    assert contract.addressing == Addressing()
    assert contract.emotion_constraint.tone_directive == (
        EMOTION_TONES.tones["worried"].tone_directive
    )
    assert contract.emotion_constraint.expression_intensity == "natural"
    assert contract.forbidden
    assert contract.principles
    assert [habit.rule_id for habit in contract.habits] == [
        "habit_care_action_first",
        "habit_comfort_companion_first",
    ]
    assert contract.style_hint


def test_memory_signal_enables_light_touch_habit():
    state = _state(message="今天我们在哪见过来着", with_memory=True)
    contract = assemble_style_contract(state, _analysis(emotion="neutral", event="daily"))
    assert "habit_memory_light_touch" in [habit.rule_id for habit in contract.habits]


def test_conflict_emotion_wins_over_relationship_expressiveness():
    partner = RelationshipState(stage="partner")
    state = _state(mood="sad", intensity=0.1, relationship=partner)
    contract = assemble_style_contract(state, _analysis(emotion="sad", event="daily"))
    assert contract.emotion_constraint.expression_intensity == "subtle"
    assert contract.addressing.emotion_expressiveness == "restrained"


def test_relationship_expressiveness_survives_when_aligned():
    partner = RelationshipState(stage="partner")
    state = _state(mood="happy", intensity=0.9, relationship=partner)
    contract = assemble_style_contract(state, _analysis(emotion="happy", event="daily"))
    assert contract.emotion_constraint.expression_intensity == "rich"
    assert contract.addressing.emotion_expressiveness == "open"


def test_relationship_boost_lifts_expression_tier():
    partner = RelationshipState(stage="partner")
    state = _state(mood="calm", intensity=0.4, relationship=partner)
    contract = assemble_style_contract(state, _analysis())
    assert contract.emotion_constraint.expression_intensity == "natural"


def test_personality_modulation_uses_persona_baseline():
    contract = assemble_style_contract(_state(), _analysis())
    modulation = contract.personality_modulation
    assert modulation.baseline == PERSONA_PROFILE.axis_baseline
    assert modulation.assertiveness == PERSONA_PROFILE.axis_baseline["assertiveness"]


def test_personality_boundary_suppresses_conflicting_habits(monkeypatch):
    def _low_warmth(profile, personality_state=None):
        return PersonalityModulation(warmth=0.2, baseline={}, bound={})

    monkeypatch.setattr(style_assembler, "build_personality_modulation", _low_warmth)
    contract = assemble_style_contract(_state(), _analysis())
    assert contract.habits == []
    assert contract.forbidden
    assert contract.principles


def test_personality_boundary_keeps_unrelated_habits(monkeypatch):
    def _low_curiosity(profile, personality_state=None):
        return PersonalityModulation(curiosity=0.2, baseline={}, bound={})

    monkeypatch.setattr(style_assembler, "build_personality_modulation", _low_curiosity)
    contract = assemble_style_contract(_state(), _analysis())
    assert [habit.rule_id for habit in contract.habits] == [
        "habit_care_action_first",
        "habit_comfort_companion_first",
    ]


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_subcomponent_failure_degrades_to_minimal_contract(monkeypatch):
    monkeypatch.setattr(style_assembler, "build_addressing", _boom)
    monkeypatch.setattr(style_assembler, "build_emotion_expression", _boom)
    monkeypatch.setattr(style_assembler, "build_personality_modulation", _boom)
    monkeypatch.setattr(style_assembler, "trigger_habits", _boom)
    contract = assemble_style_contract(_state(), _analysis())
    assert contract.habits == []
    assert contract.forbidden == list(PERSONA_PROFILE.forbidden_behaviors)
    assert contract.principles == list(PERSONA_PROFILE.principles)
    assert contract.addressing == Addressing()
    assert contract.style_hint == "自然"


def test_hard_constraints_survive_partial_failures(monkeypatch):
    monkeypatch.setattr(style_assembler, "build_addressing", _boom)
    contract = assemble_style_contract(_state(), _analysis())
    assert contract.addressing == Addressing()
    assert contract.emotion_constraint.tone_directive != ""
    assert contract.forbidden
    assert contract.habits


def test_profile_failure_yields_empty_contract(monkeypatch):
    class _BrokenProfile:
        @property
        def forbidden_behaviors(self):
            raise RuntimeError("boom")

        @property
        def principles(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(style_assembler, "PERSONA_PROFILE", _BrokenProfile())
    contract = assemble_style_contract(_state(), _analysis())
    assert contract.forbidden == []
    assert contract.principles == []
    assert contract.addressing == Addressing()
    assert [habit.rule_id for habit in contract.habits] == [
        "habit_care_action_first",
        "habit_comfort_companion_first",
    ]


def test_zero_extra_llm_imports():
    import app.services.experience.style_assembler as module

    assert "get_llm" not in dir(module)
