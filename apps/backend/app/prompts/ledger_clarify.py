"""PLA-010 澄清问句模板：数字只来自结构化字段，禁止 LLM 现场编。"""

from __future__ import annotations

from app.models.ledger import to_major

TEMPLATES: dict[str, str] = {
    "missing_amount": "这笔记多少？",
    "low_confidence": "你是说花了 {amount} 吗？",
    "amount_over_threshold": "确认记一笔 {amount} 的支出？",
    "category_ambiguous": "这笔记到哪一类？",
    "direction_ambiguous": "是支出还是收入？",
}


def render_clarify_question(
    reason: str,
    *,
    amount_minor: int | None = None,
    candidates: list[str] | None = None,
) -> str:
    template = TEMPLATES.get(reason, "这笔记要怎么处理？")
    amount_text = ""
    if amount_minor is not None:
        amount_text = f"{to_major(amount_minor)}元"
    if reason == "category_ambiguous" and candidates:
        options = "、".join(candidates[:3])
        return f"这笔记到哪一类？（{options}）"
    return template.format(amount=amount_text)
