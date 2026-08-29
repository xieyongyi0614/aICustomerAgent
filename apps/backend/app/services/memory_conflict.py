from dataclasses import dataclass

from app.core.settings import get_settings
from app.models.memory import MemoryCandidate, UserMemory

ACTION_SAVE = "save"
ACTION_UPDATE = "update"
ACTION_SUPERSEDE = "supersede"
ACTION_INVALIDATE = "invalidate"
ACTION_DISCARD_PAIR = "discard_pair"
ACTION_NOOP = "noop"


@dataclass
class ConflictOutcome:
    candidate: MemoryCandidate
    action: str
    target_id: str | None
    reason: str


def _lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    for char_a in a:
        current = [0]
        for index, char_b in enumerate(b, start=1):
            if char_a == char_b:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1]


def same_topic(left: str, right: str, threshold: float | None = None) -> bool:
    left = (left or "").strip()
    right = (right or "").strip()
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    resolved_threshold = (
        threshold if threshold is not None else get_settings().memory_conflict_threshold
    )
    longer = max(len(left), len(right))
    return _lcs_length(left, right) / longer >= resolved_threshold


def _find_matches(
    candidate: MemoryCandidate, active_memories: list[UserMemory]
) -> list[UserMemory]:
    content = candidate.content or ""
    return [
        memory
        for memory in active_memories
        if memory.type == candidate.type
        and memory.status == "active"
        and same_topic(content, memory.content)
    ]


def _best_match(
    candidate: MemoryCandidate, matches: list[UserMemory]
) -> UserMemory:
    content = candidate.content or ""
    return max(
        matches,
        key=lambda memory: (
            _lcs_length(content, memory.content) / max(len(memory.content), 1),
            memory.created_at,
        ),
    )


def resolve_candidate(
    candidate: MemoryCandidate,
    active_memories: list[UserMemory],
    threshold: float | None = None,
) -> ConflictOutcome:
    if candidate.action == "invalidate":
        targeted = None
        if candidate.target_memory_id:
            targeted = next(
                (
                    memory
                    for memory in active_memories
                    if memory.id == candidate.target_memory_id
                ),
                None,
            )
        if targeted is None:
            matches = _find_matches(candidate, active_memories)
            targeted = _best_match(candidate, matches) if matches else None
        if targeted is None:
            return ConflictOutcome(
                candidate, ACTION_NOOP, None, "invalidate 未找到目标记忆，忽略"
            )
        return ConflictOutcome(
            candidate, ACTION_INVALIDATE, targeted.id, "用户否定既有记忆"
        )

    matches = _find_matches(candidate, active_memories)
    if not matches:
        return ConflictOutcome(candidate, ACTION_SAVE, None, "无同主题记忆，直接保存")
    target = _best_match(candidate, matches)
    if candidate.relation == "refine":
        return ConflictOutcome(
            candidate, ACTION_UPDATE, target.id, "新信息为旧记忆的精化"
        )
    return ConflictOutcome(
        candidate, ACTION_SUPERSEDE, target.id, "同主题不同内容，默认以新代旧"
    )


def resolve_batch(
    candidates: list[MemoryCandidate],
    active_memories: list[UserMemory],
    threshold: float | None = None,
) -> list[ConflictOutcome]:
    outcomes: list[ConflictOutcome] = []
    save_candidates = [c for c in candidates if c.action in ("save", "update")]
    conflicted_ids: set[int] = set()
    for i in range(len(save_candidates)):
        for j in range(i + 1, len(save_candidates)):
            first, second = save_candidates[i], save_candidates[j]
            if first.type == second.type and same_topic(
                first.content or "", second.content or "", threshold
            ):
                conflicted_ids.update({id(first), id(second)})
                outcomes.append(
                    ConflictOutcome(
                        first,
                        ACTION_DISCARD_PAIR,
                        None,
                        "同轮候选互相矛盾，成对丢弃",
                    )
                )
                outcomes.append(
                    ConflictOutcome(
                        second,
                        ACTION_DISCARD_PAIR,
                        None,
                        "同轮候选互相矛盾，成对丢弃",
                    )
                )
    for candidate in save_candidates:
        if id(candidate) in conflicted_ids:
            continue
        outcomes.append(resolve_candidate(candidate, active_memories, threshold))
    for candidate in candidates:
        if candidate.action == "invalidate":
            outcomes.append(resolve_candidate(candidate, active_memories, threshold))
    return outcomes
