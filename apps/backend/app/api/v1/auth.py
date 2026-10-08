"""邮箱验证码登录 / 飞书授权登录换长期令牌 + 鉴权依赖。

契约：`POST /auth/email/code|verify` 需 SMTP + Redis + 令牌密钥齐备（缺一 503）；
飞书授权登录额外需 FEISHU_APP_ID / APP_SECRET / FEISHU_OAUTH_REDIRECT_URI；
令牌无状态签名（设备配对链路已退役）；401/403/409/429 语义分离。
新产品端点经 `require_user` 显式注入，`user_id` 只从令牌解析。

飞书登录采用「浏览器授权 → 后端回调落结果 → App 凭 state 领取」：授权码不出后端，
客户端用 404（Retry-After）区分「等待授权」与失败。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from app.core import redis_client
from app.core.settings import get_settings
from app.services.email.sender import EmailSendFailed
from app.services.identity.feishu import login as feishu_login_service
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

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 30 * 24 * 3600

_CLAIM_RETRY_AFTER_SECONDS = 2


class TokenResponse(BaseModel):
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


def require_user(authorization: str = Header(default="")) -> str:
    """产品端点鉴权依赖：user_id 仅从 token 解析，不回落 default_user。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供设备令牌")
    return parse_token(authorization.removeprefix("Bearer ").strip())


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
    except EmailSendFailed as exc:
        logger.warning("验证码邮件发送失败：%s", exc)
        raise HTTPException(
            status_code=503,
            detail="验证码邮件发不出去：服务端邮件通道配置有误，请检查 EMAIL_SMTP_* 后重试",
        ) from exc
    return EmailCodeResponse(cooldown_seconds=cooldown)


@auth_router.post("/email/verify", response_model=TokenResponse)
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
    return TokenResponse(
        token=token,
        user_id=context.user_id,
        expires_at=_iso(exp),
        device_id=body.device_id,
    )


class FeishuAuthorizeResponse(BaseModel):
    authorize_url: str
    state: str
    expires_in: int


class FeishuLoginClaimRequest(BaseModel):
    state: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    device_name: str | None = None


class FeishuBindClaimRequest(BaseModel):
    state: str = Field(min_length=1)


class BindingItem(BaseModel):
    bound: bool
    bound_at: str | None = None


class BindingsResponse(BaseModel):
    email: BindingItem
    feishu: BindingItem


def _feishu_login_ready() -> None:
    settings = get_settings()
    if not settings.oauth_configured() or not _secret() or not redis_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "飞书登录未配置（需 FEISHU_APP_ID / FEISHU_APP_SECRET /"
                " FEISHU_OAUTH_REDIRECT_URI 与 Redis、令牌密钥）"
            ),
        )


def _bindings_payload(view: feishu_login_service.BindingsView) -> BindingsResponse:
    return BindingsResponse(
        email=BindingItem(bound=view.email.bound, bound_at=view.email.bound_at),
        feishu=BindingItem(bound=view.feishu.bound, bound_at=view.feishu.bound_at),
    )


def _current_bindings(user_id: str) -> BindingsResponse:
    return _bindings_payload(feishu_login_service.list_bindings(user_id))


_CALLBACK_PAGES = {
    feishu_login_service.CALLBACK_OK: (
        "授权成功",
        "已授权成功，请返回「朝夕」App 继续。",
    ),
    feishu_login_service.CALLBACK_DENIED: (
        "授权已取消",
        "你取消了授权，可以返回「朝夕」App 重新发起。",
    ),
    feishu_login_service.CALLBACK_FAILED: (
        "授权未完成",
        "授权校验未通过，请返回「朝夕」App 重新发起。",
    ),
    feishu_login_service.CALLBACK_STALE: (
        "授权已过期",
        "这次授权请求已失效，请返回「朝夕」App 重新发起。",
    ),
}


def _callback_page(status: str) -> HTMLResponse:
    title, message = _CALLBACK_PAGES.get(status, _CALLBACK_PAGES[feishu_login_service.CALLBACK_STALE])
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{title}</title></head>"
        "<body style=\"margin:0;display:flex;min-height:100vh;align-items:center;"
        "justify-content:center;background:#faf8f5;color:#2c2a28;"
        "font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif\">"
        "<main style=\"max-width:22rem;padding:2rem;text-align:center\">"
        f"<h1 style=\"font-size:1.1rem;margin:0 0 .75rem\">{title}</h1>"
        f"<p style=\"font-size:.9rem;line-height:1.6;margin:0;color:#6b6560\">{message}</p>"
        "</main></body></html>"
    )
    return HTMLResponse(content=html, status_code=200)


@auth_router.get("/feishu/authorize", response_model=FeishuAuthorizeResponse)
async def feishu_authorize():
    _feishu_login_ready()
    ticket = await feishu_login_service.start_login()
    return FeishuAuthorizeResponse(
        authorize_url=ticket.authorize_url,
        state=ticket.state,
        expires_in=ticket.expires_in,
    )


@auth_router.get("/feishu/bind/authorize", response_model=FeishuAuthorizeResponse)
async def feishu_bind_authorize(user_id: str = Depends(require_user)):
    _feishu_login_ready()
    ticket = await feishu_login_service.start_bind(user_id)
    return FeishuAuthorizeResponse(
        authorize_url=ticket.authorize_url,
        state=ticket.state,
        expires_in=ticket.expires_in,
    )


@auth_router.get("/feishu/callback")
async def feishu_callback(code: str = "", state: str = "", error: str = ""):
    """飞书授权回调：消费授权码并回写结果，返回一句话页面。

    客户端不接收 `code`（它只在服务端消费一次）；App 凭发起时的 state 轮询
    `login/claim` 或 `bind/claim` 领取结果。
    """
    status = await feishu_login_service.record_authorization(
        state, code=code, error=error
    )
    return _callback_page(status)


@auth_router.post("/feishu/login/claim", response_model=TokenResponse)
async def feishu_login_claim(body: FeishuLoginClaimRequest):
    """领取飞书登录结果：202/404 表示授权尚未完成（客户端继续轮询）。"""
    _feishu_login_ready()
    try:
        resolved = await feishu_login_service.claim_login(body.state)
    except feishu_login_service.FeishuAuthorizationPending as exc:
        raise HTTPException(
            status_code=404,
            detail="等待飞书授权中",
            headers={"Retry-After": str(_CLAIM_RETRY_AFTER_SECONDS)},
        ) from exc
    except feishu_login_service.FeishuAuthorizationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except feishu_login_service.FeishuStateInvalid as exc:
        raise HTTPException(
            status_code=400, detail="授权请求已失效，请重新发起飞书登录"
        ) from exc
    token = issue_token(resolved.internal_user_id, body.device_id)
    _, _, exp = parse_token_parts(token)
    return TokenResponse(
        token=token,
        user_id=resolved.internal_user_id,
        expires_at=_iso(exp),
        device_id=body.device_id,
    )


@auth_router.post("/feishu/bind/claim", response_model=BindingsResponse)
async def feishu_bind_claim(
    body: FeishuBindClaimRequest, user_id: str = Depends(require_user)
):
    """领取飞书绑定结果：404 表示授权尚未完成（客户端继续轮询）。"""
    _feishu_login_ready()
    try:
        await feishu_login_service.claim_bind(user_id, body.state)
    except feishu_login_service.FeishuAuthorizationPending as exc:
        raise HTTPException(
            status_code=404,
            detail="等待飞书授权中",
            headers={"Retry-After": str(_CLAIM_RETRY_AFTER_SECONDS)},
        ) from exc
    except feishu_login_service.FeishuAuthorizationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except feishu_login_service.FeishuStateMismatch as exc:
        raise HTTPException(status_code=403, detail="授权请求与当前账号不匹配") from exc
    except feishu_login_service.FeishuBindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except feishu_login_service.FeishuStateInvalid as exc:
        raise HTTPException(
            status_code=400, detail="授权请求已失效，请重新发起绑定"
        ) from exc
    return await asyncio.to_thread(_current_bindings, user_id)


@auth_router.delete("/feishu/bind", response_model=BindingsResponse)
async def feishu_unbind(user_id: str = Depends(require_user)):
    await asyncio.to_thread(feishu_login_service.unbind, user_id)
    return await asyncio.to_thread(_current_bindings, user_id)


@auth_router.get("/bindings", response_model=BindingsResponse)
async def bindings(user_id: str = Depends(require_user)):
    return await asyncio.to_thread(_current_bindings, user_id)
