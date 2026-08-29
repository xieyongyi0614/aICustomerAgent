from datetime import datetime

from app.core.constants import (
    BEHAVIOR_DELTAS,
    EMOTION_EVENTS,
    ENERGY_BEHAVIOR_MODIFIERS,
    ENERGY_EVENT_MODIFIERS,
    EVENT_DELTAS,
    MAGNITUDE_COEFFICIENTS,
    RELATIONSHIP_EVENT_DELTAS,
    STAGE_ORDER,
)
from app.core.settings import get_settings
from app.models.character_state import CharacterState, StateUpdateDecision
from app.models.emotion import EmotionEvent, TurnAnalysis
from app.models.relationship import RelationshipDelta, RelationshipState



def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_relationship_impact(event_type: str, magnitude: str) -> RelationshipDelta:
    base = RELATIONSHIP_EVENT_DELTAS[event_type]
    coefficient = MAGNITUDE_COEFFICIENTS[magnitude]
    return RelationshipDelta(
        intimacy=round(base.intimacy * coefficient, 6),
        trust=round(base.trust * coefficient, 6),
        familiarity=round(base.familiarity * coefficient, 6),
        tension=round(base.tension * coefficient, 6),
    )


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
    intimacy: float,
    trust: float,
    familiarity: float,
    current_stage: str,
    tension: float | None = None,
) -> str:
    settings = get_settings()
    values = {"intimacy": intimacy, "trust": trust, "familiarity": familiarity}
    upgrade_frozen = tension is not None and tension > settings.rel_tension_freeze
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
    current_index = STAGE_ORDER.index(current_stage)
    next_index = current_index + 1
    if next_index < len(STAGE_ORDER):
        candidate = STAGE_ORDER[next_index]
        requirements = upgrade_requirements[candidate]
        if all(
            values[key] >= threshold for key, threshold in requirements.items()
        ) and not upgrade_frozen:
            return candidate
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


def apply_relationship_v5(
    relationship: RelationshipState,
    event_type: str,
    magnitude: str,
    behavior: str,
    day_positive: RelationshipDelta,
    day_negative: RelationshipDelta,
) -> tuple[RelationshipState, RelationshipDelta]:
    settings = get_settings()
    event_delta = build_relationship_impact(event_type, magnitude)
    behavior_delta = BEHAVIOR_DELTAS.get(behavior, RelationshipDelta())
    dimensions = ("intimacy", "trust", "familiarity", "tension")
    new_values: dict[str, float] = {}
    applied_delta = {}
    for dim in dimensions:
        total = getattr(event_delta, dim) + getattr(behavior_delta, dim)
        total = clamp(
            total, -settings.rel_max_event_delta, settings.rel_max_event_delta
        )
        total = clamp(
            total, -settings.rel_max_turn_delta, settings.rel_max_turn_delta
        )
        current = getattr(relationship, dim)
        improving = total < 0 if dim == "tension" else total > 0
        if total != 0:
            used = getattr(day_positive if improving else day_negative, dim)
            headroom = max(settings.rel_max_day_delta - used, 0.0)
            total = min(total, headroom) if total > 0 else -min(-total, headroom)
        new_value = clamp(current + total, 0.0, 1.0)
        new_values[dim] = new_value
        applied_delta[dim] = round(new_value - current, 6)
    stage = next_stage(
        new_values["intimacy"],
        new_values["trust"],
        new_values["familiarity"],
        relationship.stage,
        tension=new_values["tension"],
    )
    new_state = relationship.model_copy(update={**new_values, "stage": stage})
    return new_state, RelationshipDelta(**applied_delta)


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
        updates["inner_state"] = decision.inner_state
        updates["current_topic"] = decision.current_topic
    return state.model_copy(update=updates)
