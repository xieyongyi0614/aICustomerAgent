import logging

import pytest

from app.core.settings import Settings, SettingsError, get_settings
from app.core.settings.feishu import FeishuSettings

EXPECTED_DEFAULTS = {
    "feishu_enabled": False,
    "feishu_app_id": "",
    "feishu_app_secret": "",
    "feishu_verification_token": "",
    "feishu_encrypt_key": "",
    "feishu_api_base": "https://open.feishu.cn",
    "feishu_llm_profile": "",
    "feishu_timeout_seconds": 10.0,
    "feishu_token_refresh_ratio": 0.8,
    "feishu_max_reply_chars": 4000,
    "feishu_dedupe_ttl_seconds": 600,
    "feishu_signature_window_seconds": 300,
    "feishu_max_concurrent_turns": 4,
    "feishu_session_queue_limit": 5,
    "feishu_http_max_attempts": 3,
    "feishu_http_backoff_seconds": 0.5,
    "feishu_http_backoff_max_seconds": 8.0,
}

ENV_OVERRIDES = {
    "FEISHU_ENABLED": "false",
    "FEISHU_APP_ID": "cli_env_id",
    "FEISHU_APP_SECRET": "env-secret",
    "FEISHU_VERIFICATION_TOKEN": "env-token",
    "FEISHU_ENCRYPT_KEY": "env-encrypt",
    "FEISHU_API_BASE": "https://feishu.example.com/",
    "FEISHU_LLM_PROFILE": "longcat",
    "FEISHU_TIMEOUT_SECONDS": "3.5",
    "FEISHU_TOKEN_REFRESH_RATIO": "0.5",
    "FEISHU_MAX_REPLY_CHARS": "100",
    "FEISHU_DEDUPE_TTL_SECONDS": "60",
    "FEISHU_SIGNATURE_WINDOW_SECONDS": "30",
    "FEISHU_MAX_CONCURRENT_TURNS": "2",
    "FEISHU_SESSION_QUEUE_LIMIT": "7",
    "FEISHU_HTTP_MAX_ATTEMPTS": "5",
    "FEISHU_HTTP_BACKOFF_SECONDS": "0.1",
    "FEISHU_HTTP_BACKOFF_MAX_SECONDS": "1.0",
}

FIELD_TO_ENV = {
    "feishu_enabled": "FEISHU_ENABLED",
    "feishu_app_id": "FEISHU_APP_ID",
    "feishu_app_secret": "FEISHU_APP_SECRET",
    "feishu_verification_token": "FEISHU_VERIFICATION_TOKEN",
    "feishu_encrypt_key": "FEISHU_ENCRYPT_KEY",
    "feishu_api_base": "FEISHU_API_BASE",
    "feishu_llm_profile": "FEISHU_LLM_PROFILE",
    "feishu_timeout_seconds": "FEISHU_TIMEOUT_SECONDS",
    "feishu_token_refresh_ratio": "FEISHU_TOKEN_REFRESH_RATIO",
    "feishu_max_reply_chars": "FEISHU_MAX_REPLY_CHARS",
    "feishu_dedupe_ttl_seconds": "FEISHU_DEDUPE_TTL_SECONDS",
    "feishu_signature_window_seconds": "FEISHU_SIGNATURE_WINDOW_SECONDS",
    "feishu_max_concurrent_turns": "FEISHU_MAX_CONCURRENT_TURNS",
    "feishu_session_queue_limit": "FEISHU_SESSION_QUEUE_LIMIT",
    "feishu_http_max_attempts": "FEISHU_HTTP_MAX_ATTEMPTS",
    "feishu_http_backoff_seconds": "FEISHU_HTTP_BACKOFF_SECONDS",
    "feishu_http_backoff_max_seconds": "FEISHU_HTTP_BACKOFF_MAX_SECONDS",
}


def test_feishu_defaults():
    settings = FeishuSettings()
    for field_name, expected in EXPECTED_DEFAULTS.items():
        assert getattr(settings, field_name) == expected, field_name


def test_feishu_env_overrides_all_17_keys(monkeypatch):
    for env_name, value in ENV_OVERRIDES.items():
        monkeypatch.setenv(env_name, value)
    settings = FeishuSettings()
    assert settings.feishu_enabled is False
    assert settings.feishu_app_id == "cli_env_id"
    assert settings.feishu_api_base == "https://feishu.example.com"
    assert settings.feishu_timeout_seconds == 3.5
    assert settings.feishu_token_refresh_ratio == 0.5
    assert settings.feishu_max_reply_chars == 100
    assert settings.feishu_dedupe_ttl_seconds == 60
    assert settings.feishu_signature_window_seconds == 30
    assert settings.feishu_max_concurrent_turns == 2
    assert settings.feishu_session_queue_limit == 7
    assert settings.feishu_http_max_attempts == 5
    assert settings.feishu_http_backoff_seconds == 0.1
    assert settings.feishu_http_backoff_max_seconds == 1.0


def test_feishu_enabled_with_full_credentials_loads():
    settings = FeishuSettings(
        feishu_enabled=True,
        feishu_app_id="cli_app",
        feishu_app_secret="s3cret",
        feishu_verification_token="token-x",
    )
    assert settings.feishu_enabled is True


@pytest.mark.parametrize("missing", ["feishu_app_id", "feishu_app_secret", "feishu_verification_token"])
def test_feishu_enabled_missing_credential_raises(missing):
    kwargs = {
        "feishu_enabled": True,
        "feishu_app_id": "cli_app",
        "feishu_app_secret": "s3cret",
        "feishu_verification_token": "token-x",
    }
    kwargs[missing] = ""
    with pytest.raises(SettingsError) as exc_info:
        FeishuSettings(**kwargs)
    assert missing.upper() in str(exc_info.value)
    assert "s3cret" not in str(exc_info.value)


def test_feishu_disabled_with_empty_credentials_loads():
    settings = FeishuSettings()
    assert settings.feishu_enabled is False


@pytest.mark.parametrize("ratio", ["0", "0.0", "1.0", "1.5", "-0.1"])
def test_feishu_refresh_ratio_bounds(ratio):
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_token_refresh_ratio=float(ratio))


@pytest.mark.parametrize("seconds", ["0", "-1"])
def test_feishu_timeout_positive(seconds):
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_timeout_seconds=float(seconds))


@pytest.mark.parametrize("field_name", ["feishu_max_reply_chars", "feishu_dedupe_ttl_seconds", "feishu_signature_window_seconds", "feishu_max_concurrent_turns", "feishu_session_queue_limit"])
def test_feishu_positive_int_fields(field_name):
    with pytest.raises(SettingsError):
        FeishuSettings(**{field_name: 0})


def test_feishu_http_retry_bounds():
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_http_max_attempts=0)
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_http_backoff_seconds=-0.1)
    with pytest.raises(SettingsError):
        FeishuSettings(
            feishu_http_backoff_seconds=2.0, feishu_http_backoff_max_seconds=1.0
        )


def test_feishu_api_base_validation_and_normalization():
    assert FeishuSettings(feishu_api_base="https://x.test/").feishu_api_base == "https://x.test"
    assert FeishuSettings(feishu_api_base="http://x.test////").feishu_api_base == "http://x.test"
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_api_base="ftp://x.test")
    with pytest.raises(SettingsError):
        FeishuSettings(feishu_api_base="open.feishu.cn")


def test_feishu_settings_composed_into_settings():
    settings = get_settings()
    for field_name in EXPECTED_DEFAULTS:
        assert hasattr(settings, field_name), field_name
    assert isinstance(get_settings(), Settings)


def test_feishu_encrypt_key_empty_warns_without_secret(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.settings.feishu"):
        settings = FeishuSettings(
            feishu_enabled=True,
            feishu_app_id="cli_app",
            feishu_app_secret="s3cret-value",
            feishu_verification_token="token-value",
            feishu_encrypt_key="",
        )
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert settings.feishu_encrypt_key == ""
    assert any("FEISHU_ENCRYPT_KEY" in r.getMessage() for r in warnings)
    assert all("s3cret-value" not in r.getMessage() for r in warnings)
    assert all("token-value" not in r.getMessage() for r in warnings)


def test_feishu_encrypt_key_present_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.settings.feishu"):
        FeishuSettings(feishu_encrypt_key="key-material")
    assert not [r for r in caplog.records if r.name == "app.core.settings.feishu"]


def test_feishu_secret_values_only_nonempty():
    empty = FeishuSettings()
    assert empty.secret_values() == ()
    full = FeishuSettings(
        feishu_app_secret="s1",
        feishu_verification_token="s2",
        feishu_encrypt_key="s3",
    )
    assert full.secret_values() == ("s1", "s2", "s3")
    partial = FeishuSettings(feishu_app_secret="s1", feishu_encrypt_key="s3")
    assert partial.secret_values() == ("s1", "s3")
