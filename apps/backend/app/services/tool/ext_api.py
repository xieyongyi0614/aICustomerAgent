"""V2.4.0 外部 API 能力接入（architecture.md §10.2 / TOOL-011 §2.2、§2.3、§4.1、§4.2）。

把"接入一个外部能力"从改 Python 降为加一个声明文件，同时把安全边界固化为机制：

```text
manifests/*.yaml（声明）
     │ ToolManifestLoader.load(path)
     ▼
结构解析 + 八项校验（逐条短路：tool_id / https+白名单 / 方法 / 凭据引用 /
     │                              response_map 子集 / 权限下限 / side_effects / 长度预算）
     ├─ 失败 → 记 warning（文件名 + 失败项）+ 跳过该条，**不抛异常、不阻塞启动**
     └─ 通过 → ToolDefinition（namespace=ext.api, capability=external_api, action=call）
                → ToolRegistry.register（七项注册校验仍在注册表内）
     ▼
ExternalApiCapability.execute（统一执行器内，无旁路）
     ① host 白名单二次校验（防清单加载后配置变更）→ 不通过即 denied，不发起请求
     ② 凭据只从环境变量读取（清单里只存变量名）→ 缺失即 unavailable，不抛错不泄漏
     ③ 参数模板渲染（{params.x}）→ ④ HTTP（timeout ≤ 10s，urllib.request + to_thread）
     ⑤ response_map 子集提取 → ⑥ 全部 observations 打 untrusted=True（§9.5-10 提示注入防线）
```

**接口约束下的清单路由**：V9 `Capability.execute(action, params, ctx)` 不携带 tool_id，
而所有外部工具的 `(capability, action)` 恒为 `(external_api, call)`，故执行期按**参数签名**
在已加载清单里定位目标（`ManifestIndex.resolve`）：先取参数名集合完全相等者，其次取必需参数
齐备者，多条候选按（多出的声明参数少 → 调用方多余参数少 → tool_id 字典序）确定性取首；
装载期拒绝**参数签名完全重复**的清单（校验 1），保证"完全相等"分支恒唯一。

**错误分类（§4.2）**：凭据缺失 → `unavailable`；域名白名单二次校验不通过 → `failed` +
`failure_kind=denied`（`CapabilityResult.status` 值域不含 denied，E5 的 denied 由 failure_kind
承载）；网络异常 → `transient`；HTTP 4xx → `permanent`；5xx → `transient`；超时 → `timeout`。

纪律：凭据值只存在于执行期的局部变量与请求头，**不进清单、不进日志、不进端点响应、不进台账**
（错误文本统一经 `_scrub` 清洗）；无任意代码执行；`yaml` 守卫式导入（缺失时降级为"不加载清单 +
告警"，不成为硬依赖）。
"""

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.character.asuna.tool import EXT_API_FAILURE_TEXT
from app.core.settings import get_settings
from app.models.action import ActionSchema, CapabilityResult
from app.models.tool import (
    PERMISSION_LEVEL_VALUES,
    TOOL_CONFIRM_POLICIES,
    TOOL_DESCRIPTION_MAX_LENGTH,
    TOOL_NAME_MAX_LENGTH,
    TOOL_SIDE_EFFECT_KINDS,
    TOOL_WHEN_MAX_LENGTH,
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
    permission_level_rank,
)
from app.services.action.registry import ExecutionContext
from app.services.tool.registry import TOOL_ID_PATTERN, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

EXT_API_NAMESPACE = "ext.api"

EXT_API_CAPABILITY_NAME = "external_api"

EXT_API_ACTION = "call"

EXT_API_TOOL_ID_PREFIX = "ext.api."

EXT_API_SCOPE_PREFIX = "external:"

HOST_PARAM_NAME = "host"

MANIFEST_FILE_SUFFIXES: tuple[str, ...] = (".yaml", ".yml")

HTTP_METHODS: tuple[str, ...] = ("GET", "POST")

AUTH_TYPES: tuple[str, ...] = ("bearer", "apikey", "header")

DEFAULT_AUTH_HEADERS: dict[str, str] = {"bearer": "Authorization", "apikey": "X-API-Key"}

DEFAULT_TIMEOUT_SECONDS = 5.0

MAX_TIMEOUT_SECONDS = 10.0

DEFAULT_CONFIRM = "first_time"

ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAP_EXPRESSION_PATTERN = re.compile(
    r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+(?::(?:str|num|bool))?$"
)

OBSERVATION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

PARAM_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

PLACEHOLDER_PATTERN = re.compile(r"\{params\.([a-z][a-z0-9_]*)\}")

PLACEHOLDER_TOKEN_PATTERN = re.compile(r"\{[^{}]*\}")

UNTRUSTED_OBSERVATION_KEY = "ext.untrusted"

OBSERVATIONS_PAYLOAD_KEY = "observations"

UNTRUSTED_PAYLOAD_KEY = "untrusted"

REDACTED = "<redacted>"

SUCCEEDED = "succeeded"
FAILED = "failed"
TIMEOUT = "timeout"
UNAVAILABLE = "unavailable"

FAILURE_KIND_TRANSIENT = "transient"
FAILURE_KIND_PERMANENT = "permanent"
FAILURE_KIND_TIMEOUT = "timeout"
FAILURE_KIND_UNAVAILABLE = "unavailable"
FAILURE_KIND_DENIED = "denied"

RETRYABLE_FAILURE_KINDS: tuple[str, ...] = (
    FAILURE_KIND_TRANSIENT,
    FAILURE_KIND_TIMEOUT,
)

REASON_CREDENTIAL_MISSING = "credential_missing"
REASON_HOST_NOT_ALLOWED = "host_not_allowed"
REASON_MANIFEST_UNRESOLVED = "manifest_unresolved"
REASON_EXTERNAL_API_DISABLED = "external_api_disabled"
REASON_NETWORK_ERROR = "network_error"
REASON_HTTP_STATUS = "http_status"
REASON_REQUEST_TIMEOUT = "request_timeout"
REASON_UNEXPECTED = "unexpected_error"

MANIFEST_RULE_LABELS: dict[int | str, str] = {
    1: "校验 1｜tool_id 前缀与格式",
    2: "校验 2｜https 与域名白名单",
    3: "校验 3｜HTTP 方法白名单",
    4: "校验 4｜凭据环境变量引用",
    5: "校验 5｜response_map 表达式子集",
    6: "校验 6｜permission 等级下限",
    7: "校验 7｜side_effects 不含 irreversible",
    8: "校验 8｜name / description 长度预算",
}

RULE_STRUCTURE = "structure"
RULE_YAML_SYNTAX = "yaml_syntax"
RULE_YAML_UNAVAILABLE = "yaml_unavailable"
RULE_FILE_UNREADABLE = "file_unreadable"
RULE_REGISTRATION = "registration"

MANIFEST_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "tool_id",
        "name",
        "description",
        "when_to_use",
        "when_not_to_use",
        "capability",
        "action",
        "http",
        "response_map",
        "permission",
        "side_effects",
        "input_schema",
        "tags",
    }
)

HTTP_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"method", "url", "auth", "params", "timeout_seconds", "response_map"}
)

AUTH_ALLOWED_KEYS: frozenset[str] = frozenset({"type", "env", "header"})

PARAMETER_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"name", "type", "required", "description", "max_length", "enum", "format", "default"}
)

_MISSING = object()

_yaml_module: Any | None = None

_yaml_checked = False


def _load_yaml() -> Any | None:
    """守卫式导入 PyYAML：缺失时返回 None（调用方降级为不加载清单 + 告警）。"""
    global _yaml_module, _yaml_checked
    if not _yaml_checked:
        _yaml_checked = True
        try:
            import yaml  # noqa: PLC0415

            _yaml_module = yaml
        except Exception:  # pragma: no cover - 依赖缺失路径
            _yaml_module = None
            logger.warning(
                "PyYAML 不可用，外部 API 清单加载已跳过（yaml 非硬依赖，系统正常启动）"
            )
    return _yaml_module


class _ManifestRejected(Exception):
    """单条清单校验失败信号：承载失败项编号与原因（内部使用，load 内归一为跳过项）。"""

    def __init__(self, rule: int | str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason

    def label(self) -> str:
        return MANIFEST_RULE_LABELS.get(self.rule, str(self.rule))


def external_api_enabled(settings: Any = None) -> bool:
    """外部 API 面双闸判据：总闸 + `v24_tool_external_api_enabled`。"""
    resolved = settings if settings is not None else get_settings()
    if not bool(getattr(resolved, "v24_tool_system_enabled", False)):
        return False
    return bool(getattr(resolved, "v24_tool_external_api_enabled", False))


def allowed_ext_hosts(settings: Any = None) -> frozenset[str]:
    """域名白名单（空 = 全禁）。

    与 `services/tool/permission.py` 的读面刻意保持同构：权限闸按调用参数里的 host 判硬禁令，
    能力执行期按清单声明的 host 判二次校验，两处必须读到同一份白名单。
    """
    resolved = settings if settings is not None else get_settings()
    resolver = getattr(resolved, "allowed_ext_hosts", None)
    if callable(resolver):
        return frozenset(resolver())
    raw = getattr(resolved, "v24_tool_ext_allowed_hosts", "") or ""
    return frozenset(part.strip().lower() for part in str(raw).split(",") if part.strip())


def host_allowed(host: str, settings: Any = None) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    return normalized in allowed_ext_hosts(settings)


def failure_text_for(reason: str) -> str:
    return EXT_API_FAILURE_TEXT.get(reason, EXT_API_FAILURE_TEXT[REASON_UNEXPECTED])


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


@dataclass(frozen=True)
class LoadReport:
    """清单加载报告（§4.1）：`loaded` 为成功注册的 tool_id，`skipped` 逐条记失败项。"""

    path: str = ""
    loaded: list[str] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.loaded) + len(self.skipped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "loaded": list(self.loaded),
            "skipped": [dict(item) for item in self.skipped],
            "total": self.total,
        }


@dataclass(frozen=True)
class ExternalApiManifest:
    """单条外部 API 声明（**不保存任何凭据值**，只保存来源环境变量名）。"""

    tool_id: str
    name: str
    description: str
    method: str
    url: str
    host: str
    params: dict[str, str]
    response_map: dict[str, str]
    level: str
    scope: tuple[str, ...]
    confirm: str
    side_effects: tuple[str, ...]
    timeout_seconds: float
    declared_parameters: tuple[ToolParameter, ...]
    param_names: tuple[str, ...]
    required_param_names: tuple[str, ...]
    derived_parameters: tuple[ToolParameter, ...] = ()
    when_to_use: str = ""
    when_not_to_use: str = ""
    auth_type: str = ""
    auth_env: str = ""
    auth_header: str = ""
    source_file: str = ""
    tags: tuple[str, ...] = ()

    def credential_env_name(self) -> str:
        """凭据来源环境变量名；空串表示该清单不需要凭据。"""
        return self.auth_env

    def parameter_names(self) -> tuple[str, ...]:
        return self.param_names

    def public_view(self) -> dict[str, Any]:
        """端点投影：声明信息 + 凭据**变量名**（绝不含凭据值）。"""
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "http": {
                "method": self.method,
                "url": self.url,
                "host": self.host,
                "params": dict(self.params),
                "timeout_seconds": self.timeout_seconds,
            },
            "auth": {
                "type": self.auth_type,
                "env": self.auth_env,
                "header": self.auth_header,
                "configured": bool(self.auth_env),
            },
            "response_map": dict(self.response_map),
            "permission": {
                "level": self.level,
                "scope": list(self.scope),
                "confirm": self.confirm,
            },
            "side_effects": list(self.side_effects),
            "parameters": list(self.param_names),
            "tags": list(self.tags),
            "source_file": self.source_file,
        }


class ManifestIndex:
    """已加载清单索引：装载期登记 + 执行期按参数签名解析（确定性，见模块 docstring）。"""

    def __init__(self) -> None:
        self._manifests: dict[str, ExternalApiManifest] = {}

    def register(self, manifest: ExternalApiManifest) -> None:
        self._manifests[manifest.tool_id] = manifest

    def get(self, tool_id: str) -> ExternalApiManifest | None:
        return self._manifests.get(tool_id)

    def contains(self, tool_id: str) -> bool:
        return tool_id in self._manifests

    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._manifests))

    def all(self) -> list[ExternalApiManifest]:
        return [self._manifests[tool_id] for tool_id in sorted(self._manifests)]

    def signature(self, tool_id: str) -> tuple[str, ...]:
        manifest = self._manifests.get(tool_id)
        return () if manifest is None else tuple(sorted(manifest.param_names))

    def signatures(self) -> dict[str, tuple[str, ...]]:
        return {tool_id: self.signature(tool_id) for tool_id in self.tool_ids()}

    def clear(self) -> None:
        self._manifests.clear()

    def resolve(self, params: Mapping[str, Any] | None) -> ExternalApiManifest | None:
        """按参数签名定位目标清单；无候选返回 None（调用方判 unavailable，不误调）。"""
        if not self._manifests:
            return None
        keys = {str(key) for key in (params or {})}
        candidates = [
            manifest
            for manifest in self._manifests.values()
            if set(manifest.param_names) == keys
        ]
        if not candidates:
            candidates = [
                manifest
                for manifest in self._manifests.values()
                if set(manifest.required_param_names) <= keys
            ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        candidates.sort(
            key=lambda manifest: (
                len(set(manifest.param_names) - keys),
                len(keys - set(manifest.param_names)),
                manifest.tool_id,
            )
        )
        logger.warning(
            "外部清单参数签名匹配到多条候选，按最贴合者取首（确定性）：chosen=%s candidates=%s",
            candidates[0].tool_id,
            [manifest.tool_id for manifest in candidates],
        )
        return candidates[0]


def _require_mapping(value: Any, label: str, rule: int | str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _ManifestRejected(rule, f"{label} 必须是键值映射")
    return value


def _require_text(
    raw: Mapping[str, Any], key: str, rule: int | str, label: str = ""
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _ManifestRejected(rule, f"缺少必需字段或类型非法: {label or key}")
    return value.strip()


def _check_unknown_keys(
    raw: Mapping[str, Any], allowed: frozenset[str], label: str, rule: int | str
) -> None:
    unknown = sorted({str(key) for key in raw} - allowed)
    if unknown:
        raise _ManifestRejected(rule, f"{label} 含未允许字段: {', '.join(unknown)}")


def _check_tool_id(
    raw: Mapping[str, Any], registry: ToolRegistry, index: ManifestIndex
) -> str:
    tool_id = _require_text(raw, "tool_id", RULE_STRUCTURE)
    if not tool_id.startswith(EXT_API_TOOL_ID_PREFIX):
        raise _ManifestRejected(
            1, f"tool_id 必须以 {EXT_API_TOOL_ID_PREFIX} 为前缀: {tool_id}"
        )
    if not TOOL_ID_PATTERN.fullmatch(tool_id):
        raise _ManifestRejected(1, f"tool_id 不符合点分命名空间格式: {tool_id}")
    if index.contains(tool_id):
        raise _ManifestRejected(1, f"同一 tool_id 重复声明（首条生效，后续不覆盖）: {tool_id}")
    if registry.get(tool_id) is not None:
        raise _ManifestRejected(1, f"tool_id 已被注册，跳过不覆盖: {tool_id}")
    return tool_id


def _check_signature_unique(
    index: ManifestIndex, tool_id: str, param_names: tuple[str, ...]
) -> None:
    signature = tuple(sorted(param_names))
    for existing_id, existing_signature in index.signatures().items():
        if existing_signature == signature:
            raise _ManifestRejected(
                1,
                "参数签名与已加载清单重复，执行期无法确定性路由: "
                f"{tool_id} 与 {existing_id} 同为 {list(signature)}",
            )


def _check_http_endpoint(http: Mapping[str, Any], settings: Any) -> tuple[str, str]:
    url = _require_text(http, "url", RULE_STRUCTURE, "http.url")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise _ManifestRejected(2, f"http.url 必须为 https: {parts.scheme or '<空>'}")
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise _ManifestRejected(2, f"http.url 缺少 host: {url}")
    allowed = allowed_ext_hosts(settings)
    if not allowed:
        raise _ManifestRejected(2, "域名白名单为空（空 = 全禁），拒绝加载外部清单")
    if host not in allowed:
        raise _ManifestRejected(2, f"host 不在 v24_tool_ext_allowed_hosts 内: {host}")
    return url, host


def _check_http_method(http: Mapping[str, Any]) -> str:
    raw = http.get("method", "GET")
    if not isinstance(raw, str) or not raw.strip():
        raise _ManifestRejected(3, "http.method 必须是非空字符串")
    method = raw.strip().upper()
    if method not in HTTP_METHODS:
        raise _ManifestRejected(
            3, f"http.method 不在白名单内: {method}；合法值集: {', '.join(HTTP_METHODS)}"
        )
    return method


def _check_auth(
    http: Mapping[str, Any], environ: Mapping[str, str]
) -> tuple[str, str, str]:
    auth = http.get("auth")
    if auth is None:
        return "", "", ""
    mapping = _require_mapping(auth, "http.auth", 4)
    _check_unknown_keys(mapping, AUTH_ALLOWED_KEYS, "http.auth", 4)
    auth_type = str(mapping.get("type", "")).strip().lower()
    if auth_type not in AUTH_TYPES:
        raise _ManifestRejected(
            4,
            f"http.auth.type 非法: {auth_type or '<空>'}；合法值集: {', '.join(AUTH_TYPES)}",
        )
    env_name = mapping.get("env")
    if not isinstance(env_name, str) or not env_name.strip():
        raise _ManifestRejected(4, "http.auth.env 必须引用环境变量名（凭据只从环境变量读取）")
    env_name = env_name.strip()
    if not ENV_NAME_PATTERN.fullmatch(env_name):
        raise _ManifestRejected(4, f"http.auth.env 不是合法的环境变量名: {env_name}")
    if not environ.get(env_name):
        raise _ManifestRejected(
            4, f"环境变量 {env_name} 未设置或为空（不打印变量值，仅记变量名）"
        )
    header = str(mapping.get("header", "") or "").strip()
    if auth_type == "header" and not header:
        raise _ManifestRejected(4, "http.auth.type=header 时必须声明 header 名")
    return auth_type, env_name, header


def _map_direction(key: Any, value: Any) -> tuple[str, str]:
    key_text = str(key).strip()
    value_text = str(value).strip() if isinstance(value, str) else ""
    if key_text.startswith("$") and value_text and not value_text.startswith("$"):
        return value_text, key_text
    if value_text.startswith("$"):
        return key_text, value_text
    raise _ManifestRejected(
        5, f"response_map 必须一侧为 $. 路径表达式: {key_text!r} -> {value_text!r}"
    )


def _check_response_map(raw: Mapping[str, Any], http: Mapping[str, Any]) -> dict[str, str]:
    source = raw.get("response_map")
    if source is None:
        source = http.get("response_map")
    if source is None:
        raise _ManifestRejected(5, "缺少必需字段: response_map")
    mapping = _require_mapping(source, "response_map", 5)
    if not mapping:
        raise _ManifestRejected(5, "response_map 不得为空")
    resolved: dict[str, str] = {}
    for key, value in mapping.items():
        observation_key, expression = _map_direction(key, value)
        if not MAP_EXPRESSION_PATTERN.fullmatch(expression):
            raise _ManifestRejected(
                5,
                "表达式超出支持的子集（仅 $.a.b / $.a[0].b 与 :str/:num/:bool 后缀，"
                f"不支持函数/运算/条件/通配）: {expression}",
            )
        if not OBSERVATION_KEY_PATTERN.fullmatch(observation_key):
            raise _ManifestRejected(5, f"observations 键非法: {observation_key}")
        resolved[observation_key] = expression
    return resolved


def _check_permission(raw: Mapping[str, Any], host: str) -> tuple[str, tuple[str, ...], str]:
    permission = _require_mapping(raw.get("permission"), "permission", 6)
    level = str(permission.get("level", "")).strip().lower()
    if level not in PERMISSION_LEVEL_VALUES:
        raise _ManifestRejected(6, f"permission.level 非法: {level or '<空>'}")
    if permission_level_rank(level) < permission_level_rank("sensitive"):
        raise _ManifestRejected(6, f"permission.level 不得低于 sensitive: {level}")
    confirm = str(permission.get("confirm", DEFAULT_CONFIRM) or DEFAULT_CONFIRM).strip()
    if confirm not in TOOL_CONFIRM_POLICIES:
        raise _ManifestRejected(6, f"permission.confirm 非法: {confirm}")
    if confirm == "never":
        raise _ManifestRejected(6, "ext.api 工具不得声明 confirm=never（外部调用必须经确认流）")
    scope = _scope_values(permission.get("scope"), host)
    return level, scope, confirm


def _scope_values(raw: Any, host: str) -> tuple[str, ...]:
    default = (f"{EXT_API_SCOPE_PREFIX}{host}",)
    if raw is None:
        return default
    if isinstance(raw, str):
        values = tuple(part.strip() for part in raw.split(",") if part.strip())
        return values or default
    if isinstance(raw, (list, tuple)):
        values = tuple(str(item).strip() for item in raw if str(item).strip())
        return values or default
    raise _ManifestRejected(6, "permission.scope 必须是字符串或字符串列表")


def _check_side_effects(raw: Mapping[str, Any]) -> tuple[str, ...]:
    value = raw.get("side_effects")
    if not isinstance(value, (list, tuple)) or not value:
        raise _ManifestRejected(7, "side_effects 必须是非空列表")
    effects: list[str] = []
    for item in value:
        text = str(item).strip()
        if text not in TOOL_SIDE_EFFECT_KINDS:
            raise _ManifestRejected(
                7,
                f"side_effects 含未知取值: {text}；合法值集: {', '.join(TOOL_SIDE_EFFECT_KINDS)}",
            )
        if text == "irreversible":
            raise _ManifestRejected(7, "side_effects 不得含 irreversible")
        if text not in effects:
            effects.append(text)
    return tuple(effects)


def _check_tags(raw: Mapping[str, Any]) -> tuple[str, ...]:
    value = raw.get("tags")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        raise _ManifestRejected(RULE_STRUCTURE, "tags 必须是字符串或字符串列表")
    tags: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in tags:
            tags.append(text)
    return tuple(tags)


def _check_budget(raw: Mapping[str, Any]) -> tuple[str, str, str, str]:
    name = _require_text(raw, "name", RULE_STRUCTURE, "name")
    description = _require_text(raw, "description", RULE_STRUCTURE, "description")
    if len(name) > TOOL_NAME_MAX_LENGTH:
        raise _ManifestRejected(
            8, f"name 长度 {len(name)} 超出上限 {TOOL_NAME_MAX_LENGTH}"
        )
    if len(description) > TOOL_DESCRIPTION_MAX_LENGTH:
        raise _ManifestRejected(
            8, f"description 长度 {len(description)} 超出上限 {TOOL_DESCRIPTION_MAX_LENGTH}"
        )
    when_to_use = str(raw.get("when_to_use", "") or "").strip()
    when_not_to_use = str(raw.get("when_not_to_use", "") or "").strip()
    for field_name, value in (("when_to_use", when_to_use), ("when_not_to_use", when_not_to_use)):
        if len(value) > TOOL_WHEN_MAX_LENGTH:
            raise _ManifestRejected(
                8, f"{field_name} 长度 {len(value)} 超出上限 {TOOL_WHEN_MAX_LENGTH}"
            )
    return name, description, when_to_use, when_not_to_use


def _check_timeout(http: Mapping[str, Any]) -> float:
    raw = http.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _ManifestRejected(
            RULE_STRUCTURE, f"http.timeout_seconds 必须是数字: {raw!r}"
        )
    timeout = float(raw)
    if timeout <= 0:
        raise _ManifestRejected(RULE_STRUCTURE, f"http.timeout_seconds 必须大于 0: {timeout}")
    if timeout > MAX_TIMEOUT_SECONDS:
        logger.warning(
            "清单 http.timeout_seconds=%.1f 超过上限，按上限 %.1f 收敛",
            timeout,
            MAX_TIMEOUT_SECONDS,
        )
        return MAX_TIMEOUT_SECONDS
    return timeout


def _check_params_template(http: Mapping[str, Any]) -> dict[str, str]:
    value = http.get("params")
    if value is None:
        return {}
    mapping = _require_mapping(value, "http.params", RULE_STRUCTURE)
    templates: dict[str, str] = {}
    for key, item in mapping.items():
        name = str(key).strip()
        if not name:
            raise _ManifestRejected(RULE_STRUCTURE, "http.params 键不得为空")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise _ManifestRejected(
                RULE_STRUCTURE, f"http.params.{name} 必须是标量或 {{params.x}} 模板"
            )
        templates[name] = str(item)
    return templates


def _template_placeholders(templates: Mapping[str, str]) -> tuple[str, ...]:
    names: list[str] = []
    for template in templates.values():
        for token in PLACEHOLDER_TOKEN_PATTERN.findall(template):
            match = PLACEHOLDER_PATTERN.fullmatch(token)
            if match is None:
                raise _ManifestRejected(
                    RULE_STRUCTURE,
                    f"http.params 占位符非法（仅支持 {{params.<name>}}）: {token}",
                )
            name = match.group(1)
            if name not in names:
                names.append(name)
        remainder = PLACEHOLDER_TOKEN_PATTERN.sub("", template)
        if "{" in remainder or "}" in remainder:
            raise _ManifestRejected(RULE_STRUCTURE, "http.params 含未闭合的占位符")
    return tuple(names)


def _declared_parameters(raw: Mapping[str, Any]) -> tuple[ToolParameter, ...]:
    schema = raw.get("input_schema")
    if schema is None:
        return ()
    mapping = _require_mapping(schema, "input_schema", RULE_STRUCTURE)
    value = mapping.get("parameters")
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _ManifestRejected(RULE_STRUCTURE, "input_schema.parameters 必须是列表")
    parameters: list[ToolParameter] = []
    seen: set[str] = set()
    for item in value:
        entry = _require_mapping(item, "input_schema.parameters[]", RULE_STRUCTURE)
        _check_unknown_keys(
            entry, PARAMETER_ALLOWED_KEYS, "input_schema.parameters[]", RULE_STRUCTURE
        )
        name = _require_text(entry, "name", RULE_STRUCTURE, "input_schema.parameters[].name")
        if not PARAM_NAME_PATTERN.fullmatch(name):
            raise _ManifestRejected(RULE_STRUCTURE, f"参数名非法: {name}")
        if name == HOST_PARAM_NAME:
            raise _ManifestRejected(
                RULE_STRUCTURE, f"{HOST_PARAM_NAME} 是保留参数名（由清单 host 自动生成）"
            )
        if name in seen:
            raise _ManifestRejected(RULE_STRUCTURE, f"参数重复声明: {name}")
        seen.add(name)
        enum_value = entry.get("enum") or ()
        if enum_value and not isinstance(enum_value, (list, tuple)):
            raise _ManifestRejected(RULE_STRUCTURE, f"enum 必须是列表: {name}")
        try:
            parameters.append(
                ToolParameter(
                    name=name,
                    type=str(entry.get("type", "string") or "string"),
                    required=bool(entry.get("required", False)),
                    description=str(entry.get("description", "") or ""),
                    enum=tuple(enum_value),
                    default=entry.get("default"),
                    max_length=entry.get("max_length"),
                    format=str(entry.get("format", "") or ""),
                )
            )
        except Exception as error:
            raise _ManifestRejected(
                RULE_STRUCTURE, f"参数 {name} 声明非法: {error.__class__.__name__}"
            ) from error
    return tuple(parameters)


def _check_capability_binding(raw: Mapping[str, Any]) -> None:
    capability = str(raw.get("capability", "") or "").strip()
    if capability != EXT_API_CAPABILITY_NAME:
        raise _ManifestRejected(
            RULE_STRUCTURE, f"capability 固定为 {EXT_API_CAPABILITY_NAME}: {capability or '<空>'}"
        )
    action = str(raw.get("action", "") or "").strip()
    if action != EXT_API_ACTION:
        raise _ManifestRejected(RULE_STRUCTURE, f"action 固定为 {EXT_API_ACTION}: {action or '<空>'}")


def parse_manifest(
    raw: Mapping[str, Any],
    *,
    registry: ToolRegistry,
    index: ManifestIndex,
    settings: Any = None,
    environ: Mapping[str, str] | None = None,
    source_file: str = "",
) -> ExternalApiManifest:
    """单条清单解析 + 八项校验（首个失败项即抛出 `_ManifestRejected`）。"""
    resolved_settings = settings if settings is not None else get_settings()
    resolved_environ = environ if environ is not None else os.environ
    _require_mapping(raw, "清单根节点", RULE_STRUCTURE)
    _check_unknown_keys(raw, MANIFEST_ALLOWED_KEYS, "清单", RULE_STRUCTURE)
    _check_capability_binding(raw)
    tool_id = _check_tool_id(raw, registry, index)
    http = _require_mapping(raw.get("http"), "http", RULE_STRUCTURE)
    _check_unknown_keys(http, HTTP_ALLOWED_KEYS, "http", RULE_STRUCTURE)
    url, host = _check_http_endpoint(http, resolved_settings)
    method = _check_http_method(http)
    auth_type, auth_env, auth_header = _check_auth(http, resolved_environ)
    response_map = _check_response_map(raw, http)
    level, scope, confirm = _check_permission(raw, host)
    side_effects = _check_side_effects(raw)
    name, description, when_to_use, when_not_to_use = _check_budget(raw)
    timeout_seconds = _check_timeout(http)
    templates = _check_params_template(http)
    declared_parameters = _declared_parameters(raw)
    declared_names = tuple(parameter.name for parameter in declared_parameters)
    placeholder_names = _template_placeholders(templates)
    derived_names = tuple(
        name
        for name in placeholder_names
        if name not in declared_names and name != HOST_PARAM_NAME
    )
    param_names = (HOST_PARAM_NAME, *declared_names, *derived_names)
    required_names = (
        HOST_PARAM_NAME,
        *(parameter.name for parameter in declared_parameters if parameter.required),
        *derived_names,
    )
    derived_parameters = tuple(
        ToolParameter(
            name=name,
            type="string",
            required=True,
            description=f"清单模板参数 {name}",
            source_hint="manifest_template",
        )
        for name in derived_names
    )
    _check_signature_unique(index, tool_id, param_names)
    return ExternalApiManifest(
        tool_id=tool_id,
        name=name,
        description=description,
        method=method,
        url=url,
        host=host,
        params=templates,
        response_map=response_map,
        level=level,
        scope=scope,
        confirm=confirm,
        side_effects=side_effects,
        timeout_seconds=timeout_seconds,
        declared_parameters=declared_parameters,
        param_names=param_names,
        required_param_names=tuple(dict.fromkeys(required_names)),
        derived_parameters=derived_parameters,
        when_to_use=when_to_use,
        when_not_to_use=when_not_to_use,
        auth_type=auth_type,
        auth_env=auth_env,
        auth_header=auth_header,
        source_file=source_file,
        tags=_check_tags(raw),
    )


def definition_for(manifest: ExternalApiManifest) -> ToolDefinition:
    """清单 → ToolDefinition（§2.1 路径 A 生成规则）。

    `host` 参数由清单自动生成（required + enum 固定为声明值）：TOOL-005 的域名白名单硬禁令
    读的是**调用参数里的 host**，声明式工具必须把 host 暴露成参数，白名单校验才在统一执行器
    前置段生效；enum 只含声明值，故该参数无法被用来打其他域名。
    """
    parameters = [
        ToolParameter(
            name=HOST_PARAM_NAME,
            type="string",
            required=True,
            description=f"外部域名（声明固定值：{manifest.host}）",
            enum=(manifest.host,),
            default=manifest.host,
            source_hint="tool_declaration",
        ),
        *manifest.declared_parameters,
        *manifest.derived_parameters,
    ]
    return ToolDefinition(
        id=manifest.tool_id,
        name=manifest.name,
        description=manifest.description,
        when_to_use=manifest.when_to_use,
        when_not_to_use=manifest.when_not_to_use,
        namespace=EXT_API_NAMESPACE,
        capability=EXT_API_CAPABILITY_NAME,
        action=EXT_API_ACTION,
        input_schema=ToolSchema(parameters=parameters),
        permission=PermissionProfile(
            level=manifest.level,
            scope=manifest.scope,
            confirm=manifest.confirm,
            requires_online=True,
            audit=True,
        ),
        side_effects=manifest.side_effects,
        idempotency="keyed",
        timeout_seconds=manifest.timeout_seconds,
        tags=tuple(dict.fromkeys(("external", "api", *manifest.tags))),
        memory_policy_key=manifest.tool_id,
        observability_fields=manifest.parameter_names(),
    )


class ToolManifestLoader:
    """声明文件目录加载器：逐条解析 + 八项校验，**不抛异常、不阻塞启动**（§4.1）。"""

    def __init__(
        self,
        index: ManifestIndex | None = None,
        *,
        settings: Any = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._index = index if index is not None else get_manifest_index()
        self._settings = settings
        self._environ = environ
        self._last_report = LoadReport()

    def last_report(self) -> LoadReport:
        return self._last_report

    def load(self, path: str | None, registry: ToolRegistry | None = None) -> LoadReport:
        report = self._load(path, registry)
        self._last_report = report
        return report

    def _load(self, path: str | None, registry: ToolRegistry | None) -> LoadReport:
        text = "" if path is None else str(path).strip()
        if not text:
            logger.info("V24_TOOL_EXT_MANIFEST_PATH 为空，不加载任何外部 API 清单（E1）")
            return LoadReport(path="")
        directory = Path(text)
        if not directory.exists():
            logger.warning("外部 API 清单目录不存在，跳过加载: %s", text)
            return LoadReport(path=text)
        if not directory.is_dir():
            logger.warning("外部 API 清单路径不是目录，跳过加载: %s", text)
            return LoadReport(path=text)
        yaml_module = _load_yaml()
        if yaml_module is None:
            return LoadReport(
                path=text,
                skipped=[
                    {
                        "file": "",
                        "tool_id": None,
                        "rule": RULE_YAML_UNAVAILABLE,
                        "reason": "PyYAML 不可用，清单加载已跳过（系统正常启动）",
                    }
                ],
            )
        resolved_registry = registry if registry is not None else get_tool_registry()
        if resolved_registry is None:
            logger.warning("工具系统总闸未开启或注册表不可用，跳过外部 API 清单加载")
            return LoadReport(path=text)
        loaded: list[str] = []
        skipped: list[dict[str, Any]] = []
        for file_path in self._manifest_files(directory):
            self._load_file(
                file_path, yaml_module, resolved_registry, loaded, skipped
            )
        return LoadReport(path=text, loaded=loaded, skipped=skipped)

    @staticmethod
    def _manifest_files(directory: Path) -> list[Path]:
        files: list[Path] = []
        for suffix in MANIFEST_FILE_SUFFIXES:
            files.extend(sorted(directory.glob(f"*{suffix}")))
        return sorted(set(files))

    def _load_file(
        self,
        file_path: Path,
        yaml_module: Any,
        registry: ToolRegistry,
        loaded: list[str],
        skipped: list[dict[str, Any]],
    ) -> None:
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as error:
            logger.warning("外部清单读取失败，跳过: %s（%s）", file_path.name, error)
            skipped.append(
                {
                    "file": file_path.name,
                    "tool_id": None,
                    "rule": RULE_FILE_UNREADABLE,
                    "reason": f"读取失败: {error.__class__.__name__}",
                }
            )
            return
        try:
            raw = yaml_module.safe_load(text)
        except Exception as error:
            logger.warning(
                "外部清单 YAML 语法错误，跳过该文件: %s（%s: %s）",
                file_path.name,
                error.__class__.__name__,
                _scrub(str(error), ()),
            )
            skipped.append(
                {
                    "file": file_path.name,
                    "tool_id": None,
                    "rule": RULE_YAML_SYNTAX,
                    "reason": f"{error.__class__.__name__}: {error}",
                }
            )
            return
        if raw is None:
            logger.warning("外部清单为空文件，跳过: %s", file_path.name)
            skipped.append(
                {
                    "file": file_path.name,
                    "tool_id": None,
                    "rule": RULE_STRUCTURE,
                    "reason": "清单为空",
                }
            )
            return
        tool_id_hint = raw.get("tool_id") if isinstance(raw, Mapping) else None
        try:
            manifest = parse_manifest(
                raw,
                registry=registry,
                index=self._index,
                settings=self._settings,
                environ=self._environ,
                source_file=file_path.name,
            )
            definition = definition_for(manifest)
            registry.register(definition, get_external_api_capability())
        except _ManifestRejected as rejection:
            logger.warning(
                "外部清单校验失败，跳过该条: file=%s rule=%s reason=%s",
                file_path.name,
                rejection.label(),
                rejection.reason,
            )
            skipped.append(
                {
                    "file": file_path.name,
                    "tool_id": tool_id_hint if isinstance(tool_id_hint, str) else None,
                    "rule": rejection.rule,
                    "reason": rejection.reason,
                }
            )
            return
        except Exception as error:
            logger.warning(
                "外部清单注册失败，跳过该条: file=%s（%s: %s）",
                file_path.name,
                error.__class__.__name__,
                _scrub(str(error), ()),
            )
            skipped.append(
                {
                    "file": file_path.name,
                    "tool_id": tool_id_hint if isinstance(tool_id_hint, str) else None,
                    "rule": RULE_REGISTRATION,
                    "reason": f"{error.__class__.__name__}: {error}",
                }
            )
            return
        self._index.register(manifest)
        loaded.append(manifest.tool_id)
        logger.info(
            "外部 API 工具已注册: tool_id=%s method=%s host=%s",
            manifest.tool_id,
            manifest.method,
            manifest.host,
        )


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
        if not external_api_enabled(settings):
            return _result(
                UNAVAILABLE,
                failure_kind=FAILURE_KIND_UNAVAILABLE,
                reason_kind=REASON_EXTERNAL_API_DISABLED,
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


_index = ManifestIndex()

_capability: ExternalApiCapability | None = None

_loader: ToolManifestLoader | None = None

_transport: HttpTransport | None = None


def get_manifest_index() -> ManifestIndex:
    """模块级清单索引（进程内存态：重启后由声明文件重建，§3 反模式警示）。"""
    return _index


def get_external_api_capability() -> ExternalApiCapability:
    global _capability
    if _capability is None:
        _capability = ExternalApiCapability()
    return _capability


def get_manifest_loader() -> ToolManifestLoader:
    global _loader
    if _loader is None:
        _loader = ToolManifestLoader()
    return _loader


def get_http_transport() -> HttpTransport:
    global _transport
    if _transport is None:
        _transport = UrllibTransport()
    return _transport


def set_http_transport(transport: HttpTransport | None) -> None:
    """测试接缝：注入传输替身；`None` 表示恢复默认 urllib 实现。"""
    global _transport
    _transport = transport


def reset_external_api_state() -> None:
    """进程态归零（测试与热修用）：清单索引 + 加载报告 + 能力单例 + 传输替身。"""
    global _capability, _loader, _transport
    _index.clear()
    _capability = None
    _loader = None
    _transport = None


def last_load_report() -> LoadReport:
    return get_manifest_loader().last_report()
