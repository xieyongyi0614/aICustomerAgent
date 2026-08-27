from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.settings import LlmProfile, get_settings


_llm_cache: dict[str, BaseChatModel] = {}


def _build_llm(profile: LlmProfile) -> ChatOpenAI:
    return ChatOpenAI(
        model=profile.model,
        api_key=profile.api_key,
        base_url=profile.base_url,
        temperature=profile.temperature,
        top_p=profile.top_p,
        frequency_penalty=profile.frequency_penalty,
        presence_penalty=profile.presence_penalty,
        max_tokens=profile.max_tokens,
        extra_body={"thinking": {"type": profile.extra_body_thinking}},
    )


def _resolve_profile_id(profile_id: str | None) -> str:
    if profile_id:
        return profile_id
    return get_settings().default_llm_profile


def get_llm(profile_id: str | None = None) -> ChatOpenAI:
    target = _resolve_profile_id(profile_id)
    if target in _llm_cache:
        return _llm_cache[target]
    profile = get_settings().get_llm_profile(target)
    llm = _build_llm(profile)
    _llm_cache[target] = llm
    return llm


def set_llm(llm, profile_id: str | None = None) -> None:
    if profile_id is None:
        _llm_cache.clear()
        _llm_cache[get_settings().default_llm_profile] = llm
        return
    _llm_cache[profile_id] = llm


def reset_llm() -> None:
    _llm_cache.clear()


def list_llm_profiles() -> list[dict]:
    return [profile.to_public() for profile in get_settings().llm_profiles()]
