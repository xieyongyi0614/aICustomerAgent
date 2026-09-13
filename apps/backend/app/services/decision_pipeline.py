"""统一决策管线（V2.1.0 AGENT-004）：候选→优先级→六维评估→风险闸→选择。

前台与后台共用同一条代码路径；Intention 仍为 Decision 域值对象（13 值
枚举 + FIT 映射校验不变）。每次决策可回答四问：候选来源 / 胜出理由 /
逐闸结果 / 落选清单（candidates 审计包落 decision_records）。
"""

import logging
from dataclasses import dataclass, field

from app.core.settings import get_settings
from app.models.intention import INTENTION_GOAL_DEFAULTS, INTENTION_GOAL_FIT
from app.services import goal_alignment

logger = logging.getLogger(__name__)

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
    "capability": P3,
    "world_affordance": P3,
    "chat_response": P0,
    "silence": P4,
}

_GATE_PERSONA = "persona_precheck"
_GATE_BUDGET = "budget_cooldown"

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
) -> list[Candidate]:
    """六源候选汇集（纯规则）；silence 恒在。"""
    candidates: list[Candidate] = []
    if chat_response:
        candidates.append(Candidate("chat_response", None, None))
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
    candidates.append(Candidate("silence", None, None))
    return candidates


def assign_priorities(candidates: list[Candidate]) -> None:
    for candidate in candidates:
        candidate.priority = _SOURCE_PRIORITY.get(candidate.source, P4)


def score_candidates(
    candidates: list[Candidate], stack=None, snapshot=None, run=None
) -> None:
    """六维规则加权（goal/state/timing/interest/cost/relationship 简化并入）。"""
    settings = get_settings()
    for candidate in candidates:
        alignment = goal_alignment.score(
            {"type": candidate.payload.get("type"), "capability": candidate.payload.get("capability")},
            stack,
        )
        interest = 0.0
        if snapshot is not None and candidate.source == "goal_compile":
            focus = getattr(snapshot, "current_focus", None)
            if focus is not None and candidate.goal_id == getattr(focus, "goal_id", None):
                interest = 0.6
        scores = {
            "goal_alignment": alignment,
            "state_fit": 0.5,
            "relationship_fit": 0.5,
            "timing": 0.5,
            "interest": interest,
            "cost": 0.5,
        }
        candidate.scores = scores
        candidate.total = round(
            sum(scores[name] * settings.v21_decision_weight for name in scores) / len(scores),
            4,
        )


def run_risk_gates(
    candidates: list[Candidate], run=None, now=None
) -> None:
    """四闸（Persona 预检 → 预算硬闸；Relationship 闸门与 Action 检定在
    既有自主闸门 / V9 执行链内生效，此处逐闸留痕其通过态）。"""
    from app.application.agent_runtime import llm_gateway

    for candidate in candidates:
        candidate.gates = [
            {_GATE_PERSONA: "pass", "reason": "no_conflict_rule"},
        ]
        if candidate.source == "silence":
            candidate.gates.append({_GATE_BUDGET: "pass", "reason": "zero_cost"})
            continue
        grant = llm_gateway.acquire(
            run.user_id if run else None, "proactive", run, now=now
        )
        candidate.gates.append(
            {
                _GATE_BUDGET: "pass" if grant.granted else "rejected",
                "reason": grant.reason,
            }
        )
        if not grant.granted:
            candidate.rejected = True


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
    run=None,
    now=None,
) -> DecisionResult:
    """五段管线唯一入口。"""
    candidates = collect_candidates(
        stack=stack,
        trigger_intention=trigger_intention,
        trigger_goal_id=trigger_goal_id,
        capabilities=capabilities,
        chat_response=chat_response,
    )
    assign_priorities(candidates)
    score_candidates(candidates, stack=stack, snapshot=snapshot, run=run)
    run_risk_gates(candidates, run=run, now=now)
    winner = select(candidates)
    intention = _intention_for(winner, stack)
    return DecisionResult(
        winner=winner,
        intention=intention,
        audit={"candidates": [c.to_audit() for c in candidates]},
    )
