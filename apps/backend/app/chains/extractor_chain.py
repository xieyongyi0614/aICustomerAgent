from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.models.memory import MemoryDecision
from app.prompts.extractor import extractor_prompt


def build_chain(llm=None):
    prompt = ChatPromptTemplate.from_messages([("system", extractor_prompt)])
    return prompt | (llm or get_llm()).with_structured_output(MemoryDecision)


async def extract(user_input: str, ai_reply: str, llm=None) -> MemoryDecision:
    chain = build_chain(llm)
    return await chain.ainvoke({"user_input": user_input, "ai_reply": ai_reply})
