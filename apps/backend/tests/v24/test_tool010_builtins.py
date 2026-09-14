"""TOOL-010 §6.1：内置工具完整声明与角色资产（E1、E4、E12、E15）。"""

from dataclasses import asdict

import pytest

from app.character.asuna.tool import (
    CHANNEL_FAILURE_TEXT,
    CONFIRM_APPROVE_LEXICON,
    CONFIRM_DENY_LEXICON,
    CONFIRM_PROMPT_MAX_CHARS,
    CONFIRM_PROMPT_TEMPLATES,
    TOOL_CONFIRM_PROMPTS,
    TOOL_FAILURE_TEXT,
    TOOL_FAILURE_TEXT_MAX_CHARS,
    TOOL_MEMORY_TEMPLATES,
    TOOL_OBSERVATION_KEYS,
    TOOL_SEMANTIC_TEXT,
    TOOL_SEMANTIC_TEXT_MAX_CHARS,
    TOOL_SURFACE_RULES,
    TOOL_UNAVAILABLE_REASON,
    TOOL_UNAVAILABLE_TOOL_IDS,
)
from app.models.tool import TOOL_DESCRIPTION_MAX_LENGTH, PermissionProfile
from app.services.tool import channel_tools
from app.services.tool.builtin import (
    MEMORY_TYPES,
    OBJECT_CATEGORIES,
    IMPORTANCE_VALUES,
    ENVIRONMENT_DIMENSIONS,
    SEARCH_QUERY_MAX_CHARS,
    REMINDER_CONTENT_MAX_CHARS,
    NOTIFICATION_CONTENT_MAX_CHARS,
    definitions,
    observation_keys,
)
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import SURFACE_LIMIT_REASON, ToolSurfaceResolver
from tests.v24.tool003_support import tool_settings
from tests.v24.tool004_support import surface_context
from tests.v24.tool010_support import (
    BUILTIN_TOOL_IDS,
    CHANNEL_ENVS,
    CHANNEL_TOOL_ID,
    ENABLED_TOOL_IDS,
    EXPECTED_OBSERVATIONS,
    NOTIFICATION_TOOL_ID,
    SEARCH_TOOL_ID,
    builtin_registry,
    definitions_by_id,
    enable,
    reset_runtime_state,
)


@pytest.fixture(autouse=True)
def _isolate_singletons():
    reset_runtime_state()
    yield
    reset_runtime_state()


def _params(definition) -> dict[str, object]:
    return {parameter.name: parameter for parameter in definition.input_schema.parameters}


# --- §2.2 声明表逐行 ---------------------------------------------------------


def test_definitions_cover_all_documented_tool_ids():
    assert sorted(item.id for item in definitions()) == list(BUILTIN_TOOL_IDS)
    assert len(definitions()) >= 9


def test_declared_required_params_cover_bound_action_schema():
    for definition in definitions():
        capability = channel_tools.get_channel_capability()
        if definition.capability != capability.name:
            from app.services.action.registry import get_capability_registry

            capability = get_capability_registry().get(definition.capability)
        action_schema = capability.actions[definition.action]
        declared_required = {
            parameter.name
            for parameter in definition.input_schema.parameters
            if parameter.required
        }
        assert set(action_schema.required) <= declared_required, definition.id


def test_schema_budgets_and_enums_match_section_2_2():
    by_id = definitions_by_id()

    reminder_content = _params(by_id["builtin.reminder.create"])["content"]
    assert reminder_content.required is True
    assert reminder_content.max_length == REMINDER_CONTENT_MAX_CHARS == 40
    assert _params(by_id["builtin.reminder.create"])["importance"].enum == IMPORTANCE_VALUES

    memory = _params(by_id["builtin.memory.save"])
    assert memory["fact"].required is True
    assert memory["memory_type"].enum == MEMORY_TYPES
    assert (memory["importance"].min, memory["importance"].max) == (0, 1)

    obj = _params(by_id["world.object.create"])
    assert obj["object"].required is True
    assert obj["category"].enum == OBJECT_CATEGORIES

    assert _params(by_id["world.object.move"])["location"].required is True
    assert _params(by_id["world.object.use"])["object"].required is True

    env = _params(by_id["world.env.query"])
    assert env["dimension"].enum == ENVIRONMENT_DIMENSIONS
    assert not any(parameter.required for parameter in env.values())

    query = _params(by_id[SEARCH_TOOL_ID])["query"]
    assert query.required is True
    assert query.max_length == SEARCH_QUERY_MAX_CHARS == 60

    assert _params(by_id[NOTIFICATION_TOOL_ID])["content"].max_length == (
        NOTIFICATION_CONTENT_MAX_CHARS
    )

    channel = _params(by_id[CHANNEL_TOOL_ID])
    assert channel["content"].required is True
    assert channel["content"].max_length == NOTIFICATION_CONTENT_MAX_CHARS == 200
    assert channel["recipient"].required is True


def test_semantic_validators_match_section_2_2():
    by_id = definitions_by_id()
    assert by_id["builtin.reminder.create"].input_schema.semantic_validators == (
        "future_datetime",
        "content_within_budget",
    )
    assert by_id["builtin.reminder.cancel"].input_schema.semantic_validators == ()
    assert by_id["builtin.memory.save"].input_schema.semantic_validators == (
        "content_within_budget",
    )
    assert by_id["world.object.create"].input_schema.semantic_validators == ()
    assert by_id["world.object.move"].input_schema.semantic_validators == (
        "object_in_inventory",
        "location_exists",
    )
    assert by_id["world.object.use"].input_schema.semantic_validators == (
        "object_in_inventory",
    )
    assert by_id["world.env.query"].input_schema.semantic_validators == ()
    assert by_id[SEARCH_TOOL_ID].input_schema.semantic_validators == (
        "content_within_budget",
    )
    assert by_id[NOTIFICATION_TOOL_ID].input_schema.semantic_validators == (
        "content_within_budget",
    )
    assert by_id[CHANNEL_TOOL_ID].input_schema.semantic_validators == (
        "recipient_authorized",
        "content_within_budget",
    )


def test_memory_policy_keys_match_section_2_2():
    by_id = definitions_by_id()
    depositing = {
        "builtin.reminder.create",
        "builtin.reminder.cancel",
        "builtin.memory.save",
        "world.object.create",
        NOTIFICATION_TOOL_ID,
        CHANNEL_TOOL_ID,
    }
    for tool_id in BUILTIN_TOOL_IDS:
        expected = tool_id if tool_id in depositing else None
        assert by_id[tool_id].memory_policy_key == expected, tool_id


def test_channel_declaration_matches_section_2_2():
    definition = definitions_by_id()[CHANNEL_TOOL_ID]
    assert definition.namespace == "channel"
    assert definition.capability == channel_tools.CHANNEL_CAPABILITY_NAME == "channel_feishu"
    assert definition.action == "send"
    assert definition.permission.level == "sensitive"
    assert definition.permission.scope == ("channel:feishu",)
    assert definition.permission.confirm == "first_time"
    assert definition.permission.requires_online is True
    assert definition.permission.audit is True
    assert definition.side_effects == ("send_external",)
    assert definition.idempotency == "keyed"
    assert definition.priority == 100
    assert definition.tags == ("channel", "feishu")


def test_read_only_tools_keep_override_reason():
    by_id = definitions_by_id()
    for tool_id in ("world.env.query", SEARCH_TOOL_ID):
        assert by_id[tool_id].permission.level == "safe"
        assert by_id[tool_id].permission.override_reason
        assert by_id[tool_id].is_read_only()


def test_declaration_set_is_byte_stable_across_builds():
    payloads = [
        repr([asdict(item) for item in builtin_registry().describe()]) for _ in range(3)
    ]
    assert len(set(payloads)) == 1


def test_declarations_touch_no_capability_implementation():
    from app.services.action.registry import get_capability_registry

    described = {
        entry["name"]: sorted(entry["actions"]) for entry in get_capability_registry().describe()
    }
    assert described == {
        "reminder": ["cancel", "create"],
        "memory": ["save"],
        "world_action": ["create", "move", "use"],
        "environment_query": ["query"],
        "search": ["query"],
        "notification": ["send"],
    }


# --- E4｜通道未绑定即 disabled，绑定后可执行 ----------------------------------


def test_e4_channel_tool_is_disabled_until_channel_is_bound():
    registry = builtin_registry()
    definition = registry.get(CHANNEL_TOOL_ID)
    assert definition.status == "disabled"
    assert registry.effective_status(CHANNEL_TOOL_ID) == "disabled"
    assert registry.has(CHANNEL_TOOL_ID) is False
    assert CHANNEL_TOOL_ID not in [item.tool_id for item in registry.describe()]
    assert [item.id for item in registry.list(status="enabled")] == list(ENABLED_TOOL_IDS)
    assert len(registry.describe()) >= 9
    assert registry.namespaces()["channel"].enabled_count == 0


def test_e4_channel_tool_turns_enabled_when_channel_is_bound(monkeypatch):
    enable(monkeypatch, **CHANNEL_ENVS)
    registry = builtin_registry()
    definition = registry.get(CHANNEL_TOOL_ID)
    assert definition.status == "enabled"
    assert registry.effective_status(CHANNEL_TOOL_ID) == "enabled"
    assert registry.has(CHANNEL_TOOL_ID) is True
    assert CHANNEL_TOOL_ID in [item.tool_id for item in registry.describe()]
    assert registry.namespaces()["channel"].enabled_count == 1
    from app.services.action.registry import get_capability_registry

    assert get_capability_registry().has("channel_feishu", "send")


# --- E1｜路线 B：默认裁剪 + 仍可 resolve ------------------------------------


def test_e1_search_tool_is_pruned_from_every_surface_but_still_resolvable():
    registry = builtin_registry()
    definition = registry.get(SEARCH_TOOL_ID)
    assert definition.status == "enabled"
    assert registry.has(SEARCH_TOOL_ID) is True
    assert SEARCH_TOOL_ID in [item.tool_id for item in registry.describe()]
    assert SEARCH_TOOL_ID in TOOL_UNAVAILABLE_TOOL_IDS
    for run_kind in TOOL_SURFACE_RULES:
        surface = ToolSurfaceResolver(registry, tool_settings()).resolve(
            run_kind, surface_context(settings=tool_settings())
        )
        reasons = {item["tool_id"]: item["reason"] for item in surface.excluded}
        assert reasons[SEARCH_TOOL_ID] == TOOL_UNAVAILABLE_REASON
        assert SEARCH_TOOL_ID not in surface.tool_ids


def test_e1_pruned_tool_reason_is_not_a_generic_status_reason():
    assert TOOL_UNAVAILABLE_REASON.startswith("unavailable:")
    assert TOOL_UNAVAILABLE_REASON != SURFACE_LIMIT_REASON


# --- 角色资产 ---------------------------------------------------------------


def test_semantic_text_covers_tools_within_budget():
    assert set(TOOL_SEMANTIC_TEXT) == set(BUILTIN_TOOL_IDS)
    for tool_id, text in TOOL_SEMANTIC_TEXT.items():
        assert text.strip(), tool_id
        assert len(text) <= TOOL_SEMANTIC_TEXT_MAX_CHARS, tool_id
        assert not text.startswith(("系统", "工具：")), tool_id
    assert TOOL_SEMANTIC_TEXT_MAX_CHARS == TOOL_DESCRIPTION_MAX_LENGTH == 120


def test_confirm_prompts_cover_confirming_tools_within_budget():
    by_id = definitions_by_id()
    confirming = {
        tool_id
        for tool_id, definition in by_id.items()
        if definition.permission.confirm != "never"
    }
    assert confirming == {NOTIFICATION_TOOL_ID, CHANNEL_TOOL_ID}
    assert set(TOOL_CONFIRM_PROMPTS) == confirming
    assert TOOL_CONFIRM_PROMPTS is CONFIRM_PROMPT_TEMPLATES
    for tool_id, template in TOOL_CONFIRM_PROMPTS.items():
        for text in (template.with_subject, template.without_subject):
            assert 0 < len(text) <= CONFIRM_PROMPT_MAX_CHARS, tool_id
            assert text.rstrip().endswith(("？", "吗？", "。")), tool_id


def test_memory_templates_cover_depositing_tools():
    by_id = definitions_by_id()
    depositing = {
        tool_id
        for tool_id, definition in by_id.items()
        if definition.memory_policy_key is not None
    }
    assert set(TOOL_MEMORY_TEMPLATES) == depositing


def test_observation_key_assets_are_shared_with_normalizer():
    from app.services.tool.normalizer import TOOL_OBSERVATION_MAP

    assert TOOL_OBSERVATION_MAP == TOOL_OBSERVATION_KEYS
    assert TOOL_OBSERVATION_MAP is not TOOL_OBSERVATION_KEYS
    for tool_id, mapping in TOOL_OBSERVATION_KEYS.items():
        assert observation_keys(tool_id) == mapping
        assert set(mapping.values()) == set(EXPECTED_OBSERVATIONS[tool_id])
        assert len(set(mapping.values())) == len(mapping), tool_id
    assert observation_keys("unknown.tool.id") == {}


def test_failure_texts_cover_degraded_tools_within_budget():
    assert set(TOOL_FAILURE_TEXT) == {SEARCH_TOOL_ID, CHANNEL_TOOL_ID, NOTIFICATION_TOOL_ID}
    for tool_id, text in TOOL_FAILURE_TEXT.items():
        assert 0 < len(text) <= TOOL_FAILURE_TEXT_MAX_CHARS, tool_id
    assert set(CHANNEL_FAILURE_TEXT) == {
        "not_found",
        "auth",
        "rate_limited",
        "timeout",
        "server_error",
        "client_error",
        "disabled",
        "invalid_request",
        "unknown",
    }


def test_confirm_lexicons_are_disjoint_and_usable():
    approve = set(CONFIRM_APPROVE_LEXICON)
    deny = set(CONFIRM_DENY_LEXICON)
    assert approve and deny
    assert not approve & deny
    assert {"好", "可以"} <= approve
    assert {"不用了", "别发"} <= deny


# --- E12｜文案超长在声明期被拒 ----------------------------------------------


def test_e12_over_budget_copy_is_rejected_at_registration():
    from tests.v24.tool002_support import raw_definition

    oversized = raw_definition(description="长" * (TOOL_SEMANTIC_TEXT_MAX_CHARS + 1))
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(oversized)
    assert "校验 7" in str(excinfo.value)


def test_over_budget_confirm_prompt_is_truncated_by_budget_guard():
    from app.services.tool.permission import build_confirm_prompt
    from tests.v24.tool005_support import invocation

    registry = builtin_registry()
    prompt = build_confirm_prompt(
        registry.get(CHANNEL_TOOL_ID),
        invocation(CHANNEL_TOOL_ID, {"content": "在吗", "recipient": "ou_asuna"}),
    )
    assert 0 < len(prompt) <= CONFIRM_PROMPT_MAX_CHARS


def test_e13_missing_template_parameter_falls_back_to_generic_prompt(monkeypatch):
    from app.character.asuna.tool import CONFIRM_PROMPT_FALLBACK, ConfirmPromptTemplate
    from app.services.tool import permission
    from app.services.tool.permission import build_confirm_prompt
    from tests.v24.tool005_support import invocation

    monkeypatch.setattr(
        permission,
        "CONFIRM_PROMPT_TEMPLATES",
        {"channel.feishu.send": ConfirmPromptTemplate("{ghost}", "{ghost}")},
    )
    prompt = build_confirm_prompt(
        builtin_registry().get(CHANNEL_TOOL_ID),
        invocation(CHANNEL_TOOL_ID, {"content": "在吗", "recipient": "ou_asuna"}),
    )
    assert prompt == CONFIRM_PROMPT_FALLBACK
    assert len(prompt) <= CONFIRM_PROMPT_MAX_CHARS


# --- E15｜漏加资产即被快照测试抓住 ------------------------------------------


def missing_asset_entries(registry: ToolRegistry) -> list[str]:
    """声明↔资产一致性：语义文案、观察键、确认话术、记忆模板四类逐工具核对。"""
    missing: list[str] = []
    for definition in registry.list():
        if definition.id not in TOOL_SEMANTIC_TEXT:
            missing.append(f"{definition.id}:semantic_text")
        if definition.id not in TOOL_OBSERVATION_KEYS:
            missing.append(f"{definition.id}:observation_keys")
        if definition.permission.confirm != "never" and definition.id not in TOOL_CONFIRM_PROMPTS:
            missing.append(f"{definition.id}:confirm_prompt")
        if definition.memory_policy_key is not None:
            template_key = definition.memory_policy_key
            if template_key not in TOOL_MEMORY_TEMPLATES:
                missing.append(f"{definition.id}:memory_template")
    return missing


def test_e15_all_declared_tools_have_complete_assets():
    assert missing_asset_entries(builtin_registry()) == []


def test_e15_missing_asset_entries_are_detected():
    from tests.v24.tool004_support import tool_definition

    registry = ToolRegistry()
    register_builtin_tools(registry)
    registry.register(tool_definition("builtin.experimental.tidy"))
    assert missing_asset_entries(registry) == [
        "builtin.experimental.tidy:semantic_text",
        "builtin.experimental.tidy:observation_keys",
    ]


def test_permission_profile_constructor_is_usable_for_channel():
    profile = PermissionProfile(level="sensitive", scope=("channel:feishu",), confirm="first_time")
    assert profile.confirm == "first_time"
