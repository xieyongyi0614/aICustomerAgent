import re
from dataclasses import dataclass, field

from app.core.settings import get_settings
from app.models.memory import MemoryCandidate

DECISION_SAVE = "save"
DECISION_DISCARD = "discard"
DECISION_PRIVACY = "privacy"

ONE_OFF_PATTERN = re.compile(r"今天|今晚|昨晚|刚才|刚刚|马上|等一下|一会儿")

UNRESOLVED_REFERENCE_PATTERN = re.compile(r"它|那个|他|她")


@dataclass
class PolicyOutcome:
    candidate: MemoryCandidate
    decision: str
    rule: str
    reason: str


@dataclass
class PolicyReport:
    outcomes: list[PolicyOutcome] = field(default_factory=list)

    @property
    def saved(self) -> list[MemoryCandidate]:
        return [o.candidate for o in self.outcomes if o.decision == DECISION_SAVE]

    @property
    def privacy_items(self) -> list[MemoryCandidate]:
        return [o.candidate for o in self.outcomes if o.decision == DECISION_PRIVACY]

    @property
    def discarded(self) -> list[PolicyOutcome]:
        return [o for o in self.outcomes if o.decision == DECISION_DISCARD]

    def has_suppress(self) -> bool:
        return any(o.rule == "R2" for o in self.outcomes)


def _is_exact_duplicate(content: str, active_contents: list[str]) -> bool:
    normalized = content.strip()
    return any(normalized == existing.strip() for existing in active_contents)


def _evaluate(
    candidate: MemoryCandidate, active_contents: list[str]
) -> PolicyOutcome:
    settings = get_settings()
    if candidate.action == "forget":
        return PolicyOutcome(candidate, DECISION_PRIVACY, "R3", "用户要求遗忘，转隐私执行")
    if candidate.source == "ai_inferred":
        return PolicyOutcome(candidate, DECISION_DISCARD, "R1", "AI 推测不入库")
    if candidate.action != "invalidate":
        if ONE_OFF_PATTERN.search(candidate.content or ""):
            return PolicyOutcome(candidate, DECISION_DISCARD, "R4", "一次性信息")
        if candidate.confidence < settings.memory_min_confidence:
            return PolicyOutcome(candidate, DECISION_DISCARD, "R5", "置信度过低")
        if candidate.importance < settings.memory_importance_threshold:
            return PolicyOutcome(candidate, DECISION_DISCARD, "R6", "重要性过低")
    if (
        candidate.action in ("save", "update")
        and _is_exact_duplicate(candidate.content or "", active_contents)
    ):
        return PolicyOutcome(candidate, DECISION_DISCARD, "R7", "与既有记忆完全重复")
    if UNRESOLVED_REFERENCE_PATTERN.search(candidate.content or ""):
        return PolicyOutcome(candidate, DECISION_DISCARD, "R8", "含未消解指代")
    return PolicyOutcome(candidate, DECISION_SAVE, "", "通过全部硬规则")


def apply_policy(
    candidates: list[MemoryCandidate], active_contents: list[str] | None = None
) -> PolicyReport:
    active_contents = active_contents or []
    report = PolicyReport()
    if any(c.action == "suppress" for c in candidates):
        for candidate in candidates:
            if candidate.action == "suppress":
                report.outcomes.append(
                    PolicyOutcome(candidate, DECISION_DISCARD, "R2", "本轮被 suppress 指令阻断")
                )
            elif candidate.action == "forget":
                report.outcomes.append(
                    PolicyOutcome(candidate, DECISION_PRIVACY, "R3", "用户要求遗忘，转隐私执行")
                )
            else:
                report.outcomes.append(
                    PolicyOutcome(candidate, DECISION_DISCARD, "R2", "本轮被 suppress 指令阻断")
                )
        return report
    for candidate in candidates:
        if candidate.action == "none":
            report.outcomes.append(
                PolicyOutcome(candidate, DECISION_DISCARD, "none", "提取器判定无可保存内容")
            )
            continue
        report.outcomes.append(_evaluate(candidate, active_contents))
    return report
