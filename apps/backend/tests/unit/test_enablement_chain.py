"""Enablement 串行链校验单元测试（V2.0.0 dependency-graph 串行链）。"""

from app.core.settings._shared import SettingsError
from app.core.settings.enablement import enablement_violations, validate_enablement_chain


class _FakeSettings:
    def __init__(self, **flags):
        self.v2_autonomy_advanced_enabled = flags.get("v2_autonomy_advanced_enabled", False)
        self.v2_life_loop_enabled = flags.get("v2_life_loop_enabled", False)
        self.v2_action_outbox_enabled = flags.get("v2_action_outbox_enabled", False)
        self.action_enabled = flags.get("action_enabled", False)
        self.v21_agent_runtime_enabled = flags.get("v21_agent_runtime_enabled", False)
        self.v21_unified_run_enabled = flags.get("v21_unified_run_enabled", False)
        self.v21_goal_stack_enabled = flags.get("v21_goal_stack_enabled", False)
        self.v21_personality_evolution_enabled = flags.get(
            "v21_personality_evolution_enabled", False
        )
        self.v21_agent_metrics_enabled = flags.get("v21_agent_metrics_enabled", False)


def test_all_off_no_violations():
    assert enablement_violations(_FakeSettings()) == []


def test_autonomy_advanced_requires_life_loop():
    flags = _FakeSettings(v2_autonomy_advanced_enabled=True, action_enabled=True)
    assert "v2_life_loop_enabled" in "\n".join(enablement_violations(flags))


def test_autonomy_advanced_requires_action_gate():
    flags = _FakeSettings(
        v2_autonomy_advanced_enabled=True, v2_life_loop_enabled=True
    )
    assert "action_enabled" in "\n".join(enablement_violations(flags))


def test_outbox_requires_life_loop_consumer():
    flags = _FakeSettings(v2_action_outbox_enabled=True, v2_life_loop_enabled=False)
    assert "v2_life_loop_enabled" in "\n".join(enablement_violations(flags))


def test_valid_chain_passes():
    flags = _FakeSettings(
        v2_autonomy_advanced_enabled=True,
        v2_life_loop_enabled=True,
        v2_action_outbox_enabled=True,
        action_enabled=True,
    )
    assert enablement_violations(flags) == []


def test_validate_raises_on_broken_chain():
    flags = _FakeSettings(v2_autonomy_advanced_enabled=True)
    try:
        validate_enablement_chain(flags)
    except SettingsError:
        return
    raise AssertionError("expected SettingsError")