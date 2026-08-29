from app.chains.structured import build_structured_chain
from app.core.settings import get_settings
from app.models.memory import MemoryDecision, MemoryExtraction
from app.prompts.extractor import extractor_prompt, v4_extractor_prompt


def build_chain(llm=None):
    return build_structured_chain(
        [
            ("system", extractor_prompt),
            ("user", "用户输入：{user_input}\nAI 回复：{ai_reply}"),
        ],
        MemoryDecision,
        llm,
    )


async def extract(user_input: str, ai_reply: str, llm=None) -> MemoryDecision:
    chain = build_chain(llm)
    return await chain.ainvoke({"user_input": user_input, "ai_reply": ai_reply})


def build_extraction_chain(llm=None):
    return build_structured_chain(
        [
            ("system", v4_extractor_prompt),
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
