from fastapi import APIRouter, Depends

from app.api.v1.auth import require_user
from app.api.v1.schemas import LlmProfileOut, LlmProfilesOut
from app.core.llm_factory import list_llm_profiles
from app.core.settings import get_settings

llm_router = APIRouter(dependencies=[Depends(require_user)])


@llm_router.get("/llm/profiles", response_model=LlmProfilesOut)
def list_profiles() -> LlmProfilesOut:
    settings = get_settings()
    return LlmProfilesOut(
        default=settings.default_llm_profile,
        profiles=[LlmProfileOut(**item) for item in list_llm_profiles()],
    )
