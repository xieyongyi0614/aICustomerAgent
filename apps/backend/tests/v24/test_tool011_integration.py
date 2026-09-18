"""TOOL-011 集成：总闸纪律、统一执行器（无旁路）、记忆硬纪律与 V9 零扰动。"""

import asyncio

import pytest

from app.core.settings import get_settings
from app.models.action import ActionIntent, ActionSchema, CapabilityResult
from app.models.tool import ToolInvocation
from app.services.action import registry as capability_registry_module
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import CapabilityRegistry, ExecutionContext
from app.services.tool import ext_api, user_defined
from app.services.tool.executor import ToolExecutor
from app.services.tool.memory_policy import ToolMemoryPolicy
from app.services.tool.permission import PermissionSnapshot, ToolPermissionGate
from app.services.tool.registry import ToolRegistry, get_tool_registry
from tests.v24.tool011_support import (
    NOW,
    USER_TOOL_ID,
    WEATHER_ENV,
    WEATHER_HOST,
    WEATHER_SECRET,
    WEATHER_TOOL_ID,
    capability,
    ext_context,
    ext_settings,
    load_manifests,
    response,
    user_declaration,
    weather_manifest,
)
from tests.v24.tool011_support import StubTransport


class ScriptedCapability:
    def __init__(self, name: str, actions: dict[str, list[str]], payload: dict) -> None:
        self.name = name
        self.description = "打桩能力"
        self.actions = {
            action: ActionSchema(required=list(required)) for action, required in actions.items()
        }
        self.calls: list[tuple[str, dict]] = []
        self._payload = payload

    def validate(self, action: str, params: dict) -> list[str]:
        return []

    async def execute(self, action: str, params: dict, ctx) -> CapabilityResult:
        self.calls.append((action, dict(params)))
        return CapabilityResult(status="succeeded", payload=dict(self._payload))


@pytest.fixture(autouse=True)
def _clean_singletons():
    capability_registry_module._registry = None
    ext_api.reset_external_api_state()
    user_defined.reset_user_tool_registrar()
    yield
    user_defined.reset_user_tool_registrar()
    ext_api.reset_external_api_state()
    capability_registry_module._registry = None
    get_settings.cache_clear()


def test_flag_off_keeps_v9_capability_registry_untouched():
    """AC：Flag 全 off → 外部能力不进全局注册表（V9 仍是六个能力）。"""
    registry = capability_registry_module.get_capability_registry()
    names = {entry["name"] for entry in registry.describe()}
    assert ext_api.EXT_API_CAPABILITY_NAME not in names
    assert "channel_feishu" not in names
    assert names == {
        "reminder",
        "memory",
        "world_action",
        "environment_query",
        "search",
        "notification",
    }


def test_flag_on_registers_external_capability(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_EXTERNAL_API_ENABLED=True)
    registry = capability_registry_module.get_capability_registry()
    assert ext_api.EXT_API_CAPABILITY_NAME in {entry["name"] for entry in registry.describe()}


def test_flag_off_means_no_tool_registry_and_no_manifests(tmp_path, monkeypatch):
    """AC：Flag 全 off 时清单不加载、ext.api.* 工具不存在、自定义注册拒绝。"""
    from tests.v24.tool011_support import write_manifest

    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    monkeypatch.setenv(WEATHER_ENV, WEATHER_SECRET)
    get_settings.cache_clear()

    assert ext_api.external_api_enabled(get_settings()) is False
    assert get_tool_registry() is None
    report = ext_api.get_manifest_loader().load(str(tmp_path))
    assert report.as_dict()["total"] == 0

    registrar = user_defined.get_user_tool_registrar()
    assert registrar.enabled() is False
    with pytest.raises(user_defined.UserToolRejected):
        registrar.register(user_declaration())
    assert registrar.list_registered() == []


def test_master_gate_alone_does_not_load_manifests(v24_tool_env, tmp_path):
    """总闸单开（外部面关）：清单不加载、能力不进注册表。"""
    from tests.v24.tool011_support import write_manifest

    v24_tool_env(
        TOOL_SYSTEM_ENABLED=True,
        TOOL_EXTERNAL_API_ENABLED=False,
        TOOL_EXT_ALLOWED_HOSTS=WEATHER_HOST,
        TOOL_EXT_MANIFEST_PATH=str(tmp_path),
        **{WEATHER_ENV: WEATHER_SECRET},
    )
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    capability_registry_module._registry = None

    assert ext_api.external_api_enabled(get_settings()) is False
    assert ext_api.EXT_API_CAPABILITY_NAME not in {
        entry["name"] for entry in capability_registry_module.get_capability_registry().describe()
    }
    tools = get_tool_registry()
    assert tools is not None
    assert [tool.id for tool in tools.list(namespace="ext.api")] == []


def test_ext_and_user_namespaces_never_deposit_memory():
    """AC：`ext.api.*` / `user.*` 记忆沉淀硬纪律生效（配置声明沉淀仍不沉淀）。"""
    from app.models.action import ActionRecord

    policy = ToolMemoryPolicy()
    for tool_id, namespace in (
        (WEATHER_TOOL_ID, "ext.api"),
        (USER_TOOL_ID, "user"),
    ):
        record = ActionRecord(
            id="rec-1",
            user_id="u1",
            action_type="query_environment",
            status="succeeded",
            params={"content": "今天很好"},
            steps=[{"tool_id": tool_id, "status": "succeeded"}],
        )
        definition = _read_only_definition(tool_id, namespace, policy_key="builtin.reminder.create")
        decision = policy.classify(record, definition)
        assert decision.deposit is False, tool_id
        assert decision.reason == "untrusted_source"


def _read_only_definition(tool_id: str, namespace: str, *, policy_key: str):
    from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema

    level = "dangerous" if namespace == "user" else "sensitive"
    return ToolDefinition(
        id=tool_id,
        name="外部工具",
        description="外部工具",
        namespace=namespace,
        capability="external_api",
        action="call",
        input_schema=ToolSchema(),
        permission=PermissionProfile(level=level, confirm="first_time"),
        side_effects=("write_memory",),
        memory_policy_key=policy_key,
    )


def test_ext_tool_runs_through_unified_executor(tmp_path):
    """AC：外部工具经统一执行器（权限 / 校验 / 超时 / 归一全部生效，无旁路）。"""
    settings = ext_settings(
        tool_permission_enabled=True,
        tool_schema_validation_enabled=True,
        tool_observation_enabled=True,
    )
    registry = ToolRegistry()
    index = ext_api.ManifestIndex()
    transport = StubTransport(response({"data": {"temperature": "9.5", "condition": "cloudy"}}))
    ext_capability = capability(index, transport, settings=settings)
    registry, index, report = load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=settings,
        environ={WEATHER_ENV: WEATHER_SECRET},
        registry=registry,
        index=index,
    )
    assert report.loaded == [WEATHER_TOOL_ID]

    capability_registry = CapabilityRegistry()
    capability_registry.register(ext_capability)
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, settings.action_execution_timeout_seconds),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    binding = registry.resolve(WEATHER_TOOL_ID)
    invocation = ToolInvocation(
        tool_id=WEATHER_TOOL_ID,
        params={"host": WEATHER_HOST, "city": "东京"},
        intent=ActionIntent(action_type="query_environment", confidence="confident"),
        dedupe_key="dk-ext",
    )
    result = asyncio.run(
        executor.run(
            binding,
            invocation,
            ext_context(settings),
            permission_snapshot=_snapshot(settings),
        )
    )

    assert result.status == "succeeded"
    assert result.permission["decision"] == "allow"
    assert result.validation is None
    assert result.duration_ms is not None
    observations = result.result["observations"]
    assert observations["weather.temperature"] == 9.5
    assert observations["weather.condition"] == "cloudy"
    assert observations["ext.untrusted"] is True
    assert result.result["status"] == "succeeded"
    assert transport.calls[0]["timeout"] == 5.0


def test_ext_tool_invalid_params_are_rejected_before_request(tmp_path):
    """校验闸在能力之前：声明外参数被拒 → `invalid`，不发起请求。"""
    settings = ext_settings(
        tool_permission_enabled=True,
        tool_schema_validation_enabled=True,
    )
    registry = ToolRegistry()
    index = ext_api.ManifestIndex()
    transport = StubTransport(response({"data": {}}))
    registry, index, _ = load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=settings,
        environ={WEATHER_ENV: WEATHER_SECRET},
        registry=registry,
        index=index,
    )
    capability_registry = CapabilityRegistry()
    capability_registry.register(capability(index, transport, settings=settings))
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, 10),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    result = asyncio.run(
        executor.run(
            registry.resolve(WEATHER_TOOL_ID),
            ToolInvocation(
                tool_id=WEATHER_TOOL_ID,
                params={"host": WEATHER_HOST, "city": "东京", "evil": "x"},
                intent=ActionIntent(action_type="query_environment", confidence="confident"),
            ),
            ext_context(settings),
            permission_snapshot=_snapshot(settings),
        )
    )
    assert result.status == "invalid"
    assert transport.called is False


def test_ext_tool_without_grant_waits_for_confirmation_and_never_calls(tmp_path):
    """未授权 → 首次确认（pending_confirmation），请求不发出（无旁路）。"""
    settings = ext_settings(tool_permission_enabled=True)
    registry = ToolRegistry()
    index = ext_api.ManifestIndex()
    transport = StubTransport(response({"data": {}}))
    registry, index, report = load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=settings,
        environ={WEATHER_ENV: WEATHER_SECRET},
        registry=registry,
        index=index,
    )
    capability_registry = CapabilityRegistry()
    capability_registry.register(capability(index, transport, settings=settings))
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, 10),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    invocation = ToolInvocation(
        tool_id=WEATHER_TOOL_ID,
        params={"host": WEATHER_HOST, "city": "东京"},
        intent=ActionIntent(action_type="query_environment", confidence="confident"),
    )
    result = asyncio.run(
        executor.run(
            registry.resolve(WEATHER_TOOL_ID),
            invocation,
            ext_context(settings),
            permission_snapshot=_snapshot(settings, grants=[]),
        )
    )

    assert result.status == "pending_confirmation"
    assert result.permission["decision"] == "confirm_required"
    assert transport.called is False


def test_user_tool_runs_through_unified_executor(tmp_path):
    """自定义工具同样经统一执行器：能力名 = tool_id，(capability, action) 唯一可解析。"""
    settings = ext_settings(
        tool_permission_enabled=True,
        tool_schema_validation_enabled=True,
        tool_observation_enabled=True,
    )
    registry = ToolRegistry()
    memory = ScriptedCapability("memory", {"save": ["fact"]}, {"memory_id": "mem-42"})
    capability_registry = CapabilityRegistry()
    capability_registry.register(memory)
    registrar = user_defined.UserToolRegistrar(
        registry,
        settings=settings,
        capability_registry=capability_registry,
        executor=CapabilityExecutor(capability_registry, 10),
    )
    registrar.register(user_declaration())

    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, 10),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    invocation = ToolInvocation(
        tool_id=USER_TOOL_ID,
        params={"content": "今天很好"},
        intent=ActionIntent(action_type="remember_fact", confidence="confident"),
        dedupe_key="dk-user",
    )
    result = asyncio.run(
        executor.run(
            registry.resolve(USER_TOOL_ID),
            invocation,
            ext_context(settings),
            permission_snapshot=_snapshot(settings),
        )
    )

    assert result.status == "succeeded"
    assert result.permission["decision"] == "allow"
    assert memory.calls == [("save", {"fact": "今天很好"})]
    assert result.result["observations"]["memory.id"] == "mem-42"


def test_user_tool_requires_grant_before_execution():
    settings = ext_settings(tool_permission_enabled=True)
    registry = ToolRegistry()
    memory = ScriptedCapability("memory", {"save": ["fact"]}, {"memory_id": "mem-1"})
    capability_registry = CapabilityRegistry()
    capability_registry.register(memory)
    registrar = user_defined.UserToolRegistrar(
        registry, settings=settings, capability_registry=capability_registry
    )
    registrar.register(user_declaration())
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, 10),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    invocation = ToolInvocation(
        tool_id=USER_TOOL_ID,
        params={"content": "x"},
        intent=ActionIntent(action_type="remember_fact", confidence="confident"),
    )
    result = asyncio.run(
        executor.run(
            registry.resolve(USER_TOOL_ID),
            invocation,
            ext_context(settings),
            permission_snapshot=_snapshot(settings, grants=[]),
        )
    )
    assert result.status == "denied"
    assert memory.calls == []


def test_unregistered_user_tool_is_unavailable_through_executor():
    settings = ext_settings(tool_permission_enabled=True)
    registry = ToolRegistry()
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        ScriptedCapability("memory", {"save": ["fact"]}, {"memory_id": "mem-1"})
    )
    registrar = user_defined.UserToolRegistrar(
        registry, settings=settings, capability_registry=capability_registry
    )
    registrar.register(user_declaration())
    binding = registry.resolve(USER_TOOL_ID)
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(capability_registry, 10),
        settings=settings,
        permission_gate=ToolPermissionGate(settings),
    )
    registrar.unregister(USER_TOOL_ID)
    result = asyncio.run(
        executor.run(
            binding,
            ToolInvocation(
                tool_id=USER_TOOL_ID,
                params={"content": "x"},
                intent=ActionIntent(action_type="remember_fact", confidence="confident"),
            ),
            ext_context(settings),
            permission_snapshot=_snapshot(settings),
        )
    )
    assert result.status == "unavailable"
    assert result.result["failure_kind"] == "unavailable"


def test_execution_context_is_the_v9_surface(tmp_path):
    """能力实现体拿到的仍是 V9 `ExecutionContext`（形状未变）。"""
    settings = ext_settings()
    index = ext_api.ManifestIndex()
    load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=settings,
        environ={WEATHER_ENV: WEATHER_SECRET},
        index=index,
    )
    transport = StubTransport(response({"data": {}}))
    cap = capability(index, transport, settings=settings)
    ctx = ExecutionContext(user_id="u1", now=NOW, settings=settings, dedupe_key="dk")
    result = asyncio.run(cap.execute("call", {"host": WEATHER_HOST, "city": "东京"}, ctx))
    assert result.status == "succeeded"
    assert transport.calls[0]["method"] == "GET"


def _snapshot(settings, grants: list[dict] | None = None) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id="u-tool011",
        now=NOW,
        grants=(
            [{"tool_id": "*", "scope": ["*"], "source": "user_confirm", "expires_at": None}]
            if grants is None
            else grants
        ),
        settings=settings,
        namespace_floors={
            "builtin": "normal",
            "world": "normal",
            "channel": "sensitive",
            "ext.api": "sensitive",
            "user": "dangerous",
        },
    )
