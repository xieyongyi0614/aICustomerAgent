import re
from datetime import datetime

import pytest

from app.core.settings import SettingsError, get_settings
from app.models.observability import (
    CallSite,
    DecisionKind,
    DecisionRecord,
    LlmCallRecord,
    MetricReport,
    PromptSnapshot,
    RuntimeTrace,
    SCHEMA_CALL_SITES,
    TraceEvent,
    TraceKind,
    bound_extra,
    bound_text,
    deterministic_sample,
    estimate_cost,
)

SNAPSHOT_KEYS = {
    "turn_id",
    "request_id",
    "token_usage",
    "model_name",
    "status",
    "role_mode",
    "analysis",
    "behavior",
    "mode",
    "total_ms",
    "steps",
}


def test_bound_text_truncates_and_flags():
    text, truncated = bound_text("abcdef", 3)
    assert (text, truncated) == ("abc", True)
    assert bound_text("ab", 3) == ("ab", False)
    assert bound_text(None, 3) == ("", False)


def test_bound_extra_passes_through_small_dict():
    extra, truncated = bound_extra({"a": 1}, 100)
    assert extra == {"a": 1}
    assert truncated is False


def test_bound_extra_replaces_oversized_dict_with_summary():
    extra, truncated = bound_extra({"blob": "x" * 100}, 10)
    assert truncated is True
    assert list(extra) == ["truncated_summary"]
    assert len(extra["truncated_summary"]) == 10
    assert bound_extra(None, 10) == ({}, False)


def test_deterministic_sample_boundaries_and_stability():
    assert deterministic_sample("same-key", 1.0) is True
    assert deterministic_sample("same-key", 0.0) is False
    first = deterministic_sample("key-a", 0.5)
    for _ in range(20):
        assert deterministic_sample("key-a", 0.5) == first


def test_runtime_trace_api_dict_matches_snapshot_shape():
    trace = RuntimeTrace(
        trace_id="req-1",
        kind=TraceKind.TURN,
        user_id="u1",
        conversation_id="c1",
        turn_id="42",
        status="complete",
        duration_ms=12.345,
        token_usage={"input_tokens": 10},
        model_name="fake",
        meta={"role_mode": {"mode": "default"}},
        steps=[
            {
                "name": "llm",
                "status": "ok",
                "duration_ms": 1.5,
                "first_token_ms": 0.4,
                "error": None,
                "extra": {"k": "v"},
            }
        ],
        events=[TraceEvent(kind="emotion_change", at_ms=5.0, payload={"after": "happy"})],
    )
    payload = trace.api_dict()
    assert SNAPSHOT_KEYS <= set(payload)
    assert payload["request_id"] == "req-1"
    assert payload["turn_id"] == "42"
    assert payload["total_ms"] == 12.35
    assert payload["role_mode"] == {"mode": "default"}
    step = payload["steps"][0]
    assert step["durationMs"] == 1.5
    assert step["firstTokenMs"] == 0.4
    assert step["extra"] == {"k": "v"}
    assert payload["kind"] == "turn"
    assert payload["events"][0]["kind"] == "emotion_change"


def test_decision_record_defaults():
    record = DecisionRecord(
        kind=DecisionKind.PROACTIVE_AUTONOMY,
        user_id="u1",
        decision="act",
        reason="触发 conversation_inactivity",
    )
    assert len(record.id) == 32
    assert record.outcome is None
    assert record.confidence is None
    assert isinstance(record.created_at, datetime)


def test_prompt_snapshot_call_site_enum():
    snapshot = PromptSnapshot(request_id="req-1", call_site=CallSite.ANSWER)
    assert snapshot.call_site is CallSite.ANSWER
    assert snapshot.messages == []
    assert snapshot.truncated is False
    with pytest.raises(ValueError):
        PromptSnapshot(request_id="req-1", call_site="nope")


def test_llm_call_record_defaults():
    record = LlmCallRecord(request_id="req-1", call_site=CallSite.JUDGE, latency_ms=12.0)
    assert record.status == "ok"
    assert record.input_tokens is None
    assert record.cost_estimate is None


def test_estimate_cost_matches_configured_prices_only():
    table = {"fake": {"input_per_mtok": 1.0, "output_per_mtok": 3.0}}
    assert estimate_cost("fake", 1_000_000, 1_000_000, table) == pytest.approx(4.0)
    assert estimate_cost("unknown", 10, 10, table) is None
    assert estimate_cost(None, 10, 10, table) is None
    assert estimate_cost("fake", None, 10, table) is None
    assert estimate_cost("fake", 10, 10, {"fake": {"input_per_mtok": 1.0}}) is None


def test_metric_report_defaults():
    report = MetricReport(window_hours=24)
    assert report.pipeline.turn_count == 0
    assert report.llm.calls == 0
    assert report.quality.verdict_distribution == {}
    assert report.business.proactive.ack_rate is None


def test_schema_call_sites_cover_structured_chains():
    assert SCHEMA_CALL_SITES["RoleMode"] is CallSite.ROUTER
    assert SCHEMA_CALL_SITES["TurnAnalysis"] is CallSite.TURN_ANALYSIS
    assert SCHEMA_CALL_SITES["SceneIntentResult"] is CallSite.SCENE_INTENT
    assert SCHEMA_CALL_SITES["IntentionDecision"] is CallSite.INTENTION
    assert SCHEMA_CALL_SITES["SceneActionDecision"] is CallSite.SCENE_UPDATE
    assert SCHEMA_CALL_SITES["StateUpdateDecision"] is CallSite.STATE_UPDATE
    assert SCHEMA_CALL_SITES["MemoryExtraction"] is CallSite.EXTRACTOR
    assert SCHEMA_CALL_SITES["TurnJudgeResult"] is CallSite.JUDGE


def test_observability_settings_defaults(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_PERSIST_ENABLED", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.observability_persist_enabled is True
    assert settings.observability_trace_sample_rate == 1.0
    assert settings.observability_prompt_capture_mode == "sampled"
    assert settings.observability_prompt_sample_rate == 0.2
    assert settings.observability_prompt_max_chars == 20000
    assert settings.observability_step_extra_max_chars == 2000
    assert settings.observability_trace_retention_days == 7
    assert settings.observability_prompt_retention_days == 3
    assert settings.observability_decision_retention_days == 14
    assert settings.observability_llm_call_retention_days == 30


def test_observability_settings_env_override(override_settings):
    override_settings(
        observability_persist_enabled=False,
        observability_prompt_sample_rate=0.5,
        observability_trace_retention_days=9,
    )
    settings = get_settings()
    assert settings.observability_persist_enabled is False
    assert settings.observability_prompt_sample_rate == 0.5
    assert settings.observability_trace_retention_days == 9


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ("OBSERVABILITY_TRACE_SAMPLE_RATE", "必须在 [0, 1]"),
        ("OBSERVABILITY_PROMPT_SAMPLE_RATE", "必须在 [0, 1]"),
    ],
)
def test_observability_rate_validation_rejects_out_of_range(monkeypatch, env, message):
    monkeypatch.setenv(env, "1.5")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match=re.escape(message)):
        get_settings()
    get_settings.cache_clear()


def test_observability_mode_validation_rejects_unknown(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_PROMPT_CAPTURE_MODE", "sometimes")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="disabled/sampled/always"):
        get_settings()
    get_settings.cache_clear()


def test_observability_cost_json_validation(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_LLM_COST_JSON", "not-json")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="OBSERVABILITY_LLM_COST_JSON"):
        get_settings()
    get_settings.cache_clear()
    monkeypatch.setenv("OBSERVABILITY_LLM_COST_JSON", "[1]")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="必须是对象"):
        get_settings()
    get_settings.cache_clear()


def test_observability_cost_table_helper(override_settings):
    override_settings(
        observability_llm_cost_json='{"fake": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}'
    )
    assert get_settings().observability_llm_cost_table()["fake"]["input_per_mtok"] == 1.0
