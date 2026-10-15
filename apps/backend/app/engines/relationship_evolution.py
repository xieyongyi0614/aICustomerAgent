"""V8.5 M1 派生指标 + M3 演化引擎（relationship-model.md / evolution-engine.md）。

全部纯函数、可重放；LLM 无分数修改权（原则 3）。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import RELATIONSHIP_DIMENSIONS, BEHAVIOR_DELTAS
from app.core.settings import get_settings
from app.models.relationship import (
    InteractionSignal,
    RelationshipDelta,
    RelationshipEvent,
    RelationshipState,
)
from app.engines.state import build_relationship_impact, next_stage

DEFAULT_CONFLICT_BASELINE_PENALTY = 0.10

DYNAMICS_DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def comfort_baseline(stage: str, conflict_active: bool = False) -> float:
    """阶段均衡基线；active conflict 期 −0.10（冷战期自在不起来）。"""
    settings = get_settings()
    baseline = float(settings.comfort_baselines().get(stage, 0.60))
    if conflict_active:
        baseline -= DEFAULT_CONFLICT_BASELINE_PENALTY
    return clamp01(baseline)


def distance_index(
    state: RelationshipState, now: datetime, neglect_days: dict | None = None
) -> float:
    """疏离度 0~1：M8 主动行为克制门控与 prompt 距离档使用。"""
    settings = get_settings()
    thresholds = neglect_days or settings.neglect_thresholds()
    threshold = float(thresholds.get(state.stage, 7.0))
    if state.last_interaction_at is None:
        recency_penalty = 1.0
    else:
        gap_days = max((now - state.last_interaction_at).total_seconds() / 86400, 0.0)
        recency_penalty = min(gap_days / max(threshold, 1e-9), 1.0)
    return clamp01(
        0.5 * state.tension + 0.3 * (1.0 - state.comfort) + 0.2 * recency_penalty
    )


class EvolutionOutcome(BaseModel):
    """M3 → M4/M5/M6/M7/M8 的唯一交接物（evolution-engine.md §2）。"""

    applied_delta: RelationshipDelta = Field(default_factory=RelationshipDelta)
    event_type: str = "none"
    magnitude: str = "normal"
    event: RelationshipEvent | None = None
    truncated: dict[str, float] = Field(default_factory=dict)
    window: tuple[tuple[str, str], ...] = ()
    flags: dict[str, bool] = Field(default_factory=dict)
    comfort_drift_applied: float = 0.0
    version_before: int = 0
    version_after: int = 0


def _d1_repetition(delta: float, repeats: int, decay: float, flags: dict) -> float:
    """D1 边际递减：仅正向，第 n 次重复 × r^n。"""
    if delta > 0 and repeats > 0:
        flags["d1_repetition"] = True
        return delta * (decay**repeats)
    return delta


def _d2_saturation(delta: float, current: float, dimension: str, flags: dict) -> float:
    """D2 高值钝化：仅正向 × (1 − current²)；familiarity 豁免。"""
    if delta > 0 and dimension != "familiarity":
        factor = 1.0 - current * current
        if factor < 1.0:
            flags["d2_saturation"] = True
        return delta * factor
    return delta


def _d3_trust_asymmetry(
    delta: float, dimension: str, amp: float, flags: dict
) -> float:
    """D3 信任不对称：trust 负向 × amp。"""
    if dimension == "trust" and delta < 0 and amp != 1.0:
        flags["d3_trust_asymmetry"] = True
        return delta * amp
    return delta


def _d5_salience(delta: float, salience: float, flags: dict) -> float:
    """D5 显著度调制：× (0.5 + salience)。"""
    if salience > 0.0 and delta != 0.0:
        flags["d5_salience"] = True
        return delta * (0.5 + salience)
    return delta


def apply_dynamics(
    base: RelationshipDelta,
    state: RelationshipState,
    repeats_by_kind: dict[tuple[str, str], int],
    signal: InteractionSignal | None,
) -> tuple[RelationshipDelta, dict[str, bool]]:
    """D1~D5 动力学修饰（顺序固定：D1→D2→D3→D5；D4=comfort 豁免 D1/D2）。

    负向不递减不钝化；comfort 不参与 D1/D2；familiarity 不参与 D2。
    """
    flags: dict[str, bool] = {}
    settings = get_settings()
    decay = settings.rel_repetition_decay
    amp = settings.rel_trust_negative_amp
    salience = signal.salience if signal is not None else 0.0
    key = (signal.kind, signal.quality) if signal is not None else None
    repeats = repeats_by_kind.get(key, 0) if key is not None else 0
    modified = {dimension: getattr(base, dimension) for dimension in ("tension",)}
    for dimension in DYNAMICS_DIMENSIONS:
        value = getattr(base, dimension)
        if value == 0.0:
            modified[dimension] = 0.0
            continue
        if dimension != "comfort":
            value = _d1_repetition(value, repeats, decay, flags)
            value = _d2_saturation(value, getattr(state, dimension), dimension, flags)
        value = _d3_trust_asymmetry(value, dimension, amp, flags)
        value = _d5_salience(value, salience, flags)
        modified[dimension] = value
    return RelationshipDelta(**modified), flags


def rate_limit(
    state: RelationshipState,
    event_delta: RelationshipDelta,
    behavior_delta: RelationshipDelta,
    day_positive: RelationshipDelta,
    day_negative: RelationshipDelta,
) -> tuple[RelationshipDelta, dict[str, float]]:
    """V5 三级限速（原值，6 维覆盖）：单事件 0.17 / 单轮 0.15 / 每日 0.30。"""
    settings = get_settings()
    truncated: dict[str, float] = {}
    limited = {}
    for dimension in RELATIONSHIP_DIMENSIONS:
        total = getattr(event_delta, dimension) + getattr(behavior_delta, dimension)
        capped = max(
            -settings.rel_max_event_delta, min(settings.rel_max_event_delta, total)
        )
        if abs(capped - total) > 1e-9:
            truncated[dimension] = capped - total
        capped = max(
            -settings.rel_max_turn_delta, min(settings.rel_max_turn_delta, capped)
        )
        if abs(capped - total) > 1e-9:
            truncated[dimension] = capped - total
        improving = capped < 0 if dimension == "tension" else capped > 0
        if capped != 0:
            used = getattr(day_positive if improving else day_negative, dimension)
            headroom = max(settings.rel_max_day_delta - used, 0.0)
            bounded = min(capped, headroom) if capped > 0 else -min(-capped, headroom)
            if abs(bounded - capped) > 1e-9:
                truncated[dimension] = bounded - capped
            capped = bounded
        limited[dimension] = capped
    return RelationshipDelta(**limited), truncated


def apply_comfort_drift(
    state: RelationshipState, conflict_active: bool
) -> tuple[RelationshipState, float]:
    """comfort 均衡回归（无信号轮也执行；不计限速与账本，计入因白名单）。"""
    settings = get_settings()
    baseline = comfort_baseline(state.stage, conflict_active)
    drift = (baseline - state.comfort) * settings.rel_comfort_drift
    if abs(drift) < 1e-9:
        return state, 0.0
    updated = state.model_copy(update={"comfort": clamp01(state.comfort + drift)})
    return updated, round(updated.comfort - state.comfort, 6)


def evolve(
    state: RelationshipState,
    event_type: str,
    magnitude: str,
    behavior: str,
    signal: InteractionSignal | None,
    repeats_by_kind: dict[tuple[str, str], int],
    day_positive: RelationshipDelta,
    day_negative: RelationshipDelta,
    now: datetime,
    session_id: str = "",
    user_id: str = "",
    cause: str = "",
    confidence: float = 0.0,
    window: tuple[tuple[str, str], ...] = (),
) -> tuple[RelationshipState, EvolutionOutcome]:
    """信号 → 事件 → 动力学 → 限速 → clamp（纯函数）；同事务落库由调用方完成。"""

    event_delta = build_relationship_impact(event_type, magnitude)
    behavior_delta = BEHAVIOR_DELTAS.get(behavior, RelationshipDelta())
    dynamics, flags = apply_dynamics(
        event_delta,
        state,
        repeats_by_kind,
        signal,
    )
    limited, truncated = rate_limit(
        state, dynamics, behavior_delta, day_positive, day_negative
    )
    new_values: dict[str, float] = {}
    applied: dict[str, float] = {}
    for dimension in RELATIONSHIP_DIMENSIONS:
        current = getattr(state, dimension)
        new_value = clamp01(current + getattr(limited, dimension))
        new_values[dimension] = new_value
        applied[dimension] = round(new_value - current, 6)
    stage = next_stage(
        new_values["intimacy"],
        new_values["trust"],
        new_values["familiarity"],
        state.stage,
        tension=new_values["tension"],
    )
    drifted, comfort_drift = apply_comfort_drift(
        RelationshipState(
            intimacy=new_values["intimacy"],
            trust=new_values["trust"],
            familiarity=new_values["familiarity"],
            respect=new_values["respect"],
            comfort=new_values["comfort"],
            tension=new_values["tension"],
            stage=stage,
            conflict_status=state.conflict_status,
            neglect_active=state.neglect_active,
            last_interaction_at=now,
            version=state.version + 1,
        ),
        state.conflict_status in ("conflict", "cold"),
    )
    event = None
    if event_type != "none":
        event = RelationshipEvent(
            user_id=user_id,
            session_id=session_id,
            type=event_type,
            magnitude=magnitude,
            impact=RelationshipDelta(**applied),
            confidence=confidence,
            source="conversation",
            cause=cause,
            created_at=now,
        )
    outcome = EvolutionOutcome(
        applied_delta=RelationshipDelta(**applied),
        event_type=event_type,
        magnitude=magnitude,
        event=event,
        truncated=truncated,
        window=window,
        flags=flags,
        comfort_drift_applied=comfort_drift,
        version_before=state.version,
        version_after=drifted.version,
    )
    return drifted, outcome


def replay(state: RelationshipState, events: list[Any]) -> RelationshipState:
    """重放（evolution-engine.md §6）：replay(state_0, stream) = state_t 对任意截断点成立。

    事件 impact 为实际生效值（含 system 结算），直接前向应用。
    """

    current = state
    for event in events:
        impact = event.impact
        updates = {
            dimension: clamp01(
                getattr(current, dimension) + getattr(impact, dimension)
            )
            for dimension in RELATIONSHIP_DIMENSIONS
        }
        updates["stage"] = next_stage(
            updates["intimacy"],
            updates["trust"],
            updates["familiarity"],
            current.stage,
            tension=updates["tension"],
        )
        updates["version"] = current.version + 1
        current = current.model_copy(update=updates)
    return current
