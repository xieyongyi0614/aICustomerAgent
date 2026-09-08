"""V6.5 Behavior Engine（behavior-strategy.md §3 / action-budget.md §4 / habit-system.md §4~5 / activity-state.md §3~4）。

纯函数：intention → strategy（确定性映射 + 白名单修饰）→ Budget（7 步预算表）
→ habit 匹配（≤2 条）→ activity 分类。无 IO、无 LLM。
observe_budget 为输出侧只读统计（V6.5-010），不阻塞不重写。
"""

import logging
import re
from dataclasses import dataclass

from app.character.asuna.behavior_policy import BEHAVIOR_POLICY, STRATEGY_INSTRUCTIONS
from app.models.behavior_strategy import (
    ActionBudget,
    BehaviorDirective,
    BehaviorStrategy,
    BehaviorStrategyType,
    HabitDomain,
    HabitRule,
    PhysicalContactLevel,
    StageBehaviorParams,
)
from app.models.scene import SceneContext
from app.services import habit_runtime
from app.character.asuna.behavior_instructions import BEHAVIOR_INSTRUCTIONS

logger = logging.getLogger(__name__)

INTENTION_STRATEGY_MAP: dict[str, BehaviorStrategyType] = {
    "comfort_user": "quiet_companion",
    "suggest_rest": "gentle_redirect",
    "encourage_user": "direct_support",
    "celebrate_with_user": "warm_celebration",
    "express_affection": "affectionate_expression",
    "tease_user": "playful_tease",
    "maintain_distance": "reserved_distance",
    "repair_rapport": "sincere_repair",
    "continue_topic": "natural_continuation",
    "ask_followup": "curious_inquiry",
    "share_own_feeling": "self_disclosure",
    "lighten_mood": "playful_tease",
}

NO_ACTION_STRATEGIES = frozenset({"quiet_companion", "reserved_distance", "sincere_repair"})

HABIT_APPLICABILITY: dict[str, set[HabitDomain]] = {
    "quiet_companion": {"relate", "pace"},
    "direct_support": {"relate", "pace"},
    "gentle_redirect": {"relate", "pace"},
    "warm_celebration": {"express", "relate"},
    "playful_tease": {"express"},
    "affectionate_expression": {"express", "relate"},
    "reserved_distance": {"express", "pace"},
    "sincere_repair": {"relate", "express"},
    "natural_continuation": {"pace", "relate", "express"},
    "curious_inquiry": {"pace"},
    "self_disclosure": {"express"},
    "focused_assistance": set(),
}

HABIT_MAX_COUNT = 2

# 与 strategy 语义同向、不重复渲染的 habit（habit-system.md §5 去重表）
HABIT_SAME_DIRECTION: dict[str, frozenset[str]] = {
    "quiet_companion": frozenset({"habit_comfort_companion_first"}),
    "sincere_repair": frozenset({"habit_angry_restrained"}),
}

SCENE_ADVANCING_INTENTS = frozenset(
    {"request_action", "continue_scene", "correct_scene", "interrupt"}
)

SOCIAL_COMFORT_STRATEGIES = frozenset(
    {
        "affectionate_expression",
        "warm_celebration",
        "playful_tease",
        "direct_support",
        "curious_inquiry",
        "self_disclosure",
    }
)

STAGE_RANK = {"stranger": 0, "friend": 1, "close_friend": 2, "partner": 3}


@dataclass
class RelationshipBehaviorContext:
    stage: str = "friend"
    comfort: float = 0.6
    respect: float = 0.6
    conflict_status: str = "none"
    unlocks: tuple[str, ...] = ()


def classify_activity(scene_state) -> tuple[str, str | None]:
    if scene_state is None:
        return "idle", None
    if scene_state.pending_action is not None and scene_state.pending_action.status == "pending":
        return "pending_obligation", scene_state.pending_action.action
    if scene_state.current_action is not None:
        return "engaged_action", scene_state.current_action
    if scene_state.current_activity is not None:
        return "ambient_activity", scene_state.current_activity
    return "idle", None


def _base_strategy(intention: str) -> BehaviorStrategyType:
    strategy = INTENTION_STRATEGY_MAP.get(intention)
    if strategy is None:
        logger.warning("intention 无映射：%s，兜底 natural_continuation", intention)
        return "natural_continuation"
    return strategy


def _apply_modifiers(
    base: BehaviorStrategyType,
    intention: str,
    mode: str,
    tension: float,
    energy: float,
    stage: str,
    mood: str,
    scene_pending: bool,
    intensity: float,
) -> tuple[BehaviorStrategyType, list[str]]:
    strategy = base
    rules: list[str] = []
    if mode == "professional":
        strategy = "focused_assistance"
        rules.append("mode_professional")
        return strategy, rules
    if tension > 0.5 and intention != "repair_rapport":
        strategy = "reserved_distance"
        rules.append("tension_reserved")
    if (
        intention == "comfort_user"
        and energy >= 0.7
        and stage in ("close_friend", "partner")
        and strategy == "quiet_companion"
    ):
        strategy = "direct_support"
        rules.append("comfort_upgrade")
    if mood in ("tired", "sad") and strategy in ("playful_tease", "warm_celebration"):
        strategy = "natural_continuation"
        rules.append("low_energy_calm")
    if scene_pending and strategy != "natural_continuation":
        strategy = "natural_continuation"
        rules.append("scene_pending_collapse")
    if intensity >= 0.8:
        rules.append("strong_emotion_budget_zero")
    return strategy, rules


def _mode_baseline(mode: str) -> tuple[int, bool]:
    if mode == "professional":
        return 0, False
    if mode == "immersive":
        return 2, True
    return 1, True


def compute_budget(
    mode: str,
    stage_params: StageBehaviorParams,
    mood_factor: float,
    strategy: BehaviorStrategyType,
    scene: SceneContext | None,
    intensity: float,
) -> ActionBudget:
    baseline, allow = _mode_baseline(mode)
    max_desc = min(baseline, stage_params.action_desc_max)
    max_desc = round(min(max_desc * mood_factor, max_desc))
    physical_contact: PhysicalContactLevel = (
        "none" if mode == "professional" else stage_params.physical_contact
    )
    if strategy in NO_ACTION_STRATEGIES:
        max_desc = 0
    if strategy == "affectionate_expression":
        physical_contact = stage_params.physical_contact
    activity, _ = classify_activity(scene.state if scene is not None else None)
    if activity != "idle":
        max_desc = max(0, max_desc - 1)
    if intensity >= 0.8:
        max_desc = 0
    emotion_expression = "rich" if mode == "immersive" else "natural"
    if mode == "professional":
        emotion_expression = "subtle"
    return ActionBudget(
        max_action_desc=max_desc,
        allow_action_desc=allow,
        physical_contact=physical_contact,
        emotion_expression=emotion_expression,
        action_desc_factor=mood_factor,
    )


def match_habits(
    strategy: BehaviorStrategyType, extra_candidates: list[HabitRule] | None = None
) -> list[HabitRule]:
    domains = HABIT_APPLICABILITY.get(strategy, set())
    effective = habit_runtime.load_effective_habits()
    candidates = [habit for habit in effective if habit.domain in domains]
    if extra_candidates:
        known_ids = {habit.id for habit in effective}
        for habit in extra_candidates:
            if habit.id in known_ids or habit.domain not in domains:
                continue
            known_ids.add(habit.id)
            candidates.append(habit)
    ordered = [
        habit
        for _, habit in sorted(
            enumerate(candidates), key=lambda item: (item[1].priority, item[0])
        )
    ]
    same_direction = HABIT_SAME_DIRECTION.get(strategy, frozenset())
    return [h for h in ordered if h.id not in same_direction][:HABIT_MAX_COUNT]


def _degraded_directive(analysis=None) -> BehaviorDirective:
    fallback = None
    if analysis is not None:
        behavior = getattr(getattr(analysis, "behavior", None), "behavior", "normal_reply")

        fallback = BEHAVIOR_INSTRUCTIONS.get(
            behavior, BEHAVIOR_INSTRUCTIONS["normal_reply"]
        )
    return BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="natural_continuation",
            base_strategy="natural_continuation",
            degraded=True,
        ),
        budget=ActionBudget(),
        fallback_v2=fallback,
    )


def _apply_relationship_modifiers(
    strategy: BehaviorStrategyType,
    budget: ActionBudget,
    rules: list[str],
    ctx: RelationshipBehaviorContext | None,
) -> tuple[BehaviorStrategyType, ActionBudget, list[str]]:
    """B1~B5（behavior-integration.md §4）：relationship_ctx=None 时原样返回。"""
    if ctx is None:
        return strategy, budget, rules
    updated_rules = list(rules)
    max_desc = budget.max_action_desc
    if ctx.conflict_status in ("conflict", "cold") and strategy in SOCIAL_COMFORT_STRATEGIES:
        strategy = "reserved_distance"
        max_desc = max_desc // 2
        updated_rules.append("B1_conflict_restrained")
    if ctx.comfort < 0.35:
        max_desc = max(0, max_desc - 1)
        updated_rules.append("B2_low_comfort")
    if ctx.respect < 0.40 and strategy in (
        "affectionate_expression",
        "playful_tease",
        "warm_celebration",
    ):
        strategy = "natural_continuation"
        updated_rules.append("B3_low_respect")
    if STAGE_RANK.get(ctx.stage, 0) >= STAGE_RANK["close_friend"] and ctx.comfort > 0.7:
        max_desc = max_desc + 1
        if strategy == "reserved_distance":
            strategy = "natural_continuation"
        updated_rules.append("B4_high_comfort")
    if (
        "deep_commitment_language" not in ctx.unlocks
        and strategy == "affectionate_expression"
        and ctx.stage == "partner"
    ):
        strategy = "natural_continuation"
        updated_rules.append("B5_locked_commitment")
    return (
        strategy,
        budget.model_copy(update={"max_action_desc": max_desc}),
        updated_rules,
    )


def resolve(
    intention,
    state,
    scene_ctx: SceneContext | None,
    mode: str,
    analysis=None,
    relationship_ctx: RelationshipBehaviorContext | None = None,
    development_overlay=None,
) -> BehaviorDirective:
    try:
        return _resolve(
            intention,
            state,
            scene_ctx,
            mode,
            analysis,
            relationship_ctx,
            development_overlay,
        )
    except Exception:
        logger.exception("behavior_engine 解析失败，降级默认 directive")
        return _degraded_directive(analysis)


def _resolve(
    intention,
    state,
    scene_ctx: SceneContext | None,
    mode: str,
    analysis=None,
    relationship_ctx: RelationshipBehaviorContext | None = None,
    development_overlay=None,
) -> BehaviorDirective:
    if intention is None or getattr(intention, "degraded", False):
        directive = _degraded_directive(analysis)
        directive.budget = _mode_budget(state, scene_ctx, mode)
        return _attach_activity(directive, scene_ctx)

    intention_name = intention.intention
    base = _base_strategy(intention_name)
    relationship = state.relationship_state
    character = state.character_state
    strategy_value, rules = _apply_modifiers(
        base,
        intention_name,
        mode,
        tension=relationship.tension,
        energy=character.energy,
        stage=relationship.stage,
        mood=character.mood,
        scene_pending=_is_pending(scene_ctx),
        intensity=character.intensity,
    )
    policy = BEHAVIOR_POLICY
    stage_params = policy.stage_params[relationship.stage]
    mood_modifier = policy.mood_modifiers[character.mood]
    budget = compute_budget(
        mode,
        stage_params,
        mood_modifier.action_desc_factor,
        strategy_value,
        scene_ctx,
        character.intensity,
    )
    strategy_value, budget, rules = _apply_relationship_modifiers(
        strategy_value, budget, rules, relationship_ctx
    )
    strategy = BehaviorStrategy(
        strategy=strategy_value,
        base_strategy=base,
        applied_rules=rules,
        instruction=STRATEGY_INSTRUCTIONS.get(strategy_value, ""),
        mood_tone=mood_modifier.tone_directive,
        degraded=False,
    )
    directive = BehaviorDirective(
        strategy=strategy,
        budget=budget,
        habits=match_habits(
            strategy_value,
            extra_candidates=_overlay_habit_candidates(development_overlay),
        ),
    )
    if development_overlay is not None:
        directive.development_care_hint = development_overlay.care_hint or ""
        directive.development_style = development_overlay.style
    return _attach_activity(directive, scene_ctx)


def _overlay_habit_candidates(development_overlay) -> list[HabitRule] | None:
    """overlay 候选 dict → HabitRule（非法形状丢弃，不进生效集资产）。"""
    if development_overlay is None or not development_overlay.habit_candidates:
        return None
    candidates: list[HabitRule] = []
    for candidate in development_overlay.habit_candidates:
        try:
            candidates.append(HabitRule(**candidate))
        except Exception:
            logger.warning("development habit 候选非法，丢弃：%s", candidate)
    return candidates or None


def _mode_budget(state, scene_ctx: SceneContext | None, mode: str) -> ActionBudget:
    policy = BEHAVIOR_POLICY
    stage_params = policy.stage_params[state.relationship_state.stage]
    mood_factor = policy.mood_modifiers[state.character_state.mood].action_desc_factor
    return compute_budget(
        mode,
        stage_params,
        mood_factor,
        "natural_continuation",
        scene_ctx,
        state.character_state.intensity,
    )


def _attach_activity(
    directive: BehaviorDirective, scene_ctx: SceneContext | None
) -> BehaviorDirective:
    activity, activity_text = classify_activity(
        scene_ctx.state if scene_ctx is not None else None
    )
    if activity == "idle":
        return directive
    if activity == "pending_obligation" or _continuation_scene_intent(scene_ctx):
        directive.activity = activity
        directive.activity_text = activity_text
    return directive


def _continuation_scene_intent(scene_ctx: SceneContext | None) -> bool:
    return scene_ctx is None or scene_ctx.intent in ("chat", "question", "emotional")


def _is_pending(scene_ctx: SceneContext | None) -> bool:
    return (
        scene_ctx is not None
        and scene_ctx.state.pending_action is not None
        and scene_ctx.state.pending_action.status == "pending"
    )


ACTION_DESC_PATTERN = re.compile(r"\*[^*\n]+\*")

CONTACT_LEVELS = ("none", "light", "moderate")

LIGHT_CONTACT_WORDS = (
    "递给",
    "递到",
    "递上",
    "整理衣角",
    "整理衣领",
    "理了理",
    "拍了拍",
    "搭在肩",
)
MODERATE_CONTACT_WORDS = (
    "牵手",
    "牵起",
    "握住",
    "拉住",
    "挽住",
    "拥抱",
    "抱住",
    "搂",
    "亲吻",
    "吻了",
)


def _observed_contact_level(reply: str) -> str:
    if any(word in reply for word in MODERATE_CONTACT_WORDS):
        return "moderate"
    if any(word in reply for word in LIGHT_CONTACT_WORDS):
        return "light"
    return "none"


def observe_budget(reply: str, budget) -> dict:
    if reply is None:
        reply = ""
    action_count = len(ACTION_DESC_PATTERN.findall(reply))
    contact_level = _observed_contact_level(reply)
    action_violated = action_count > budget.max_action_desc
    contact_violated = (
        CONTACT_LEVELS.index(contact_level) > CONTACT_LEVELS.index(budget.physical_contact)
    )
    return {
        "action_count": action_count,
        "contact_level": contact_level,
        "budget_max": budget.max_action_desc,
        "budget_contact": budget.physical_contact,
        "action_violated": action_violated,
        "contact_violated": contact_violated,
        "violated": action_violated or contact_violated,
    }
