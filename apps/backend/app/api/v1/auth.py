"""API-001 设备配对换长期令牌（Q3 裁决：新增参数类 auth_token_secret）。"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.settings import get_settings

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class PairRequest(BaseModel):
    device_id: str = Field(min_length=1)
    device_name: str | None = None


class PairResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


def _secret() -> str:
    return getattr(get_settings(), "auth_token_secret", "") or ""


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def issue_token(user_id: str, device_id: str) -> str:
    exp = int(time.time()) + 30 * 24 * 3600
    body = f"{user_id}.{device_id}.{exp}"
    return f"{body}.{_sign(body)}"


def parse_token(token: str) -> str:
    parts = token.split(".")
    if len(parts) != 4:
        raise HTTPException(status_code=401, detail="invalid token")
    user_id, device_id, exp, sig = parts
    body = f"{user_id}.{device_id}.{exp}"
    if not hmac.compare_digest(_sign(body), sig):
        raise HTTPException(status_code=401, detail="invalid token")
    if int(exp) < time.time():
        raise HTTPException(status_code=401, detail="token expired")
    return user_id


def current_user_id(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    return parse_token(authorization.removeprefix("Bearer ").strip())


@auth_router.post("/pair", response_model=PairResponse)
def pair_device(body: PairRequest):
    secret = _secret()
    if not secret:
        raise HTTPException(status_code=503, detail="auth_token_secret not configured")
    user_id = get_settings().default_user
    return PairResponse(access_token=issue_token(user_id, body.device_id), user_id=user_id)


@auth_router.get("/me")
def me(user_id: str = Depends(current_user_id)):
    return {"user_id": user_id}
