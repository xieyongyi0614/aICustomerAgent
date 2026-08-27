from fastapi import HTTPException, Request, status

from app.api.v1.schemas import ChatRequest
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError


def get_chat_llm(body: ChatRequest, request: Request):
    raw = (
        body.profile_id
        or request.headers.get("x-llm-profile")
        or request.query_params.get("profile_id")
    )
    try:
        return get_llm(raw)
    except SettingsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))