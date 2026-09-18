"""TOOL-005 §6.1/§6.2/§6.3：确认状态机、TTL 复用两态、授权撤销、词表检出与调试端点。"""

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.character.asuna.tool import (
    CONFIRM_APPROVE_LEXICON,
    CONFIRM_DENY_LEXICON,
)
from app.core.db import ChannelIdentityRow
from app.main import app
from app.repositories import channel_identity_repository
from app.services.tool.confirmation import (
    CONFIRMATION_ROW_KIND,
    CONFIRMATION_TRIGGER_TYPE,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_NOT_FOUND,
    STATUS_PENDING,
    ConfirmationIntentDetector,
    ConfirmationService,
    confirmation_key,
    get_confirmation_detector,
    get_confirmation_service,
    reset_session_grants,
)
import app.repositories.trigger_registry_repository as trigger_repository
from app.services.tool.context import ToolContext
from app.services.tool.permission import (
    DECISION_ALLOW,
    DECISION_CONFIRM_REQUIRED,
    REASON_GRANT_MATCHED,
    PermissionDecision,
    ToolPermissionGate,
)
from tests.v24.tool005_support import (
    CHANNEL_TOOL_ID,
    CHANNEL_TOOL_SCOPE,
    SENSITIVE_TOOL_ID,
    invocation,
    permission_settings,
    sensitive_definition,
)
from app.repositories import trigger_registry_repository

BASE = "/api/v1"
USER_ID = "u-tool005"
CHANNEL = "feishu"
EXTERNAL_ID = "ext-005"


@pytest.fixture(autouse=True)
def _clean_session_grants():
    reset_session_grants()
    yield
    reset_session_grants()


def _settings(**overrides):
    return permission_settings(**overrides)


def _decision(
    *,
    kind: str = "first_time",
    scope: tuple[str, ...] = ("self",),
    prompt: str = "要我现在把这条消息发出去吗？",
) -> PermissionDecision:
    return PermissionDecision(
        decision=DECISION_CONFIRM_REQUIRED,
        level="sensitive",
        reason="first_time_confirmation",
        confirm_prompt=prompt,
        scope_required=scope,
        confirm_kind=kind,
    )


def _ctx(now: datetime, settings=None) -> ToolContext:
    return ToolContext(
        user_id=USER_ID, now=now, settings=settings if settings is not None else _settings()
    )


def _register(
    service: ConfirmationService,
    now: datetime,
    *,
    content: str = "明天开会",
    tool_id: str = SENSITIVE_TOOL_ID,
    decision: PermissionDecision | None = None,
    settings=None,
):
    inv = invocation(tool_id, {"content": content})
    return service.request(
        inv, decision or _decision(), _ctx(now, settings)
    )


def _bind_channel(user_id: str = USER_ID) -> None:
    channel_identity_repository.get_or_create(
        CHANNEL, EXTERNAL_ID, user_id, f"{CHANNEL}:{EXTERNAL_ID}"
    )


def _unbind_channel(user_id: str = USER_ID, db_session_factory=None) -> None:
    session = db_session_factory() if db_session_factory is not None else None
    if session is None:
        raise AssertionError("需要 db_session_factory 才能模拟解绑")
    session.query(ChannelIdentityRow).filter(
        ChannelIdentityRow.internal_user_id == user_id
    ).update({"status": "inactive"})
    session.commit()


# --- request 登记 -------------------------------------------------------------


def test_request_registers_pending_row(db_session_factory):
    now = datetime.now()
    service = ConfirmationService(_settings())
    request = _register(service, now)
    assert request is not None
    assert request.status == STATUS_PENDING
    assert request.tool_id == SENSITIVE_TOOL_ID
    assert request.dedupe_key
    assert request.confirm_kind == "first_time"
    assert request.prompt == "要我现在把这条消息发出去吗？"
    assert request.expires_at - request.created_at == timedelta(hours=24)

    row = trigger_registry_repository.get(request.request_id)
    assert row is not None
    assert row.trigger_type == CONFIRMATION_TRIGGER_TYPE
    assert row.status == "pending"
    assert row.due_at == request.expires_at
    payload = dict(row.payload)
    assert payload["kind"] == CONFIRMATION_ROW_KIND
    assert payload["dedupe_key"] == request.dedupe_key
    assert payload["scope_required"] == ["self"]
    assert payload["invocation_snapshot"]["params"] == {"content": "明天开会"}
    assert payload["invocation_snapshot"]["intent"]["action_type"] == "send_notification"


def test_request_returns_none_when_registration_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("trigger registry down")

    monkeypatch.setattr(trigger_repository, "register", _boom)
    service = ConfirmationService(_settings())
    assert _register(service, datetime.now()) is None


def test_request_is_idempotent_per_dedupe_key():
    now = datetime.now()
    service = ConfirmationService(_settings())
    first = _register(service, now)
    second = _register(service, now)
    assert first.request_id == second.request_id
    assert len(service.pending(USER_ID, now)) == 1


# --- 状态机：approve / deny / expired / 非法迁移 -------------------------------


def test_resolve_approve_grants_scope_and_rejects_illegal_migration():
    now = datetime.now()
    service = ConfirmationService(_settings())
    request = _register(service, now)

    outcome = service.resolve(request.request_id, approved=True)
    assert outcome.status == STATUS_APPROVED
    assert outcome.migrated is True
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now) is True

    replay = service.resolve(request.request_id, approved=True)
    assert replay.status == STATUS_APPROVED
    assert replay.migrated is False
    assert replay.reason == "already_resolved"

    conflict = service.resolve(request.request_id, approved=False)
    assert conflict.status == STATUS_APPROVED
    assert conflict.migrated is False


def test_resolve_deny_marks_terminal_and_allows_new_request_e6():
    now = datetime.now()
    service = ConfirmationService(_settings())
    request = _register(service, now)

    outcome = service.resolve(request.request_id, approved=False)
    assert outcome.status == STATUS_DENIED
    assert outcome.migrated is True
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now) is False
    assert service.pending(USER_ID, now) == []

    again = _register(service, now)
    assert again.request_id == request.request_id
    assert again.status == STATUS_PENDING
    assert len(service.pending(USER_ID, now)) == 1


def test_resolve_after_ttl_returns_expired_e5():
    service = ConfirmationService(_settings())
    stale = datetime.now() - timedelta(hours=48)
    request = _register(service, stale)

    outcome = service.resolve(request.request_id, approved=True)
    assert outcome.status == STATUS_EXPIRED
    assert outcome.migrated is True
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",)) is False


def test_resolve_unknown_request_returns_not_found():
    service = ConfirmationService(_settings())
    outcome = service.resolve("tool_confirm:nobody:missing", approved=True)
    assert outcome.status == STATUS_NOT_FOUND
    assert outcome.request is None


def test_pending_orders_newest_first_e7_e13():
    service = ConfirmationService(_settings())
    base = datetime.now()
    older = _register(service, base - timedelta(hours=2), content="旧消息")
    newer = _register(service, base, content="新消息")
    pending = service.pending(USER_ID, base)
    assert [item.request_id for item in pending] == [
        newer.request_id,
        older.request_id,
    ]

    detected = ConfirmationIntentDetector().detect("好", pending)
    assert detected == (newer.request_id, "approve")


def test_expire_due_cleans_only_expired_requests():
    service = ConfirmationService(_settings())
    now = datetime.now()
    expired_request = _register(service, now - timedelta(hours=48))
    live_request = _register(service, now, content="现在的消息")

    assert service.expire_due(now) == 1
    assert service.expire_due(now) == 0
    assert service.get(expired_request.request_id).status == STATUS_EXPIRED
    assert service.get(live_request.request_id).status == STATUS_PENDING
    assert [item.request_id for item in service.pending(USER_ID, now)] == [
        live_request.request_id
    ]


def test_expire_due_cleans_expired_grant_rows():
    """到期授权行落终态：避免被 `has_due` 长期误计为到期待办触发。"""
    now = datetime.now()
    settings = _settings()
    service = ConfirmationService(settings)
    grant_id = service.grant_scope(USER_ID, SENSITIVE_TOOL_ID, ("self",))
    assert grant_id is not None
    row = trigger_registry_repository.get(grant_id)
    assert row.status == "pending"

    assert service.expire_due(now - timedelta(seconds=1)) == 0
    assert trigger_registry_repository.get(grant_id).status == "pending"

    assert service.expire_due(now + timedelta(hours=25)) == 1
    assert trigger_registry_repository.get(grant_id).status == "cancelled"
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now) is False


# --- P2-1：确认 / 授权行不污染 has_due 的待办口径 ------------------------------


def test_has_due_excludes_confirmation_and_grant_rows():
    """确认行与授权行不再被计入"到期待办触发"（污染窗口 = TTL 到期到 `expire_due` 之间）。"""
    from app.services.tool.confirmation import non_todo_payload_kinds

    now = datetime.now()
    settings = _settings()
    service = ConfirmationService(settings)

    request = _register(service, now - timedelta(hours=48))
    grant_id = service.grant_scope(
        USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now - timedelta(hours=48)
    )
    assert request is not None and grant_id is not None
    assert trigger_registry_repository.get(grant_id).due_at <= now

    kinds = non_todo_payload_kinds()
    assert kinds == (CONFIRMATION_ROW_KIND, "tool_grant")

    assert (
        trigger_registry_repository.has_due(
            user_id=USER_ID, now=now, include_types=(CONFIRMATION_TRIGGER_TYPE,)
        )
        is True
    )
    assert (
        trigger_registry_repository.has_due(
            user_id=USER_ID,
            now=now,
            include_types=(CONFIRMATION_TRIGGER_TYPE,),
            exclude_payload_kinds=kinds,
        )
        is False
    )


def test_has_due_keeps_real_action_due_rows_with_exclusion():
    """排除生效时，真正的 `action_due` 待办行（payload 无 `kind` 键）仍被计入。"""
    from app.services.tool.confirmation import non_todo_payload_kinds

    now = datetime.now()
    settings = _settings()
    service = ConfirmationService(settings)
    request = _register(service, now - timedelta(hours=48))
    assert request is not None
    trigger_registry_repository.register(
        USER_ID,
        "action_due",
        "v9-real-action-due",
        due_at=now - timedelta(seconds=1),
        payload={"plan_id": "p-1"},
        now=now,
    )

    assert (
        trigger_registry_repository.has_due(
            user_id=USER_ID,
            now=now,
            include_types=(CONFIRMATION_TRIGGER_TYPE,),
            exclude_payload_kinds=non_todo_payload_kinds(),
        )
        is True
    )


def test_has_due_default_arguments_keep_v9_shape():
    """不传 `exclude_payload_kinds`：到期的确认行照旧被计入（默认口径与 V9 逐字节一致）。"""
    now = datetime.now()
    request = _register(ConfirmationService(_settings()), now - timedelta(hours=48))
    assert request is not None
    for kwargs in ({}, {"exclude_payload_kinds": None}, {"exclude_payload_kinds": ()}):
        assert (
            trigger_registry_repository.has_due(
                user_id=USER_ID,
                now=now,
                include_types=(CONFIRMATION_TRIGGER_TYPE,),
                **kwargs,
            )
            is True
        ), kwargs


# --- TTL 复用两态 -------------------------------------------------------------


def test_ttl_reuse_true_keeps_grant_within_window():
    now = datetime.now()
    settings = _settings(tool_confirm_ttl_reuse=True)
    service = ConfirmationService(settings)
    request = _register(service, now, settings=settings)
    service.resolve(request.request_id, approved=True)

    records = service.grant_records(USER_ID, now)
    persisted = [item for item in records if item["source"] == "user_confirm"]
    assert len(persisted) == 1
    assert (
        abs((persisted[0]["expires_at"] - request.expires_at).total_seconds()) < 60
    )

    gate = ToolPermissionGate(settings)
    snapshot = gate.build_snapshot(USER_ID, now, settings)
    decision = gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), snapshot)
    assert decision.decision == DECISION_ALLOW
    assert decision.reason == REASON_GRANT_MATCHED


def test_ttl_reuse_false_grants_only_current_round():
    now = datetime.now()
    settings = _settings(tool_confirm_ttl_reuse=False)
    service = ConfirmationService(settings)
    request = _register(service, now, settings=settings)
    service.resolve(request.request_id, approved=True)

    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now) is True
    assert [
        item for item in service.grant_records(USER_ID, now) if item["source"] == "user_confirm"
    ] == []

    assert service.release_session_grant(USER_ID, SENSITIVE_TOOL_ID) is True
    gate = ToolPermissionGate(settings)
    snapshot = gate.build_snapshot(USER_ID, now, settings)
    decision = gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), snapshot)
    assert decision.decision == DECISION_CONFIRM_REQUIRED


# --- 授权撤销与通道级授权 ------------------------------------------------------


def test_revoke_takes_effect_on_next_decision():
    now = datetime.now()
    settings = _settings()
    service = ConfirmationService(settings)
    service.grant_scope(USER_ID, SENSITIVE_TOOL_ID, ("self",))
    gate = ToolPermissionGate(settings)
    before = gate.build_snapshot(USER_ID, now, settings)
    assert gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), before).decision == (
        DECISION_ALLOW
    )

    assert service.revoke(USER_ID, SENSITIVE_TOOL_ID) == 1
    after = gate.build_snapshot(USER_ID, now, settings)
    decision = gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), after)
    assert decision.decision == DECISION_CONFIRM_REQUIRED
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",), now=now) is False


def test_revoke_removes_session_grant_only():
    service = ConfirmationService(_settings(tool_confirm_ttl_reuse=False))
    service.grant_scope(USER_ID, SENSITIVE_TOOL_ID, ("self",))
    assert service.revoke(USER_ID, SENSITIVE_TOOL_ID) == 1
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",)) is False


def test_channel_binding_implies_base_scope_then_unbind_loses_it(db_session_factory):
    now = datetime.now()
    service = ConfirmationService(_settings())
    assert service.channel_bound(USER_ID) is False
    assert service.grant_records(USER_ID, now) == []

    _bind_channel()
    assert service.channel_bound(USER_ID) is True
    scopes = [item["scope"] for item in service.grant_records(USER_ID, now)]
    assert [f"channel:{CHANNEL}.base"] in scopes

    _unbind_channel(db_session_factory=db_session_factory)
    assert service.channel_bound(USER_ID) is False
    assert service.grant_records(USER_ID, now) == []


def test_grant_scope_failure_returns_none(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("trigger registry down")

    monkeypatch.setattr(trigger_repository, "register", _boom)
    service = ConfirmationService(_settings())
    assert service.grant_scope(USER_ID, SENSITIVE_TOOL_ID, ("self",)) is None
    assert service.has_grant(USER_ID, SENSITIVE_TOOL_ID, ("self",)) is False


def test_revoke_request_marks_pending_request_denied():
    now = datetime.now()
    service = ConfirmationService(_settings())
    request = _register(service, now)
    assert service.revoke_request(request.request_id) is True
    assert service.get(request.request_id).status == STATUS_DENIED
    assert service.revoke_request(request.request_id) is False


def test_confirmation_key_is_scoped_by_dedupe_key():
    assert confirmation_key("u", "t", "abc") != confirmation_key("u", "t", "def")
    assert confirmation_key("u", "t", "abc").endswith("abc")


# --- 确认意图检出（词表 / 问句守卫 / 宁缺毋滥） ---------------------------------


def _pending_list(count: int = 1):
    service = ConfirmationService(_settings())
    now = datetime.now()
    return [
        _register(service, now + timedelta(minutes=index), content=f"消息{index}")
        for index in range(count)
    ]


@pytest.mark.parametrize("word", CONFIRM_APPROVE_LEXICON[:5])
def test_approve_lexicon_hits(word):
    pending = _pending_list()
    detected = get_confirmation_detector().detect(word, pending)
    assert detected == (pending[0].request_id, "approve")


@pytest.mark.parametrize("word", CONFIRM_DENY_LEXICON[:5])
def test_deny_lexicon_hits(word):
    pending = _pending_list()
    detected = get_confirmation_detector().detect(word, pending)
    assert detected == (pending[0].request_id, "deny")


@pytest.mark.parametrize(
    "content", ["能发吗？", "你可以帮我发吗", "这样可以么", "你能发嘛"]
)
def test_question_guard_blocks_approval(content):
    pending = _pending_list()
    assert get_confirmation_detector().detect(content, pending) is None


@pytest.mark.parametrize(
    "content", ["今天天气不错", "帮我记一下明天的会议", "嗯，明天几点的会？"]
)
def test_unrelated_content_detects_nothing_e8(content):
    pending = _pending_list()
    assert get_confirmation_detector().detect(content, pending) is None
    assert len(pending) == 1


def test_deny_word_wins_over_approve_word():
    pending = _pending_list()
    detected = get_confirmation_detector().detect("好是好，不过不用了", pending)
    assert detected == (pending[0].request_id, "deny")


def test_no_pending_detects_nothing():
    assert get_confirmation_detector().detect("好", []) is None


def test_detector_failure_returns_none():
    assert get_confirmation_detector().detect("好", [object()]) is None


def test_detector_returns_none_for_blank_content():
    pending = _pending_list()
    assert get_confirmation_detector().detect("   ", pending) is None


# --- 调试端点 -----------------------------------------------------------------


def _url(path: str) -> str:
    return f"{BASE}{path}"


async def _get(path: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(_url(path), params=params)


async def _post(path: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(_url(path), params=params)


@pytest.fixture
def permission_on(v24_tool_env):
    """权限面已常开；夹具只负责 settings 缓存与注册表单例隔离。"""
    v24_tool_env()


@pytest.mark.asyncio
async def test_debug_permissions_lists_and_revokes_grants(permission_on):
    service = get_confirmation_service()
    service.grant_scope(USER_ID, SENSITIVE_TOOL_ID, ("self",))

    listed = await _get("/debug/tools/permissions", user_id=USER_ID)
    assert listed.status_code == 200
    body = listed.json()
    assert body["enabled"] is True
    assert [item["tool_id"] for item in body["grants"]] == [SENSITIVE_TOOL_ID]

    revoked = await _post("/debug/tools/permissions/revoke", user_id=USER_ID, tool_id=SENSITIVE_TOOL_ID)
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] == 1
    assert (await _get("/debug/tools/permissions", user_id=USER_ID)).json()["grants"] == []


@pytest.mark.asyncio
async def test_debug_permission_revoke_unknown_returns_404(permission_on):
    response = await _post("/debug/tools/permissions/revoke", user_id="nobody", tool_id="nothing")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_debug_confirmations_list_and_revoke(permission_on):
    service = get_confirmation_service()
    request = _register(service, datetime.now())

    listed = await _get("/debug/tools/confirmations", user_id=USER_ID)
    assert listed.status_code == 200
    body = listed.json()
    assert [item["request_id"] for item in body["confirmations"]] == [request.request_id]
    assert body["confirmations"][0]["status"] == STATUS_PENDING
    assert body["confirmations"][0]["prompt"]

    revoked = await _post(f"/debug/tools/confirmations/{request.request_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json() == {
        "enabled": True,
        "request_id": request.request_id,
        "revoked": True,
        "status": "denied",
    }
    assert (
        await _get("/debug/tools/confirmations", user_id=USER_ID)
    ).json()["confirmations"] == []


@pytest.mark.asyncio
async def test_debug_confirmation_revoke_unknown_returns_404(permission_on):
    response = await _post("/debug/tools/confirmations/tool_confirm:nobody:missing/revoke")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_debug_confirmations_deny_decision_not_reached(permission_on):
    """否定路径：请求转 denied，不落授权（工具不执行由集成用例断言零外部调用）。"""
    service = get_confirmation_service()
    request = _register(service, datetime.now())
    outcome = service.resolve(request.request_id, approved=False)
    assert outcome.status == STATUS_DENIED
    assert service.has_grant(USER_ID, CHANNEL_TOOL_ID, CHANNEL_TOOL_SCOPE) is False
    listed = await _get("/debug/tools/confirmations", user_id=USER_ID)
    assert listed.json()["confirmations"] == []
