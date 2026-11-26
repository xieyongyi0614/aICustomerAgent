"""V2.4.0 外部 API 能力接入（architecture.md §10.2 / TOOL-011 §2.2、§2.3、§4.1、§4.2）。

本包由原单模块 `ext_api.py` 纯结构拆分而来：`schema`（清单常量 / 模型 / 八项校验 / 目录加载）、
`handlers`（HTTP 传输 + 响应映射表达式 + `ExternalApiCapability`）、`registry`（模块级单例与 getter）；
包 `__init__` 只做显式再导出，既有导入面（含测试可见的私有名）保持不变。

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

import logging

from app.services.tool.ext_api.schema import (
    AUTH_ALLOWED_KEYS,
    AUTH_TYPES,
    DEFAULT_AUTH_HEADERS,
    DEFAULT_CONFIRM,
    DEFAULT_TIMEOUT_SECONDS,
    ENV_NAME_PATTERN,
    EXT_API_ACTION,
    EXT_API_CAPABILITY_NAME,
    EXT_API_NAMESPACE,
    EXT_API_SCOPE_PREFIX,
    EXT_API_TOOL_ID_PREFIX,
    FAILED,
    FAILURE_KIND_DENIED,
    FAILURE_KIND_PERMANENT,
    FAILURE_KIND_TIMEOUT,
    FAILURE_KIND_TRANSIENT,
    FAILURE_KIND_UNAVAILABLE,
    HOST_PARAM_NAME,
    HTTP_ALLOWED_KEYS,
    HTTP_METHODS,
    MANIFEST_ALLOWED_KEYS,
    MANIFEST_FILE_SUFFIXES,
    MANIFEST_RULE_LABELS,
    MAP_EXPRESSION_PATTERN,
    MAX_TIMEOUT_SECONDS,
    OBSERVATIONS_PAYLOAD_KEY,
    OBSERVATION_KEY_PATTERN,
    PARAMETER_ALLOWED_KEYS,
    PARAM_NAME_PATTERN,
    PLACEHOLDER_PATTERN,
    PLACEHOLDER_TOKEN_PATTERN,
    REASON_CREDENTIAL_MISSING,
    REASON_EXTERNAL_API_DISABLED,
    REASON_HOST_NOT_ALLOWED,
    REASON_HTTP_STATUS,
    REASON_MANIFEST_UNRESOLVED,
    REASON_NETWORK_ERROR,
    REASON_REQUEST_TIMEOUT,
    REASON_UNEXPECTED,
    REDACTED,
    RETRYABLE_FAILURE_KINDS,
    RULE_FILE_UNREADABLE,
    RULE_REGISTRATION,
    RULE_STRUCTURE,
    RULE_YAML_SYNTAX,
    RULE_YAML_UNAVAILABLE,
    SUCCEEDED,
    TIMEOUT,
    UNAVAILABLE,
    UNTRUSTED_OBSERVATION_KEY,
    UNTRUSTED_PAYLOAD_KEY,
    ExternalApiManifest,
    LoadReport,
    ManifestIndex,
    ToolManifestLoader,
    _check_auth,
    _check_budget,
    _check_capability_binding,
    _check_http_endpoint,
    _check_http_method,
    _check_params_template,
    _check_permission,
    _check_response_map,
    _check_side_effects,
    _check_signature_unique,
    _check_tags,
    _check_timeout,
    _check_tool_id,
    _check_unknown_keys,
    _declared_parameters,
    _load_yaml,
    _ManifestRejected,
    _map_direction,
    _MISSING,
    _require_mapping,
    _require_text,
    _scope_values,
    _template_placeholders,
    allowed_ext_hosts,
    definition_for,
    failure_text_for,
    host_allowed,
    parse_manifest,
)
from app.services.tool.ext_api.handlers import (
    ExternalApiCapability,
    HttpResponse,
    HttpTransport,
    UrllibTransport,
    _auth_headers,
    _decode_http_response,
    _FALSE_TEXTS,
    _resolve_expression,
    _result,
    _scrub,
    _to_bool,
    _to_number,
    _TRUE_TEXTS,
    map_observations,
    render_params,
)
from app.services.tool.ext_api.registry import (
    get_external_api_capability,
    get_http_transport,
    get_manifest_index,
    get_manifest_loader,
    last_load_report,
    reset_external_api_state,
    set_http_transport,
)

logger = logging.getLogger("app.services.tool.ext_api")
