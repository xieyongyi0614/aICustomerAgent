"""设备配对 / 邮箱验证码登录换长期令牌 + 鉴权依赖。

契约：`POST /auth/pair` 需 `pairing_secret`；`POST /auth/email/code|verify` 需
SMTP + Redis + 令牌密钥齐备（缺一 503）；令牌无状态签名；401/403/429 语义分离。
既有端点不挂载（V1 纯新增）；新产品端点经 `require_user` 显式注入。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.core import redis_client
from app.core.settings import get_settings
from app.services.identity import user_service
from app.services.identity import verification as verification_service
from app.services.identity.verification import (
    CodeAttemptsExceeded,
    CodeExpired,
    CodeInvalid,
    CodeSendDenied,
    CodeUnavailable,
)

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


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeResponse(BaseModel):
    sent: bool = True
    cooldown_seconds: int


class EmailVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"\d{6}")
    device_id: str = Field(min_length=1)
    device_name: str | None = None
    platform: str = Field(min_length=1)


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


def _email_login_ready() -> None:
    settings = get_settings()
    if not _secret() or not settings.smtp_configured() or not redis_client.is_configured():
        raise HTTPException(status_code=503, detail="邮箱登录未配置（SMTP / Redis / 令牌密钥）")


@auth_router.post("/email/code", response_model=EmailCodeResponse)
async def send_email_code(body: EmailCodeRequest):
    _email_login_ready()
    try:
        cooldown = await verification_service.send_login_code(body.email)
    except CodeSendDenied as denied:
        raise HTTPException(
            status_code=429,
            detail=f"发送过于频繁，请 {denied.retry_after_seconds} 秒后重试",
            headers={"Retry-After": str(denied.retry_after_seconds)},
        ) from denied
    return EmailCodeResponse(cooldown_seconds=cooldown)


@auth_router.post("/email/verify", response_model=PairResponse)
async def verify_email_code(body: EmailVerifyRequest):
    _email_login_ready()
    try:
        normalized = await verification_service.verify_login_code(body.email, body.code)
    except CodeAttemptsExceeded as exc:
        raise HTTPException(status_code=401, detail="尝试次数过多，验证码已作废，请重新获取") from exc
    except CodeExpired as exc:
        raise HTTPException(status_code=401, detail="验证码已过期，请重新获取") from exc
    except CodeInvalid as exc:
        raise HTTPException(status_code=401, detail="验证码错误") from exc
    except CodeUnavailable as exc:
        raise HTTPException(status_code=401, detail="验证码已被使用，请重新获取") from exc
    context = await asyncio.to_thread(user_service.find_or_create_by_email, normalized)
    token = issue_token(context.user_id, body.device_id)
    _, _, exp = parse_token_parts(token)
    return PairResponse(
        token=token,
        user_id=context.user_id,
        expires_at=_iso(exp),
        device_id=body.device_id,
    )
