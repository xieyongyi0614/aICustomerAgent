"""CHAR-004：关系快照 → Addressing 档位映射单测（只读投影，零关系数学）。"""

from app.character.asuna.relationship_lexicon import (
    ADDRESSING_EXPRESSIVENESS_LADDER,
    ADDRESSING_INITIATIVE_LADDER,
    ADDRESSING_TONE_LADDER,
    ADDRESSING_TERM_LADDER,
    RELATIONSHIP_EMOTION_BOOST_MAX,
)
from app.models.relationship import RelationshipState
from app.services.experience.emotion_expression import build_emotion_expression
from app.services.experience.relationship_addressing import (
    build_addressing,
    relationship_emotion_boost,
)
from app.models.character_state import CharacterState

STAGE_EXPECTATIONS = {
    "stranger": ("respectful", "polite", "passive", "restrained"),
    "friend": ("name", "natural", "responsive", "natural"),
    "close_friend": ("affectionate", "warm", "proactive", "open"),
    "partner": ("intimate", "affectionate", "devoted", "open"),
}


def _state(stage: str, *, intimacy=0.5, familiarity=0.5, comfort=0.6, conflict="none"):
    return RelationshipState(
        stage=stage,
        intimacy=intimacy,
        familiarity=familiarity,
        comfort=comfort,
        conflict_status=conflict,
    )


def test_stage_base_mapping_is_deterministic():
    for stage, expected in STAGE_EXPECTATIONS.items():
        addressing = build_addressing(_state(stage))
        got = (
            addressing.term,
            addressing.tone,
            addressing.initiative,
            addressing.emotion_expressiveness,
        )
        assert got == expected, stage


def test_stage_progression_is_monotonic():
    order = ["stranger", "friend", "close_friend", "partner"]
    ladders = {
        "term": ADDRESSING_TERM_LADDER,
        "tone": ADDRESSING_TONE_LADDER,
        "initiative": ADDRESSING_INITIATIVE_LADDER,
        "emotion_expressiveness": ADDRESSING_EXPRESSIVENESS_LADDER,
    }
    previous = None
    for stage in order:
        addressing = build_addressing(_state(stage))
        current = {
            field: ladder.index(getattr(addressing, field))
            for field, ladder in ladders.items()
        }
        if previous is not None:
            for field in ladders:
                assert current[field] >= previous[field], (stage, field)
        previous = current


def test_intimacy_threshold_bumps_term_and_expressiveness():
    bumped = build_addressing(_state("friend", intimacy=0.70))
    assert bumped.term == "affectionate"
    assert bumped.emotion_expressiveness == "open"
    unchanged = build_addressing(_state("friend", intimacy=0.69))
    assert unchanged.term == "name"
    assert unchanged.emotion_expressiveness == "natural"


def test_comfort_threshold_bumps_tone():
    assert build_addressing(_state("friend", comfort=0.70)).tone == "warm"
    assert build_addressing(_state("friend", comfort=0.69)).tone == "natural"


def test_familiarity_thresholds_move_initiative():
    high = build_addressing(_state("friend", familiarity=0.75))
    assert high.initiative == "proactive"
    mid = build_addressing(_state("friend", familiarity=0.74))
    assert mid.initiative == "responsive"
    low = build_addressing(_state("friend", familiarity=0.29))
    assert low.initiative == "passive"
    boundary = build_addressing(_state("friend", familiarity=0.30))
    assert boundary.initiative == "responsive"


def test_low_comfort_restrains_expressiveness():
    assert build_addressing(_state("friend", comfort=0.39)).emotion_expressiveness == (
        "restrained"
    )
    assert build_addressing(_state("friend", comfort=0.40)).emotion_expressiveness == (
        "natural"
    )


def test_stranger_initiative_never_below_ladder_bottom():
    addressing = build_addressing(_state("stranger", familiarity=0.0))
    assert addressing.initiative == "passive"


def test_conflict_override_lowers_tone_and_initiative():
    expectations = {
        "strain": ("polite", "passive"),
        "conflict": ("polite", "passive"),
        "cold": ("polite", "passive"),
        "recovery": ("polite", "passive"),
    }
    for conflict, (tone, initiative) in expectations.items():
        addressing = build_addressing(_state("friend", conflict=conflict))
        assert addressing.tone == tone, conflict
        assert addressing.initiative == initiative, conflict


def test_conflict_override_takes_priority_over_dimension_bump():
    addressing = build_addressing(
        _state("friend", comfort=0.9, conflict="strain")
    )
    assert addressing.tone == "natural"


def test_conflict_override_on_partner_is_clamped_within_ladder():
    addressing = build_addressing(_state("partner", conflict="cold"))
    assert addressing.tone == "natural"
    assert addressing.initiative == "responsive"


def test_no_conflict_keeps_regular_tiers():
    for conflict in ("none", "resolved"):
        addressing = build_addressing(_state("friend", conflict=conflict))
        assert addressing.tone == "natural"
        assert addressing.initiative == "responsive"


def test_emotion_boost_by_stage():
    assert relationship_emotion_boost("stranger") == 0.0
    assert relationship_emotion_boost("friend") == 0.0
    assert relationship_emotion_boost("close_friend") == 0.10
    assert relationship_emotion_boost("partner") == 0.20


def test_emotion_boost_clamped_and_unknown_stage_safe():
    for stage in ("stranger", "friend", "close_friend", "partner", "unknown"):
        boost = relationship_emotion_boost(stage)
        assert 0.0 <= boost <= RELATIONSHIP_EMOTION_BOOST_MAX
    assert relationship_emotion_boost("unknown") == 0.0


def test_emotion_boost_integrates_with_expression_tiering():
    state = CharacterState(mood="happy", intensity=0.55)
    without_boost = build_emotion_expression(state)
    assert without_boost.expression_intensity == "natural"
    with_boost = build_emotion_expression(
        state, intensity_boost=relationship_emotion_boost("partner")
    )
    assert with_boost.expression_intensity == "rich"
