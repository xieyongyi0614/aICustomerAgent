"""飞书授权登录客户端：授权地址拼接 + 授权码换用户身份（协议 + urllib 实现）。

飞书身份提供方三模块之一（同包 `oauth_state` / `login`，见包 `__init__` 的分工说明）。

协议依据（飞书开放平台官方文档，实现期已核对）：
  authorize : GET  {feishu_oauth_authorize_url}?client_id&response_type=code&redirect_uri&state[&scope]
  token     : POST {feishu_api_base}/open-apis/authen/v2/oauth/token
              {"grant_type":"authorization_code","client_id","client_secret","code","redirect_uri"}
  user_info : GET  {feishu_api_base}/open-apis/authen/v1/user_info   Authorization: Bearer <user_access_token>

只取 open_id / union_id / tenant_key（最小化：不取昵称、头像、邮箱、手机号）；
user_access_token 用完即弃，不落库、不落日志。授权码一次性且有效期 5 分钟，
故 token 交换**不重试**（重试会把「响应丢失」变成「码已使用」的假失败）；
user_info 为幂等 GET，按 feishu_http_* 退避重试。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
USER_INFO_PATH = "/open-apis/authen/v1/user_info"

_INVALID_CODE_BIZ_CODES = frozenset({20003, 20004})
_REDIRECT_URI_MISMATCH_BIZ_CODE = 20029


@dataclass(frozen=True, slots=True)
class FeishuUserIdentity:
    open_id: str
    union_id: str | None = None
    tenant_key: str | None = None


class FeishuOAuthError(RuntimeError):
    """授权换身份失败：网络不可达 / 飞书返回错误 / 响应缺字段。"""


class FeishuOAuthCodeInvalid(FeishuOAuthError):
    """授权码无效、已过期或已被使用——用户需重新发起授权。"""


class OAuthTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url, data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()


class FeishuOAuthClient(Protocol):
    def authorize_url(self, state: str) -> str: ...

    async def exchange_code(self, code: str) -> FeishuUserIdentity: ...


class UrllibFeishuOAuthClient:
    def __init__(self, transport: OAuthTransport | None = None):
        self._transport = transport or UrllibTransport()

    def authorize_url(self, state: str) -> str:
        settings = get_settings()
        params = {
            "client_id": settings.feishu_app_id,
            "response_type": "code",
            "redirect_uri": settings.feishu_oauth_redirect_uri,
            "state": state,
        }
        if settings.feishu_oauth_scope:
            params["scope"] = settings.feishu_oauth_scope
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in settings.feishu_oauth_authorize_url else "?"
        return f"{settings.feishu_oauth_authorize_url}{separator}{query}"

    async def exchange_code(self, code: str) -> FeishuUserIdentity:
        return await asyncio.to_thread(self._exchange_sync, code)

    def _exchange_sync(self, code: str) -> FeishuUserIdentity:
        settings = get_settings()
        access_token = self._fetch_user_access_token(settings, code)
        payload = self._request_json(
            settings,
            url=f"{settings.feishu_api_base}{USER_INFO_PATH}",
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            body=None,
            retry=True,
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        open_id = data.get("open_id")
        if not isinstance(open_id, str) or not open_id:
            raise FeishuOAuthError("飞书未返回用户标识（open_id 缺失）")
        union_id = data.get("union_id")
        tenant_key = data.get("tenant_key")
        return FeishuUserIdentity(
            open_id=open_id,
            union_id=union_id if isinstance(union_id, str) and union_id else None,
            tenant_key=(
                tenant_key if isinstance(tenant_key, str) and tenant_key else None
            ),
        )

    def _fetch_user_access_token(self, settings, code: str) -> str:
        body = json.dumps(
            {
                "grant_type": "authorization_code",
                "client_id": settings.feishu_app_id,
                "client_secret": settings.feishu_app_secret,
                "code": code,
                "redirect_uri": settings.feishu_oauth_redirect_uri,
            }
        ).encode("utf-8")
        payload = self._request_json(
            settings,
            url=f"{settings.feishu_api_base}{TOKEN_PATH}",
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            body=body,
            retry=False,
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise FeishuOAuthError("飞书未返回 user_access_token")
        return access_token

    def _request_json(
        self,
        settings,
        *,
        url: str,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        retry: bool,
    ) -> dict:
        attempts = settings.feishu_http_max_attempts if retry else 1
        backoff = settings.feishu_http_backoff_seconds
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                status, raw = self._transport.request(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout=settings.feishu_timeout_seconds,
                )
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                self._sleep(backoff)
                backoff = min(backoff * 2, settings.feishu_http_backoff_max_seconds)
                continue
            return self._parse_payload(status, raw, url=url)
        raise FeishuOAuthError(
            f"飞书接口不可达（{method} {url}）：{type(last_error).__name__}"
        )

    def _parse_payload(self, status: int, raw: bytes, *, url: str) -> dict:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise FeishuOAuthError(f"飞书接口响应非法（HTTP {status}）") from exc
        if not isinstance(payload, dict):
            raise FeishuOAuthError(f"飞书接口响应非法（HTTP {status}）")
        biz_code = payload.get("code")
        if status >= 400 or (isinstance(biz_code, int) and biz_code != 0):
            raise self._biz_error(biz_code, payload, status=status, url=url)
        return payload

    def _biz_error(
        self, biz_code, payload: dict, *, status: int, url: str
    ) -> FeishuOAuthError:
        if biz_code in _INVALID_CODE_BIZ_CODES:
            return FeishuOAuthCodeInvalid(
                f"飞书授权码无效或已过期（code={biz_code}）"
            )
        if biz_code == _REDIRECT_URI_MISMATCH_BIZ_CODE:
            logger.error(
                "飞书回调地址不匹配（code=%s）：请确认 FEISHU_OAUTH_REDIRECT_URI "
                "与开发者后台「安全设置 > 重定向 URL」完全一致",
                biz_code,
            )
        return FeishuOAuthError(
            f"飞书接口返回错误（HTTP {status}, code={biz_code}, url={url}）"
        )

    @staticmethod
    def _sleep(seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


_client: FeishuOAuthClient | None = None


def get_oauth_client() -> FeishuOAuthClient:
    global _client
    if _client is None:
        _client = UrllibFeishuOAuthClient()
    return _client


def set_oauth_client(client: FeishuOAuthClient | None) -> None:
    global _client
    _client = client
