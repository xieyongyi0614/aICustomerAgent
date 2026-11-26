import pytest

from app.models.behavior_strategy import StageBehaviorParams
from app.models.scene import SceneContext, SceneState
from app.engines.behavior import compute_budget

STRANGER = StageBehaviorParams(
    physical_contact="none", affection_verbosity="restrained",
    teasing_tolerance="none", action_desc_max=1, initiative_level="passive",
)
PARTNER = StageBehaviorParams(
    physical_contact="light", affection_verbosity="expressive",
    teasing_tolerance="open", action_desc_max=2, initiative_level="proactive",
)


def _scene(activity=None):
    return SceneContext(state=SceneState(session_id="s", current_activity=activity), intent="chat")


def test_step1_mode_baselines():
    b = compute_budget("professional", PARTNER, 1.0, "natural_continuation", _scene(), 0.3)
    assert (b.max_action_desc, b.allow_action_desc, b.physical_contact) == (0, False, "none")
    b = compute_budget("immersive", PARTNER, 1.0, "natural_continuation", _scene(), 0.3)
    assert b.max_action_desc == 2


def test_step2_stage_caps_immersive():
    b = compute_budget("immersive", STRANGER, 1.0, "natural_continuation", _scene(), 0.3)
    assert b.max_action_desc == 1


def test_step3_mood_factor_only_lowers():
    b = compute_budget("default", PARTNER, 0.5, "natural_continuation", _scene(), 0.3)
    assert b.max_action_desc == 0
    b = compute_budget("default", PARTNER, 1.5, "natural_continuation", _scene(), 0.3)
    assert b.max_action_desc == 1
    b = compute_budget("immersive", PARTNER, 1.2, "natural_continuation", _scene(), 0.3)
    assert b.max_action_desc == 2


def test_step4_no_action_strategies():
    for strategy in ("quiet_companion", "reserved_distance", "sincere_repair"):
        b = compute_budget("immersive", PARTNER, 1.0, strategy, _scene(), 0.3)
        assert b.max_action_desc == 0


def test_step4_affection_contact_uses_stage():
    b = compute_budget("default", PARTNER, 1.0, "affectionate_expression", _scene(), 0.3)
    assert b.physical_contact == "light"
    b = compute_budget("default", STRANGER, 1.0, "affectionate_expression", _scene(), 0.3)
    assert b.physical_contact == "none"


def test_step5_activity_occupies_one_action():
    b = compute_budget("immersive", PARTNER, 1.0, "natural_continuation", _scene("切西瓜"), 0.3)
    assert b.max_action_desc == 1


def test_step6_strong_emotion_zero():
    b = compute_budget("default", PARTNER, 1.0, "natural_continuation", _scene(), 0.8)
    assert b.max_action_desc == 0


def test_monotonic_tightening():
    assert (
        compute_budget("professional", STRANGER, 0.5, "quiet_companion", _scene(), 0.9).max_action_desc
        == 0
    )
