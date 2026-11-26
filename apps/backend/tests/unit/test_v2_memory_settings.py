from app.core.settings import get_settings


def test_v2_memory_defaults_exist_and_disabled():
    settings = get_settings()
    assert settings.memory_eval_threshold_high > settings.memory_eval_threshold_low
    assert settings.memory_llm_fallback_rate_cap == 0.3
    assert settings.memory_decay_batch_size > 0
    assert settings.memory_forget_retention_days == 30
    assert settings.embedding_batch_size == 32
    assert settings.embedding_batch_window_seconds == 60
    assert settings.memory_retrieval_budget == 800


def test_v2_memory_flags_env_overridable(monkeypatch):
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()