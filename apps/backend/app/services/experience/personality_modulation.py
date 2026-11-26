"""V2.2.0 CHAR-003：人格 → 调制参数的读侧投影。

personality_state（V2.1.0 演化轴）仅读：当前值叠加到基线并钳制在轴自身
bound 内；演化写回仍走 Evolution Engine，本模块不写任何状态。
forbidden / principles 直接来自 Profile，是硬约束，不被轴调制稀释。
"""

from app.character.asuna.personality_profile import PersonalityProfile
from app.models.agent_state import PersonalityAxisState
from app.models.style_contract import PersonalityModulation

PERSONALITY_MODULATION_AXES = ("assertiveness", "warmth", "curiosity", "patience")


def build_personality_modulation(
    profile: PersonalityProfile,
    personality_state: list[PersonalityAxisState] | None = None,
) -> PersonalityModulation:
    states = {axis.axis: axis for axis in (personality_state or [])}
    values: dict[str, float] = {}
    baseline_meta: dict[str, float] = {}
    bound_meta: dict[str, float] = {}
    for axis in PERSONALITY_MODULATION_AXES:
        state = states.get(axis)
        if state is not None:
            baseline_meta[axis] = state.baseline
            bound_meta[axis] = round((state.bound_max - state.bound_min) / 2, 6)
            values[axis] = min(max(state.current, state.bound_min), state.bound_max)
        else:
            baseline_meta[axis] = profile.axis_baseline[axis]
            bound_meta[axis] = profile.axis_bounds[axis]
            values[axis] = profile.axis_baseline[axis]
    return PersonalityModulation(
        assertiveness=values["assertiveness"],
        warmth=values["warmth"],
        curiosity=values["curiosity"],
        patience=values["patience"],
        baseline=baseline_meta,
        bound=bound_meta,
    )
