"""TOOL-005 §6.1/§6.3：四档判定表、七步短路与正负例、默认拒绝三类原因、E1~E4/E9~E12。"""

import pytest

from app.character.asuna.tool import (
    CONFIRM_APPROVE_LEXICON,
    CONFIRM_DENY_LEXICON,
    CONFIRM_LEXICON_MIN_WORDS,
    CONFIRM_PROMPT_FALLBACK,
    CONFIRM_PROMPT_MAX_CHARS,
)
from app.core.settings._shared import SettingsError
from app.models.tool import namespace_permission_floor, resolve_permission_level
from app.services.tool import permission as permission_module
from app.services.tool.confirmation import channel_base_scope
from app.services.tool.permission import (
    CONFIRM_KIND_ALWAYS,
    CONFIRM_KIND_FIRST_TIME,
    DECISION_ALLOW,
    DECISION_CONFIRM_REQUIRED,
    DECISION_DENY,
    REASON_ALWAYS_CONFIRMATION,
    REASON_DEFAULT_DENY,
    REASON_FIRST_TIME_CONFIRMATION,
    REASON_GRANT_MATCHED,
    REASON_LAYER_DISABLED,
    REASON_LAYER_DISABLED_GRANT_FREE,
    REASON_LAYER_OFF,
    REASON_LEVEL_NO_GRANT_REQUIRED,
    REASON_OUT_OF_SCOPE,
    REASON_SNAPSHOT_UNAVAILABLE,
    REASON_UNTRUSTED_NAMESPACE,
    ToolPermissionGate,
    build_confirm_prompt,
    effective_level,
    scope_covers,
)
from tests.v24.tool005_support import (
    CHANNEL_BASE_TOOL_ID,
    CHANNEL_TOOL_ID,
    CHANNEL_TOOL_SCOPE,
    DANGEROUS_TOOL_ID,
    EXT_TOOL_ID,
    NORMAL_TOOL_ID,
    SAFE_TOOL_ID,
    SENSITIVE_TOOL_ID,
    UNTRUSTED_TOOL_ID,
    always_definition,
    channel_base_definition,
    channel_definition,
    ext_definition,
    grant,
    invocation,
    normal_definition,
    permission_settings,
    safe_definition,
    sensitive_definition,
    snapshot,
    untrusted_definition,
)

def _gate(**overrides) -> ToolPermissionGate:
    return ToolPermissionGate(permission_settings(**overrides))


# --- 四档 × 场景判定表 --------------------------------------------------------


@pytest.mark.parametrize(
    "definition_factory,grants,expected_decision,expected_reason,expected_kind",
    [
        (safe_definition, [], DECISION_ALLOW, REASON_LEVEL_NO_GRANT_REQUIRED, None),
        (normal_definition, [], DECISION_ALLOW, REASON_LEVEL_NO_GRANT_REQUIRED, None),
        (
            sensitive_definition,
            [],
            DECISION_CONFIRM_REQUIRED,
            REASON_FIRST_TIME_CONFIRMATION,
            CONFIRM_KIND_FIRST_TIME,
        ),
        (
            sensitive_definition,
            [grant(SENSITIVE_TOOL_ID, ("self",))],
            DECISION_ALLOW,
            REASON_GRANT_MATCHED,
            None,
        ),
        (
            always_definition,
            [grant("builtin.memory.purge", ("memory",))],
            DECISION_CONFIRM_REQUIRED,
            REASON_ALWAYS_CONFIRMATION,
            CONFIRM_KIND_ALWAYS,
        ),
        (
            always_definition,
            [],
            DECISION_CONFIRM_REQUIRED,
            REASON_ALWAYS_CONFIRMATION,
            CONFIRM_KIND_ALWAYS,
        ),
        (
            channel_definition,
            [],
            DECISION_CONFIRM_REQUIRED,
            REASON_FIRST_TIME_CONFIRMATION,
            CONFIRM_KIND_FIRST_TIME,
        ),
        (
            channel_definition,
            [grant(CHANNEL_TOOL_ID, CHANNEL_TOOL_SCOPE)],
            DECISION_ALLOW,
            REASON_GRANT_MATCHED,
            None,
        ),
        (
            untrusted_definition,
            [],
            DECISION_DENY,
            REASON_UNTRUSTED_NAMESPACE,
            None,
        ),
        (
            untrusted_definition,
            [grant("user.notes.delete", ("notes",))],
            DECISION_CONFIRM_REQUIRED,
            REASON_ALWAYS_CONFIRMATION,
            CONFIRM_KIND_ALWAYS,
        ),
    ],
)
def test_four_level_decision_table(
    definition_factory, grants, expected_decision, expected_reason, expected_kind
):
    definition = definition_factory()
    decision = _gate().evaluate(
        definition, invocation(definition.id), snapshot(grants=grants)
    )
    assert decision.decision == expected_decision
    assert decision.reason == expected_reason
    assert decision.confirm_kind == expected_kind
    assert decision.scope_required == tuple(definition.permission.scope)


def test_effective_level_keeps_override_below_floor():
    definition = safe_definition()
    assert effective_level(definition, snapshot()) == "safe"


def test_effective_level_raises_to_namespace_floor_without_override():
    definition = safe_definition().model_copy(
        update={
            "permission": safe_definition().permission.model_copy(
                update={"level": "safe", "override_reason": None}
            )
        }
    )
    assert definition.permission.level == "safe"
    assert effective_level(definition, snapshot()) == "normal"
    assert namespace_permission_floor("channel") == "sensitive"
    assert namespace_permission_floor("user") == "dangerous"


def test_level_only_raised_never_lowered_without_reason():
    with pytest.raises(SettingsError):
        resolve_permission_level("normal", "user", None)


# --- 七步短路：顺序与逐步正负例 -----------------------------------------------


def _recording_steps(monkeypatch) -> list[str]:
    calls: list[str] = []
    steps = []
    for step in permission_module._PERMISSION_STEPS:
        name = step.__name__

        def _wrapper(definition, inv, snap, _step=step, _name=name):
            calls.append(_name)
            return _step(definition, inv, snap)

        steps.append(_wrapper)
    monkeypatch.setattr(permission_module, "_PERMISSION_STEPS", tuple(steps))
    return calls


STEP_ORDER: tuple[str, ...] = (
    "_step_level_no_grant_required",
    "_step_grant_matched",
    "_step_first_time_confirmation",
    "_step_always_confirmation",
    "_step_out_of_scope",
    "_step_untrusted_namespace",
    "_step_default_deny",
)


def test_step_order_is_fixed():
    assert tuple(step.__name__ for step in permission_module._PERMISSION_STEPS) == STEP_ORDER


@pytest.mark.parametrize(
    "definition_factory,grants,expected_stop_step",
    [
        (safe_definition, [], "_step_level_no_grant_required"),
        (sensitive_definition, [grant(SENSITIVE_TOOL_ID, ("self",))], "_step_grant_matched"),
        (sensitive_definition, [], "_step_first_time_confirmation"),
        (always_definition, [], "_step_always_confirmation"),
        (
            channel_definition,
            [grant(CHANNEL_TOOL_ID, ("external:other",))],
            "_step_out_of_scope",
        ),
        (untrusted_definition, [], "_step_untrusted_namespace"),
    ],
)
def test_step_short_circuit_order(
    monkeypatch, definition_factory, grants, expected_stop_step
):
    calls = _recording_steps(monkeypatch)
    definition = definition_factory()
    _gate().evaluate(definition, invocation(definition.id), snapshot(grants=grants))
    assert calls[-1] == expected_stop_step
    assert len(calls) == STEP_ORDER.index(expected_stop_step) + 1


def test_default_deny_reaches_last_step(monkeypatch):
    calls = _recording_steps(monkeypatch)
    definition = always_definition(
        permission={"level": "dangerous", "scope": ("memory",), "confirm": "never"}
    )
    decision = _gate().evaluate(definition, invocation(definition.id), snapshot())
    assert decision.reason == REASON_DEFAULT_DENY
    assert calls[-1] == "_step_default_deny"
    assert len(calls) == len(permission_module._PERMISSION_STEPS)


def test_step_level_positive_and_negative():
    gate_definition = normal_definition()
    allowed = permission_module._step_level_no_grant_required(
        gate_definition, invocation(gate_definition.id), snapshot()
    )
    assert allowed is not None and allowed.decision == DECISION_ALLOW
    blocked = permission_module._step_level_no_grant_required(
        sensitive_definition(), invocation(SENSITIVE_TOOL_ID), snapshot()
    )
    assert blocked is None
    untrusted = permission_module._step_level_no_grant_required(
        untrusted_definition(), invocation(UNTRUSTED_TOOL_ID), snapshot()
    )
    assert untrusted is None


def test_step_grant_matched_positive_and_negative():
    definition = sensitive_definition()
    covered = permission_module._step_grant_matched(
        definition,
        invocation(SENSITIVE_TOOL_ID),
        snapshot(grants=[grant(SENSITIVE_TOOL_ID, ("self",))]),
    )
    assert covered is not None and covered.reason == REASON_GRANT_MATCHED
    uncovered = permission_module._step_grant_matched(
        definition,
        invocation(SENSITIVE_TOOL_ID),
        snapshot(grants=[grant(SENSITIVE_TOOL_ID, ("other",))]),
    )
    assert uncovered is None


def test_step_first_time_skips_when_grant_present():
    definition = sensitive_definition()
    decision = permission_module._step_first_time_confirmation(
        definition,
        invocation(SENSITIVE_TOOL_ID),
        snapshot(grants=[grant(SENSITIVE_TOOL_ID, ("self",))]),
    )
    assert decision is None


def test_step_always_positive_and_negative():
    decision = permission_module._step_always_confirmation(
        always_definition(), invocation("builtin.memory.purge"), snapshot()
    )
    assert decision is not None and decision.confirm_kind == CONFIRM_KIND_ALWAYS
    assert (
        permission_module._step_always_confirmation(
            sensitive_definition(), invocation(SENSITIVE_TOOL_ID), snapshot()
        )
        is None
    )


def test_step_out_of_scope_requires_existing_grant_set():
    definition = channel_definition()
    out_of_scope = permission_module._step_out_of_scope(
        definition,
        invocation(CHANNEL_TOOL_ID),
        snapshot(grants=[grant(CHANNEL_TOOL_ID, ("external:other",))]),
    )
    assert out_of_scope is not None and out_of_scope.reason == REASON_OUT_OF_SCOPE
    assert (
        permission_module._step_out_of_scope(
            definition, invocation(CHANNEL_TOOL_ID), snapshot()
        )
        is None
    )


def test_step_untrusted_positive_and_negative():
    untrusted = permission_module._step_untrusted_namespace(
        untrusted_definition(), invocation(UNTRUSTED_TOOL_ID), snapshot()
    )
    assert untrusted is not None and untrusted.reason == REASON_UNTRUSTED_NAMESPACE
    assert (
        permission_module._step_untrusted_namespace(
            normal_definition(), invocation("builtin.reminder.create"), snapshot()
        )
        is None
    )


# --- 默认拒绝（fail-closed）三类原因 -------------------------------------------


def test_deny_out_of_scope_e3():
    decision = _gate().evaluate(
        channel_definition(),
        invocation(CHANNEL_TOOL_ID),
        snapshot(
            grants=[grant(CHANNEL_TOOL_ID, ("external:a.com",))],
            channel_bound=True,
        ),
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_OUT_OF_SCOPE


def test_deny_out_of_scope_for_ext_api_with_whitelisted_host_e3():
    decision = _gate().evaluate(
        ext_definition(),
        invocation(EXT_TOOL_ID, {"content": "x", "url": "https://api.example.com/push"}),
        snapshot(
            grants=[grant(EXT_TOOL_ID, ("external:a.com",))],
            settings=permission_settings(tool_ext_allowed_hosts="api.example.com"),
        ),
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_OUT_OF_SCOPE


def test_deny_untrusted_namespace_e11():
    decision = _gate().evaluate(
        untrusted_definition(permission={"level": "dangerous", "scope": ("notes",)}),
        invocation(UNTRUSTED_TOOL_ID),
        snapshot(),
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_UNTRUSTED_NAMESPACE


def test_deny_default_deny_for_sensitive_never_policy():
    definition = sensitive_definition(
        permission={"level": "sensitive", "scope": ("self",), "confirm": "never"}
    )
    decision = _gate().evaluate(
        definition, invocation(SENSITIVE_TOOL_ID), snapshot()
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_DEFAULT_DENY


def test_ext_host_whitelist_empty_denies_every_host():
    decision = _gate().evaluate(
        ext_definition(),
        invocation(EXT_TOOL_ID, {"content": "x", "url": "https://api.example.com/v1/push"}),
        snapshot(settings=permission_settings(tool_ext_allowed_hosts="")),
    )
    assert decision.reason == REASON_UNTRUSTED_NAMESPACE


def test_ext_host_whitelist_allows_listed_host_into_confirm_flow():
    decision = _gate().evaluate(
        ext_definition(),
        invocation(EXT_TOOL_ID, {"content": "x", "url": "https://api.example.com/v1/push"}),
        snapshot(
            settings=permission_settings(tool_ext_allowed_hosts="api.example.com")
        ),
    )
    assert decision.decision == DECISION_CONFIRM_REQUIRED


# --- E1 / E2 / E4 / E9 / E10 / E14 -------------------------------------------


def test_snapshot_unavailable_is_denied_e1():
    decision = _gate().evaluate(
        sensitive_definition(), invocation(SENSITIVE_TOOL_ID), None
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_SNAPSHOT_UNAVAILABLE


def test_build_snapshot_failure_returns_none_e1(monkeypatch):
    import app.repositories.trigger_registry_repository as trigger_repository

    def _boom(*args, **kwargs):
        raise RuntimeError("repo down")

    monkeypatch.setattr(trigger_repository, "list_recent", _boom)
    gate = _gate()
    assembled = gate.build_snapshot("u-1", snapshot().now, permission_settings())
    assert assembled is None
    decision = gate.evaluate(sensitive_definition(), invocation(SENSITIVE_TOOL_ID), assembled)
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_SNAPSHOT_UNAVAILABLE


def test_expired_grant_is_not_matched_e2():
    now = snapshot().now
    boundary = _gate().evaluate(
        sensitive_definition(),
        invocation(SENSITIVE_TOOL_ID),
        snapshot(grants=[grant(SENSITIVE_TOOL_ID, ("self",), expires_at=now)]),
    )
    assert boundary.decision == DECISION_CONFIRM_REQUIRED
    alive = _gate().evaluate(
        sensitive_definition(),
        invocation(SENSITIVE_TOOL_ID),
        snapshot(
            grants=[
                grant(SENSITIVE_TOOL_ID, ("self",), expires_at=now.replace(year=now.year + 1))
            ]
        ),
    )
    assert alive.decision == DECISION_ALLOW


def test_always_policy_wins_over_existing_grant_e4():
    definition = always_definition()
    decision = _gate().evaluate(
        definition,
        invocation("builtin.memory.purge"),
        snapshot(grants=[grant("builtin.memory.purge", ("memory",))]),
    )
    assert decision.decision == DECISION_CONFIRM_REQUIRED
    assert decision.confirm_kind == CONFIRM_KIND_ALWAYS


def test_channel_bind_implies_base_scope_but_not_send_e9():
    bound = snapshot(
        grants=[grant("*", (channel_base_scope("feishu"),), source="channel_bind")],
        channel_bound=True,
    )
    base_tool = channel_base_definition()
    assert _gate().evaluate(base_tool, invocation(CHANNEL_BASE_TOOL_ID), bound).decision == (
        DECISION_ALLOW
    )
    send_tool = channel_definition()
    decision = _gate().evaluate(send_tool, invocation(CHANNEL_TOOL_ID), bound)
    assert decision.decision == DECISION_CONFIRM_REQUIRED
    assert decision.confirm_kind == CONFIRM_KIND_FIRST_TIME


def test_channel_unbind_loses_implied_grant_e10():
    unbound = snapshot()
    base_tool = channel_base_definition()
    decision = _gate().evaluate(base_tool, invocation(CHANNEL_BASE_TOOL_ID), unbound)
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_DEFAULT_DENY


def test_master_gate_off_keeps_allow_all_e14():
    definition = untrusted_definition()
    settings = permission_settings()
    decision = _gate().evaluate(
        definition, invocation(UNTRUSTED_TOOL_ID), snapshot(settings=settings)
    )
    assert decision.decision == DECISION_ALLOW
    assert decision.reason == REASON_LAYER_OFF


@pytest.mark.parametrize(
    "definition_factory,tool_id",
    [
        (safe_definition, SAFE_TOOL_ID),
        (normal_definition, NORMAL_TOOL_ID),
    ],
)
def test_sub_layer_off_grant_free_tier_still_allows(definition_factory, tool_id):
    """P0-1 中段：总闸 on + 权限子闸 off 时，免授权档（safe / normal）仍放行。"""
    settings = permission_settings()
    decision = _gate().evaluate(
        definition_factory(), invocation(tool_id), snapshot(settings=settings)
    )
    assert decision.decision == DECISION_ALLOW
    assert decision.reason == REASON_LAYER_DISABLED_GRANT_FREE


@pytest.mark.parametrize(
    "definition_factory,tool_id,expected_level",
    [
        (sensitive_definition, SENSITIVE_TOOL_ID, "sensitive"),
        (channel_definition, CHANNEL_TOOL_ID, "sensitive"),
        (always_definition, DANGEROUS_TOOL_ID, "dangerous"),
        (untrusted_definition, UNTRUSTED_TOOL_ID, "dangerous"),
        (ext_definition, EXT_TOOL_ID, "sensitive"),
    ],
)
def test_sub_layer_off_privileged_tiers_default_deny(
    definition_factory, tool_id, expected_level
):
    """P0-1 中段：总闸 on + 权限子闸 off 时，特权档默认拒绝（fail-closed）。"""
    settings = permission_settings()
    decision = _gate().evaluate(
        definition_factory(), invocation(tool_id), snapshot(settings=settings)
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_LAYER_DISABLED
    assert decision.level == expected_level


def test_sub_layer_off_ignores_passed_snapshot_grants():
    """子闸 off 时快照不参与判定：特权档即便带 grant 也不得放行（无授权存储可读）。"""
    settings = permission_settings()
    granted = snapshot(
        grants=[grant(SENSITIVE_TOOL_ID, ("self",))], settings=settings
    )
    decision = _gate().evaluate(
        sensitive_definition(), invocation(SENSITIVE_TOOL_ID), granted
    )
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_LAYER_DISABLED


def test_evaluate_never_raises_on_broken_snapshot():
    broken = snapshot()
    object.__setattr__(broken, "namespace_floors", {"world": "nonsense"})
    decision = _gate().evaluate(safe_definition(), invocation(SAFE_TOOL_ID), broken)
    assert decision.decision == DECISION_DENY
    assert decision.reason == REASON_DEFAULT_DENY


# --- 确认话术（角色语气 + 长度预算 + E12 回退） --------------------------------


def test_confirm_prompt_is_character_tone_within_budget():
    prompt = build_confirm_prompt(
        channel_definition(), invocation(CHANNEL_TOOL_ID, {"content": "明天开会"})
    )
    assert "明天开会" in prompt
    assert len(prompt) <= CONFIRM_PROMPT_MAX_CHARS
    assert "吗" in prompt
    for announcement in ("系统", "确认请求", "操作", "等待用户"):
        assert announcement not in prompt


def test_confirm_prompt_falls_back_when_template_breaks_e12(monkeypatch):
    from app.character.asuna.tool import CONFIRM_PROMPT_TEMPLATES, ConfirmPromptTemplate

    broken = dict(CONFIRM_PROMPT_TEMPLATES)
    broken[CHANNEL_TOOL_ID] = ConfirmPromptTemplate(
        with_subject="{missing_key}", without_subject="{missing_key}"
    )
    monkeypatch.setattr(
        permission_module, "CONFIRM_PROMPT_TEMPLATES", broken, raising=False
    )
    prompt = build_confirm_prompt(
        channel_definition(), invocation(CHANNEL_TOOL_ID, {"content": "明天开会"})
    )
    assert prompt == CONFIRM_PROMPT_FALLBACK


def test_confirm_prompt_without_subject_uses_generic_line():
    prompt = build_confirm_prompt(
        sensitive_definition(), invocation(SENSITIVE_TOOL_ID, {})
    )
    assert prompt
    assert len(prompt) <= CONFIRM_PROMPT_MAX_CHARS
    assert "「」" not in prompt


# --- 范围覆盖与词表资产下限 ----------------------------------------------------


@pytest.mark.parametrize(
    "granted,required,expected",
    [
        (("self",), ("self",), True),
        (("*",), ("channel:feishu",), True),
        ((), (), True),
        (("self",), ("other",), False),
        (("external:a.com",), ("external:b.com",), False),
        (("channel:feishu",), ("channel:feishu.base",), False),
    ],
)
def test_scope_covers(granted, required, expected):
    assert scope_covers(granted, required) is expected


def test_confirmation_lexicons_meet_minimum():
    assert len(CONFIRM_APPROVE_LEXICON) >= CONFIRM_LEXICON_MIN_WORDS
    assert len(CONFIRM_DENY_LEXICON) >= CONFIRM_LEXICON_MIN_WORDS
    assert len(set(CONFIRM_APPROVE_LEXICON)) == len(CONFIRM_APPROVE_LEXICON)
    assert len(set(CONFIRM_DENY_LEXICON)) == len(CONFIRM_DENY_LEXICON)


def test_no_permission_mutating_tool_in_builtin_surface():
    from app.services.tool.registry import ToolRegistry, register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    forbidden = ("permission", "grant", "revoke", "privilege", "role")
    for definition in registry.list():
        haystack = f"{definition.id} {definition.name} {definition.action}".lower()
        assert not any(word in haystack for word in forbidden)
