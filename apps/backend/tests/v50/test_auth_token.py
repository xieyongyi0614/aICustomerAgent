"""鉴权令牌测试（设备配对链路已退役，令牌由邮箱验证码登录签发）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import auth as auth_api

pytestmark = pytest.mark.unit


def test_issue_and_parse_token(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    token = auth_api.issue_token("u1", "d1")
    assert auth_api.parse_token(token) == "u1"


def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    with pytest.raises(HTTPException):
        auth_api.parse_token("u1.d1.999.deadbeef")


def test_require_user_rejects_missing_header():
    with pytest.raises(HTTPException) as exc:
        auth_api.require_user("")
    assert exc.value.status_code == 401


def test_require_user_reads_token(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    token = auth_api.issue_token("u-abc", "d1")
    assert auth_api.require_user(f"Bearer {token}") == "u-abc"
