"""API-001 设备配对换长期令牌 + 鉴权依赖。

契约：`POST /auth/pair` 需 `pairing_secret`；令牌无状态签名；401/403 语义分离。
既有端点不挂载（V1 纯新增）；新产品端点经 `require_user` 显式注入。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.settings import get_settings

auth_router = APIRouter(prefix="/auth", tags=["auth"])

TOKEN_TTL_SECONDS = 30 * 24 * 3600


class PairRequest(BaseModel):
    pairing_secret: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    device_name: str | None = None
    platform: str = Field(min_length=1)


class PairResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    user_id: str
    expires_at: str
    device_id: str


class MeResponse(BaseModel):
    user_id: str
    device_id: str
    expires_at: str


def _secret() -> str:
    return getattr(get_settings(), "auth_token_secret", "") or ""


def _pairing_secret() -> str:
    return getattr(get_settings(), "auth_pairing_code", "") or ""


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def issue_token(user_id: str, device_id: str) -> str:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    body = f"{user_id}.{device_id}.{exp}"
    return f"{body}.{_sign(body)}"


def parse_token(token: str) -> str:
    user_id, _device_id, _exp = parse_token_parts(token)
    return user_id


def parse_token_parts(token: str) -> tuple[str, str, int]:
    parts = token.split(".")
    if len(parts) != 4:
        raise HTTPException(status_code=401, detail="设备令牌无效")
    user_id, device_id, exp, sig = parts
    body = f"{user_id}.{device_id}.{exp}"
    if not hmac.compare_digest(_sign(body), sig):
        raise HTTPException(status_code=401, detail="设备令牌无效")
    exp_i = int(exp)
    if exp_i < time.time():
        raise HTTPException(status_code=401, detail="设备令牌已过期，建议重新配对")
    return user_id, device_id, exp_i


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def current_user_id(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供设备令牌")
    return parse_token(authorization.removeprefix("Bearer ").strip())


def require_user(authorization: str = Header(default="")) -> str:
    """产品端点鉴权依赖：user_id 仅从 token 解析，不回落 default_user。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供设备令牌")
    return parse_token(authorization.removeprefix("Bearer ").strip())


@auth_router.post("/pair", response_model=PairResponse)
def pair_device(body: PairRequest):
    secret = _secret()
    if not secret:
        raise HTTPException(status_code=503, detail="auth_token_secret not configured")
    expected = _pairing_secret()
    if not expected:
        raise HTTPException(status_code=503, detail="auth_pairing_code not configured")
    if not hmac.compare_digest(body.pairing_secret, expected):
        raise HTTPException(status_code=401, detail="配对凭据无效")
    user_id = get_settings().default_user
    token = issue_token(user_id, body.device_id)
    _, _, exp = parse_token_parts(token)
    return PairResponse(
        token=token,
        user_id=user_id,
        expires_at=_iso(exp),
        device_id=body.device_id,
    )


@auth_router.get("/me", response_model=MeResponse)
def me(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供设备令牌")
    raw = authorization.removeprefix("Bearer ").strip()
    user_id, device_id, exp = parse_token_parts(raw)
    return MeResponse(user_id=user_id, device_id=device_id, expires_at=_iso(exp))
