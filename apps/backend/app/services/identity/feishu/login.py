"""飞书授权登录 / 账号绑定编排与冲突裁决。

链路：`start_*` 签发一次性 state → 用户在浏览器完成飞书授权 → 飞书回调后端
`record_authorization`（消费授权码并回写结果）→ App 凭 state `claim_*` 领取
结果（GETDEL 只可领取一次）。授权码始终不经过客户端。

三条路径：
  1. 登录 · 未绑定 → 复用 `channel.resolve`（建 users 行 + 写绑定行）；
  2. 登录 · 已绑定 → `resolve` 命中即复用既有 `user_id`，**绝不重复建号**；
  3. 补绑 → 已登录用户把 open_id 改绑到本人（改绑一行，不迁移数据）。

裁决记录：
  - **一人一飞书**：本人已有其它飞书绑定行时拒绝（否则出站收件人解析
    `resolve_recipient` 取「created_at 最早一行」的确定性会退化为隐性歧义）。
  - **壳账号可接管**：目标 open_id 已绑到另一用户时，仅当对方是「无邮箱、
    仅此一条通道绑定」的纯飞书身份才允许改绑——此时用户已用 OAuth 证明对该
    open_id 的控制权。接管**不做数据归并**，旧壳用户行与其数据保留原样。
  - **冲突拒绝**：其余情况一律拒绝并返回明确文案，不做自动合并。
  - **解绑**：删除绑定行，飞书侧回到「首次私聊自动建独立用户」的既有行为；
    users 行保留（可能持有历史数据），不删除。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.settings import get_settings
from app.repositories import channel_identity_repository, user_repository
from app.services.identity import channel as channel_identity_service
from app.services.identity import user_service
from app.services.identity.feishu import oauth as feishu_oauth
from app.services.identity.feishu import oauth_state

logger = logging.getLogger(__name__)

CHANNEL = "feishu"

CALLBACK_OK = "ok"
CALLBACK_DENIED = "denied"
CALLBACK_FAILED = "failed"
CALLBACK_STALE = "stale"


@dataclass(frozen=True, slots=True)
class BindingView:
    bound: bool
    bound_at: str | None = None


@dataclass(frozen=True, slots=True)
class BindingsView:
    email: BindingView
    feishu: BindingView


@dataclass(frozen=True, slots=True)
class AuthorizeTicket:
    authorize_url: str
    state: str
    expires_in: int


class FeishuStateInvalid(RuntimeError):
    """state 缺失 / 已领取 / 已过期 / 模式不符。"""


class FeishuStateMismatch(RuntimeError):
    """state 由其他用户发起，不得被当前令牌领取。"""


class FeishuAuthorizationPending(RuntimeError):
    """授权结果尚未产生——客户端应继续轮询。"""


class FeishuAuthorizationFailed(RuntimeError):
    """用户在飞书侧拒绝授权，或授权码交换失败。"""


class FeishuBindingConflict(RuntimeError):
    """目标飞书账号已绑定其他账号，或本人已有其它飞书绑定。"""


async def start_login() -> AuthorizeTicket:
    return await _start(mode=oauth_state.LOGIN_MODE, user_id=None)


async def start_bind(user_id: str) -> AuthorizeTicket:
    return await _start(mode=oauth_state.BIND_MODE, user_id=user_id)


async def record_authorization(
    state_token: str, *, code: str = "", error: str = ""
) -> str:
    """飞书回调落地：把授权结果回写到 state，供 App 领取。

    返回展示状态（`CALLBACK_*`），**不抛异常**——回调页只负责给用户一句话。
    授权码在本函数内消费一次，客户端永远看不到它。
    """
    store = oauth_state.get_state_store()
    ttl = get_settings().feishu_oauth_state_ttl_seconds
    if not state_token:
        return CALLBACK_STALE
    if error:
        stored = await store.save_outcome(
            state_token,
            oauth_state.OAuthOutcome(error=_error_marker(error)),
            ttl_seconds=ttl,
        )
        return CALLBACK_DENIED if stored else CALLBACK_STALE
    if not code:
        return CALLBACK_STALE
    try:
        identity = await feishu_oauth.get_oauth_client().exchange_code(code)
    except feishu_oauth.FeishuOAuthError as exc:
        logger.warning("飞书授权码换身份失败：%s", exc)
        stored = await store.save_outcome(
            state_token,
            oauth_state.OAuthOutcome(error=oauth_state.ERROR_EXCHANGE_FAILED),
            ttl_seconds=ttl,
        )
        return CALLBACK_FAILED if stored else CALLBACK_STALE
    stored = await store.save_outcome(
        state_token,
        oauth_state.OAuthOutcome(
            open_id=identity.open_id,
            union_id=identity.union_id,
            tenant_key=identity.tenant_key,
        ),
        ttl_seconds=ttl,
    )
    return CALLBACK_OK if stored else CALLBACK_STALE


async def claim_login(state_token: str) -> channel_identity_service.ResolvedIdentity:
    identity = await _claim_identity(
        state_token, expected_mode=oauth_state.LOGIN_MODE
    )
    return await asyncio.to_thread(
        channel_identity_service.resolve,
        CHANNEL,
        identity.open_id,
        union_id=identity.union_id,
        tenant_key=identity.tenant_key,
    )


async def claim_bind(user_id: str, state_token: str) -> None:
    identity = await _claim_identity(
        state_token, expected_mode=oauth_state.BIND_MODE, initiated_by=user_id
    )
    await asyncio.to_thread(bind_identity, user_id, identity)


def bind_identity(user_id: str, identity: feishu_oauth.FeishuUserIdentity) -> None:
    target = channel_identity_repository.find(CHANNEL, identity.open_id)
    if target is not None and target.internal_user_id == user_id:
        return
    owned = _active_bindings(user_id)
    if owned:
        raise FeishuBindingConflict("已绑定其它飞书账号，请先解绑后再绑定新的飞书账号")
    if target is not None:
        if not _is_shell_identity(target.internal_user_id):
            raise FeishuBindingConflict("该飞书账号已绑定其他账号，如需合并请联系管理员")
        channel_identity_repository.update_identity(
            CHANNEL,
            identity.open_id,
            internal_user_id=user_id,
            union_id=identity.union_id,
            tenant_key=identity.tenant_key,
        )
        return
    channel_identity_repository.get_or_create(
        CHANNEL,
        identity.open_id,
        user_id,
        channel_identity_service.build_session_id(CHANNEL, identity.open_id),
        union_id=identity.union_id,
        tenant_key=identity.tenant_key,
    )


def unbind(user_id: str) -> bool:
    rows = _active_bindings(user_id)
    if not rows:
        return False
    for row in rows:
        channel_identity_repository.remove(CHANNEL, row.external_id)
    return True


def list_bindings(user_id: str) -> BindingsView:
    rows = channel_identity_repository.list_by_internal_user(user_id)
    email_row = _first(rows, user_service.EMAIL_CHANNEL)
    feishu_row = _first(rows, CHANNEL)
    return BindingsView(
        email=BindingView(
            bound=email_row is not None,
            bound_at=_iso(email_row.created_at) if email_row is not None else None,
        ),
        feishu=BindingView(
            bound=feishu_row is not None,
            bound_at=_iso(feishu_row.created_at) if feishu_row is not None else None,
        ),
    )


async def _start(*, mode: str, user_id: str | None) -> AuthorizeTicket:
    ttl = get_settings().feishu_oauth_state_ttl_seconds
    store = oauth_state.get_state_store()
    state = await store.issue(
        oauth_state.OAuthState(state="", mode=mode, user_id=user_id),
        ttl_seconds=ttl,
    )
    url = feishu_oauth.get_oauth_client().authorize_url(state)
    return AuthorizeTicket(authorize_url=url, state=state, expires_in=ttl)


async def _claim_identity(
    state_token: str, *, expected_mode: str, initiated_by: str | None = None
) -> feishu_oauth.FeishuUserIdentity:
    store = oauth_state.get_state_store()
    payload = await store.peek(state_token)
    if payload is None:
        raise FeishuStateInvalid()
    if payload.mode != expected_mode:
        await store.take(state_token)
        raise FeishuStateInvalid()
    if initiated_by is not None and payload.user_id and payload.user_id != initiated_by:
        raise FeishuStateMismatch()
    if payload.outcome is None:
        raise FeishuAuthorizationPending()
    taken = await store.take(state_token)
    if taken is None or taken.mode != expected_mode or taken.outcome is None:
        raise FeishuStateInvalid()
    if not taken.outcome.ok:
        raise FeishuAuthorizationFailed(_failure_text(taken.outcome.error))
    return feishu_oauth.FeishuUserIdentity(
        open_id=taken.outcome.open_id or "",
        union_id=taken.outcome.union_id,
        tenant_key=taken.outcome.tenant_key,
    )


def _error_marker(error: str) -> str:
    if error == oauth_state.ERROR_DENIED:
        return oauth_state.ERROR_DENIED
    return oauth_state.ERROR_OTHER


def _failure_text(marker: str | None) -> str:
    if marker == oauth_state.ERROR_DENIED:
        return "你在飞书侧取消了授权"
    return "飞书授权未完成，请重试"


def _active_bindings(user_id: str):
    return [
        row
        for row in channel_identity_repository.list_by_internal_user(user_id)
        if row.channel == CHANNEL and row.status == "active"
    ]


def _first(rows, channel: str):
    for row in rows:
        if row.channel == channel and row.status == "active":
            return row
    return None


def _is_shell_identity(candidate_user_id: str) -> bool:
    user = user_repository.get(candidate_user_id)
    if user is None or user.email:
        return False
    return not any(
        row.channel == user_service.EMAIL_CHANNEL
        for row in channel_identity_repository.list_by_internal_user(candidate_user_id)
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
