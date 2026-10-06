"""V2.4.0 工具权限闸（architecture.md §9.2~§9.5 / TOOL-005 §2.2、§2.3、§4.1）。

执行前的最后一道闸：回答"这次调用被授权了吗"。与 V9 六闸门正交串联——六闸门先过
（不通过则根本不装配计划），权限闸在 `ToolExecutor` 内、参数校验之前。

七步短路（判定顺序固定，每步一个独立私有函数，按序被调用且首命中即终止）：

```text
⓪ 快照不可用                       → deny(snapshot_unavailable)
① 等级为 safe 或 normal            → allow(level_no_grant_required)
② 存在有效 grant（scope 覆盖）      → allow(grant_matched)
③ confirm == first_time 且无授权集  → confirm_required(kind=first_time)
④ confirm == always                → confirm_required(kind=always，grant 不生效)
⑤ 授权集存在但不覆盖本次请求范围     → deny(out_of_scope)
⑥ 不受信命名空间无任何 grant        → deny(untrusted_namespace)
⑦ 以上皆非                         → deny(default_deny)
```

**默认拒绝（fail-closed）是硬纪律**：任何未明确 allow 的情况一律 deny——
与 V9 detector"宁缺毋滥"同一价值观；判定函数不抛异常，编程级异常也归一为 deny。

第 ⓪ 步只判“授权快照是否可用”：不可用即 deny，可用则交 ①~⑦。原“总闸 / 权限子闸”
三段语义（`permission_layer_off` / `permission_layer_disabled_grant_free` /
`permission_layer_disabled`）已随 V2.4.0 开关体系删除而消失——权限段**转正常开**，
不再存在“子闸未启用即特权豁免”的部署口子。

纪律：`evaluate` 纯函数、零 IO；`build_snapshot` 是**唯一的读 IO 入口**，装配失败返回
`None`，由 `evaluate` 保守拒绝（E1）。授权 / 确认请求 / 通道绑定的读面全部经既有仓储，
本模块不直接触碰 SessionLocal。

P2-2：`PermissionDecision` 的类定义归口 `app/models/tool.py`（模型层零服务依赖，
`ToolExecution.permission_model()` 需要它是模型层契约），本模块**原样再导入**——
`from app.services.tool.permission import PermissionDecision` 的既有调用点全部不变。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.core import timeutil
from app.character.asuna.tool import (
    CONFIRM_PROMPT_DEFAULT,
    CONFIRM_PROMPT_FALLBACK,
    CONFIRM_PROMPT_MAX_CHARS,
    CONFIRM_PROMPT_TEMPLATES,
    CONFIRM_SUBJECT_MAX_CHARS,
)
from app.core.settings import get_settings
from app.models.tool import (
    TOOL_NAMESPACES,
    PermissionDecision,
    PermissionLevel,
    ToolDefinition,
    ToolInvocation,
    namespace_permission_floor,
    permission_level_rank,
)

logger = logging.getLogger(__name__)

DECISION_ALLOW = "allow"
DECISION_CONFIRM_REQUIRED = "confirm_required"
DECISION_DENY = "deny"

PERMISSION_DECISIONS: tuple[str, ...] = (
    DECISION_ALLOW,
    DECISION_CONFIRM_REQUIRED,
    DECISION_DENY,
)

GRANT_FREE_LEVELS: tuple[str, ...] = ("safe", "normal")

UNTRUSTED_NAMESPACES: tuple[str, ...] = ("user", "ext.api")

USER_NAMESPACE = "user"
EXT_API_NAMESPACE = "ext.api"

CONFIRM_POLICY_FIRST_TIME = "first_time"
CONFIRM_POLICY_ALWAYS = "always"

CONFIRM_KIND_FIRST_TIME = "first_time"
CONFIRM_KIND_ALWAYS = "always"

GRANT_SOURCE_USER_CONFIRM = "user_confirm"
GRANT_SOURCE_CHANNEL_BIND = "channel_bind"
GRANT_SOURCE_SESSION = "session"

WILDCARD = "*"

EXT_HOST_PARAM_KEYS: tuple[str, ...] = ("url", "endpoint", "host", "target")

REASON_NOT_EVALUATED = "permission_not_evaluated"
REASON_NOT_EVALUATED = "permission_not_evaluated"
REASON_SNAPSHOT_UNAVAILABLE = "snapshot_unavailable"
REASON_LEVEL_NO_GRANT_REQUIRED = "level_no_grant_required"
REASON_GRANT_MATCHED = "grant_matched"
REASON_FIRST_TIME_CONFIRMATION = "first_time_confirmation"
REASON_ALWAYS_CONFIRMATION = "always_confirmation"
REASON_OUT_OF_SCOPE = "out_of_scope"
REASON_UNTRUSTED_NAMESPACE = "untrusted_namespace"
REASON_DEFAULT_DENY = "default_deny"

PROMPT_SUBJECT_PARAM_KEYS: tuple[str, ...] = (
    "content",
    "query",
    "fact",
    "target",
    "object",
)


@dataclass(frozen=True)
class PermissionSnapshot:
    """授权快照（纯数据）：调用方预读，闸门内零 IO（TOOL-005 §2.2）。"""

    user_id: str = ""
    now: datetime | None = None
    grants: list[dict[str, Any]] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    channel_bound: bool = False
    settings: Any = None
    namespace_floors: dict[str, str] = field(default_factory=dict)


def _allow(reason: str, level: PermissionLevel, scope: tuple[str, ...]) -> PermissionDecision:
    return PermissionDecision(
        decision=DECISION_ALLOW, level=level, reason=reason, scope_required=scope
    )


def _deny(reason: str, level: PermissionLevel, scope: tuple[str, ...]) -> PermissionDecision:
    return PermissionDecision(
        decision=DECISION_DENY, level=level, reason=reason, scope_required=scope
    )


def _confirm(
    reason: str,
    level: PermissionLevel,
    scope: tuple[str, ...],
    *,
    kind: str,
    prompt: str | None,
) -> PermissionDecision:
    return PermissionDecision(
        decision=DECISION_CONFIRM_REQUIRED,
        level=level,
        reason=reason,
        confirm_prompt=prompt,
        scope_required=scope,
        confirm_kind=kind,
    )


def required_scope(definition: ToolDefinition) -> tuple[str, ...]:
    return tuple(str(item) for item in definition.permission.scope)


def confirm_policy(definition: ToolDefinition) -> str:
    return str(definition.permission.confirm or "never")


def is_untrusted_namespace(definition: ToolDefinition) -> bool:
    return definition.namespace in UNTRUSTED_NAMESPACES


def effective_level(definition: ToolDefinition, snapshot: PermissionSnapshot) -> PermissionLevel:
    """生效等级：声明等级为准；低于命名空间下限且无 override_reason 时取下限（只升不降）。"""
    declared = definition.permission.level
    floor = (snapshot.namespace_floors or {}).get(definition.namespace)
    if floor is None:
        try:
            floor = namespace_permission_floor(definition.namespace)
        except Exception:
            logger.exception("命名空间权限下限解析失败，按声明等级判定：%s", definition.namespace)
            return declared
    if permission_level_rank(declared) < permission_level_rank(floor):
        if not definition.permission.override_reason:
            return floor
    return declared


def normalize_scope(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw else ()
    return tuple(str(item) for item in raw)


def scope_covers(granted: Any, required: Any) -> bool:
    """范围覆盖：授权范围 ⊇ 请求范围；授权含通配 `*` 时视为工具级全范围授权。"""
    granted_scope = set(normalize_scope(granted))
    required_values = set(normalize_scope(required))
    if WILDCARD in granted_scope:
        return True
    if not required_values:
        return True
    return required_values <= granted_scope


def _grant_matches_tool(grant: dict[str, Any], tool_id: str) -> bool:
    value = grant.get("tool_id")
    return value in (None, "", WILDCARD) or str(value) == tool_id


def active_grants(
    snapshot: PermissionSnapshot, now: datetime, *, tool_id: str | None = None
) -> list[dict[str, Any]]:
    """有效授权（按 `now` 严格判定：过期即不匹配，E2）。"""
    result: list[dict[str, Any]] = []
    for grant in snapshot.grants or []:
        if not isinstance(grant, dict):
            continue
        if tool_id is not None and not _grant_matches_tool(grant, tool_id):
            continue
        expires_at = grant.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= now:
            continue
        result.append(grant)
    return result


def matching_grant(
    snapshot: PermissionSnapshot,
    definition: ToolDefinition,
    scope: tuple[str, ...],
    now: datetime,
) -> dict[str, Any] | None:
    for grant in active_grants(snapshot, now, tool_id=definition.id):
        if scope_covers(grant.get("scope"), scope):
            return grant
    return None


def tool_grants(
    snapshot: PermissionSnapshot, definition: ToolDefinition, now: datetime
) -> list[dict[str, Any]]:
    """该工具的**显式授权**（用户批准 / 会话级 / 范围级）。

    通道级隐含基础授权（`source=channel_bind`，范围为 `channel.<name>.base`）只参与 ② 的
    范围覆盖判定，不计入"该工具已有授权集"——否则通道绑定会让发送类工具的首次确认被
    误判为越界拒绝（E9）。
    """
    return [
        grant
        for grant in active_grants(snapshot, now, tool_id=definition.id)
        if str(grant.get("source") or "") != GRANT_SOURCE_CHANNEL_BIND
    ]


def has_tool_grant(
    snapshot: PermissionSnapshot, definition: ToolDefinition, now: datetime
) -> bool:
    return bool(tool_grants(snapshot, definition, now))


def _yields_to_untrusted_namespace(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
    now: datetime,
) -> bool:
    """③/④/⑤ 让位给第 ⑥ 步的两种情况（E11、§9.5-4）：

    - `user.*` 无任何 grant：未经用户显式授权，不进入确认流（E11）；
    - `ext.api.*` 不在域名白名单：白名单是硬禁令，不论是否已有授权。

    `ext.api.*` 命中白名单且尚未授权时按常规进入 ③（首次确认）。
    """
    if definition.namespace == USER_NAMESPACE:
        return not has_tool_grant(snapshot, definition, now)
    if definition.namespace == EXT_API_NAMESPACE:
        return not ext_host_allowed(definition, invocation, snapshot.settings)
    return False


def ext_host_allowed(
    definition: ToolDefinition, invocation: ToolInvocation, settings: Any
) -> bool:
    """§9.5-4 域名白名单：`ext.api.*` 的 host 必须在白名单内，空 = 全禁。"""
    if definition.namespace != "ext.api":
        return True
    allowed = _allowed_ext_hosts(settings)
    host = _invocation_host(invocation)
    return bool(host) and host in allowed


def _allowed_ext_hosts(settings: Any) -> frozenset[str]:
    resolver = getattr(settings, "allowed_ext_hosts", None)
    if callable(resolver):
        return frozenset(resolver())
    raw = getattr(settings, "tool_ext_allowed_hosts", "") or ""
    return frozenset(part.strip() for part in str(raw).split(",") if part.strip())


def _invocation_host(invocation: ToolInvocation) -> str:
    for key in EXT_HOST_PARAM_KEYS:
        value = invocation.params.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        text = text.split("://", 1)[-1]
        return text.split("/", 1)[0].split("?", 1)[0].strip().lower()
    return ""


def prompt_subject(definition: ToolDefinition, invocation: ToolInvocation) -> str:
    for key in PROMPT_SUBJECT_PARAM_KEYS:
        value = invocation.params.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        return " ".join(value.split())[:CONFIRM_SUBJECT_MAX_CHARS]
    return ""


def build_confirm_prompt(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    *,
    max_chars: int = CONFIRM_PROMPT_MAX_CHARS,
) -> str:
    """确认话术（角色语气，长度预算内）：生成失败回退通用话术（E12），不阻断流程。"""
    subject = prompt_subject(definition, invocation)
    template = CONFIRM_PROMPT_TEMPLATES.get(definition.id, CONFIRM_PROMPT_DEFAULT)
    raw = template.with_subject if subject else template.without_subject
    try:
        text = " ".join(str(raw).format(subject=subject, name=definition.name).split())
    except Exception:
        logger.exception("确认话术生成失败，回退通用话术：tool_id=%s", definition.id)
        return CONFIRM_PROMPT_FALLBACK
    if not text:
        return CONFIRM_PROMPT_FALLBACK
    return text[:max_chars]


def _step_snapshot_guard(
    definition: ToolDefinition,
    snapshot: PermissionSnapshot | None,
) -> PermissionDecision | None:
    """⓪ 快照不可用 → 拒绝；否则交后续步骤（权限层已随 V2.4.0 转正常开）。"""
    if snapshot is not None:
        return None
    return _deny(
        REASON_SNAPSHOT_UNAVAILABLE,
        definition.permission.level,
        required_scope(definition),
    )


def _step_level_no_grant_required(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """① safe / normal 无需授权即放行；不受信命名空间不享有免授权待遇。"""
    level = effective_level(definition, snapshot)
    if level not in GRANT_FREE_LEVELS or is_untrusted_namespace(definition):
        return None
    return _allow(REASON_LEVEL_NO_GRANT_REQUIRED, level, required_scope(definition))


def _step_grant_matched(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """② 有效 grant 覆盖请求范围 → 放行；`always` 策略下 grant 恒不生效（E4）。"""
    level = effective_level(definition, snapshot)
    if level in GRANT_FREE_LEVELS and not is_untrusted_namespace(definition):
        return None
    if confirm_policy(definition) == CONFIRM_POLICY_ALWAYS:
        return None
    scope = required_scope(definition)
    now = _snapshot_now(snapshot)
    if not _yields_to_untrusted_namespace(definition, invocation, snapshot, now):
        if matching_grant(snapshot, definition, scope, now) is not None:
            return _allow(REASON_GRANT_MATCHED, level, scope)
    return None


def _step_first_time_confirmation(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """③ first_time 且尚无任何授权集 → 首次确认（批准后落 grant）。"""
    if confirm_policy(definition) != CONFIRM_POLICY_FIRST_TIME:
        return None
    now = _snapshot_now(snapshot)
    if _yields_to_untrusted_namespace(definition, invocation, snapshot, now):
        return None
    if has_tool_grant(snapshot, definition, now):
        return None
    return _confirm(
        REASON_FIRST_TIME_CONFIRMATION,
        effective_level(definition, snapshot),
        required_scope(definition),
        kind=CONFIRM_KIND_FIRST_TIME,
        prompt=build_confirm_prompt(definition, invocation),
    )


def _step_always_confirmation(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """④ always → 每次确认，不落长期 grant。"""
    if confirm_policy(definition) != CONFIRM_POLICY_ALWAYS:
        return None
    now = _snapshot_now(snapshot)
    if _yields_to_untrusted_namespace(definition, invocation, snapshot, now):
        return None
    return _confirm(
        REASON_ALWAYS_CONFIRMATION,
        effective_level(definition, snapshot),
        required_scope(definition),
        kind=CONFIRM_KIND_ALWAYS,
        prompt=build_confirm_prompt(definition, invocation),
    )


def _step_out_of_scope(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """⑤ 有授权集但未覆盖本次请求范围 → 越界拒绝（E3）。"""
    now = _snapshot_now(snapshot)
    if _yields_to_untrusted_namespace(definition, invocation, snapshot, now):
        return None
    if not has_tool_grant(snapshot, definition, now):
        return None
    return _deny(
        REASON_OUT_OF_SCOPE, effective_level(definition, snapshot), required_scope(definition)
    )


def _step_untrusted_namespace(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision | None:
    """⑥ user.* 无 grant 或 ext.api.* 不在白名单 → 不受信命名空间拒绝（E11、§9.5-4）。"""
    namespace = definition.namespace
    if namespace == EXT_API_NAMESPACE:
        if ext_host_allowed(definition, invocation, snapshot.settings):
            return None
        logger.warning("ext.api 未命中域名白名单，按不受信命名空间拒绝：tool_id=%s", definition.id)
    elif namespace != USER_NAMESPACE:
        return None
    elif has_tool_grant(snapshot, definition, _snapshot_now(snapshot)):
        return None
    return _deny(
        REASON_UNTRUSTED_NAMESPACE,
        effective_level(definition, snapshot),
        required_scope(definition),
    )


def _step_default_deny(
    definition: ToolDefinition,
    invocation: ToolInvocation,
    snapshot: PermissionSnapshot,
) -> PermissionDecision:
    """⑦ 默认拒绝：未明确 allow 的一切情况（fail-closed 硬纪律）。"""
    return _deny(
        REASON_DEFAULT_DENY, effective_level(definition, snapshot), required_scope(definition)
    )


def _snapshot_now(snapshot: PermissionSnapshot) -> datetime:
    return timeutil.ensure_aware(snapshot.now) or timeutil.now()


_PERMISSION_STEPS: tuple[
    Callable[
        [ToolDefinition, ToolInvocation, PermissionSnapshot], PermissionDecision | None
    ],
    ...,
] = (
    _step_level_no_grant_required,
    _step_grant_matched,
    _step_first_time_confirmation,
    _step_always_confirmation,
    _step_out_of_scope,
    _step_untrusted_namespace,
    _step_default_deny,
)


class ToolPermissionGate:
    """七步短路权限闸：`evaluate` 纯函数零 IO，`build_snapshot` 是唯一读 IO 入口。"""

    def __init__(self, settings: Any = None, confirmations: Any = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._confirmations = confirmations

    def evaluate(
        self,
        defn: ToolDefinition,
        inv: ToolInvocation,
        snapshot: PermissionSnapshot | None,
    ) -> PermissionDecision:
        scope = required_scope(defn)
        try:
            guard = _step_snapshot_guard(defn, snapshot)
            if guard is not None:
                return guard
            assert snapshot is not None
            for step in _PERMISSION_STEPS:
                decision = step(defn, inv, snapshot)
                if decision is not None:
                    return decision
        except Exception:
            logger.exception("权限判定异常，按默认拒绝处理：tool_id=%s", defn.id)
            return _deny(REASON_DEFAULT_DENY, defn.permission.level, scope)
        return _deny(REASON_DEFAULT_DENY, defn.permission.level, scope)

    def build_snapshot(
        self, user_id: str, now: datetime, settings: Any = None
    ) -> PermissionSnapshot | None:
        """装配授权快照（唯一读 IO 入口）；任何装配失败返回 `None`（→ deny，E1）。"""
        resolved = settings if settings is not None else self._settings
        try:
            service = self._confirmation_service(resolved)
            return PermissionSnapshot(
                user_id=user_id,
                now=now,
                grants=service.grant_records(user_id, now),
                pending=service.pending_records(user_id, now),
                channel_bound=service.channel_bound(user_id),
                settings=resolved,
                namespace_floors={
                    namespace: namespace_permission_floor(namespace)
                    for namespace in TOOL_NAMESPACES
                },
            )
        except Exception:
            logger.exception("权限快照装配失败，按保守拒绝处理：user_id=%s", user_id)
            return None

    def _confirmation_service(self, settings: Any):
        if self._confirmations is not None:
            return self._confirmations
        from app.services.tool.confirmation import ConfirmationService

        return ConfirmationService(settings)
