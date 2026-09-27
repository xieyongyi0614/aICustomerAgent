"""邮件发件端口：EmailSender 协议 + SMTP 实现（MVP：163 个人邮箱）。

替换 Resend / 阿里云 / 腾讯云时新增实现类并扩展 build_email_sender 的
provider 分支；验证码服务只依赖协议。连接按次建立（MVP 发信量下无池化必要）。
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.settings import SettingsError, get_settings


@dataclass(frozen=True, slots=True)
class EmailContent:
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    async def send(self, to_address: str, content: EmailContent) -> None: ...


def build_message(to_address: str, content: EmailContent) -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.from_header()
    message["To"] = to_address
    message["Subject"] = content.subject
    message.set_content(content.text)
    message.add_alternative(content.html, subtype="html")
    return message


class SmtpEmailSender:
    async def send(self, to_address: str, content: EmailContent) -> None:
        settings = get_settings()
        message = build_message(to_address, content)
        common = {
            "hostname": settings.email_smtp_host,
            "port": settings.email_smtp_port,
            "username": settings.email_smtp_user,
            "password": settings.email_smtp_password,
        }
        if settings.email_smtp_ssl:
            await aiosmtplib.send(message, use_tls=True, **common)
        else:
            await aiosmtplib.send(message, start_tls=True, **common)


_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    global _sender
    if _sender is None:
        _sender = build_email_sender()
    return _sender


def set_email_sender(sender: EmailSender | None) -> None:
    global _sender
    _sender = sender


def build_email_sender() -> EmailSender:
    provider = get_settings().email_provider
    if provider == "smtp":
        return SmtpEmailSender()
    raise SettingsError(f"不支持的 EMAIL_PROVIDER: {provider}")
