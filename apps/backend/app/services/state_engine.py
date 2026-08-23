from datetime import datetime

from app.core.settings import get_settings
from app.models.character_state import CharacterState, StateUpdateDecision
from app.models.emotion import TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipState

STAGE_ORDER = ("stranger", "friend", "close_friend", "partner")

EVENT_DELTAS: dict[str, RelationshipDelta] = {
    "achievement": RelationshipDelta(intimacy=0.04, familiarity=0.02),
    "setback": RelationshipDelta(intimacy=0.03),
    "share_goal": RelationshipDelta(intimacy=0.02, trust=0.06),
    "seek_help": RelationshipDelta(intimacy=0.02, trust=0.05, familiarity=0.02),
    "help_given": RelationshipDelta(intimacy=0.03, trust=0.02, familiarity=0.06),
    "complaint": RelationshipDelta(trust=-0.03),
    "conflict": RelationshipDelta(intimacy=-0.12, trust=-0.10, familiarity=-0.05),
    "daily": RelationshipDelta(familiarity=0.01),
    "farewell": RelationshipDelta(),
}

BEHAVIOR_DELTAS: dict[str, RelationshipDelta] = {
    "comfort": RelationshipDelta(intimacy=0.02),
    "celebrate": RelationshipDelta(intimacy=0.02),
    "encourage": RelationshipDelta(trust=0.01),
    "recall_memory": RelationshipDelta(trust=0.02, familiarity=0.03),
}

ENERGY_EVENT_MODIFIERS: dict[str, float] = {
    "achievement": 0.10,
    "help_given": 0.05,
    "setback": -0.05,
    "complaint": -0.05,
    "conflict": -0.10,
}

ENERGY_BEHAVIOR_MODIFIERS: dict[str, float] = {
    "comfort": -0.05,
    "show_concern": -0.03,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_idle_recovery(state: CharacterState, now: datetime) -> CharacterState:
    if state.updated_at is None:
        return state
    settings = get_settings()
    elapsed_hours = (now - state.updated_at).total_seconds() / 3600
    if elapsed_hours <= settings.energy_reset_hours:
        return state
    mood = "calm" if state.mood in ("tired", "angry") else state.mood
    return state.model_copy(
        update={"energy": max(state.energy, settings.energy_reset_value), "mood": mood}
    )


def update_energy(state: CharacterState, analysis: TurnAnalysis) -> float:
    settings = get_settings()
    energy = state.energy - settings.energy_turn_decay
    energy += ENERGY_EVENT_MODIFIERS.get(analysis.user_emotion.event, 0.0)
    energy += ENERGY_BEHAVIOR_MODIFIERS.get(analysis.behavior.behavior, 0.0)
    return clamp(energy, settings.energy_min, 1.0)


def relationship_deltas(event: str, behavior: str) -> RelationshipDelta:
    event_delta = EVENT_DELTAS.get(event, RelationshipDelta())
    behavior_delta = BEHAVIOR_DELTAS.get(behavior, RelationshipDelta())
    return RelationshipDelta(
        intimacy=event_delta.intimacy + behavior_delta.intimacy,
        trust=event_delta.trust + behavior_delta.trust,
        familiarity=event_delta.familiarity + behavior_delta.familiarity,
    )


def next_stage(
    intimacy: float, trust: float, familiarity: float, current_stage: str
) -> str:
    settings = get_settings()
    values = {"intimacy": intimacy, "trust": trust, "familiarity": familiarity}
    upgrade_requirements = {
        "friend": {"familiarity": settings.stage_friend_familiarity},
        "close_friend": {
            "intimacy": settings.stage_close_intimacy,
            "trust": settings.stage_close_trust,
        },
        "partner": {
            "intimacy": settings.stage_partner_intimacy,
            "trust": settings.stage_partner_trust,
        },
    }
    for stage in reversed(STAGE_ORDER[1:]):
        requirements = upgrade_requirements[stage]
        if all(values[key] >= threshold for key, threshold in requirements.items()):
            if STAGE_ORDER.index(stage) > STAGE_ORDER.index(current_stage):
                return stage
            break
    requirements = upgrade_requirements.get(current_stage)
    if requirements and all(
        values[key] < threshold - settings.stage_hysteresis
        for key, threshold in requirements.items()
    ):
        return STAGE_ORDER[STAGE_ORDER.index(current_stage) - 1]
    return current_stage


def apply_relationship(
    relationship: RelationshipState, event: str, behavior: str
) -> RelationshipState:
    delta = relationship_deltas(event, behavior)
    intimacy = clamp(relationship.intimacy + delta.intimacy, 0.0, 1.0)
    trust = clamp(relationship.trust + delta.trust, 0.0, 1.0)
    familiarity = clamp(relationship.familiarity + delta.familiarity, 0.0, 1.0)
    stage = next_stage(intimacy, trust, familiarity, relationship.stage)
    return relationship.model_copy(
        update={
            "intimacy": intimacy,
            "trust": trust,
            "familiarity": familiarity,
            "stage": stage,
        }
    )


def apply_character(
    state: CharacterState,
    decision: StateUpdateDecision | None,
    analysis: TurnAnalysis,
    now: datetime,
) -> CharacterState:
    updates: dict = {
        "energy": update_energy(state, analysis),
        "updated_at": now,
    }
    if decision is not None:
        updates["mood"] = decision.mood
        updates["inner_state"] = decision.inner_state
        updates["current_topic"] = decision.current_topic
    return state.model_copy(update=updates)
