import json

import pytest
from fastapi import HTTPException, Request, status
from fastapi.testclient import TestClient

from app.api.v1.deps import get_chat_llm
from app.api.v1.schemas import ChatRequest, LlmProfileOut, LlmProfilesOut
from app.core import llm_factory
from app.core.llm_factory import get_llm, list_llm_profiles, reset_llm, set_llm
from app.core.settings import Settings, SettingsError, get_settings
from app.main import app
from tests.conftest import FakeLLM


def _make_settings(**overrides):
    base = {
        "llm_profiles_json": json.dumps(
            [
                {
                    "id": "alpha",
                    "label": "Alpha",
                    "base_url": "https://a.example/v1",
                    "model": "alpha-model",
                    "api_key": "k1",
                    "max_tokens": 11,
                },
                {
                    "id": "beta",
                    "label": "Beta",
                    "base_url": "https://b.example/v1",
                    "model": "beta-model",
                    "api_key": "k2",
                    "max_tokens": 22,
                },
            ]
        ),
        "default_llm_profile": "alpha",
    }
    base.update(overrides)
    return Settings(**base)


def test_settings_lists_profiles_and_marks_default():
    settings = _make_settings()
    profiles = settings.llm_profiles()
    assert [p.id for p in profiles] == ["alpha", "beta"]
    assert profiles[0].default is True
    assert profiles[1].default is False
    assert profiles[0].to_public() == {
        "id": "alpha",
        "label": "Alpha",
        "model": "alpha-model",
        "default": True,
    }


def test_settings_rejects_unknown_default():
    with pytest.raises(SettingsError):
        Settings(
            llm_profiles_json=_make_settings().llm_profiles_json,
            default_llm_profile="ghost",
        )


def test_settings_rejects_duplicate_ids():
    raw = json.dumps(
        [
            {
                "id": "dup",
                "label": "Dup",
                "base_url": "https://a/v1",
                "model": "m",
                "api_key": "k",
            },
            {
                "id": "dup",
                "label": "Dup2",
                "base_url": "https://b/v1",
                "model": "m",
                "api_key": "k",
            },
        ]
    )
    with pytest.raises(SettingsError):
        Settings(llm_profiles_json=raw, default_llm_profile="dup")


def test_settings_loads_profiles_from_file(tmp_path):
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text(
        json.dumps(
            [
                {
                    "id": "file-a",
                    "label": "A",
                    "base_url": "https://a.example/v1",
                    "model": "m",
                    "api_key": "k",
                },
                {
                    "id": "file-b",
                    "label": "B",
                    "base_url": "https://b.example/v1",
                    "model": "m",
                    "api_key": "k",
                },
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        llm_profiles_json="",
        llm_profiles_file=str(profiles_file),
        default_llm_profile="file-a",
    )
    assert [p.id for p in settings.llm_profiles()] == ["file-a", "file-b"]
    assert settings.get_llm_profile(None).id == "file-a"


def test_llm_profiles_json_takes_priority_over_file(tmp_path):
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text(
        json.dumps(
            [
                {
                    "id": "file-a",
                    "label": "A",
                    "base_url": "https://a.example/v1",
                    "model": "m",
                    "api_key": "k",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        llm_profiles_json=json.dumps(
            [
                {
                    "id": "inline",
                    "label": "Inline",
                    "base_url": "https://i.example/v1",
                    "model": "m",
                    "api_key": "k",
                }
            ]
        ),
        llm_profiles_file=str(profiles_file),
        default_llm_profile="inline",
    )
    assert [p.id for p in settings.llm_profiles()] == ["inline"]


def test_settings_rejects_missing_profiles_file(tmp_path):
    with pytest.raises(SettingsError, match="不存在"):
        Settings(
            llm_profiles_json="",
            llm_profiles_file=str(tmp_path / "missing.json"),
            default_llm_profile="file-a",
        )


def test_get_llm_profile_lookup():
    settings = _make_settings()
    assert settings.get_llm_profile(None).id == "alpha"
    assert settings.get_llm_profile("beta").id == "beta"
    with pytest.raises(SettingsError):
        settings.get_llm_profile("missing")


def test_factory_caches_per_profile(monkeypatch):
    reset_llm()
    fake_alpha = FakeLLM(response="alpha")
    fake_beta = FakeLLM(response="beta")
    calls = {"alpha": 0, "beta": 0}

    def fake_get_settings():
        return _make_settings()

    monkeypatch.setattr(llm_factory, "get_settings", fake_get_settings)
    set_llm(fake_alpha, profile_id="alpha")
    set_llm(fake_beta, profile_id="beta")

    a = get_llm("alpha")
    b = get_llm("beta")
    assert a is fake_alpha
    assert b is fake_beta
    assert a is not b


def test_list_profiles_returns_public_view(monkeypatch):
    monkeypatch.setattr(llm_factory, "get_settings", lambda: _make_settings())
    payload = list_llm_profiles()
    assert payload == [
        {"id": "alpha", "label": "Alpha", "model": "alpha-model", "default": True},
        {"id": "beta", "label": "Beta", "model": "beta-model", "default": False},
    ]


def test_profiles_endpoint(monkeypatch):
    monkeypatch.setattr("app.api.v1.llm.get_settings", lambda: _make_settings())
    monkeypatch.setattr(llm_factory, "get_settings", lambda: _make_settings())
    with TestClient(app) as client:
        response = client.get("/api/v1/llm/profiles")
    assert response.status_code == 200
    body = LlmProfilesOut.model_validate(response.json())
    assert body.default == "alpha"
    assert [p.id for p in body.profiles] == ["alpha", "beta"]
    assert all(isinstance(p, LlmProfileOut) for p in body.profiles)


def _make_request(header_profile=None, query_profile=None):
    headers = [(b"x-llm-profile", header_profile.encode())] if header_profile else []
    query_string = f"profile_id={query_profile}".encode() if query_profile else b""
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/message",
            "headers": headers,
            "query_string": query_string,
        }
    )


def test_get_chat_llm_prefers_body_then_header_then_query(monkeypatch):
    monkeypatch.setattr(llm_factory, "get_settings", lambda: _make_settings())
    reset_llm()
    fake_alpha = FakeLLM(response="alpha")
    fake_beta = FakeLLM(response="beta")
    set_llm(fake_alpha, profile_id="alpha")
    set_llm(fake_beta, profile_id="beta")

    assert (
        get_chat_llm(ChatRequest(content="hi", profile_id="beta"), _make_request())
        is fake_beta
    )
    assert (
        get_chat_llm(ChatRequest(content="hi"), _make_request(header_profile="beta"))
        is fake_beta
    )
    assert (
        get_chat_llm(ChatRequest(content="hi"), _make_request(query_profile="alpha"))
        is fake_alpha
    )
    reset_llm()


def test_get_chat_llm_falls_back_to_default_profile(monkeypatch):
    monkeypatch.setattr(llm_factory, "get_settings", lambda: _make_settings())
    reset_llm()
    fake_default = FakeLLM(response="default")
    set_llm(fake_default)

    assert get_chat_llm(ChatRequest(content="hi"), _make_request()) is fake_default
    reset_llm()


def test_get_chat_llm_unknown_profile_raises_http_400(monkeypatch):
    monkeypatch.setattr(llm_factory, "get_settings", lambda: _make_settings())
    reset_llm()

    with pytest.raises(HTTPException) as excinfo:
        get_chat_llm(ChatRequest(content="hi", profile_id="ghost"), _make_request())

    assert excinfo.value.status_code == status.HTTP_400_BAD_REQUEST
    reset_llm()


def test_chat_message_rejects_unknown_body_profile_before_streaming():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/message",
            json={"content": "你好", "profile_id": "ghost"},
        )

    assert response.status_code == 400
    assert "未知 LLM profile" in response.json()["detail"]
