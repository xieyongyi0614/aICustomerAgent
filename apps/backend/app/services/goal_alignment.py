"""Goal Alignment Scorer（V2.1.0 AGENT-003）：候选行动与活跃目标栈的对齐度。

纯函数接口契约（AGENT-004 决策管线消费，本任务冻结）：
score(candidate, stack) -> float ∈ [0, 1]；candidate 为 {"type": str} 形状
（capability 候选可附 "capability"）；空栈 / 空候选恒 0。
"""

from app.models.goal import GOAL_TIER

_LAYER_WEIGHT = {"short_term": 1.0, "medium": 0.6, "long_term": 0.3}

_CAPABILITY_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "environment_query": ("scene",),
    "memory": ("conversation",),
    "notification": ("user_care",),
    "reminder": ("user_care",),
    "search": ("conversation",),
    "world_action": ("scene",),
}


def score(candidate: dict | None, stack) -> float:
    if not candidate or stack is None:
        return 0.0
    candidate_type = candidate.get("type") or ""
    capability = candidate.get("capability")
    best = 0.0
    for layer, weight in _LAYER_WEIGHT.items():
        goal = getattr(stack, layer, None)
        if goal is None:
            continue
        match = _match_score(candidate_type, capability, goal)
        best = max(best, weight * match)
    return round(min(best, 1.0), 4)


def _match_score(candidate_type: str, capability: str | None, goal) -> float:
    score = 0.0
    if candidate_type and candidate_type == goal.type:
        score = max(score, 1.0)
    elif candidate_type and goal.domain and _type_in_domain(candidate_type, goal.domain):
        score = max(score, 0.6)
    if capability:
        hints = _CAPABILITY_DOMAIN_HINTS.get(capability) or ()
        domain = goal.domain or ""
        if domain in hints or goal.type in hints:
            score = max(score, 0.6)
        elif not candidate_type:
            score = max(score, 0.3)
    if not score and goal.type == "scene":
        score = max(score, 0.2)
    return score


def _type_in_domain(candidate_type: str, domain: str) -> bool:
    return GOAL_TIER.get(candidate_type, 9) < 9 and bool(domain)
