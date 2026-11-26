"""CHAR-003：PersonalityProfile 结构化与人格调制单测（纯函数，无 IO / 无 LLM）。"""

from app.character.asuna.evolution import PERSONALITY_AXES
from app.character.asuna.identity import IDENTITY_BLOCK
from app.character.asuna.personality import PERSONALITY_BLOCK
from app.character.asuna.personality_profile import PERSONA_PROFILE, LanguageStyle
from app.models.agent_state import PersonalityAxisState
from app.services.experience.personality_modulation import (
    build_personality_modulation,
)


def _axis_state(axis: str, baseline: float, current: float, amplitude: float):
    return PersonalityAxisState(
        axis=axis,
        baseline=baseline,
        current=current,
        bound_min=round(max(baseline - amplitude, 0.0), 6),
        bound_max=round(min(baseline + amplitude, 1.0), 6),
    )


def test_profile_covers_all_structured_sections():
    profile = PERSONA_PROFILE
    assert profile.core_traits
    assert profile.behavior_preferences
    assert isinstance(profile.language_style, LanguageStyle)
    assert profile.language_style.summary
    assert profile.language_style.length
    assert profile.language_style.pacing
    assert profile.language_style.avoid
    assert profile.forbidden_behaviors
    assert profile.principles


def test_profile_semantically_matches_identity_block():
    profile = PERSONA_PROFILE
    assert "温柔但坚定" in profile.core_traits
    assert "独立自主" in profile.core_traits
    assert "认真负责" in profile.core_traits
    assert "对亲近的人非常体贴" in profile.core_traits
    assert "偶尔害羞、撒娇" in profile.core_traits
    assert "面对困难时冷静果断" in profile.principles
    assert "拥有自己的判断、原则和情绪" in profile.principles
    assert "不为了讨好用户而无条件赞同" in profile.forbidden_behaviors


def test_profile_semantically_matches_personality_block():
    style = PERSONA_PROFILE.language_style
    assert "1~3 句" in style.length
    assert "一次只说一件事" in style.pacing
    for banned in ("过度动漫化", "网络流行梗", "颜文字", "客服式模板"):
        assert banned in style.avoid


def test_identity_and_personality_assets_untouched():
    assert "温柔但坚定" in IDENTITY_BLOCK
    assert "无条件赞同" in IDENTITY_BLOCK
    assert "1~3 句话" in PERSONALITY_BLOCK
    assert "客服式模板" in PERSONALITY_BLOCK


def test_profile_axis_metadata_matches_evolution_declaration():
    assert PERSONA_PROFILE.axis_baseline == {
        axis: spec["baseline"] for axis, spec in PERSONALITY_AXES.items()
    }
    assert PERSONA_PROFILE.axis_bounds == {
        axis: spec["bound"] for axis, spec in PERSONALITY_AXES.items()
    }


def test_modulation_without_state_returns_persona_baseline():
    modulation = build_personality_modulation(PERSONA_PROFILE)
    assert modulation.assertiveness == PERSONALITY_AXES["assertiveness"]["baseline"]
    assert modulation.warmth == PERSONALITY_AXES["warmth"]["baseline"]
    assert modulation.curiosity == PERSONALITY_AXES["curiosity"]["baseline"]
    assert modulation.patience == PERSONALITY_AXES["patience"]["baseline"]
    assert modulation.baseline == PERSONA_PROFILE.axis_baseline
    assert modulation.bound == PERSONA_PROFILE.axis_bounds


def test_modulation_overlays_evolution_axes():
    states = [
        _axis_state("assertiveness", 0.30, 0.38, 0.20),
        _axis_state("warmth", 0.70, 0.64, 0.20),
        _axis_state("curiosity", 0.60, 0.75, 0.20),
        _axis_state("patience", 0.60, 0.60, 0.15),
    ]
    modulation = build_personality_modulation(PERSONA_PROFILE, states)
    assert modulation.assertiveness == 0.38
    assert modulation.warmth == 0.64
    assert modulation.curiosity == 0.75
    assert modulation.patience == 0.60
    assert modulation.baseline["warmth"] == 0.70
    assert modulation.bound["patience"] == 0.15


def test_modulation_clamps_current_within_axis_bounds():
    states = [
        _axis_state("warmth", 0.70, 1.0, 0.20),
        _axis_state("assertiveness", 0.30, 0.0, 0.20),
    ]
    modulation = build_personality_modulation(PERSONA_PROFILE, states)
    assert modulation.warmth == 0.90
    assert modulation.assertiveness == 0.10


def test_modulation_partial_state_falls_back_to_baseline():
    states = [_axis_state("curiosity", 0.60, 0.66, 0.20)]
    modulation = build_personality_modulation(PERSONA_PROFILE, states)
    assert modulation.curiosity == 0.66
    assert modulation.assertiveness == PERSONA_PROFILE.axis_baseline["assertiveness"]
    assert modulation.warmth == PERSONA_PROFILE.axis_baseline["warmth"]
    assert modulation.patience == PERSONA_PROFILE.axis_baseline["patience"]


def test_modulation_ignores_unknown_axes():
    states = [_axis_state("humor", 0.5, 0.9, 0.2)]
    modulation = build_personality_modulation(PERSONA_PROFILE, states)
    assert set(modulation.baseline) == {
        "assertiveness",
        "warmth",
        "curiosity",
        "patience",
    }
    assert modulation.assertiveness == PERSONA_PROFILE.axis_baseline["assertiveness"]


def test_hard_constraints_not_diluted_by_modulation():
    before_forbidden = list(PERSONA_PROFILE.forbidden_behaviors)
    before_principles = list(PERSONA_PROFILE.principles)
    build_personality_modulation(
        PERSONA_PROFILE,
        [
            _axis_state("assertiveness", 0.30, 0.5, 0.2),
            _axis_state("warmth", 0.70, 0.5, 0.2),
        ],
    )
    assert PERSONA_PROFILE.forbidden_behaviors == before_forbidden
    assert PERSONA_PROFILE.principles == before_principles
    assert PERSONA_PROFILE.forbidden_behaviors
    assert PERSONA_PROFILE.principles
