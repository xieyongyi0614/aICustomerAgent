"""飞书 HTTP 客户端：tenant_access_token 获取 / 缓存 / 提前刷新 / 并发单飞 / 有界重试。

懒构造：transport 与锁在首次需要时创建；`FEISHU_ENABLED=false` 时调用即抛
`FeishuDisabledError`，全程零网络。token 明文只存在于模块内 `_TenantToken`，
任何日志 / 异常 / `token_view()` 均不携带。
"""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from app.channels.base import ChannelErrorKind, SendResult
from app.channels.feishu.errors import (
    FeishuConfigError,
    FeishuDisabledError,
    FeishuError,
    classify,
    error_kind_of,
)
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

TOKEN_OPERATION = "tenant_access_token"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
IM_SEND_OPERATION = "im_send"
IM_REPLY_OPERATION = "im_reply"
IM_MESSAGES_PATH = "/open-apis/im/v1/messages"
REDACTED = "<redacted>"


class Transport(Protocol):
    async def post_json(
        self, url: str, body: dict, timeout: float, headers: dict | None = None
    ) -> "HttpResponse": ...


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    json: dict | None
    raw_len: int


@dataclass(frozen=True, slots=True)
class TokenView:
    has_token: bool
    needs_refresh: bool
    expires_in: int | None
    age_seconds: float | None


class UrllibTransport:
    async def post_json(
        self, url: str, body: dict, timeout: float, headers: dict | None = None
    ) -> HttpResponse:
        return await asyncio.to_thread(
            self._post_json_sync, url, body, timeout, headers
        )

    def _post_json_sync(
        self, url: str, body: dict, timeout: float, headers: dict | None = None
    ) -> HttpResponse:
        payload = json.dumps(body).encode("utf-8")
        request_headers = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            url,
            data=payload,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _decode_response(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return _decode_response(exc.code, exc.read())


def _decode_response(status: int, raw: bytes) -> HttpResponse:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        payload = None
    return HttpResponse(status=status, json=payload if isinstance(payload, dict) else None, raw_len=len(raw))


class _TenantToken:
    __slots__ = ("access_token", "issued_at", "expires_in")

    def __init__(self, access_token: str, issued_at: float, expires_in: int):
        self.access_token = access_token
        self.issued_at = issued_at
        self.expires_in = expires_in

    def needs_refresh(self, now: float, ratio: float) -> bool:
        return now >= self.issued_at + self.expires_in * ratio

    def is_expired(self, now: float) -> bool:
        return now >= self.issued_at + self.expires_in


_token: _TenantToken | None = None
_token_lock: asyncio.Lock | None = None
_transport: Transport | None = None
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def set_transport(transport: Transport | None) -> None:
    global _transport
    _transport = transport


def reset_feishu_client() -> None:
    global _token, _token_lock, _transport, _clock, _sleep
    _token = None
    _token_lock = None
    _transport = None
    _clock = time.monotonic
    _sleep = asyncio.sleep


def token_view() -> TokenView:
    token = _token
    if token is None:
        return TokenView(
            has_token=False, needs_refresh=True, expires_in=None, age_seconds=None
        )
    now = _clock()
    settings = get_settings()
    return TokenView(
        has_token=True,
        needs_refresh=token.needs_refresh(now, settings.feishu_token_refresh_ratio),
        expires_in=max(0, int(token.expires_in - (now - token.issued_at))),
        age_seconds=now - token.issued_at,
    )


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _scrubbed_error(error: FeishuError, secrets: tuple[str, ...]) -> FeishuError:
    error.args = tuple(
        _scrub(arg, secrets) if isinstance(arg, str) else arg for arg in error.args
    )
    return error


def _ensure_lock() -> asyncio.Lock:
    global _token_lock
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    return _token_lock


def _ensure_transport() -> Transport:
    global _transport
    if _transport is None:
        _transport = UrllibTransport()
    return _transport


def _fresh_token(settings) -> _TenantToken | None:
    token = _token
    if token is None:
        return None
    if token.needs_refresh(_clock(), settings.feishu_token_refresh_ratio):
        return None
    return token


async def get_tenant_access_token() -> str:
    settings = get_settings()
    if not settings.feishu_enabled:
        raise FeishuDisabledError(TOKEN_OPERATION)
    token = _fresh_token(settings)
    if token is not None:
        return token.access_token
    async with _ensure_lock():
        token = _fresh_token(settings)
        if token is not None:
            return token.access_token
        token = await _fetch_token_with_degradation(settings)
    return token.access_token


async def _fetch_token_with_degradation(settings) -> _TenantToken:
    started = _clock()
    attempts = 0

    async def _attempt() -> _TenantToken:
        nonlocal attempts
        attempts += 1
        return await _fetch_tenant_token(settings)

    try:
        token = await _with_retry(_attempt, settings, TOKEN_OPERATION)
    except FeishuError:
        stale = _token
        if stale is not None and not stale.is_expired(_clock()):
            logger.warning(
                "%s",
                _scrub(
                    f"feishu {TOKEN_OPERATION} refresh failed; "
                    "reusing unexpired cached token (degraded)",
                    settings.secret_values(),
                ),
            )
            return stale
        _set_token(None)
        raise
    _set_token(token)
    elapsed_ms = (_clock() - started) * 1000
    logger.info(
        "%s",
        _scrub(
            f"feishu {TOKEN_OPERATION} fetched: attempt={attempts} "
            f"elapsed_ms={elapsed_ms:.0f} expires_in={token.expires_in}",
            settings.secret_values(),
        ),
    )
    return token


async def _fetch_tenant_token(settings) -> _TenantToken:
    transport = _ensure_transport()
    url = f"{settings.feishu_api_base}{TOKEN_PATH}"
    body = {"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret}
    try:
        response = await transport.post_json(url, body, settings.feishu_timeout_seconds)
    except OSError as exc:
        raise _scrubbed_error(
            classify(TOKEN_OPERATION, exc=exc), settings.secret_values()
        ) from exc
    payload = response.json if response.json is not None else {}
    code = payload.get("code")
    if not (200 <= response.status < 300 and code == 0):
        raise _scrubbed_error(
            classify(TOKEN_OPERATION, response.status, code),
            settings.secret_values(),
        )
    token_value = payload.get("tenant_access_token")
    expire = payload.get("expire")
    if (
        not isinstance(token_value, str)
        or not token_value
        or isinstance(expire, bool)
        or not isinstance(expire, (int, float))
        or expire <= 0
    ):
        raise _scrubbed_error(
            FeishuConfigError(
                TOKEN_OPERATION, response.status, code, detail="invalid token response structure"
            ),
            settings.secret_values(),
        )
    return _TenantToken(
        access_token=token_value, issued_at=_clock(), expires_in=int(expire)
    )


def _set_token(token: _TenantToken | None) -> None:
    global _token
    _token = token


async def _with_retry(
    operation: Callable[[], Awaitable[Any]], settings, operation_name: str
) -> Any:
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except FeishuError as error:
            if attempt >= settings.feishu_http_max_attempts or not error.retryable:
                raise
            delay = min(
                settings.feishu_http_backoff_seconds * (2 ** (attempt - 1)),
                settings.feishu_http_backoff_max_seconds,
            )
            logger.warning(
                "%s",
                _scrub(
                    f"feishu {operation_name} retryable failure: "
                    f"attempt={attempt} error_type={type(error).__name__} "
                    f"status={error.http_status}",
                    settings.secret_values(),
                ),
            )
            await _sleep(delay)


def _text_content(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


async def reply_message(message_ref: str, text: str) -> SendResult:
    url = (
        f"{get_settings().feishu_api_base}"
        f"{IM_MESSAGES_PATH}/{quote(message_ref, safe='')}/reply"
    )
    body = {"msg_type": "text", "content": _text_content(text)}
    return await _send_request(IM_REPLY_OPERATION, url, body)


async def send_message(recipient_external_id: str, text: str) -> SendResult:
    url = f"{get_settings().feishu_api_base}{IM_MESSAGES_PATH}?receive_id_type=open_id"
    body = {
        "receive_id": recipient_external_id,
        "msg_type": "text",
        "content": _text_content(text),
    }
    return await _send_request(IM_SEND_OPERATION, url, body)


async def _send_request(operation: str, url: str, body: dict) -> SendResult:
    settings = get_settings()
    try:
        token = await get_tenant_access_token()
    except FeishuError as exc:
        logger.error(
            "feishu %s skipped: %s",
            operation,
            _scrub(str(exc), settings.secret_values()),
        )
        return SendResult(ok=False, error=error_kind_of(exc))
    transport = _ensure_transport()
    headers = {"Authorization": f"Bearer {token}"}

    async def _call() -> dict:
        try:
            response = await transport.post_json(
                url, body, settings.feishu_timeout_seconds, headers=headers
            )
        except OSError as exc:
            raise _scrubbed_error(
                classify(operation, exc=exc), settings.secret_values()
            ) from exc
        payload = response.json if response.json is not None else {}
        code = payload.get("code")
        if not (200 <= response.status < 300 and code == 0):
            raise _scrubbed_error(
                classify(operation, response.status, code), settings.secret_values()
            )
        return payload

    try:
        payload = await _with_retry(_call, settings, operation)
    except FeishuError as exc:
        logger.error(
            "feishu %s failed: %s",
            operation,
            _scrub(str(exc), settings.secret_values()),
        )
        return SendResult(ok=False, error=error_kind_of(exc))
    except Exception:
        logger.exception("feishu %s failed unexpectedly", operation)
        return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_id = data.get("message_id")
    return SendResult(
        ok=True,
        external_message_id=message_id if isinstance(message_id, str) else None,
    )
