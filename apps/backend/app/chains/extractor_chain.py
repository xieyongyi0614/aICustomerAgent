from app.chains.structured import build_structured_chain
from app.models.memory import MemoryDecision
from app.prompts.extractor import extractor_prompt


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
