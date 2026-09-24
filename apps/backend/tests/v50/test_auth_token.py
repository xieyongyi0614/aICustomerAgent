"""API-001 设备配对令牌测试。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import auth as auth_api

pytestmark = pytest.mark.unit


def test_pair_requires_secret(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "")
    with pytest.raises(HTTPException) as exc:
        auth_api.pair_device(auth_api.PairRequest(device_id="d1"))
    assert exc.value.status_code == 503


def test_issue_and_parse_token(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    token = auth_api.issue_token("u1", "d1")
    assert auth_api.parse_token(token) == "u1"


def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setattr(auth_api, "_secret", lambda: "test-secret")
    with pytest.raises(HTTPException):
        auth_api.parse_token("u1.d1.999.deadbeef")
