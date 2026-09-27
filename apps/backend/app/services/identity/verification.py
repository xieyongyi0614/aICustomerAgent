"""邮箱验证码签发与校验（登录前置流程）。

任意邮箱校验通过即建号（用户开通在 user_service.find_or_create_by_email），
故无需防枚举歧义；频控与单次消费由 VerificationCodeStore 承担。策略数字读
EmailSettings，存储机制在 RedisCodeStore，二者经参数解耦。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from app.core.settings import get_settings
from app.services.email.sender import EmailContent, EmailSender, get_email_sender
from app.services.identity.code_store import (
    RedisCodeStore,
    VerificationCodeStore,
)


class CodeSendDenied(Exception):
    def __init__(self, retry_after_seconds: int):
        super().__init__(f"send denied, retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class CodeInvalid(Exception):
    pass


class CodeExpired(Exception):
    pass


class CodeAttemptsExceeded(CodeInvalid):
    pass


class CodeUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    ttl_seconds: int
    cooldown_seconds: int
    hourly_cap: int
    daily_cap: int
    max_attempts: int


def _policy() -> VerificationPolicy:
    settings = get_settings()
    return VerificationPolicy(
        ttl_seconds=settings.email_code_ttl_seconds,
        cooldown_seconds=settings.email_code_cooldown_seconds,
        hourly_cap=settings.email_code_send_hourly_cap,
        daily_cap=settings.email_code_send_daily_cap,
        max_attempts=settings.email_code_max_attempts,
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _code_hash(email: str, code: str) -> str:
    secret = get_settings().auth_token_secret
    payload = f"email-code:{email}:{code}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _login_code_content(code: str, ttl_seconds: int) -> EmailContent:
    minutes = max(ttl_seconds // 60, 1)
    return EmailContent(
        subject="朝夕登录验证码",
        text=(
            f"你的登录验证码是 {code}，{minutes} 分钟内有效。\n\n"
            "若非本人操作，请忽略本邮件。"
        ),
        html=(
            f"<p>你的登录验证码是 <b style=\"font-size:20px;letter-spacing:4px\">{code}</b>，"
            f"{minutes} 分钟内有效。</p><p>若非本人操作，请忽略本邮件。</p>"
        ),
    )


async def send_login_code(
    email: str,
    *,
    store: VerificationCodeStore | None = None,
    sender: EmailSender | None = None,
) -> int:
    normalized = normalize_email(email)
    policy = _policy()
    code_store = store or RedisCodeStore()
    gate = await code_store.reserve_send(
        normalized,
        cooldown_seconds=policy.cooldown_seconds,
        hourly_cap=policy.hourly_cap,
        daily_cap=policy.daily_cap,
    )
    if not gate.allowed:
        raise CodeSendDenied(gate.retry_after_seconds)
    code = _generate_code()
    await code_store.save_code(
        normalized, _code_hash(normalized, code), ttl_seconds=policy.ttl_seconds
    )
    mailer = sender or get_email_sender()
    await mailer.send(normalized, _login_code_content(code, policy.ttl_seconds))
    return policy.cooldown_seconds


async def verify_login_code(
    email: str,
    code: str,
    *,
    store: VerificationCodeStore | None = None,
) -> str:
    normalized = normalize_email(email)
    policy = _policy()
    code_store = store or RedisCodeStore()
    stored = await code_store.peek_code(normalized)
    if stored is None:
        raise CodeExpired()
    if not hmac.compare_digest(stored, _code_hash(normalized, code.strip())):
        attempts = await code_store.bump_attempts(
            normalized, max_attempts=policy.max_attempts, ttl_seconds=policy.ttl_seconds
        )
        if attempts >= policy.max_attempts:
            raise CodeAttemptsExceeded()
        raise CodeInvalid()
    consumed = await code_store.consume_code(normalized)
    if consumed is None:
        raise CodeUnavailable()
    return normalized
