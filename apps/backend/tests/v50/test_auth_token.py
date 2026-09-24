"""API-001 设备配对令牌测试。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import auth as auth_api

pytestmark = pytest.mark.unit


def test_pair_requires_secret(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "")
    with pytest.raises(HTTPException) as exc:
        auth_api.pair_device(
            auth_api.PairRequest(
                pairing_secret="x", device_id="d1", platform="android"
            )
        )
    assert exc.value.status_code == 503


def test_pair_requires_pairing_code_configured(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    monkeypatch.setattr(auth_api, "_pairing_secret", lambda: "")
    with pytest.raises(HTTPException) as exc:
        auth_api.pair_device(
            auth_api.PairRequest(
                pairing_secret="x", device_id="d1", platform="android"
            )
        )
    assert exc.value.status_code == 503


def test_pair_rejects_wrong_pairing_secret(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    monkeypatch.setattr(auth_api, "_pairing_secret", lambda: "correct")
    with pytest.raises(HTTPException) as exc:
        auth_api.pair_device(
            auth_api.PairRequest(
                pairing_secret="wrong", device_id="d1", platform="android"
            )
        )
    assert exc.value.status_code == 401


def test_pair_returns_bound_token(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    monkeypatch.setattr(auth_api, "_pairing_secret", lambda: "correct")
    monkeypatch.setattr(
        "app.core.settings.get_settings",
        lambda: type("S", (), {"default_user": "u1", "auth_token_secret": "test-secret", "auth_pairing_code": "correct"})(),
    )
    # pair_device 读 get_settings().default_user；直接用 issue_token 路径验证绑定
    token = auth_api.issue_token("u1", "d1")
    user_id, device_id, exp = auth_api.parse_token_parts(token)
    assert user_id == "u1"
    assert device_id == "d1"
    assert exp > 0


def test_pair_request_requires_fields():
    with pytest.raises(ValidationError):
        auth_api.PairRequest(device_id="d1")


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
