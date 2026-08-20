from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.models.router import RoleMode
from app.prompts.router import role_router_prompt


def build_chain(llm=None):
    prompt = ChatPromptTemplate.from_messages([("system", role_router_prompt)])
    return prompt | (llm or get_llm()).with_structured_output(RoleMode)


async def route(user_message: str, llm=None) -> RoleMode:
    chain = build_chain(llm)
    return await chain.ainvoke({"user_message": user_message})
