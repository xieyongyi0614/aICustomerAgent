"""V7.5 评估上下文切片数据类（evaluation-model.md §4）。

只读切片载体：全部为纯数据类，无仓储依赖；收集逻辑见 `collectors`，
digest 组装见 `digest`。
"""

from dataclasses import dataclass, field
from datetime import datetime

DIGEST_USER_MESSAGE_CHARS = 200
DIGEST_REPLY_CHARS = 400
DIGEST_RECENT_CHARS = 120
DIGEST_MEMORY_CHARS = 40
DIGEST_RECENT_MESSAGES = 6
DIGEST_MEMORIES = 5

RECENT_TURNS_FOR_WINDOW = 6


@dataclass
class RecentMessage:
    role: str
    content: str
    mood_after: str | None = None


@dataclass
class EmotionSlice:
    mood_before: str | None = None
    mood_after: str | None = None
    intensity: float | None = None
    event: str | None = None
    magnitude: str | None = None
    cause: str | None = None


@dataclass
class BehaviorSlice:
    max_action_desc: int = 0
    physical_contact: str = "none"
    emotion_expression: str = "natural"
    strategy: str = ""
    observed_action_count: int = 0
    observed_contact_level: str = "none"


@dataclass
class StateSlice:
    mood: str | None = None
    energy: float | None = None
    stage: str | None = None
    intimacy: float | None = None


@dataclass
class MemoryRef:
    id: str
    type: str
    content: str
    importance: float = 0.0


@dataclass
class ProactiveSlice:
    action_id: str = ""
    trigger_type: str = ""
    intention: str = ""
    reason: str = ""
    delivered_at: object | None = None
    payload_text: str = ""
    previous_delivered_at: object | None = None
    last_user_message_at: object | None = None
    episode_attempts: int = 1


@dataclass
class RelationshipSlice:
    before: dict | None = None
    after: dict | None = None
    applied: dict | None = None
    truncated: dict | None = None
    day_positive: dict | None = None
    day_negative: dict | None = None
    events: list = field(default_factory=list)
    signal_present: bool = False
    comfort_drift: float = 0.0
    conflict_status: str = "none"


@dataclass
class InsightRef:
    id: str
    statement: str
    status: str
    confidence: float = 0.0
    evidence_count: int = 0


@dataclass
class ReflectionSlice:
    insights: list[InsightRef] = field(default_factory=list)
    injected_insight_ids: list[str] = field(default_factory=list)


@dataclass
class DevelopmentStateRef:
    id: str
    key: str
    kind: str
    status: str
    strength: float = 0.0
    value: dict = field(default_factory=dict)
    source_insight_id: str = ""


@dataclass
class DevelopmentChangeRef:
    id: str
    state_id: str
    insight_id: str
    reason: str = ""
    before: dict | None = None
    after: dict | None = None


@dataclass
class DevelopmentSlice:
    active_states: list[DevelopmentStateRef] = field(default_factory=list)
    changes: list[DevelopmentChangeRef] = field(default_factory=list)
    insight_statuses: dict[str, str] = field(default_factory=dict)


@dataclass
class NarrativeFactRef:
    id: str
    type: str
    source_ref: dict | None = None


@dataclass
class NarrativeMilestoneRef:
    id: str
    milestone_key: str
    meta: dict | None = None


@dataclass
class NarrativeSlice:
    """REL-004 叙事事实审计切片（只读）；缺席为 None = 规则跳过。"""

    facts: list[NarrativeFactRef] = field(default_factory=list)
    narrative_milestones: list[NarrativeMilestoneRef] = field(default_factory=list)
    insight_ids: set[str] = field(default_factory=set)


@dataclass
class LifeLoopRunRef:
    """LIFE-006 周期 run 审计引用（只读摘要）。"""

    run_id: str
    kind: str
    status: str
    reason: str = ""
    step_names: list[str] = field(default_factory=list)
    llm_call_count: int = 0
    budget_degraded: bool = False
    aborted_with_reason: bool = True


@dataclass
class LifeLoopTriggerRef:
    trigger_key: str
    trigger_type: str
    status: str
    attempt_count: int = 0
    stale: bool = False
    cancelled_without_reason: bool = False


@dataclass
class LifeLoopProactiveRef:
    action_id: str
    trigger_type: str = ""
    provenanced: bool = True


@dataclass
class LifeLoopSlice:
    """LIFE-006 Life Loop 审计切片（只读）；缺席为 None = 规则跳过。"""

    runs: list[LifeLoopRunRef] = field(default_factory=list)
    triggers: list[LifeLoopTriggerRef] = field(default_factory=list)
    delivered_proactive: list[LifeLoopProactiveRef] = field(default_factory=list)
    day_llm_calls: int = 0
    day_llm_call_limit: int = 0
    outbox_dead_letters: int = 0

@dataclass
class ActionSlice:
    records: list = field(default_factory=list)
    intent: dict | None = None

    def has_succeeded(self, action_type: str, session_id: str | None = None) -> bool:
        return any(
            r.get("action_type") == action_type
            and r.get("status") == "succeeded"
            and (session_id is None or r.get("session_id") == session_id)
            for r in self.records
        )


@dataclass
class GoalRef:
    goal_id: str
    layer: str
    domain: str
    status: str
    horizon: str = ""
    parent_goal_id: str | None = None
    failure_reason: str | None = None
    arbitration_state: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class GoalPlanRef:
    goal_id: str
    version: int
    status: str
    sub_goal_statuses: list[str] = field(default_factory=list)
    sub_goal_attempt_counts: list[int] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
    updated_at: datetime | None = None


@dataclass
class GoalLifecycleRef:
    goal_id: str
    decision: str
    reason: str = ""
    created_at: datetime | None = None


@dataclass
class GoalSlice:
    """AUT-005 Goal 审计切片（只读）；缺席为 None = 规则跳过。"""

    goals: list[GoalRef] = field(default_factory=list)
    plans: list[GoalPlanRef] = field(default_factory=list)
    lifecycles: list[GoalLifecycleRef] = field(default_factory=list)

@dataclass
class EvaluationContext:
    subject: str
    subject_id: str
    session_id: str
    user_id: str
    character_id: str = "asuna"
    mode: str = "default"
    stage: str = "friend"
    user_message: str = ""
    reply: str = ""
    recent_messages: list[RecentMessage] = field(default_factory=list)
    injected_memories: list[MemoryRef] = field(default_factory=list)
    emotion: EmotionSlice = field(default_factory=EmotionSlice)
    behavior: BehaviorSlice | None = None
    behavior_history: list[list[str]] = field(default_factory=list)
    state: StateSlice = field(default_factory=StateSlice)
    proactive: ProactiveSlice | None = None
    request_id: str = ""
    fidelity: str = "live"
    world: dict | None = None
    relationship: RelationshipSlice | None = None
    action: ActionSlice | None = None
    reflection: ReflectionSlice | None = None
    development: DevelopmentSlice | None = None
    narrative: NarrativeSlice | None = None
    life_loop: LifeLoopSlice | None = None
    goal: GoalSlice | None = None


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return text[:limit]
