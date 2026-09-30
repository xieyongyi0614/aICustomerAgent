"""V7.5 评估上下文包：切片 / 收集器 / digest。

由 `evaluation_context.py`（834 行）拆分归位（services-reorganization-plan
§十②，2026-09-30）；本 `__init__` 全量再导出，既有 `from ...context import X`
消费面零改动。
"""

from app.services.evaluation.context.digest import (
    build_digest,
    _proactive_digest,
    _truncate_digest,
    _LOW_PRIORITY_KEYS,
)
from app.services.evaluation.context.collectors import (
    collect_goal_slice,
    collect_life_loop_slice,
    collect_proactive_context,
    collect_turn_context,
)
from app.services.evaluation.context.slices import (
    ActionSlice,
    BehaviorSlice,
    DevelopmentChangeRef,
    DevelopmentSlice,
    DevelopmentStateRef,
    DIGEST_MEMORY_CHARS,
    DIGEST_MEMORIES,
    DIGEST_RECENT_CHARS,
    DIGEST_RECENT_MESSAGES,
    DIGEST_REPLY_CHARS,
    DIGEST_USER_MESSAGE_CHARS,
    EmotionSlice,
    EvaluationContext,
    GoalLifecycleRef,
    GoalPlanRef,
    GoalRef,
    GoalSlice,
    InsightRef,
    LifeLoopProactiveRef,
    LifeLoopRunRef,
    LifeLoopSlice,
    LifeLoopTriggerRef,
    MemoryRef,
    NarrativeFactRef,
    NarrativeMilestoneRef,
    NarrativeSlice,
    ProactiveSlice,
    RecentMessage,
    ReflectionSlice,
    RelationshipSlice,
    RECENT_TURNS_FOR_WINDOW,
    StateSlice,
    _clip,
)

__all__ = [name for name in dir() if not name.startswith("_")] or []
