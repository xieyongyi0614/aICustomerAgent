"""TOOL-001：v24 串行链已随开关删除移除（architecture.md §7.8 / TOOL-001 §6.2）。

总闸与九个子闸已随 V2.4.0 转正删除，`enablement` 中不再有 v24 段，故原
「子闸 ⇒ 总闸」「通道 ⇒ 飞书绑定」两类 fail-fast 规则整体消失。本文件保留两条
反向断言：**旧规则不再产生任何违规**，且旧 env 名即使残留也不会伪造违规。
"""

from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations, validate_enablement_chain

V24_REMOVED_FLAGS = (
    "tool_system_enabled",
    "tool_permission_enabled",
    "tool_schema_validation_enabled",
    "tool_observation_enabled",
    "tool_surface_enabled",
    "tool_memory_enabled",
    "tool_reflection_enabled",
    "tool_channel_enabled",
    "tool_external_api_enabled",
    "tool_user_defined_enabled",
)

V24_REMOVED_TOKENS = V24_REMOVED_FLAGS + ("feishu_enabled",)


def _violating_tokens(violations: list[str]) -> list[str]:
    return [
        token
        for violation in violations
        for token in V24_REMOVED_TOKENS
        if token in violation
    ]


def test_no_v24_enablement_rules_remain():
    assert _violating_tokens(enablement_violations(get_settings())) == []


def test_legacy_v24_env_names_no_longer_produce_violations(monkeypatch):
    for flag in V24_REMOVED_FLAGS:
        monkeypatch.setenv(flag.upper(), "true")
    monkeypatch.setenv("V24_TOOL_SYSTEM_ENABLED", "true")
    monkeypatch.setenv("V24_TOOL_PERMISSION_ENABLED", "true")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert _violating_tokens(enablement_violations(settings)) == []
    finally:
        get_settings.cache_clear()


def test_default_settings_pass_chain():
    validate_enablement_chain(get_settings())
