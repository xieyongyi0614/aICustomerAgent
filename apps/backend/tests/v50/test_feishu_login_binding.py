"""飞书授权登录与账号绑定：三条路径 / 冲突裁决 / 解绑 / 回调与领取端点。"""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from app.api.v1 import auth as auth_api
from app.repositories import channel_identity_repository as repo
from app.repositories import user_repository
from app.services.identity import channel as channel_identity_service
from app.services.identity import user_service
from app.services.identity.feishu import login as feishu_login
from app.services.identity.feishu import oauth as feishu_oauth
from app.services.identity.feishu import oauth_state
from app.services.identity.feishu.oauth import (
    FeishuOAuthError,
    FeishuUserIdentity,
)

pytestmark = pytest.mark.unit

TARGET_OPEN_ID = "ou_target"


def identity(open_id: str = TARGET_OPEN_ID) -> FeishuUserIdentity:
    return FeishuUserIdentity(open_id=open_id, union_id="on_1", tenant_key="tk_1")


class FakeOAuthClient:
    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.codes: list[str] = []

    def authorize_url(self, state: str) -> str:
        return f"https://accounts.feishu.cn/open-apis/authen/v1/authorize?state={state}"

    async def exchange_code(self, code: str) -> FeishuUserIdentity:
        self.codes.append(code)
        if self.failure is not None:
            raise self.failure
        return identity()


@pytest.fixture
async def state_store():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = oauth_state.RedisOAuthStateStore(client)
    original = oauth_state.get_state_store()
    oauth_state.set_state_store(store)
    yield store
    oauth_state.set_state_store(original)
    await client.aclose()


@pytest.fixture
def oauth_client():
    client = FakeOAuthClient()
    original = feishu_oauth.get_oauth_client()
    feishu_oauth.set_oauth_client(client)
    yield client
    feishu_oauth.set_oauth_client(original)


def test_login_creates_user_and_binding_for_new_identity():
    resolved = channel_identity_service.resolve(
        "feishu", TARGET_OPEN_ID, union_id="on_1", tenant_key="tk_1"
    )

    binding = repo.find("feishu", TARGET_OPEN_ID)
    assert resolved.created is True
    assert binding is not None
    assert binding.internal_user_id == resolved.internal_user_id
    assert binding.session_id == f"feishu:{TARGET_OPEN_ID}"
    assert binding.external_union_id == "on_1"
    assert binding.external_tenant_key == "tk_1"
    assert user_repository.get(resolved.internal_user_id) is not None


def test_login_reuses_existing_user_without_duplicate():
    first = channel_identity_service.resolve("feishu", TARGET_OPEN_ID)
    users_before = len(user_repository.list_all())

    second = channel_identity_service.resolve("feishu", TARGET_OPEN_ID)

    assert second.created is False
    assert second.internal_user_id == first.internal_user_id
    assert len(user_repository.list_all()) == users_before


def test_bind_writes_binding_for_logged_in_user():
    owner = user_service.find_or_create_by_email("owner@example.com")

    feishu_login.bind_identity(owner.user_id, identity())

    binding = repo.find("feishu", TARGET_OPEN_ID)
    assert binding is not None
    assert binding.internal_user_id == owner.user_id
    assert binding.session_id == f"feishu:{TARGET_OPEN_ID}"


def test_bind_is_idempotent():
    owner = user_service.create_user()
    feishu_login.bind_identity(owner.user_id, identity())

    feishu_login.bind_identity(owner.user_id, identity())

    assert len(repo.list_by_internal_user(owner.user_id)) == 1


def test_bind_rejects_second_feishu_account_for_same_user():
    owner = user_service.create_user()
    feishu_login.bind_identity(owner.user_id, identity("ou_first"))

    with pytest.raises(feishu_login.FeishuBindingConflict):
        feishu_login.bind_identity(owner.user_id, identity("ou_second"))

    assert repo.find("feishu", "ou_second") is None


def test_bind_takes_over_shell_identity_and_keeps_shell_user():
    shell = channel_identity_service.resolve("feishu", TARGET_OPEN_ID)
    owner = user_service.find_or_create_by_email("owner@example.com")

    feishu_login.bind_identity(owner.user_id, identity())

    binding = repo.find("feishu", TARGET_OPEN_ID)
    assert binding.internal_user_id == owner.user_id
    assert binding.session_id == f"feishu:{TARGET_OPEN_ID}"
    assert user_repository.get(shell.internal_user_id) is not None
    assert repo.list_by_internal_user(owner.user_id)[0].channel == "feishu"


def test_bind_rejects_takeover_of_account_with_email():
    friend = user_service.find_or_create_by_email("friend@example.com")
    feishu_login.bind_identity(friend.user_id, identity())
    actor = user_service.find_or_create_by_email("actor@example.com")

    with pytest.raises(feishu_login.FeishuBindingConflict):
        feishu_login.bind_identity(actor.user_id, identity())

    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == friend.user_id


def test_unbind_removes_binding_and_feishu_regains_independent_identity():
    owner = user_service.find_or_create_by_email("owner@example.com")
    feishu_login.bind_identity(owner.user_id, identity())

    assert feishu_login.unbind(owner.user_id) is True
    assert repo.find("feishu", TARGET_OPEN_ID) is None

    recreated = channel_identity_service.resolve("feishu", TARGET_OPEN_ID)
    assert recreated.internal_user_id != owner.user_id


def test_unbind_without_binding_is_noop():
    owner = user_service.create_user()

    assert feishu_login.unbind(owner.user_id) is False


def test_list_bindings_reports_email_and_feishu():
    owner = user_service.find_or_create_by_email("owner@example.com")
    feishu_login.bind_identity(owner.user_id, identity())

    view = feishu_login.list_bindings(owner.user_id)

    assert view.email.bound is True
    assert view.email.bound_at
    assert view.feishu.bound is True
    assert view.feishu.bound_at


def test_list_bindings_is_empty_for_fresh_user():
    owner = user_service.create_user()

    view = feishu_login.list_bindings(owner.user_id)

    assert (view.email.bound, view.feishu.bound) == (False, False)
    assert view.feishu.bound_at is None


async def test_start_login_issues_state_without_outcome(state_store, oauth_client):
    ticket = await feishu_login.start_login()

    assert ticket.state in ticket.authorize_url
    assert ticket.expires_in > 0
    payload = await state_store.peek(ticket.state)
    assert payload.mode == oauth_state.LOGIN_MODE
    assert payload.outcome is None


async def test_start_bind_binds_state_to_initiator(state_store, oauth_client):
    ticket = await feishu_login.start_bind("u-initiator")

    payload = await state_store.peek(ticket.state)
    assert (payload.mode, payload.user_id) == (oauth_state.BIND_MODE, "u-initiator")


async def test_claim_login_pending_before_callback(state_store, oauth_client):
    ticket = await feishu_login.start_login()

    with pytest.raises(feishu_login.FeishuAuthorizationPending):
        await feishu_login.claim_login(ticket.state)

    assert await state_store.peek(ticket.state) is not None


async def test_callback_records_identity_and_claim_resolves_user(
    state_store, oauth_client
):
    ticket = await feishu_login.start_login()

    status = await feishu_login.record_authorization(ticket.state, code="code-1")
    resolved = await feishu_login.claim_login(ticket.state)

    assert status == feishu_login.CALLBACK_OK
    assert oauth_client.codes == ["code-1"]
    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == resolved.internal_user_id


async def test_claim_login_is_single_use(state_store, oauth_client):
    ticket = await feishu_login.start_login()
    await feishu_login.record_authorization(ticket.state, code="code-1")
    await feishu_login.claim_login(ticket.state)

    with pytest.raises(feishu_login.FeishuStateInvalid):
        await feishu_login.claim_login(ticket.state)


async def test_claim_login_rejects_bind_state(state_store, oauth_client):
    ticket = await feishu_login.start_bind("u-initiator")
    await feishu_login.record_authorization(ticket.state, code="code-1")

    with pytest.raises(feishu_login.FeishuStateInvalid):
        await feishu_login.claim_login(ticket.state)

    assert await state_store.peek(ticket.state) is None


async def test_claim_login_rejects_unknown_state(state_store):
    with pytest.raises(feishu_login.FeishuStateInvalid):
        await feishu_login.claim_login("no-such-state")


async def test_callback_records_denied_without_exchange(state_store, oauth_client):
    ticket = await feishu_login.start_login()

    status = await feishu_login.record_authorization(
        ticket.state, error="access_denied"
    )

    assert status == feishu_login.CALLBACK_DENIED
    assert oauth_client.codes == []
    with pytest.raises(feishu_login.FeishuAuthorizationFailed):
        await feishu_login.claim_login(ticket.state)


async def test_callback_records_unknown_error_marker_verbatim_is_sanitized(
    state_store, oauth_client
):
    ticket = await feishu_login.start_login()

    status = await feishu_login.record_authorization(ticket.state, error="weird<code>")

    assert status == feishu_login.CALLBACK_DENIED
    payload = await state_store.peek(ticket.state)
    assert payload.outcome.error == oauth_state.ERROR_OTHER


async def test_callback_reports_exchange_failure(state_store, oauth_client):
    oauth_client.failure = FeishuOAuthError("down")
    ticket = await feishu_login.start_login()

    status = await feishu_login.record_authorization(ticket.state, code="code-1")

    assert status == feishu_login.CALLBACK_FAILED
    with pytest.raises(feishu_login.FeishuAuthorizationFailed):
        await feishu_login.claim_login(ticket.state)


async def test_callback_without_state_is_stale(state_store, oauth_client):
    assert await feishu_login.record_authorization("", code="c") == (
        feishu_login.CALLBACK_STALE
    )
    assert await feishu_login.record_authorization("ghost", code="c") == (
        feishu_login.CALLBACK_STALE
    )
    assert oauth_client.codes == ["c"]


async def test_claim_bind_rejects_state_from_another_user(state_store, oauth_client):
    ticket = await feishu_login.start_bind("u-initiator")
    await feishu_login.record_authorization(ticket.state, code="code-1")

    with pytest.raises(feishu_login.FeishuStateMismatch):
        await feishu_login.claim_bind("u-other", ticket.state)

    assert repo.find("feishu", TARGET_OPEN_ID) is None


async def test_claim_bind_binds_open_id_to_initiator(state_store, oauth_client):
    owner = user_service.find_or_create_by_email("owner@example.com")
    ticket = await feishu_login.start_bind(owner.user_id)
    await feishu_login.record_authorization(ticket.state, code="code-1")

    await feishu_login.claim_bind(owner.user_id, ticket.state)

    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == owner.user_id


async def test_claim_bind_maps_conflict_when_target_taken(state_store, oauth_client):
    friend = user_service.find_or_create_by_email("friend@example.com")
    feishu_login.bind_identity(friend.user_id, identity())
    actor = user_service.find_or_create_by_email("actor@example.com")
    ticket = await feishu_login.start_bind(actor.user_id)
    await feishu_login.record_authorization(ticket.state, code="code-1")

    with pytest.raises(feishu_login.FeishuBindingConflict):
        await feishu_login.claim_bind(actor.user_id, ticket.state)

    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == friend.user_id


async def test_callback_endpoint_reports_success(state_store, oauth_client):
    ticket = await feishu_login.start_login()

    response = await auth_api.feishu_callback(code="code-1", state=ticket.state)

    assert response.status_code == 200
    assert "授权成功" in response.body.decode("utf-8")


async def test_callback_endpoint_reports_stale_state(state_store):
    response = await auth_api.feishu_callback(code="code-1", state="ghost")

    assert response.status_code == 200
    assert "授权已过期" in response.body.decode("utf-8")


async def test_callback_endpoint_reports_denied(state_store):
    ticket = await feishu_login.start_login()

    response = await auth_api.feishu_callback(
        error="access_denied", state=ticket.state
    )

    assert "授权已取消" in response.body.decode("utf-8")


async def test_login_claim_endpoint_issues_token(monkeypatch, state_store, oauth_client):
    ticket = await feishu_login.start_login()
    await feishu_login.record_authorization(ticket.state, code="code-1")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")

    response = await auth_api.feishu_login_claim(
        auth_api.FeishuLoginClaimRequest(
            state=ticket.state, device_id="d-1", platform="android"
        )
    )

    user_id, device_id, _ = auth_api.parse_token_parts(response.token)
    assert device_id == "d-1"
    assert response.user_id == user_id
    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == user_id


async def test_login_claim_endpoint_maps_pending_to_404(
    monkeypatch, state_store, oauth_client
):
    ticket = await feishu_login.start_login()
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_login_claim(
            auth_api.FeishuLoginClaimRequest(
                state=ticket.state, device_id="d-1", platform="android"
            )
        )

    assert exc.value.status_code == 404
    assert exc.value.headers["Retry-After"] == "2"


async def test_login_claim_endpoint_maps_denied_to_400(
    monkeypatch, state_store, oauth_client
):
    ticket = await feishu_login.start_login()
    await feishu_login.record_authorization(ticket.state, error="access_denied")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_login_claim(
            auth_api.FeishuLoginClaimRequest(
                state=ticket.state, device_id="d-1", platform="android"
            )
        )

    assert exc.value.status_code == 400
    assert "取消" in exc.value.detail


async def test_login_claim_endpoint_maps_stale_state_to_400(
    monkeypatch, state_store
):
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_login_claim(
            auth_api.FeishuLoginClaimRequest(
                state="ghost", device_id="d-1", platform="android"
            )
        )
    assert exc.value.status_code == 400


async def test_bind_claim_endpoint_returns_bindings(
    monkeypatch, state_store, oauth_client
):
    owner = user_service.find_or_create_by_email("owner@example.com")
    ticket = await feishu_login.start_bind(owner.user_id)
    await feishu_login.record_authorization(ticket.state, code="code-1")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    response = await auth_api.feishu_bind_claim(
        auth_api.FeishuBindClaimRequest(state=ticket.state), user_id=owner.user_id
    )

    assert response.feishu.bound is True
    assert response.email.bound is True


async def test_bind_claim_endpoint_maps_conflict_to_409(
    monkeypatch, state_store, oauth_client
):
    friend = user_service.find_or_create_by_email("friend@example.com")
    feishu_login.bind_identity(friend.user_id, identity())
    actor = user_service.find_or_create_by_email("actor@example.com")
    ticket = await feishu_login.start_bind(actor.user_id)
    await feishu_login.record_authorization(ticket.state, code="code-1")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_bind_claim(
            auth_api.FeishuBindClaimRequest(state=ticket.state), user_id=actor.user_id
        )

    assert exc.value.status_code == 409
    assert repo.find("feishu", TARGET_OPEN_ID).internal_user_id == friend.user_id


async def test_bind_claim_endpoint_maps_state_mismatch_to_403(
    monkeypatch, state_store, oauth_client
):
    ticket = await feishu_login.start_bind("u-initiator")
    await feishu_login.record_authorization(ticket.state, code="code-1")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_bind_claim(
            auth_api.FeishuBindClaimRequest(state=ticket.state), user_id="u-other"
        )

    assert exc.value.status_code == 403


async def test_bind_claim_endpoint_maps_pending_to_404(
    monkeypatch, state_store, oauth_client
):
    ticket = await feishu_login.start_bind("u-initiator")
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await auth_api.feishu_bind_claim(
            auth_api.FeishuBindClaimRequest(state=ticket.state), user_id="u-initiator"
        )

    assert exc.value.status_code == 404


async def test_feishu_unbind_endpoint_returns_bindings(state_store, oauth_client):
    owner = user_service.find_or_create_by_email("owner@example.com")
    feishu_login.bind_identity(owner.user_id, identity())

    response = await auth_api.feishu_unbind(user_id=owner.user_id)

    assert response.feishu.bound is False
    assert repo.find("feishu", TARGET_OPEN_ID) is None


async def test_bindings_endpoint_reports_state(state_store):
    owner = user_service.create_user()

    response = await auth_api.bindings(user_id=owner.user_id)

    assert response.feishu.bound is False
    assert response.email.bound is False


async def test_bind_authorize_returns_url_with_state(
    monkeypatch, state_store, oauth_client
):
    owner = user_service.create_user()
    monkeypatch.setattr(auth_api, "_feishu_login_ready", lambda: None)

    response = await auth_api.feishu_bind_authorize(user_id=owner.user_id)

    assert response.state in response.authorize_url
    payload = await state_store.peek(response.state)
    assert payload.user_id == owner.user_id


def test_feishu_login_ready_requires_oauth_config(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "sec")
    monkeypatch.setattr(
        auth_api,
        "redis_client",
        type("R", (), {"is_configured": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: type("S", (), {"oauth_configured": lambda self: False})(),
    )
    with pytest.raises(HTTPException) as exc:
        auth_api._feishu_login_ready()
    assert exc.value.status_code == 503


def test_feishu_login_ready_requires_redis(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "sec")
    monkeypatch.setattr(
        auth_api,
        "redis_client",
        type("R", (), {"is_configured": staticmethod(lambda: False)})(),
    )
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: type("S", (), {"oauth_configured": lambda self: True})(),
    )
    with pytest.raises(HTTPException) as exc:
        auth_api._feishu_login_ready()
    assert exc.value.status_code == 503


def test_feishu_routes_registered():
    paths = {route.path for route in auth_api.auth_router.routes}
    assert "/auth/feishu/authorize" in paths
    assert "/auth/feishu/bind/authorize" in paths
    assert "/auth/feishu/callback" in paths
    assert "/auth/feishu/login/claim" in paths
    assert "/auth/feishu/bind/claim" in paths
    assert "/auth/feishu/bind" in paths
    assert "/auth/bindings" in paths
