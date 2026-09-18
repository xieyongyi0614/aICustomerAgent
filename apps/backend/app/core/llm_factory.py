from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.settings import LlmProfile, SettingsError, get_settings


_llm_cache: dict[str, BaseChatModel] = {}


def _build_llm(profile: LlmProfile) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=profile.model,
        api_key=profile.api_key,
        base_url=profile.base_url,
        temperature=profile.temperature,
        top_p=profile.top_p,
        frequency_penalty=profile.frequency_penalty,
        presence_penalty=profile.presence_penalty,
        max_tokens=profile.max_tokens,
        request_timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
        extra_body=(
            profile.extra_body
            if profile.extra_body is not None
            else {"thinking": {"type": profile.extra_body_thinking}}
        ),
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


EMBEDDING_CLIENT_CACHE_KEY = "embedding"


def get_embedding_client():
    """embedding 端点客户端（OpenAI 兼容）；未配置 embedding_model 时返回 None。

    凭据复用 llm_profiles 中 embedding_profile 指向的 profile（空则默认 profile），
    不改 chat profile 结构。
    """
    settings = get_settings()
    if not settings.embedding_model:
        return None
    if EMBEDDING_CLIENT_CACHE_KEY in _llm_cache:
        return _llm_cache[EMBEDDING_CLIENT_CACHE_KEY]
    profile = settings.get_llm_profile(settings.embedding_profile or None)
    from openai import OpenAI

    client = OpenAI(
        api_key=profile.api_key,
        base_url=profile.base_url,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    _llm_cache[EMBEDDING_CLIENT_CACHE_KEY] = client
    return client


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


def profile_id_of(llm) -> str | None:
    for profile_id, instance in _llm_cache.items():
        if instance is llm:
            return profile_id
    return None


def provider_of(llm) -> str | None:
    from urllib.parse import urlparse

    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    target = str(base_url) if base_url else None
    if target is None:
        profile_id = profile_id_of(llm)
        if profile_id is None:
            return None
        try:
            target = get_settings().get_llm_profile(profile_id).base_url
        except SettingsError:
            return None
    return urlparse(target).hostname
