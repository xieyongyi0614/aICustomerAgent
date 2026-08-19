from langchain_core.prompts import ChatPromptTemplate

from app.core.llm_factory import get_llm
from app.models.router import RoleMode
from app.prompts.router import role_router_prompt


def build_chain():
    prompt = ChatPromptTemplate.from_messages([("system", role_router_prompt)])
    return prompt | get_llm().with_structured_output(RoleMode)


async def route(user_message: str) -> RoleMode:
    chain = build_chain()
    return await chain.ainvoke({"user_message": user_message})
