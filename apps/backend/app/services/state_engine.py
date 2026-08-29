from datetime import datetime

from app.core.settings import get_settings
from app.models.character_state import CharacterState, EmotionLabel, StateUpdateDecision
from app.models.emotion import EmotionEvent, EmotionEventType, TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipState

STAGE_ORDER = ("stranger", "friend", "close_friend", "partner")

EMOTION_EVENTS: dict[str, dict] = {
    "praise": {"emotion": "happy", "delta": 0.3},
    "comforted": {"emotion": "happy", "delta": 0.25},
    "teased": {"emotion": "shy", "delta": 0.25},
    "warm_moment": {"emotion": "happy", "delta": 0.2},
    "funny_moment": {"emotion": "excited", "delta": 0.3},
    "criticized": {"emotion": "sad", "delta": 0.3},
    "conflict": {"emotion": "angry", "delta": 0.4},
    "worrying_news": {"emotion": "worried", "delta": 0.35},
    "reunion": {"emotion": "excited", "delta": 0.3},
}

MAGNITUDE_COEFFICIENTS: dict[str, float] = {
    "weak": 0.6,
    "normal": 1.0,
    "strong": 1.4,
}

RELATIONSHIP_EVENT_DELTAS: dict[str, RelationshipDelta] = {
    "user_care": RelationshipDelta(trust=0.04, intimacy=0.03, familiarity=0.01, tension=-0.02),
    "user_help": RelationshipDelta(trust=0.05, intimacy=0.03, familiarity=0.02),
    "long_interaction": RelationshipDelta(intimacy=0.01, familiarity=0.02),
    "intimate_moment": RelationshipDelta(trust=0.02, intimacy=0.06, familiarity=0.01, tension=-0.01),
    "praise": RelationshipDelta(trust=0.02, intimacy=0.02, familiarity=0.01, tension=-0.01),
    "warm_moment": RelationshipDelta(trust=0.02, intimacy=0.02, familiarity=0.01, tension=-0.01),
    "criticized": RelationshipDelta(trust=-0.03, tension=0.05),
    "conflict": RelationshipDelta(intimacy=-0.12, trust=-0.10, familiarity=-0.05, tension=0.20),
    "boundary_violation": RelationshipDelta(trust=-0.08, intimacy=-0.05, tension=0.15),
    "none": RelationshipDelta(),
}

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


def update_emotion(
    state: CharacterState, event: EmotionEvent, now: datetime
) -> CharacterState:
    settings = get_settings()
    if event.type == "none":
        return apply_emotion_decay(state, now)
    spec = EMOTION_EVENTS[event.type]
    target = spec["emotion"]
    raw_delta = spec["delta"] * MAGNITUDE_COEFFICIENTS[event.magnitude]
    if target == state.mood:
        new_intensity = clamp(state.intensity + raw_delta, 0.0, 1.0)
    else:
        if (
            state.intensity >= settings.emotion_strong_threshold
            and event.confidence < settings.emotion_switch_min_confidence
        ):
            return state
        new_intensity = clamp(
            raw_delta + state.intensity * settings.emotion_inertia, 0.0, 1.0
        )
    max_delta = settings.emotion_max_turn_delta
    if abs(new_intensity - state.intensity) > max_delta:
        step = max_delta if new_intensity > state.intensity else -max_delta
        new_intensity = clamp(state.intensity + step, 0.0, 1.0)
    return state.model_copy(
        update={
            "mood": target,
            "intensity": new_intensity,
            "cause": event.cause or state.cause,
            "last_event_at": now,
            "updated_at": now,
        }
    )


def apply_emotion_decay(
    state: CharacterState, now: datetime
) -> CharacterState:
    settings = get_settings()
    if state.last_event_at is None:
        return state
    elapsed_hours = (now - state.last_event_at).total_seconds() / 3600
    if elapsed_hours <= 0:
        return state
    rate = (
        settings.emotion_decay_strong
        if state.intensity > settings.emotion_strong_boundary
        else settings.emotion_decay_mild
    )
    decayed = state.intensity - rate * elapsed_hours
    if decayed <= settings.emotion_decay_floor:
        return state.model_copy(
            update={
                "mood": "calm",
                "intensity": settings.emotion_rest_intensity,
                "cause": "",
            }
        )
    return state.model_copy(update={"intensity": clamp(decayed, 0.0, 1.0)})


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
