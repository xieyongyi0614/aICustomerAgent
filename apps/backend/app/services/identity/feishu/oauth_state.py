"""飞书授权 state 契约与 Redis 实现：短 TTL 一次性状态（防 CSRF / 防重放）。

键面：``feishu_oauth_state:<state>`` 载荷 JSON，TTL = state 有效期；``take`` 走
GETDEL 保证**结果只被领取一次**，不会二次签发令牌或重复绑定。

载荷两段式：
  1. 签发时只写 ``mode`` 与发起用户（``user_id``，仅 bind 场景）；
  2. 飞书回调落回后端时写入 ``outcome``（授权换到的身份，或用户拒绝/交换失败的标记）。

App 侧不接收 ``code``：授权码只在校验过的后端回调里消费一次，客户端凭 state 轮询
领取结果（`peek` 不消费，`take` 原子消费）。

载荷无飞书专有字段（``mode`` 的 login/bind 属本流程语义），当前只服务飞书登录；
出现第二个 OAuth 提供方时再上提到 `services/identity/` 或 `core/`，不预先抽象。
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from app.core import redis_client

logger = logging.getLogger(__name__)

_STATE_PREFIX = "feishu_oauth_state:"

LOGIN_MODE = "login"
BIND_MODE = "bind"
_MODES = (LOGIN_MODE, BIND_MODE)

ERROR_DENIED = "access_denied"
ERROR_EXCHANGE_FAILED = "exchange_failed"
ERROR_OTHER = "authorization_error"


@dataclass(frozen=True, slots=True)
class OAuthOutcome:
    open_id: str | None = None
    union_id: str | None = None
    tenant_key: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.open_id)

    def to_payload(self) -> dict:
        payload = {
            "open_id": self.open_id,
            "union_id": self.union_id,
            "tenant_key": self.tenant_key,
            "error": self.error,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @classmethod
    def from_payload(cls, payload: dict) -> OAuthOutcome:
        return cls(
            open_id=_text(payload.get("open_id")),
            union_id=_text(payload.get("union_id")),
            tenant_key=_text(payload.get("tenant_key")),
            error=_text(payload.get("error")),
        )


@dataclass(frozen=True, slots=True)
class OAuthState:
    state: str
    mode: str
    user_id: str | None = None
    outcome: OAuthOutcome | None = None


class OAuthStateStore(Protocol):
    async def issue(self, payload: OAuthState, *, ttl_seconds: int) -> str: ...

    async def peek(self, state: str) -> OAuthState | None: ...

    async def save_outcome(
        self, state: str, outcome: OAuthOutcome, *, ttl_seconds: int
    ) -> bool: ...

    async def take(self, state: str) -> OAuthState | None: ...


def new_state_token() -> str:
    return secrets.token_urlsafe(32)


class RedisOAuthStateStore:
    def __init__(self, client: Redis | None = None):
        self._client = client

    def _redis(self) -> Redis:
        if self._client is not None:
            return self._client
        return redis_client.get_redis()

    async def issue(self, payload: OAuthState, *, ttl_seconds: int) -> str:
        client = self._redis()
        state = payload.state or new_state_token()
        body = json.dumps(
            {"mode": payload.mode, "user_id": payload.user_id},
            ensure_ascii=False,
        )
        await client.set(f"{_STATE_PREFIX}{state}", body, ex=ttl_seconds)
        return state

    async def peek(self, state: str) -> OAuthState | None:
        if not state:
            return None
        return _parse(state, await self._redis().get(f"{_STATE_PREFIX}{state}"))

    async def save_outcome(
        self, state: str, outcome: OAuthOutcome, *, ttl_seconds: int
    ) -> bool:
        if not state:
            return False
        client = self._redis()
        key = f"{_STATE_PREFIX}{state}"
        raw = await client.get(key)
        parsed = _parse(state, raw)
        if parsed is None:
            return False
        body = json.dumps(
            {
                "mode": parsed.mode,
                "user_id": parsed.user_id,
                "outcome": outcome.to_payload(),
            },
            ensure_ascii=False,
        )
        await client.set(key, body, ex=ttl_seconds)
        return True

    async def take(self, state: str) -> OAuthState | None:
        if not state:
            return None
        return _parse(state, await self._redis().getdel(f"{_STATE_PREFIX}{state}"))


def _parse(state: str, raw) -> OAuthState | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("飞书授权 state 载荷非法，按失效处理")
        return None
    if not isinstance(data, dict):
        return None
    mode = data.get("mode")
    if mode not in _MODES:
        logger.warning("飞书授权 state 模式非法，按失效处理")
        return None
    outcome = data.get("outcome")
    return OAuthState(
        state=state,
        mode=mode,
        user_id=_text(data.get("user_id")),
        outcome=(
            OAuthOutcome.from_payload(outcome) if isinstance(outcome, dict) else None
        ),
    )


def _text(value) -> str | None:
    return value if isinstance(value, str) and value else None


_store: OAuthStateStore | None = None


def get_state_store() -> OAuthStateStore:
    global _store
    if _store is None:
        _store = RedisOAuthStateStore()
    return _store


def set_state_store(store: OAuthStateStore | None) -> None:
    global _store
    _store = store
