"""TOOL-011 单测共享构造：清单声明、设置替身、传输替身、注册表引导与敏感串断言。"""

import logging
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from app.core.settings import get_settings
from app.services.tool import ext_api
from app.services.tool.context import ToolContext
from app.services.tool.ext_api import HttpResponse, ManifestIndex, ToolManifestLoader
from app.services.tool.registry import ToolRegistry

NOW = datetime(2026, 9, 14, 12, 0, 0)

USER = "u-tool011"

WEATHER_TOOL_ID = "ext.api.weather.current"

HOOK_TOOL_ID = "ext.api.hook.notify"

WEATHER_HOST = "api.example.com"

HOOK_HOST = "hooks.example.com"

WEATHER_ENV = "EXT_API_WEATHER_TOKEN"

HOOK_ENV = "EXT_API_HOOK_KEY"

WEATHER_SECRET = "s3cr3t-weather-token-value"

HOOK_SECRET = "s3cr3t-hook-key-value"

SECRET_PATTERN = re.compile(r"s3cr3t")

USER_TOOL_ID = "user.mood.append"

MANIFESTS_DIR = Path("app/services/tool/manifests")


def assert_no_secret(text: str) -> None:
    """凭据值不可见断言：文本里不得出现任何 secret 模式串。"""
    assert not SECRET_PATTERN.search(text), text


def ext_settings(**overrides: Any) -> SimpleNamespace:
    """外部/自定义面设置替身：双闸默认 on，白名单默认含两个示例域名。"""
    values: dict[str, Any] = {
        "tool_system_enabled": True,
        "tool_external_api_enabled": True,
        "tool_user_defined_enabled": True,
        "tool_permission_enabled": False,
        "tool_schema_validation_enabled": False,
        "tool_observation_enabled": True,
        "tool_memory_enabled": True,
        "tool_ext_manifest_path": "",
        "tool_ext_allowed_hosts": f"{WEATHER_HOST},{HOOK_HOST}",
        "action_execution_timeout_seconds": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def clear_secret_env(monkeypatch) -> None:
    """清掉真实进程环境里的凭据变量，避免"环境中恰好存在"造成的假绿。"""
    monkeypatch.delenv(WEATHER_ENV, raising=False)
    monkeypatch.delenv(HOOK_ENV, raising=False)
    get_settings.cache_clear()


def weather_manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_id": WEATHER_TOOL_ID,
        "name": "查询天气",
        "description": "查询指定城市的当前天气。",
        "capability": "external_api",
        "action": "call",
        "http": {
            "method": "GET",
            "url": f"https://{WEATHER_HOST}/v1/weather",
            "auth": {"type": "bearer", "env": WEATHER_ENV},
            "params": {"city": "{params.city}", "units": "metric"},
            "timeout_seconds": 5,
        },
        "input_schema": {
            "parameters": [
                {"name": "city", "type": "string", "required": True, "max_length": 40}
            ]
        },
        "response_map": {
            "weather.temperature": "$.data.temperature:num",
            "weather.condition": "$.data.condition",
        },
        "permission": {
            "level": "sensitive",
            "scope": [f"external:{WEATHER_HOST}"],
            "confirm": "first_time",
        },
        "side_effects": ["read", "send_external"],
    }
    payload.update(overrides)
    return payload


def hook_manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_id": HOOK_TOOL_ID,
        "name": "外部提醒投递",
        "description": "把一个短标题投递到外部 webhook。",
        "capability": "external_api",
        "action": "call",
        "http": {
            "method": "POST",
            "url": f"https://{HOOK_HOST}/services/notify",
            "auth": {"type": "apikey", "env": HOOK_ENV},
            "params": {"title": "{params.title}"},
            "timeout_seconds": 8,
        },
        "input_schema": {
            "parameters": [{"name": "title", "type": "string", "required": True}]
        },
        "response_map": {"hook.accepted": "$.ok:bool", "hook.job_id": "$.job[0].id:str"},
        "permission": {"level": "sensitive", "confirm": "first_time"},
        "side_effects": ["send_external"],
    }
    payload.update(overrides)
    return payload


def user_declaration(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_id": USER_TOOL_ID,
        "name": "记录心情",
        "description": "把一句话心情写入长期记忆。",
        "steps": [
            {
                "capability": "memory",
                "action": "save",
                "params_map": {"fact": "{params.content}"},
            }
        ],
        "input_schema": {
            "parameters": [
                {"name": "content", "type": "string", "required": True, "max_length": 120}
            ]
        },
        "side_effects": ["write_memory"],
    }
    payload.update(overrides)
    return payload


def write_manifest(directory: Path, name: str, payload: dict[str, Any] | str) -> Path:
    path = directory / name
    text = payload if isinstance(payload, str) else yaml.safe_dump(payload, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


def loader(
    index: ManifestIndex,
    settings: Any = None,
    environ: dict[str, str] | None = None,
) -> ToolManifestLoader:
    return ToolManifestLoader(
        index,
        settings=settings if settings is not None else ext_settings(),
        environ=environ if environ is not None else {WEATHER_ENV: WEATHER_SECRET},
    )


def load_manifests(
    directory: Path,
    *,
    manifests: dict[str, dict[str, Any] | str],
    settings: Any = None,
    environ: dict[str, str] | None = None,
    registry: ToolRegistry | None = None,
    index: ManifestIndex | None = None,
) -> tuple[ToolRegistry, ManifestIndex, ext_api.LoadReport]:
    for name, payload in manifests.items():
        write_manifest(directory, name, payload)
    resolved_registry = registry if registry is not None else ToolRegistry()
    resolved_index = index if index is not None else ManifestIndex()
    report = loader(resolved_index, settings, environ).load(directory, resolved_registry)
    return resolved_registry, resolved_index, report


class StubTransport:
    """HTTP 传输替身：记录请求，按脚本返回响应 / 抛异常（默认 200 + 空 JSON）。"""

    def __init__(self, *responses: Any) -> None:
        self.responses: list[Any] = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        if not self.responses:
            return HttpResponse(status=200, json={}, raw_len=2)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def called(self) -> bool:
        return bool(self.calls)

    def header(self, name: str, index: int = 0) -> str:
        return self.calls[index]["headers"].get(name, "")


def response(
    payload: Any = None, *, status: int = 200, raw_len: int = 0
) -> HttpResponse:
    return HttpResponse(status=status, json=payload, raw_len=raw_len)


def capability(
    index: ManifestIndex,
    transport: StubTransport,
    settings: Any = None,
    environ: dict[str, str] | None = None,
) -> ext_api.ExternalApiCapability:
    return ext_api.ExternalApiCapability(
        index,
        settings=settings if settings is not None else ext_settings(),
        transport=transport,
        environ=environ if environ is not None else {WEATHER_ENV: WEATHER_SECRET},
    )


def ext_context(settings: Any = None, **overrides: Any) -> ToolContext:
    payload: dict[str, Any] = {
        "user_id": USER,
        "now": NOW,
        "settings": settings if settings is not None else ext_settings(),
        "dedupe_key": "dk-tool011",
    }
    payload.update(overrides)
    return ToolContext(**payload)


class CapturingHandler(logging.Handler):
    """日志捕获：用于断言告警含文件名/失败项、且**不含凭据值**。"""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self) -> str:
        rendered: list[str] = []
        for record in self.records:
            try:
                rendered.append(record.getMessage())
            except Exception:  # pragma: no cover - 格式串异常时退化为原始串
                rendered.append(str(record.msg))
        return "\n".join(rendered)
