from app.chains.structured import build_structured_chain
from app.core.settings import get_settings
from app.models.memory import MemoryExtraction
from app.prompts.extractor import MEMORY_EXTRACTOR_PROMPT


def build_extraction_chain(llm=None):
    return build_structured_chain(
        [
            ("system", MEMORY_EXTRACTOR_PROMPT),
            (
                "user",
                "用户消息：{user_input}\nAI 回复：{ai_reply}\n最近对话：\n{recent_context}",
            ),
        ],
        MemoryExtraction,
        llm,
    )


def _cap_candidates(extraction: MemoryExtraction) -> MemoryExtraction:
    max_candidates = get_settings().memory_max_candidates
    if len(extraction.candidates) > max_candidates:
        return extraction.model_copy(
            update={"candidates": extraction.candidates[:max_candidates]}
        )
    return extraction


async def extract_candidates(
    user_input: str,
    ai_reply: str,
    recent_context: str = "",
    llm=None,
) -> MemoryExtraction:
    chain = build_extraction_chain(llm)
    extraction = await chain.ainvoke(
        {
            "user_input": user_input,
            "ai_reply": ai_reply,
            "recent_context": recent_context or "（无）",
        }
    )
    if extraction is None:
        return MemoryExtraction(candidates=[])
    return _cap_candidates(extraction)
