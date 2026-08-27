from app.chains.structured import build_structured_chain
from app.models.router import RoleMode
from app.prompts.router import role_router_prompt


def build_chain(llm=None):
    return build_structured_chain(
        [
            ("system", role_router_prompt),
            ("user", "{user_message}"),
        ],
        RoleMode,
        llm,
    )


async def route(user_message: str, llm=None) -> RoleMode:
    chain = build_chain(llm)
    return await chain.ainvoke({"user_message": user_message})
