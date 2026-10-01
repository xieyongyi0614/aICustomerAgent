"""邮箱验证码登录：验证码服务 / 用户开通 / API 映射测试。"""

from __future__ import annotations

import re

import aiosmtplib
import fakeredis.aioredis
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import auth as auth_api
from app.services.email import sender as sender_module
from app.services.email.sender import EmailContent
from app.services.identity import user_service
from app.services.identity import verification as verification_service
from app.services.identity.code_store import RedisCodeStore

pytestmark = pytest.mark.unit


class RecordingSender:
    def __init__(self):
        self.sent: list[tuple[str, EmailContent]] = []

    async def send(self, to_address: str, content: EmailContent) -> None:
        self.sent.append((to_address, content))


@pytest.fixture
async def store():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield RedisCodeStore(client)
    await client.aclose()


@pytest.fixture
def sender():
    return RecordingSender()


async def test_send_login_code_sends_to_normalized_email(store, sender):
    cooldown = await verification_service.send_login_code(
        "User@X.COM ", store=store, sender=sender
    )
    assert cooldown > 0
    assert sender.sent[0][0] == "user@x.com"
    assert re.search(r"\d{6}", sender.sent[0][1].text)


async def test_send_login_code_denied_within_cooldown(store, sender):
    await verification_service.send_login_code("user@x.com", store=store, sender=sender)
    with pytest.raises(verification_service.CodeSendDenied) as exc:
        await verification_service.send_login_code("user@x.com", store=store, sender=sender)
    assert exc.value.retry_after_seconds > 0
    assert len(sender.sent) == 1


async def test_verify_correct_code_consumes_once(store, sender):
    await verification_service.send_login_code("user@x.com", store=store, sender=sender)
    code = re.search(r"\d{6}", sender.sent[0][1].text).group(0)
    normalized = await verification_service.verify_login_code(
        "USER@x.com", f" {code} ", store=store
    )
    assert normalized == "user@x.com"
    with pytest.raises(verification_service.CodeExpired):
        await verification_service.verify_login_code("user@x.com", code, store=store)


async def test_wrong_code_attempts_exhaustion_revokes_code(store, sender):
    await verification_service.send_login_code("user@x.com", store=store, sender=sender)
    for _ in range(4):
        with pytest.raises(verification_service.CodeInvalid):
            await verification_service.verify_login_code(
                "user@x.com", "000000", store=store
            )
    with pytest.raises(verification_service.CodeAttemptsExceeded):
        await verification_service.verify_login_code("user@x.com", "000000", store=store)
    assert await store.peek_code("user@x.com") is None


async def test_verify_without_code_raises_expired(store):
    with pytest.raises(verification_service.CodeExpired):
        await verification_service.verify_login_code("user@x.com", "123456", store=store)


def test_find_or_create_by_email_is_idempotent():
    first = user_service.find_or_create_by_email("newuser@example.com")
    second = user_service.find_or_create_by_email("NewUser@Example.com")
    assert first.user_id.startswith("email-")
    assert first.user_id == second.user_id
    assert first.display_name == "newuser"
    assert first.status == "active"


async def test_send_email_code_endpoint_returns_cooldown(monkeypatch):
    async def ok(email, **kwargs):
        return 60

    monkeypatch.setattr(verification_service, "send_login_code", ok)
    monkeypatch.setattr(auth_api, "_email_login_ready", lambda: None)
    response = await auth_api.send_email_code(
        auth_api.EmailCodeRequest(email="u@x.com")
    )
    assert response.sent is True
    assert response.cooldown_seconds == 60


async def test_send_email_code_endpoint_maps_denied_to_429(monkeypatch):
    async def denied(email, **kwargs):
        raise verification_service.CodeSendDenied(42)

    monkeypatch.setattr(verification_service, "send_login_code", denied)
    monkeypatch.setattr(auth_api, "_email_login_ready", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await auth_api.send_email_code(auth_api.EmailCodeRequest(email="u@x.com"))
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "42"


class FailingSender:
    async def send(self, to_address: str, content: EmailContent) -> None:
        raise sender_module.EmailSendFailed("SMTP 认证失败（535）")


async def test_send_login_code_releases_quota_when_send_fails(store):
    with pytest.raises(sender_module.EmailSendFailed):
        await verification_service.send_login_code(
            "user@x.com", store=store, sender=FailingSender()
        )
    assert await store.peek_code("user@x.com") is None
    retry = RecordingSender()
    cooldown = await verification_service.send_login_code(
        "user@x.com", store=store, sender=retry
    )
    assert cooldown > 0
    assert len(retry.sent) == 1


async def test_smtp_sender_maps_auth_error_to_email_send_failed(monkeypatch):
    def boom(*args, **kwargs):
        raise aiosmtplib.SMTPAuthenticationError(535, "Error: authentication failed")

    monkeypatch.setattr(sender_module.aiosmtplib, "send", boom)
    with pytest.raises(sender_module.EmailSendFailed):
        await sender_module.SmtpEmailSender().send(
            "u@x.com", EmailContent(subject="s", text="t", html="<b>t</b>")
        )


async def test_send_email_code_endpoint_maps_send_failure_to_503(monkeypatch):
    async def failed(email, **kwargs):
        raise sender_module.EmailSendFailed("SMTP 认证失败（535）")

    monkeypatch.setattr(verification_service, "send_login_code", failed)
    monkeypatch.setattr(auth_api, "_email_login_ready", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await auth_api.send_email_code(auth_api.EmailCodeRequest(email="u@x.com"))
    assert exc.value.status_code == 503


async def test_verify_email_code_endpoint_issues_bound_token(monkeypatch):
    async def ok(email, code, **kwargs):
        return "u@x.com"

    def fake_find(email):
        return user_service.UserContext(
            user_id="email-abc123", display_name="u", status="active"
        )

    monkeypatch.setattr(verification_service, "verify_login_code", ok)
    monkeypatch.setattr(user_service, "find_or_create_by_email", fake_find)
    monkeypatch.setattr(auth_api, "_email_login_ready", lambda: None)
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    response = await auth_api.verify_email_code(
        auth_api.EmailVerifyRequest(
            email="u@x.com", code="123456", device_id="d1", platform="android"
        )
    )
    user_id, device_id, _ = auth_api.parse_token_parts(response.token)
    assert (user_id, device_id) == ("email-abc123", "d1")
    assert response.user_id == "email-abc123"


def test_email_login_ready_requires_smtp(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "sec")
    monkeypatch.setattr(
        auth_api,
        "redis_client",
        type("R", (), {"is_configured": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: type("S", (), {"smtp_configured": lambda self: False})(),
    )
    with pytest.raises(HTTPException) as exc:
        auth_api._email_login_ready()
    assert exc.value.status_code == 503


def test_email_login_ready_requires_redis(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "sec")
    monkeypatch.setattr(
        auth_api,
        "redis_client",
        type("R", (), {"is_configured": staticmethod(lambda: False)})(),
    )
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: type("S", (), {"smtp_configured": lambda self: True})(),
    )
    with pytest.raises(HTTPException) as exc:
        auth_api._email_login_ready()
    assert exc.value.status_code == 503


def test_email_code_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        auth_api.EmailCodeRequest(email="not-an-email")


def test_email_verify_request_rejects_non_digit_code():
    with pytest.raises(ValidationError):
        auth_api.EmailVerifyRequest(
            email="u@x.com", code="12ab56", device_id="d1", platform="android"
        )


def test_email_login_routes_registered():
    paths = {route.path for route in auth_api.auth_router.routes}
    assert "/auth/email/code" in paths
    assert "/auth/email/verify" in paths
