"""EmailSettings 校验与 SMTP 消息构造单测。

用例断言的是「默认值 / 缺项」语义，故一律以 `_env_file=None` 构造，
不读开发机 `.env`（否则本机配了真实邮箱配置就只剩本机红）。
"""

from __future__ import annotations

import pytest

from app.core.settings._shared import SettingsError
from app.core.settings.email import EmailSettings
from app.services.email import sender as sender_module
from app.services.email.sender import EmailContent, build_message, build_email_sender

pytestmark = pytest.mark.unit


def test_defaults_valid():
    settings = EmailSettings(_env_file=None)
    assert settings.email_provider == "smtp"
    assert settings.smtp_configured() is False


def test_host_requires_credentials_and_from():
    with pytest.raises(SettingsError):
        EmailSettings(_env_file=None, email_smtp_host="smtp.163.com")
    settings = EmailSettings(
        _env_file=None,
        email_smtp_host="smtp.163.com",
        email_smtp_user="x@163.com",
        email_smtp_password="authcode",
        email_from_address="x@163.com",
    )
    assert settings.smtp_configured() is True


def test_positive_int_fields_reject_zero():
    with pytest.raises(SettingsError):
        EmailSettings(email_code_ttl_seconds=0)


def test_unknown_provider_rejected():
    with pytest.raises(SettingsError):
        EmailSettings(email_provider="resend")


def test_from_header_prefers_from_address():
    settings = EmailSettings(
        _env_file=None,
        email_smtp_host="smtp.163.com",
        email_smtp_user="sender@163.com",
        email_smtp_password="authcode",
        email_from_address="hello@zhaoxi.app",
    )
    assert settings.from_header() == "朝夕 <hello@zhaoxi.app>"
    bare = EmailSettings(_env_file=None)
    assert bare.from_header() == ""


def test_build_message_has_text_and_html_parts(monkeypatch):
    settings = EmailSettings(
        email_smtp_host="smtp.163.com",
        email_smtp_user="sender@163.com",
        email_smtp_password="authcode",
        email_from_address="sender@163.com",
    )
    monkeypatch.setattr(sender_module, "get_settings", lambda: settings)
    message = build_message(
        "user@example.com",
        EmailContent(subject="登录验证码", text="验证码 123456", html="<b>123456</b>"),
    )
    assert message["To"] == "user@example.com"
    assert message["Subject"] == "登录验证码"
    body = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert body is not None and "123456" in body.get_content()
    assert html is not None and "123456" in html.get_content()


def test_build_email_sender_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(
        sender_module,
        "get_settings",
        lambda: type("S", (), {"email_provider": "pigeon"})(),
    )
    with pytest.raises(SettingsError):
        build_email_sender()


def test_build_email_sender_returns_smtp(monkeypatch):
    monkeypatch.setattr(
        sender_module,
        "get_settings",
        lambda: EmailSettings(_env_file=None),
    )
    assert isinstance(build_email_sender(), sender_module.SmtpEmailSender)
