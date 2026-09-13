"""统一决策管线（V2.1.0 AGENT-004）：候选→优先级→六维评估→风险闸→选择。

前台与后台共用同一条代码路径；Intention 仍为 Decision 域值对象（13 值
枚举 + FIT 映射校验不变）。每次决策可回答四问：候选来源 / 胜出理由 /
逐闸结果 / 落选清单（candidates 审计包落 decision_records）。
"""

import logging
from dataclasses import dataclass, field
from typing import get_args

from app.core.settings import get_settings
from app.models.intention import (
    INTENTION_GOAL_DEFAULTS,
    INTENTION_GOAL_FIT,
    IntentionType,
)
from app.services import goal_alignment

logger = logging.getLogger(__name__)

_INTENTION_VALUES = frozenset(get_args(IntentionType))

P0 = 0
P1 = 1
P2 = 2
P3 = 3
P4 = 4
PRIORITY_LABELS = {0: "P0", 1: "P1", 2: "P2", 3: "P3", 4: "P4"}

_SOURCE_PRIORITY = {
    "user_directive": P0,
    "commitment_delivery": P1,
    "autonomy_trigger": P2,
    "goal_compile": P2,
    "turn_intention": P2,
    "capability": P3,
    "world_affordance": P3,
    "chat_response": P0,
    "silence": P4,
}

_GATE_PERSONA = "persona_precheck"
_GATE_RELATIONSHIP = "relationship_gate"
_GATE_ACTION = "action_check"
_GATE_BUDGET = "budget_cooldown"

# 六维权重（§5.2③）：和为 1；v21_decision_weight 为全局缩放（默认 1.0）
_DIMENSION_WEIGHTS = {
    "goal_alignment": 0.35,
    "state_fit": 0.15,
    "relationship_fit": 0.15,
    "timing": 0.15,
    "interest": 0.10,
    "cost": 0.10,
}

# 状态相容性：低能量/低强度状态下高主动候选不相容
_ACTION_SOURCES = ("autonomy_trigger", "goal_compile", "turn_intention")
_AFFORDANCE_SOURCES = ("capability", "world_affordance")
_LOW_MOODS = frozenset({"sad", "tired", "worried"})
_HIGH_TENSION = 0.6
_CARE_GOAL_TYPES = frozenset({"user_care", "relationship"})

_CAPABILITY_TYPE_HINTS = {
    "environment_query": "scene",
    "memory": "conversation",
    "notification": "user_care",
    "reminder": "user_care",
    "search": "conversation",
    "world_action": "scene",
}


@dataclass
class Candidate:
    source: str
    intention: str | None
    goal_id: str | None
    payload: dict = field(default_factory=dict)
    priority: int = P4
    scores: dict = field(default_factory=dict)
    total: float = 0.0
    gates: list = field(default_factory=list)
    rejected: bool = False
    won: bool = False

    def to_audit(self) -> dict:
        return {
            "source": self.source,
            "intention": self.intention,
            "goal_id": self.goal_id,
            "priority": PRIORITY_LABELS[self.priority],
            "scores": self.scores,
            "total": self.total,
            "gates": self.gates,
            "won": self.won,
        }


@dataclass
class DecisionResult:
    winner: Candidate | None
    intention: str | None
    audit: dict


def collect_candidates(
    stack=None,
    trigger_intention: str | None = None,
    trigger_goal_id: str | None = None,
    capabilities: list[str] | None = None,
    chat_response: bool = False,
    chat_response_intention: str | None = None,
    chat_response_goal_id: str | None = None,
    world_impacts: list[dict] | None = None,
) -> list[Candidate]:
    """候选汇集（纯规则）；silence 恒在；V2.3.0 支持世界影响候选。"""
    candidates: list[Candidate] = []
    if chat_response:
        candidates.append(
            Candidate("chat_response", chat_response_intention, chat_response_goal_id)
        )
    if trigger_intention:
        candidates.append(
            Candidate("autonomy_trigger", trigger_intention, trigger_goal_id)
        )
    if stack is not None:
        for layer in ("short_term", "medium", "long_term"):
            goal = getattr(stack, layer, None)
            if goal is not None:
                candidates.append(Candidate("goal_compile", None, goal.id, {"type": goal.type}))
                break
    for name in capabilities or []:
        candidates.append(
            Candidate("capability", None, None, {"capability": name, "type": _CAPABILITY_TYPE_HINTS.get(name, "")})
        )
    for impact in world_impacts or []:
        hint = impact.get("goal_opportunity") or {}
        if not hint.get("type"):
            continue
        candidates.append(
            Candidate(
                "world_affordance",
                None,
                None,
                {"type": hint.get("type", ""), "impact": impact},
            )
        )
    candidates.append(Candidate("silence", None, None))
    return candidates


def assign_priorities(candidates: list[Candidate]) -> None:
    for candidate in candidates:
        candidate.priority = _SOURCE_PRIORITY.get(candidate.source, P4)


def score_candidates(
    candidates: list[Candidate], stack=None, snapshot=None, run=None,
    world_schedule: dict | None = None,
) -> None:
    """六维规则评分（§5.2③）：每维取自 Snapshot / Goal Stack / 候选成本。

    无对应数据源时该维取中性 0.5（不臆造信号）；silence 恒为「与一切状态相容」。
    V2.3.0：world_schedule 提供日程信号，None 时路径与上一版本逐字节一致。
    """
    settings = get_settings()
    for candidate in candidates:
        alignment = goal_alignment.score(
            {"type": candidate.payload.get("type"), "capability": candidate.payload.get("capability")},
            stack,
        )
        scores = {
            "goal_alignment": alignment,
            "state_fit": _state_fit(candidate, snapshot),
            "relationship_fit": _relationship_fit(candidate, snapshot),
            "timing": _timing(candidate, snapshot, world_schedule),
            "interest": _interest(candidate, snapshot),
            "cost": _cost(candidate),
        }
        candidate.scores = scores
        weighted = sum(scores[name] * _DIMENSION_WEIGHTS[name] for name in scores)
        candidate.total = round(min(max(weighted * settings.v21_decision_weight, 0.0), 1.0), 4)


def _state_fit(candidate: Candidate, snapshot) -> float:
    """与 mood/energy 的匹配：低能量下高主动候选降分，关心类在低落情绪上升分。"""
    if snapshot is None:
        return 0.5
    if candidate.source == "silence":
        return 1.0
    energy = float(getattr(snapshot, "energy", 0.9) or 0.0)
    if candidate.source in _ACTION_SOURCES:
        score = 0.2 + 0.8 * energy
    elif candidate.source in _AFFORDANCE_SOURCES:
        score = 0.3 + 0.6 * energy
    else:
        score = 0.6
    mood = getattr(snapshot, "mood", "")
    if mood in _LOW_MOODS and candidate.payload.get("type") in _CARE_GOAL_TYPES:
        score += 0.15
    return round(min(max(score, 0.0), 1.0), 4)


def _relationship_fit(candidate: Candidate, snapshot) -> float:
    """与关系阶段/边界的匹配：张力高时社交与表达型候选降分。"""
    if snapshot is None:
        return 0.5
    if candidate.source == "silence":
        return 1.0
    relationship = getattr(snapshot, "relationship", None) or {}
    tension = float(relationship.get("tension") or 0.0)
    if tension >= _HIGH_TENSION and candidate.source in _ACTION_SOURCES + _AFFORDANCE_SOURCES:
        return 0.2
    return round(min(max(1.0 - tension * 0.5, 0.0), 1.0), 4)


_BUSY_ACTIVITIES = ("工作", "学习", "上课", "工作学习")


def _timing(candidate: Candidate, snapshot, world_schedule: dict | None = None) -> float:
    """冷却/在途间隔：已有进行中行动时不再叠加新行动候选。

    V2.3.0：工作/学习块内低紧迫候选降分；高关怀候选豁免（打断合理性）。"""
    if snapshot is None:
        base = 0.5
    else:
        focus = getattr(snapshot, "current_focus", None)
        in_progress = bool(getattr(focus, "action", "")) if focus is not None else False
        if not in_progress:
            base = 0.7
        elif candidate.source in _ACTION_SOURCES:
            base = 0.2
        else:
            base = 0.9
    if world_schedule is None:
        return base
    block = world_schedule.get("current_block") or {}
    activity = str(block.get("activity") or "")
    if activity and any(busy in activity for busy in _BUSY_ACTIVITIES):
        impact = candidate.payload.get("impact") or {}
        urgent = impact.get("urgency") in ("high",) or (impact.get("care_relevance") or 0) >= 0.8
        if not urgent:
            base = min(base, 0.35)
    return base


def _interest(candidate: Candidate, snapshot) -> float:
    """新颖度与兴趣信号：命中当前焦点目标得高分，否则按兴趣榜首递减。"""
    if snapshot is None:
        return 0.0
    focus = getattr(snapshot, "current_focus", None)
    if focus is not None and candidate.goal_id and candidate.goal_id == getattr(focus, "goal_id", None):
        return 0.6
    if candidate.source == "goal_compile" and candidate.payload.get("type"):
        topics = [t.topic for t in getattr(snapshot, "interest_focus", []) or []]
        if topics and candidate.payload["type"] in topics:
            return 0.4
    return 0.0


def _cost(candidate: Candidate) -> float:
    """预算与执行风险成本（成本越低分越高）：静默零成本恒 1.0。"""
    return {
        "silence": 1.0,
        "chat_response": 0.9,
        "goal_compile": 0.6,
        "turn_intention": 0.6,
        "autonomy_trigger": 0.5,
        "capability": 0.4,
        "world_affordance": 0.4,
    }.get(candidate.source, 0.5)


def run_risk_gates(
    candidates: list[Candidate], run=None, now=None, stack=None, snapshot=None
) -> None:
    """四闸固定顺序（§5.2④）：Persona 预检 → Relationship 闸门 → Action 检定 → 预算硬闸。

    Action 检定在 V9 执行链内进行（本处只声明 delegated，不冒充通过）；
    其余三闸逐候选给出真实判定与理由。
    """
    from app.application.agent_runtime import llm_gateway

    for candidate in candidates:
        gates = [
            _persona_gate(candidate, stack, snapshot),
            _relationship_gate(candidate, snapshot),
            {_GATE_ACTION: "delegated", "reason": "v9_execution_chain"},
        ]
        if candidate.source == "silence":
            gates.append({_GATE_BUDGET: "pass", "reason": "zero_cost"})
            candidate.gates = gates
            continue
        grant = llm_gateway.acquire(
            run.user_id if run else None,
            _gate_capability(candidate),
            run,
            now=now,
            account=False,
        )
        gates.append(
            {
                _GATE_BUDGET: "pass" if grant.granted else "rejected",
                "reason": grant.reason,
            }
        )
        candidate.gates = gates
        if not grant.granted or any(
            gate.get(_GATE_PERSONA) == "rejected" or gate.get(_GATE_RELATIONSHIP) == "rejected"
            for gate in gates
        ):
            candidate.rejected = True


def _persona_gate(candidate: Candidate, stack=None, snapshot=None) -> dict:
    """Persona 一致性预检：意图值合法 + 与目标类型 FIT + 人格轴在界内。

    注意 FIT 只覆盖「目标驱动型」意图；无 FIT 条目的合法意图（如 check_in）不判冲突。
    """
    intention = candidate.intention
    if intention is None and candidate.goal_id and stack is not None:
        intention = _intention_for(candidate, stack)
    if intention is not None:
        if intention not in _INTENTION_VALUES:
            return {_GATE_PERSONA: "rejected", "reason": "unknown_intention"}
        allowed = INTENTION_GOAL_FIT.get(intention)
        goal_type = candidate.payload.get("type") or _goal_type_of(candidate, stack)
        if allowed is not None and goal_type and goal_type not in allowed:
            return {_GATE_PERSONA: "rejected", "reason": "intention_goal_mismatch"}
    for axis in getattr(snapshot, "personality", None) or []:
        if not (axis.bound_min <= axis.current <= axis.bound_max):
            return {_GATE_PERSONA: "rejected", "reason": f"axis_out_of_bound:{axis.axis}"}
    return {_GATE_PERSONA: "pass", "reason": "no_conflict_rule"}


def _relationship_gate(candidate: Candidate, snapshot=None) -> dict:
    """Relationship 闸门：高张力下不出社交/表达型主动候选（沿 V9 自主闸门语义）。"""
    if snapshot is None:
        return {_GATE_RELATIONSHIP: "delegated", "reason": "no_snapshot"}
    if candidate.source not in _ACTION_SOURCES + _AFFORDANCE_SOURCES:
        return {_GATE_RELATIONSHIP: "pass", "reason": "not_social_candidate"}
    relationship = getattr(snapshot, "relationship", None) or {}
    tension = float(relationship.get("tension") or 0.0)
    if tension >= _HIGH_TENSION:
        return {_GATE_RELATIONSHIP: "rejected", "reason": "high_tension"}
    return {_GATE_RELATIONSHIP: "pass", "reason": "within_boundary"}


def _goal_type_of(candidate: Candidate, stack):
    if stack is None or not candidate.goal_id:
        return None
    for layer in ("short_term", "medium", "long_term"):
        goal = getattr(stack, layer, None)
        if goal is not None and goal.id == candidate.goal_id:
            return goal.type
    return None


def _gate_capability(candidate: Candidate) -> str:
    """闸门按候选所属预算档取能力：前台候选走前台档，其余走后台档。"""
    return "answer" if candidate.source == "chat_response" else "proactive"


def select(candidates: list[Candidate]) -> Candidate:
    """被闸拒绝的候选出局；其余按 P 级 → 综合分 → 确定性 tiebreak。"""
    eligible = [c for c in candidates if not c.rejected] or [
        c for c in candidates if c.source == "silence"
    ]
    winner = sorted(eligible, key=lambda c: (c.priority, -c.total, c.source != "silence"))[0]
    winner.won = True
    return winner


def _intention_for(candidate: Candidate, stack=None) -> str | None:
    if candidate.intention:
        return candidate.intention
    if candidate.source == "chat_response":
        return None
    goal = None
    if stack is not None and candidate.goal_id:
        for layer in ("short_term", "medium", "long_term"):
            g = getattr(stack, layer, None)
            if g is not None and g.id == candidate.goal_id:
                goal = g
                break
    goal_type = goal.type if goal is not None else candidate.payload.get("type")
    if goal_type and goal_type in INTENTION_GOAL_DEFAULTS:
        intention = INTENTION_GOAL_DEFAULTS[goal_type]
        allowed = INTENTION_GOAL_FIT.get(intention, frozenset())
        if goal_type in allowed:
            return intention
    return None


def run_pipeline(
    stack=None,
    snapshot=None,
    trigger_intention: str | None = None,
    trigger_goal_id: str | None = None,
    capabilities: list[str] | None = None,
    chat_response: bool = False,
    chat_response_intention: str | None = None,
    chat_response_goal_id: str | None = None,
    run=None,
    now=None,
    world_impacts: list[dict] | None = None,
    world_schedule: dict | None = None,
) -> DecisionResult:
    """五段管线唯一入口（前台 chat_response 与后台自主共用同一代码路径）。
    V2.3.0：world_impacts / world_schedule 为可选输入，None 时行为不变。"""
    candidates = collect_candidates(
        stack=stack,
        trigger_intention=trigger_intention,
        trigger_goal_id=trigger_goal_id,
        capabilities=capabilities,
        chat_response=chat_response,
        chat_response_intention=chat_response_intention,
        chat_response_goal_id=chat_response_goal_id,
        world_impacts=world_impacts,
    )
    assign_priorities(candidates)
    score_candidates(candidates, stack=stack, snapshot=snapshot, run=run, world_schedule=world_schedule)
    run_risk_gates(candidates, run=run, now=now, stack=stack, snapshot=snapshot)
    winner = select(candidates)
    intention = _intention_for(winner, stack)
    return DecisionResult(
        winner=winner,
        intention=intention,
        audit={"candidates": [c.to_audit() for c in candidates]},
    )
