"""V7.5 Memory 维规则集（memory-evaluation.md §2）：虚构候选 + 高重要度漏用。

规则只产候选不定罪：FABRICATION 定罪权在 judge；MISSED 是 info 级优化信号。
"""

from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import EvaluationRule, lexicons


def _support_corpus(ctx: EvaluationContext) -> str:
    parts = [memory.content for memory in ctx.injected_memories]
    parts += [
        message.content
        for message in ctx.recent_messages
        if message.role == "human"
    ]
    return "\n".join(parts)


def _reply_corpus(ctx: EvaluationContext) -> str:
    return "\n".join(message.content for message in ctx.recent_messages) + "\n" + ctx.reply


class FabricationCandidateRule(EvaluationRule):
    code = IssueCode.MEMORY_FABRICATION_CANDIDATE
    dimension = EvaluationDimension.MEMORY

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        settings = get_settings()
        found = lexicons.extract_recall_clause(ctx.reply)
        if found is None:
            return None
        marker, clause = found
        overlap = lexicons.bigram_overlap(clause, _support_corpus(ctx))
        if overlap >= settings.evaluation_memory_support_min_overlap:
            return None
        return build_issue(
            self.code, evidence_quote=f"{marker}{clause}（重叠 {overlap:.2f}）"
        )


class MissedMemoryRule(EvaluationRule):
    code = IssueCode.MEMORY_MISSED
    dimension = EvaluationDimension.MEMORY

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        settings = get_settings()
        reply_corpus = _reply_corpus(ctx)
        for memory in ctx.injected_memories:
            if memory.importance < settings.evaluation_memory_missed_min_importance:
                continue
            relevance = lexicons.bigram_overlap(memory.content, ctx.user_message)
            if relevance < settings.evaluation_memory_missed_min_overlap:
                continue
            usage = lexicons.bigram_overlap(memory.content, reply_corpus)
            if usage >= settings.evaluation_memory_support_min_overlap:
                continue
            return build_issue(
                self.code,
                evidence_quote=f"memory={memory.id}：{memory.content}",
            )
        return None


FABRICATION_CANDIDATE = FabricationCandidateRule()
MISSED = MissedMemoryRule()

RULES = [FABRICATION_CANDIDATE, MISSED]
