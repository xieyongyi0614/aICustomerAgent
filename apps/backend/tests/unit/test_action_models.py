"""V9-001 Action Domain Model 单测（action-model.md / testing.md §1）。"""

import pytest
from pydantic import ValidationError

from app.models.action import (
    ACTION_STATUSES,
    GATE_REASONS,
    ActionEffect,
    ActionIntent,
    ActionPlan,
    ActionRecord,
    ActionResult,
    ActionSchema,
    ActionStep,
    CapabilityResult,
    make_dedupe_key,
    normalize_core_params,
    transition_action,
)
from app.core.settings import Settings, SettingsError, get_settings


class TestActionModels:
    def test_action_intent_confident(self):
        intent = ActionIntent(
            action_type="create_reminder",
            confidence="confident",
            params={"content": "开会", "due": "明天早上8点"},
            evidence="提醒我",
            dedupe_key="abc123",
        )
        assert intent.trigger_source == "lexicon"

    def test_action_intent_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            ActionIntent(action_type="fly_to_moon", confidence="confident")

    def test_action_step_and_plan(self):
        step = ActionStep(index=0, capability="reminder", action="create", params={})
        plan = ActionPlan(
            intent=ActionIntent(action_type="create_reminder", confidence="confident"), steps=[step]
        )
        assert plan.steps[0].status == "pending"

    def test_action_result_effects(self):
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_1", detail="创建提醒 due 20:00")],
        )
        assert result.effects[0].kind == "world"

    def test_capability_result_statuses(self):
        for status in ("succeeded", "failed", "timeout", "unavailable"):
            assert CapabilityResult(status=status).status == status
        with pytest.raises(ValidationError):
            CapabilityResult(status="weird")

    def test_action_schema_validate(self):
        schema = ActionSchema(required=["content", "due"])
        errors = schema.validate({"content": "开会"})
        assert any("due" in e for e in errors)
        assert schema.validate({"content": "开会", "due": "明天"}) == []

    def test_action_schema_validator(self):
        schema = ActionSchema(
            required=["n"],
            validators={"n": lambda name, value: "必须为正数" if value <= 0 else None},
        )
        assert schema.validate({"n": -1}) == ["必须为正数"]
        assert schema.validate({"n": 1}) == []

    def test_action_record_defaults_and_terminal(self):
        record = ActionRecord(id="act_1", user_id="u1", action_type="create_reminder")
        assert record.status == "created"
        assert not record.is_terminal()
        record.status = "succeeded"
        assert record.is_terminal()


class TestTransitionAction:
    def test_full_success_path(self):
        assert transition_action("created", "gate_pass") == "planned"
        assert transition_action("planned", "execute_start") == "executing"
        assert transition_action("executing", "step_all_succeeded") == "succeeded"

    def test_gate_reject(self):
        assert transition_action("created", "gate_reject") == "cancelled"

    def test_retryable_failure_stays_executing(self):
        assert transition_action("executing", "step_retryable_failed") == "executing"

    def test_retryable_failure_exceeded(self):
        assert transition_action("executing", "step_retryable_failed", attempts_exceeded=True) == "failed"
        assert transition_action("planned", "step_retryable_failed", attempts_exceeded=True) is None

    def test_permanent_failure(self):
        assert transition_action("executing", "step_permanent_failed") == "failed"

    def test_expire(self):
        assert transition_action("planned", "expire") == "cancelled"

    def test_cancel_semantics(self):
        assert transition_action("created", "cancel_requested") == "cancelled"
        assert transition_action("planned", "cancel_requested") == "cancelled"
        assert transition_action("executing", "cancel_requested") is None

    def test_terminal_states_immutable(self):
        for status in ("succeeded", "failed", "cancelled"):
            for event in (
                "gate_pass",
                "execute_start",
                "step_all_succeeded",
                "cancel_requested",
                "expire",
            ):
                assert transition_action(status, event) is None

    def test_illegal_forward_transition(self):
        assert transition_action("created", "step_all_succeeded") is None
        assert transition_action("planned", "step_all_succeeded") is None
        assert transition_action("created", "execute_start") is None

    def test_all_statuses_and_reasons_covered(self):
        assert len(ACTION_STATUSES) == 6
        assert set(ACTION_STATUSES) == {
            "created",
            "planned",
            "executing",
            "succeeded",
            "failed",
            "cancelled",
        }
        assert set(GATE_REASONS) == {
            "disabled",
            "ambiguous_params",
            "capability_unavailable",
            "duplicate",
            "quota_exceeded",
            "effect_already_satisfied",
            "target_not_found",
        }


class TestDedupeKey:
    def test_word_order_irrelevant(self):
        key_a = make_dedupe_key("create_reminder", {"content": "买牛奶", "due": "晚上"})
        key_b = make_dedupe_key("create_reminder", {"due": "晚上", "content": "买牛奶"})
        assert key_a == key_b

    def test_content_sensitive(self):
        assert make_dedupe_key("create_reminder", {"content": "开会", "due": "明天"}) != make_dedupe_key(
            "create_reminder", {"content": "买牛奶", "due": "明天"}
        )

    def test_type_sensitive(self):
        assert make_dedupe_key("create_reminder", {"content": "开会"}) != make_dedupe_key(
            "cancel_reminder", {"content": "开会"}
        )

    def test_whitespace_normalized(self):
        assert make_dedupe_key("remember_fact", {"fact": "  生日  7月30日 "}) == make_dedupe_key(
            "remember_fact", {"fact": "生日 7月30日"}
        )

    def test_normalize_drops_empty(self):
        assert normalize_core_params({"a": "", "b": None, "c": " x "}) == {"c": "x"}

    def test_key_length(self):
        assert len(make_dedupe_key("create_object", {"object": "牛奶"})) == 16


class TestSettingsActionGroup:
    def test_defaults(self):
        settings = get_settings()
        assert settings.action_enabled is False
        assert settings.action_detector_enabled is True
        assert settings.action_plan_max_steps == 1
        assert settings.action_max_active_per_user == 5
        assert settings.action_dedupe_window_hours == 24
        assert settings.action_execution_timeout_seconds == 10
        assert settings.action_retry_max_attempts == 2
        assert settings.action_retry_backoff_seconds == 30
        assert settings.action_context_char_budget == 400
        assert settings.action_memory_policy_enabled is True
        assert settings.action_relationship_enabled is False
        assert settings.action_record_retention_days == 180
        assert settings.autonomy_action_enabled is False
        assert settings.autonomy_action_daily_limit == 1

    def test_memory_policy_table(self):
        policy = get_settings().action_memory_policy()
        assert policy["create_reminder"]["source"] == "user_derived"
        assert policy["remember_fact"]["source"] == "user_stated"
        assert policy["remember_fact"]["importance"] == 0.8

    def test_invalid_memory_policy_rejected(self):
        with pytest.raises(SettingsError):
            Settings(
                action_memory_policy_json='{"remember_fact": {"deposit": true, "source": "ai_inferred"}}',
                llm_profiles_json='[{"id":"p","label":"p","base_url":"u","model":"m","api_key":"k"}]',
                default_llm_profile="p",
            )
