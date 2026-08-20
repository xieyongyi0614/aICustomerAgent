from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.prompts.summary import summary_prompt


def build_chain():
    prompt = ChatPromptTemplate.from_messages([("system", summary_prompt)])
    return prompt | get_llm()


async def summarize(old_summary: str, new_messages: str) -> str:
    chain = build_chain()
    result = await chain.ainvoke({"old_summary": old_summary, "new_messages": new_messages})
    return getattr(result, "content", str(result)).strip()
