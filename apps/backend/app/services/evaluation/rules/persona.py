"""V7.5 Persona 维规则集（persona-evaluation.md §2）：辱骂硬信号 + 人设矛盾模式。

词表抓"确定的错"；语义层 OOC 交 LLM judge（llm-judge.md）。
"""

import re

from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation.context import EvaluationContext
from app.services.evaluation.rules import EvaluationRule, lexicons
from app.character.asuna.evaluation import PERSONA_CONTRADICTION_PATTERNS

_PERSONA_PATTERNS: dict[str, tuple] = {}


def _persona_patterns(character_id: str) -> tuple:
    if character_id not in _PERSONA_PATTERNS:
        if character_id == "asuna":
            _PERSONA_PATTERNS[character_id] = PERSONA_CONTRADICTION_PATTERNS
        else:
            _PERSONA_PATTERNS[character_id] = ()
    return _PERSONA_PATTERNS[character_id]


_NEGATION_MARKERS = ("别", "不要", "勿", "没", "不", "无")


def _is_negated(reply: str, index: int) -> bool:
    prefix = reply[max(0, index - 3) : index]
    return any(marker in prefix for marker in _NEGATION_MARKERS)


class AbusiveLanguageRule(EvaluationRule):
    code = IssueCode.PERSONA_ABUSIVE_LANGUAGE
    dimension = EvaluationDimension.PERSONA

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        for word in lexicons.ABUSIVE_WORDS:
            index = ctx.reply.find(word)
            while index != -1:
                if not _is_negated(ctx.reply, index):
                    return build_issue(self.code, evidence_quote=word)
                index = ctx.reply.find(word, index + 1)
        return None


class ContradictionPatternRule(EvaluationRule):
    code = IssueCode.PERSONA_CONTRADICTION_PATTERN
    dimension = EvaluationDimension.PERSONA

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        for entry in _persona_patterns(ctx.character_id):
            if ctx.mode in entry.allowed_modes:
                continue
            match = re.search(entry.pattern, ctx.reply)
            if match is not None:
                return build_issue(self.code, evidence_quote=match.group(0))
        return None


ABUSIVE_LANGUAGE = AbusiveLanguageRule()
CONTRADICTION_PATTERN = ContradictionPatternRule()

RULES = [ABUSIVE_LANGUAGE, CONTRADICTION_PATTERN]
