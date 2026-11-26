"""外部 API 的 HTTP 传输、响应映射表达式与声明式能力执行器（TOOL-011 §2.3、§4.2、§6.1、§6.3 E5~E9）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext
from app.services.tool.ext_api.schema import (
    DEFAULT_AUTH_HEADERS,
    EXT_API_ACTION,
    EXT_API_CAPABILITY_NAME,
    FAILED,
    FAILURE_KIND_DENIED,
    FAILURE_KIND_PERMANENT,
    FAILURE_KIND_TIMEOUT,
    FAILURE_KIND_TRANSIENT,
    FAILURE_KIND_UNAVAILABLE,
    HOST_PARAM_NAME,
    MAP_EXPRESSION_PATTERN,
    OBSERVATIONS_PAYLOAD_KEY,
    PLACEHOLDER_PATTERN,
    REASON_CREDENTIAL_MISSING,
    REASON_HOST_NOT_ALLOWED,
    REASON_HTTP_STATUS,
    REASON_MANIFEST_UNRESOLVED,
    REASON_NETWORK_ERROR,
    REASON_REQUEST_TIMEOUT,
    REASON_UNEXPECTED,
    REDACTED,
    RETRYABLE_FAILURE_KINDS,
    SUCCEEDED,
    TIMEOUT,
    UNAVAILABLE,
    UNTRUSTED_OBSERVATION_KEY,
    UNTRUSTED_PAYLOAD_KEY,
    ExternalApiManifest,
    ManifestIndex,
    _MISSING,
    failure_text_for,
    host_allowed,
)

logger = logging.getLogger("app.services.tool.ext_api")


@dataclass(frozen=True)
class HttpResponse:
    """HTTP 响应投影（无凭据、无请求头）。"""

    status: int
    json: Any = None
    raw_len: int = 0


class HttpTransport(Protocol):
    """HTTP 传输接缝（默认 urllib；测试注入替身，与通道适配器同款倒置）。"""

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """标准库传输实现（项目既有 `channels/feishu/client.py` 同款：to_thread + urlopen）。"""

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        return await asyncio.to_thread(
            self._request_sync,
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout=timeout,
        )

    def _request_sync(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _decode_http_response(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return _decode_http_response(exc.code, exc.read())


def _decode_http_response(status: int, raw: bytes) -> HttpResponse:
    try:
        payload: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        payload = None
    return HttpResponse(status=status, json=payload, raw_len=len(raw))


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    scrubbed = text
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed


def _resolve_expression(expression: str, payload: Any) -> Any:
    """响应映射子集求值：不可达 / 类型转换失败返回 `_MISSING`（E6：不抛错、键缺省）。"""
    if not isinstance(expression, str) or not MAP_EXPRESSION_PATTERN.fullmatch(expression):
        return _MISSING
    path, separator, suffix = expression.partition(":")
    current = payload
    for match in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path):
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(current, Mapping) or key not in current:
                return _MISSING
            current = current[key]
        else:
            position = int(index)
            if not isinstance(current, (list, tuple)) or position >= len(current):
                return _MISSING
            current = current[position]
    if not separator:
        return current
    if suffix == "str":
        return "" if current is None else str(current)
    if suffix == "num":
        return _to_number(current)
    if suffix == "bool":
        return _to_bool(current)
    return _MISSING


def _to_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return _MISSING
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _MISSING
        try:
            number = float(text)
        except ValueError:
            return _MISSING
        return int(number) if number.is_integer() else number
    return _MISSING


_TRUE_TEXTS = frozenset({"true", "1", "yes", "on"})
_FALSE_TEXTS = frozenset({"false", "0", "no", "off"})


def _to_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if value is None:
        return _MISSING
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in _TRUE_TEXTS:
            return True
        if text in _FALSE_TEXTS:
            return False
        return _MISSING
    return _MISSING


def map_observations(
    response_map: Mapping[str, str], payload: Any
) -> dict[str, Any]:
    """按 response_map 提取 observations（不可达键缺省，不打占位值）。"""
    observations: dict[str, Any] = {}
    for observation_key, expression in response_map.items():
        value = _resolve_expression(expression, payload)
        if value is _MISSING:
            continue
        observations[observation_key] = value
    return observations


def render_params(templates: Mapping[str, str], params: Mapping[str, Any]) -> dict[str, str]:
    """参数模板渲染：`{params.x}` → 调用参数值（字符串化，bool 用 json 形态）。"""

    def _replace(match: re.Match[str]) -> str:
        value = params.get(match.group(1))
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return {
        key: PLACEHOLDER_PATTERN.sub(_replace, template)
        for key, template in templates.items()
    }


def _auth_headers(manifest: ExternalApiManifest, credential: str) -> dict[str, str]:
    if not manifest.auth_type or not credential:
        return {}
    header = manifest.auth_header or DEFAULT_AUTH_HEADERS.get(manifest.auth_type, "")
    if not header:
        return {}
    if manifest.auth_type == "bearer":
        return {header: f"Bearer {credential}"}
    return {header: credential}


def _result(
    status: str,
    *,
    failure_kind: str | None = None,
    reason_kind: str = "",
    observations: dict[str, Any] | None = None,
    host: str = "",
    http_status: int | None = None,
    response_bytes: int = 0,
    message: str = "",
) -> CapabilityResult:
    """统一结果形态：observations 恒在 payload 内且恒打 `untrusted=True` 标记。"""
    payload: dict[str, Any] = {
        UNTRUSTED_PAYLOAD_KEY: True,
        OBSERVATIONS_PAYLOAD_KEY: dict(observations or {}),
        "failure_kind": failure_kind,
        "retryable": failure_kind in RETRYABLE_FAILURE_KINDS,
        "reason_kind": reason_kind,
        "request_host": host,
        "http_status": http_status,
        "response_bytes": response_bytes,
        "message": message or ("" if failure_kind is None else failure_text_for(reason_kind)),
    }
    usage = {"http_status": http_status, "response_bytes": response_bytes, "external_calls": 1}
    return CapabilityResult(status=status, payload=payload, usage=usage)


class ExternalApiCapability:
    """声明驱动的通用 HTTP 能力（§4.2）：`call` 单动作，失败不抛异常。"""

    name = EXT_API_CAPABILITY_NAME
    description = "外部 API 声明式调用：域名白名单 + 环境变量凭据 + 响应映射（内容不受信）"
    actions = {EXT_API_ACTION: ActionSchema(required=[HOST_PARAM_NAME])}

    def __init__(
        self,
        index: ManifestIndex | None = None,
        *,
        settings: Any = None,
        transport: HttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._index = index
        self._settings = settings
        self._transport = transport
        self._environ = environ

    def validate(self, action: str, params: dict) -> list[str]:
        from app.services.tool.ext_api.registry import get_manifest_index

        if action != EXT_API_ACTION:
            return [f"未知动作: {action}"]
        errors = self.actions[EXT_API_ACTION].validate(params)
        host = str(params.get(HOST_PARAM_NAME) or "").strip().lower()
        if host and not host_allowed(host, self._settings):
            errors.append(f"host 不在域名白名单内: {host}")
        return errors

    async def execute(
        self, action: str, params: dict, ctx: ExecutionContext
    ) -> CapabilityResult:
        settings = self._settings if self._settings is not None else getattr(ctx, "settings", None)
        if action != EXT_API_ACTION:
            return _result(
                FAILED,
                failure_kind=FAILURE_KIND_PERMANENT,
                reason_kind=REASON_UNEXPECTED,
                message=f"未知动作: {action}",
            )
        index = self._index if self._index is not None else get_manifest_index()
        manifest = index.resolve(params)
        if manifest is None:
            return _result(
                UNAVAILABLE,
                failure_kind=FAILURE_KIND_UNAVAILABLE,
                reason_kind=REASON_MANIFEST_UNRESOLVED,
            )
        declared_host = str(params.get(HOST_PARAM_NAME) or "").strip().lower()
        if declared_host and declared_host != manifest.host:
            return _result(
                FAILED,
                failure_kind=FAILURE_KIND_DENIED,
                reason_kind=REASON_HOST_NOT_ALLOWED,
                host=manifest.host,
            )
        if not host_allowed(manifest.host, settings):
            logger.warning(
                "外部工具执行期白名单二次校验不通过，拒绝调用: tool_id=%s host=%s",
                manifest.tool_id,
                manifest.host,
            )
            return _result(
                FAILED,
                failure_kind=FAILURE_KIND_DENIED,
                reason_kind=REASON_HOST_NOT_ALLOWED,
                host=manifest.host,
            )
        credential, missing = self._credential(manifest)
        if missing:
            return _result(
                UNAVAILABLE,
                failure_kind=FAILURE_KIND_UNAVAILABLE,
                reason_kind=REASON_CREDENTIAL_MISSING,
                host=manifest.host,
            )
        return await self._call(manifest, params, credential)

    def _credential(self, manifest: ExternalApiManifest) -> tuple[str, bool]:
        """凭据读取：只从环境变量取；缺失返回 (\"\", True)，**不打印变量值**。"""
        env_name = manifest.credential_env_name()
        if not env_name:
            return "", False
        environ = self._environ if self._environ is not None else os.environ
        value = environ.get(env_name, "")
        if not value:
            logger.warning(
                "外部工具凭据缺失，按 unavailable 处理: tool_id=%s env=%s",
                manifest.tool_id,
                env_name,
            )
            return "", True
        return value, False

    async def _call(
        self, manifest: ExternalApiManifest, params: Mapping[str, Any], credential: str
    ) -> CapabilityResult:
        from app.services.tool.ext_api.registry import get_http_transport

        rendered = render_params(manifest.params, params)
        url = manifest.url
        body: bytes | None = None
        headers = {"Accept": "application/json"}
        if manifest.method == "GET":
            if rendered:
                separator = "&" if urlsplit(url).query else "?"
                url = f"{url}{separator}{urllib.parse.urlencode(rendered)}"
        else:
            body = json.dumps(rendered, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        headers.update(_auth_headers(manifest, credential))
        transport = self._transport if self._transport is not None else get_http_transport()
        try:
            response = await transport.request(
                method=manifest.method,
                url=url,
                headers=headers,
                body=body,
                timeout=manifest.timeout_seconds,
            )
        except (socket.timeout, TimeoutError):
            logger.warning("外部工具请求超时: tool_id=%s", manifest.tool_id)
            return _result(
                TIMEOUT,
                failure_kind=FAILURE_KIND_TIMEOUT,
                reason_kind=REASON_REQUEST_TIMEOUT,
                host=manifest.host,
            )
        except urllib.error.URLError as error:
            logger.warning(
                "外部工具网络异常: tool_id=%s（%s）",
                manifest.tool_id,
                _scrub(str(error.reason), (credential,)),
            )
            return _result(
                FAILED,
                failure_kind=FAILURE_KIND_TRANSIENT,
                reason_kind=REASON_NETWORK_ERROR,
                host=manifest.host,
            )
        except Exception as error:
            logger.warning(
                "外部工具调用异常，归一为 transient: tool_id=%s（%s: %s）",
                manifest.tool_id,
                error.__class__.__name__,
                _scrub(str(error), (credential,)),
            )
            return _result(
                FAILED,
                failure_kind=FAILURE_KIND_TRANSIENT,
                reason_kind=REASON_NETWORK_ERROR,
                host=manifest.host,
            )
        return self._from_response(manifest, response)

    def _from_response(
        self, manifest: ExternalApiManifest, response: HttpResponse
    ) -> CapabilityResult:
        status = int(getattr(response, "status", 0) or 0)
        if not 200 <= status < 300:
            kind = (
                FAILURE_KIND_PERMANENT
                if 400 <= status < 500
                else FAILURE_KIND_TRANSIENT
                if 500 <= status < 600
                else FAILURE_KIND_PERMANENT
            )
            logger.warning(
                "外部工具返回非 2xx: tool_id=%s status=%s kind=%s",
                manifest.tool_id,
                status,
                kind,
            )
            return _result(
                FAILED,
                failure_kind=kind,
                reason_kind=REASON_HTTP_STATUS,
                host=manifest.host,
                http_status=status,
                response_bytes=int(getattr(response, "raw_len", 0) or 0),
            )
        observations = map_observations(manifest.response_map, getattr(response, "json", None))
        return _result(
            SUCCEEDED,
            observations={UNTRUSTED_OBSERVATION_KEY: True, **observations},
            host=manifest.host,
            http_status=status,
            response_bytes=int(getattr(response, "raw_len", 0) or 0),
        )
