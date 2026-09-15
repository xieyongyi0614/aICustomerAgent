"""V2.4.0 确认流与授权存储（architecture.md §8.5 / §9.3、§9.4；TOOL-005 §2.2、§3.2、§4.2、§4.3）。

确认请求与授权行的**持久化通道复用 `trigger_registry`**（§3.1 裁决 A：零 DDL、零迁移）：
既有 `payload`(JSON) 承载 `invocation_snapshot` / `scope_required` / `dedupe_key` / 话术与
精确状态，`trigger_key`(唯一幂等键位) 承载 `request_id`，`due_at` 承载 TTL 到期时刻，
`trigger_type` 取既有白名单值 `action_due`（等待用户回应的待办触发）——
判别位（`payload["kind"]`）区分「确认请求」与「授权行」。

两层存储叠加：
- **持久层**（`trigger_registry`）：工具级 / 范围级授权与未决确认请求；
- **进程层**（内存态）：会话级授权（`v24_tool_confirm_ttl_reuse=False` 时批准只放行当次）；
- **通道级**：不新增存储，由 `channel_identities` 绑定状态隐含 `channel.<name>.base` 基础授权。

纪律：一切读 IO 经既有仓储（`trigger_registry_repository` / `channel_identity_repository`），
本模块不直接触碰 `SessionLocal`；`request` 为登记动作（DB 写），闸门路径（`evaluate`）
不经过本模块的写面。
"""

import hashlib
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from app.character.asuna.tool import (
    CONFIRM_APPROVE_LEXICON,
    CONFIRM_DENY_LEXICON,
    CONFIRM_WORD_MAX_CONTENT_CHARS,
)
from app.core.settings import get_settings
from app.models.action import ActionIntent
from app.models.tool import ToolInvocation
from app.repositories import channel_identity_repository, conversation_repository
from app.repositories import trigger_registry_repository
from app.services.tool.permission import (
    CONFIRM_KIND_FIRST_TIME,
    GRANT_SOURCE_CHANNEL_BIND,
    GRANT_SOURCE_SESSION,
    GRANT_SOURCE_USER_CONFIRM,
    WILDCARD,
    PermissionDecision,
    normalize_scope,
    scope_covers,
)

logger = logging.getLogger(__name__)

CONFIRMATION_ROW_KIND = "tool_confirmation"
GRANT_ROW_KIND = "tool_grant"

CONFIRMATION_TRIGGER_TYPE = "action_due"

CONFIRMATION_KEY_PREFIX = "tool_confirm"
GRANT_KEY_PREFIX = "tool_grant"

CONFIRMATION_OUTCOME_MARKER = "tool_confirmation"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_NOT_FOUND = "not_found"

CONFIRMATION_STATUSES: tuple[str, ...] = (
    STATUS_PENDING,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
)

ROW_STATUS_PENDING = "pending"
ROW_TERMINAL_STATUS = "cancelled"

CHANNEL_BOUND_STATUS = "active"

SCAN_LIMIT_PER_USER = 50
SCAN_LIMIT_GLOBAL = 200

DEFAULT_CONFIRM_TIMEOUT_HOURS = 24
DEFAULT_CONFIRM_TTL_REUSE = True

_QUESTION_GUARDS: tuple[str, ...] = (
    "能不能",
    "可不可以",
    "可以吗",
    "能吗",
    "你会",
    "能不能帮我",
)

_QUESTION_PATTERN = re.compile(r"(你|能|可以|会).{0,10}(吗|么|嘛)")


def non_todo_payload_kinds(settings: Any = None) -> tuple[str, ...] | None:
    """借表的**非待办行**判别位（P2-1）：确认请求行与授权行。

    这两类行用 `trigger_type = action_due` 复用既有表（零 DDL 裁决），`due_at` 只表达 TTL，
    因此从到期到清理（`expire_due`）的窗口里会被 `has_due` 误计为"到期待办触发"。
    返回 `None` 表示**不做排除**（工具总闸 off：这些行根本不会被登记，口径与 V9 完全一致），
    工具总闸 on 时返回两类 kind，供调用侧按需传给 `trigger_registry_repository.has_due`。
    """
    resolved = settings if settings is not None else get_settings()
    if not bool(getattr(resolved, "v24_tool_system_enabled", False)):
        return None
    return (CONFIRMATION_ROW_KIND, GRANT_ROW_KIND)


@dataclass(frozen=True)
class GrantRecord:
    """授权记录（TOOL-005 §2.2）：工具级 / 范围级 / 会话级 / 通道级四粒度共用。"""

    user_id: str
    tool_id: str
    scope: tuple[str, ...]
    granted_at: datetime | None
    expires_at: datetime | None
    source: str
    grant_id: str = ""

    def covers(self, scope: tuple[str, ...]) -> bool:
        return scope_covers(self.scope, scope)

    def matches_tool(self, tool_id: str) -> bool:
        return self.tool_id in ("", WILDCARD) or self.tool_id == tool_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "scope": list(self.scope),
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "source": self.source,
            "grant_id": self.grant_id,
        }


@dataclass(frozen=True)
class ConfirmationRequest:
    """确认请求（TOOL-005 §2.2）：`request_id` 即 `trigger_registry.trigger_key`。"""

    request_id: str
    user_id: str
    tool_id: str
    invocation_snapshot: dict[str, Any]
    dedupe_key: str
    scope_required: tuple[str, ...]
    status: str
    created_at: datetime
    expires_at: datetime
    prompt: str | None = None
    confirm_kind: str = CONFIRM_KIND_FIRST_TIME
    character_id: str = "asuna"

    def is_pending(self) -> bool:
        return self.status == STATUS_PENDING

    def expired_at(self, now: datetime) -> bool:
        return self.expires_at <= now

    def invocation(self) -> ToolInvocation:
        """还原原调用意图（参数与幂等键原样复用，防参数漂移）。"""
        snapshot = self.invocation_snapshot or {}
        intent_payload = snapshot.get("intent") or {
            "action_type": (snapshot.get("action_type") or "send_notification"),
            "confidence": "confident",
            "params": dict(snapshot.get("params") or {}),
        }
        intent = ActionIntent.model_validate(intent_payload)
        if not intent.dedupe_key:
            intent = intent.model_copy(update={"dedupe_key": self.dedupe_key})
        return ToolInvocation(
            tool_id=self.tool_id,
            params=dict(snapshot.get("params") or {}),
            rationale=str(snapshot.get("rationale") or ""),
            source=str(snapshot.get("source") or "conversation"),
            intent=intent,
            goal_id=snapshot.get("goal_id"),
            dedupe_key=self.dedupe_key or intent.dedupe_key,
            run_id=snapshot.get("run_id"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "dedupe_key": self.dedupe_key,
            "scope_required": list(self.scope_required),
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "prompt": self.prompt,
            "confirm_kind": self.confirm_kind,
        }


@dataclass(frozen=True)
class ConfirmationOutcome:
    """确认裁决结果（TOOL-005 §4.2）：`approved` / `denied` / `expired` / `not_found`。"""

    status: str
    request: ConfirmationRequest | None = None
    migrated: bool = False
    reason: str = ""


_SESSION_GRANTS: dict[tuple[str, str], GrantRecord] = {}


def reset_session_grants() -> None:
    """清空进程层授权（测试隔离与运维复位）。"""
    _SESSION_GRANTS.clear()


def session_grants_snapshot() -> dict[tuple[str, str], GrantRecord]:
    return dict(_SESSION_GRANTS)


def confirmation_key(user_id: str, tool_id: str, dedupe_key: str) -> str:
    suffix = (dedupe_key or "").strip() or tool_id
    return f"{CONFIRMATION_KEY_PREFIX}:{user_id}:{suffix}"


def grant_key(user_id: str, tool_id: str, scope: tuple[str, ...]) -> str:
    material = "|".join(scope) or WILDCARD
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:8]
    return f"{GRANT_KEY_PREFIX}:{user_id}:{tool_id}:{digest}"


def session_grant_id(user_id: str, tool_id: str) -> str:
    return f"session:{user_id}:{tool_id}"


def channel_base_scope(channel: str) -> str:
    """通道级基础授权范围：绑定通道即隐含 `channel.<name>.base`（不含发送类范围）。"""
    return f"channel:{channel}.base"


class ConfirmationService:
    """确认请求 / 批准 / 撤销 / 过期 / 授权复用（TOOL-005 §4.2）。"""

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def request(
        self,
        inv: ToolInvocation,
        decision: PermissionDecision,
        ctx: Any,
    ) -> ConfirmationRequest | None:
        """登记未决确认请求（DB 写）；登记失败返回 `None`，调用方按 deny 保守处理。"""
        now = _ctx_now(ctx)
        user_id = str(getattr(ctx, "user_id", "") or "")
        character_id = str(getattr(ctx, "character_id", "asuna") or "asuna")
        dedupe_key = inv.dedupe_key or _fallback_dedupe_key(inv)
        request_id = confirmation_key(user_id, inv.tool_id, dedupe_key)
        expires_at = now + timedelta(hours=self.confirm_timeout_hours())
        scope_required = tuple(decision.scope_required or ())
        intent_payload = inv.intent.model_dump(mode="json") if inv.intent else {}
        payload = {
            "kind": CONFIRMATION_ROW_KIND,
            "request_id": request_id,
            "user_id": user_id,
            "tool_id": inv.tool_id,
            "dedupe_key": dedupe_key,
            "scope_required": list(scope_required),
            "confirm_kind": decision.confirm_kind or CONFIRM_KIND_FIRST_TIME,
            "prompt": decision.confirm_prompt,
            "reason": decision.reason,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "invocation_snapshot": {
                "tool_id": inv.tool_id,
                "params": dict(inv.params),
                "rationale": inv.rationale,
                "source": inv.source,
                "goal_id": inv.goal_id,
                "run_id": inv.run_id,
                "intent": intent_payload,
            },
        }
        try:
            trigger_registry_repository.register(
                user_id,
                CONFIRMATION_TRIGGER_TYPE,
                request_id,
                expires_at,
                payload=payload,
                character_id=character_id,
                now=now,
            )
        except Exception:
            logger.exception("确认请求登记失败，按保守拒绝处理：tool_id=%s", inv.tool_id)
            return None
        return ConfirmationRequest(
            request_id=request_id,
            user_id=user_id,
            tool_id=inv.tool_id,
            invocation_snapshot=payload["invocation_snapshot"],
            dedupe_key=dedupe_key,
            scope_required=scope_required,
            status=STATUS_PENDING,
            created_at=now,
            expires_at=expires_at,
            prompt=decision.confirm_prompt,
            confirm_kind=payload["confirm_kind"],
            character_id=character_id,
        )

    def resolve(
        self, request_id: str, *, approved: bool, source: str = "user_confirm"
    ) -> ConfirmationOutcome:
        """未决请求 → 批准 / 否定（非法迁移即已决态原样返回，不二次迁移）。"""
        now = datetime.now()
        request = self.get(request_id)
        if request is None:
            return ConfirmationOutcome(STATUS_NOT_FOUND, None, reason="request_not_found")
        if not request.is_pending():
            return ConfirmationOutcome(
                request.status, request, migrated=False, reason="already_resolved"
            )
        if request.expired_at(now):
            self._terminate(request_id, STATUS_EXPIRED, now)
            return ConfirmationOutcome(
                STATUS_EXPIRED,
                replace(request, status=STATUS_EXPIRED),
                migrated=True,
                reason="ttl_expired",
            )
        if not approved:
            self._terminate(request_id, STATUS_DENIED, now)
            return ConfirmationOutcome(
                STATUS_DENIED,
                replace(request, status=STATUS_DENIED),
                migrated=True,
                reason=f"denied_by_{source}",
            )
        self._terminate(request_id, STATUS_APPROVED, now)
        if request.confirm_kind == CONFIRM_KIND_FIRST_TIME:
            self.grant_scope(
                request.user_id, request.tool_id, request.scope_required, now=now
            )
        return ConfirmationOutcome(
            STATUS_APPROVED,
            replace(request, status=STATUS_APPROVED),
            migrated=True,
            reason=f"approved_by_{source}",
        )

    def get(self, request_id: str) -> ConfirmationRequest | None:
        row = self._row(request_id)
        if row is None:
            return None
        return _to_request(row)

    def pending(self, user_id: str, now: datetime | None = None) -> list[ConfirmationRequest]:
        """未决且未过期的确认请求，按 `created_at` 倒序（E7：命中最近一条）。"""
        now = now or datetime.now()
        requests = [
            request
            for request in self._requests(user_id)
            if request.is_pending() and not request.expired_at(now)
        ]
        requests.sort(key=lambda item: item.created_at, reverse=True)
        return requests

    def pending_records(self, user_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
        return [
            {
                "request_id": request.request_id,
                "tool_id": request.tool_id,
                "created_at": request.created_at,
                "expires_at": request.expires_at,
            }
            for request in self.pending(user_id, now)
        ]

    def expire_due(self, now: datetime | None = None) -> int:
        """过期清理（复用既有维护步，不新增维护步）：返回清理条数。

        两类行都需要清理，否则 `trigger_registry.has_due` 会把它们计入"到期待办触发"：
        - 未决确认请求超时 → `expired`（工具不执行，E5）；
        - 到期授权行 → `cancelled`（授权本就按 `expires_at` 严格判定失效，落终态只为
          不污染 `has_due` 的待办口径）。
        """
        now = now or datetime.now()
        expired = 0
        for row in self._scan_rows():
            payload = dict(getattr(row, "payload", None) or {})
            kind = payload.get("kind")
            if kind == CONFIRMATION_ROW_KIND:
                request = _to_request(row)
                if request is None or not request.is_pending() or not request.expired_at(now):
                    continue
                if self._terminate(request.request_id, STATUS_EXPIRED, now):
                    expired += 1
            elif kind == GRANT_ROW_KIND:
                if str(getattr(row, "status", "")) != ROW_STATUS_PENDING:
                    continue
                expires_at = _as_datetime(payload.get("expires_at")) or _row_due_at(row)
                if not isinstance(expires_at, datetime) or expires_at > now:
                    continue
                if trigger_registry_repository.cancel(
                    str(getattr(row, "trigger_key", "")), "tool_grant:expired", now
                ):
                    expired += 1
        return expired

    def revoke_request(self, request_id: str, *, reason: str = "operator_revoke") -> bool:
        """运维撤销未决请求（等价否定，不执行）。"""
        request = self.get(request_id)
        if request is None or not request.is_pending():
            return False
        outcome = self.resolve(request_id, approved=False, source=reason)
        return outcome.migrated

    def grant_scope(
        self,
        user_id: str,
        tool_id: str,
        scope: tuple[str, ...],
        *,
        persistent: bool | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """落授权：`v24_tool_confirm_ttl_reuse=True` 落 TTL 持久授权，False 只放行当次。"""
        now = now or datetime.now()
        resolved_persistent = (
            self.confirm_ttl_reuse() if persistent is None else bool(persistent)
        )
        scope_tuple = normalize_scope(scope) or (WILDCARD,)
        if not resolved_persistent:
            grant_id = session_grant_id(user_id, tool_id)
            _SESSION_GRANTS[(user_id, tool_id)] = GrantRecord(
                user_id=user_id,
                tool_id=tool_id,
                scope=scope_tuple,
                granted_at=now,
                expires_at=None,
                source=GRANT_SOURCE_SESSION,
                grant_id=grant_id,
            )
            return grant_id
        grant_id = grant_key(user_id, tool_id, scope_tuple)
        expires_at = now + timedelta(hours=self.confirm_timeout_hours())
        payload = {
            "kind": GRANT_ROW_KIND,
            "grant_id": grant_id,
            "user_id": user_id,
            "tool_id": tool_id,
            "scope": list(scope_tuple),
            "source": GRANT_SOURCE_USER_CONFIRM,
            "granted_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        try:
            trigger_registry_repository.register(
                user_id,
                CONFIRMATION_TRIGGER_TYPE,
                grant_id,
                expires_at,
                payload=payload,
                now=now,
            )
        except Exception:
            logger.exception("授权落库失败，按未授权处理：tool_id=%s", tool_id)
            return None
        return grant_id

    def has_grant(
        self,
        user_id: str,
        tool_id: str,
        scope: tuple[str, ...],
        *,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now()
        for record in self.grant_records(user_id, now):
            record_tool_id = record["tool_id"]
            if record_tool_id not in ("", WILDCARD) and record_tool_id != tool_id:
                continue
            if scope_covers(record["scope"], scope):
                return True
        return False

    def grant_records(self, user_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
        """有效授权清单（含通道级隐含授权）：持久层 + 进程层 + 通道绑定。"""
        now = now or datetime.now()
        records: list[dict[str, Any]] = []
        for (grant_user, _tool_id), grant in sorted(_SESSION_GRANTS.items()):
            if grant_user != user_id:
                continue
            records.append(grant.as_dict())
        for channel in self.bound_channels(user_id):
            records.append(
                GrantRecord(
                    user_id=user_id,
                    tool_id=WILDCARD,
                    scope=(channel_base_scope(channel),),
                    granted_at=None,
                    expires_at=None,
                    source=GRANT_SOURCE_CHANNEL_BIND,
                    grant_id=channel_base_scope(channel),
                ).as_dict()
            )
        records.extend(self._persistent_grants(user_id, now))
        return records

    def bound_channels(self, user_id: str) -> list[str]:
        try:
            rows = channel_identity_repository.list_by_internal_user(user_id)
        except Exception:
            logger.exception("通道绑定状态读取失败，按未绑定处理：user_id=%s", user_id)
            return []
        channels: list[str] = []
        for row in rows:
            channel = str(getattr(row, "channel", "") or "")
            status = str(getattr(row, "status", "") or "")
            if channel and status == CHANNEL_BOUND_STATUS and channel not in channels:
                channels.append(channel)
        return channels

    def channel_bound(self, user_id: str) -> bool:
        return bool(self.bound_channels(user_id))

    def revoke(self, user_id: str, tool_id: str, now: datetime | None = None) -> int:
        """撤销授权（工具级 / 范围级 / 会话级；通道级随解绑失效）：返回撤销条数。"""
        now = now or datetime.now()
        revoked = 0
        for key, grant in list(_SESSION_GRANTS.items()):
            if key[0] != user_id:
                continue
            if tool_id not in ("", WILDCARD) and key[1] != tool_id:
                continue
            _SESSION_GRANTS.pop(key, None)
            revoked += 1
        for row in self._rows(user_id):
            payload = dict(getattr(row, "payload", None) or {})
            if payload.get("kind") != GRANT_ROW_KIND:
                continue
            row_tool_id = str(payload.get("tool_id") or "")
            if tool_id not in ("", WILDCARD) and row_tool_id != tool_id:
                continue
            if trigger_registry_repository.cancel(
                str(getattr(row, "trigger_key", "")), "tool_grant:revoked", now
            ):
                revoked += 1
        return revoked

    def release_session_grant(self, user_id: str, tool_id: str) -> bool:
        """消费会话级授权（`ttl_reuse=False` 时批准只放行当次执行）。"""
        return _SESSION_GRANTS.pop((user_id, tool_id), None) is not None

    def confirm_timeout_hours(self) -> int:
        return int(
            getattr(
                self._settings, "v24_tool_confirm_timeout_hours", DEFAULT_CONFIRM_TIMEOUT_HOURS
            )
        )

    def confirm_ttl_reuse(self) -> bool:
        return bool(
            getattr(self._settings, "v24_tool_confirm_ttl_reuse", DEFAULT_CONFIRM_TTL_REUSE)
        )

    def _persistent_grants(self, user_id: str, now: datetime) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in self._rows(user_id):
            payload = dict(getattr(row, "payload", None) or {})
            if payload.get("kind") != GRANT_ROW_KIND:
                continue
            if str(getattr(row, "status", "")) != ROW_STATUS_PENDING:
                continue
            expires_at = _as_datetime(payload.get("expires_at")) or _row_due_at(row)
            if isinstance(expires_at, datetime) and expires_at <= now:
                continue
            records.append(
                GrantRecord(
                    user_id=user_id,
                    tool_id=str(payload.get("tool_id") or ""),
                    scope=normalize_scope(payload.get("scope")),
                    granted_at=_as_datetime(payload.get("granted_at")),
                    expires_at=expires_at,
                    source=str(payload.get("source") or GRANT_SOURCE_USER_CONFIRM),
                    grant_id=str(payload.get("grant_id") or getattr(row, "trigger_key", "")),
                ).as_dict()
            )
        return records

    def _requests(self, user_id: str) -> list[ConfirmationRequest]:
        return [
            request
            for request in (_to_request(row) for row in self._rows(user_id))
            if request is not None
        ]

    def _rows(self, user_id: str) -> list[Any]:
        return trigger_registry_repository.list_recent(user_id, limit=SCAN_LIMIT_PER_USER)

    def _row(self, request_id: str) -> Any:
        return trigger_registry_repository.get(request_id)

    def _scan_rows(self) -> list[Any]:
        rows: dict[str, Any] = {}
        try:
            user_ids = conversation_repository.list_user_ids()
        except Exception:
            logger.exception("用户清单读取失败，回退全局有界扫描")
            user_ids = []
        for user_id in user_ids:
            for row in self._rows(user_id):
                rows[str(getattr(row, "trigger_key", ""))] = row
        if not user_ids:
            for row in trigger_registry_repository.list_recent(
                None, limit=SCAN_LIMIT_GLOBAL
            ):
                rows[str(getattr(row, "trigger_key", ""))] = row
        return list(rows.values())

    def _terminate(self, request_id: str, status: str, now: datetime) -> bool:
        return bool(
            trigger_registry_repository.cancel(
                request_id, f"{CONFIRMATION_OUTCOME_MARKER}:{status}", now
            )
        )


class ConfirmationIntentDetector:
    """确认意图检出（TOOL-005 §4.3）：确定性词表 + 问句守卫 + 祈使优先，宁缺毋滥。"""

    def detect(
        self, content: str, pending: list[ConfirmationRequest]
    ) -> tuple[str, str] | None:
        try:
            return self._detect(content, pending)
        except Exception:
            logger.exception("确认意图检出异常，降级为 None")
            return None

    def _detect(
        self, content: str, pending: list[ConfirmationRequest]
    ) -> tuple[str, str] | None:
        if not content or not content.strip() or not pending:
            return None
        if _is_question_inquiry(content):
            return None
        verb = _confirmation_verb(content)
        if verb is None:
            return None
        target = _most_recent(pending)
        if target is None:
            return None
        return target.request_id, verb


def _confirmation_verb(content: str) -> str | None:
    """祈使优先：否定祈使（别发 / 不要 / 取消）先于泛肯定词判定。"""
    text = content.strip()
    for word in CONFIRM_DENY_LEXICON:
        if word in text:
            return "deny"
    for word in CONFIRM_APPROVE_LEXICON:
        if word in text:
            if len(word) == 1 and len(text) > CONFIRM_WORD_MAX_CONTENT_CHARS:
                continue
            return "approve"
    return None


def _is_question_inquiry(content: str) -> bool:
    """问句守卫：询问语气（"能发吗"、"明天几点的会？"）不触发确认执行，存疑即不执行。"""
    text = content.strip()
    if text.endswith(("?", "？")):
        return True
    if any(guard in content for guard in _QUESTION_GUARDS):
        return True
    return _QUESTION_PATTERN.search(content) is not None


def _most_recent(pending: list[ConfirmationRequest]) -> ConfirmationRequest | None:
    ordered = sorted(pending, key=lambda item: item.created_at, reverse=True)
    return ordered[0] if ordered else None


def _to_request(row: Any) -> ConfirmationRequest | None:
    payload = dict(getattr(row, "payload", None) or {})
    if payload.get("kind") != CONFIRMATION_ROW_KIND:
        return None
    snapshot = dict(payload.get("invocation_snapshot") or {})
    request_id = str(payload.get("request_id") or getattr(row, "trigger_key", ""))
    if not request_id:
        return None
    created_at = _as_datetime(payload.get("created_at")) or _row_created_at(row)
    expires_at = _as_datetime(payload.get("expires_at")) or _row_due_at(row)
    return ConfirmationRequest(
        request_id=request_id,
        user_id=str(payload.get("user_id") or getattr(row, "user_id", "")),
        tool_id=str(payload.get("tool_id") or snapshot.get("tool_id") or ""),
        invocation_snapshot=snapshot,
        dedupe_key=str(payload.get("dedupe_key") or ""),
        scope_required=normalize_scope(payload.get("scope_required")),
        status=_request_status(row),
        created_at=created_at or datetime.min,
        expires_at=expires_at or datetime.min,
        prompt=payload.get("prompt"),
        confirm_kind=str(payload.get("confirm_kind") or CONFIRM_KIND_FIRST_TIME),
        character_id=str(getattr(row, "character_id", "asuna") or "asuna"),
    )


def _request_status(row: Any) -> str:
    """行状态 pending 即未决；终态从 `last_error` 结果标记还原（精确状态不落专用列）。"""
    if str(getattr(row, "status", "")) == ROW_STATUS_PENDING:
        return STATUS_PENDING
    marker = str(getattr(row, "last_error", "") or "")
    prefix, _, tail = marker.partition(":")
    if prefix == CONFIRMATION_OUTCOME_MARKER and tail in CONFIRMATION_STATUSES:
        return tail
    return STATUS_EXPIRED


def _row_due_at(row: Any) -> datetime | None:
    return getattr(row, "due_at", None)


def _row_created_at(row: Any) -> datetime | None:
    return getattr(row, "created_at", None)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            logger.warning("确认流时间戳解析失败：%s", value)
            return None
    return None


def _ctx_now(ctx: Any) -> datetime:
    return getattr(ctx, "now", None) or datetime.now()


def _fallback_dedupe_key(inv: ToolInvocation) -> str:
    material = inv.tool_id + "|" + "|".join(
        f"{key}={inv.params[key]}" for key in sorted(inv.params)
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def get_confirmation_service(settings: Any = None) -> ConfirmationService:
    return ConfirmationService(settings)


def get_confirmation_detector() -> ConfirmationIntentDetector:
    return ConfirmationIntentDetector()
