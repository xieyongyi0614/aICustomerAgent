from langchain_openai import ChatOpenAI

from app.core.settings import get_settings

_llm_holder: dict[str, ChatOpenAI | None] = {"llm": None}


def get_llm() -> ChatOpenAI:
    if _llm_holder["llm"] is None:
        settings = get_settings()
        _llm_holder["llm"] = ChatOpenAI(
            model=settings.model,
            api_key=settings.openai_api_key,
            base_url=settings.base_url,
            temperature=settings.temperature,
            top_p=settings.top_p,
            frequency_penalty=settings.frequency_penalty,
            presence_penalty=settings.presence_penalty,
            max_tokens=settings.max_tokens,
            extra_body={"thinking": {"type": settings.extra_body_thinking}},
        )
    return _llm_holder["llm"]


def set_llm(llm) -> None:
    _llm_holder["llm"] = llm


def reset_llm() -> None:
    _llm_holder["llm"] = None
