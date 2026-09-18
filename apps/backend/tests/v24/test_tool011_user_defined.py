"""TOOL-011 自定义工具注册（§2.2、§2.3、§4.3、§6.1、§6.3 E10~E14）。"""

import asyncio

import pytest

from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import CapabilityRegistry
from app.services.tool import user_defined
from app.services.tool.dsl import ALLOWED_ACTIONS
from app.services.tool.registry import ToolRegistry
from tests.v24.tool011_support import (
    USER_TOOL_ID,
    ext_settings,
    user_declaration,
)


class ScriptedCapability:
    """打桩能力：记录调用，按脚本返回（默认成功）。"""

    def __init__(self, name: str, actions: dict[str, list[str]], *results) -> None:
        self.name = name
        self.description = "打桩能力"
        self.actions = {
            action: ActionSchema(required=list(required))
            for action, required in actions.items()
        }
        self.calls: list[tuple[str, dict]] = []
        self._results = list(results)

    def validate(self, action: str, params: dict) -> list[str]:
        return []

    async def execute(self, action: str, params: dict, ctx) -> CapabilityResult:
        self.calls.append((action, dict(params)))
        if self._results:
            return self._results.pop(0)
        return CapabilityResult(status="succeeded", payload={"memory_id": "mem-1"})


def _registrar(**overrides) -> user_defined.UserToolRegistrar:
    values = {
        "registry": ToolRegistry(),
        "settings": ext_settings(),
        "capability_registry": CapabilityRegistry(),
    }
    values.update(overrides)
    return user_defined.UserToolRegistrar(**values)


def _full_registry(*capabilities) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability in capabilities:
        registry.register(capability)
    return registry


def test_register_returns_tool_id_and_applies_forced_disciplines():
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)

    tool_id = registrar.register(user_declaration())

    assert tool_id == USER_TOOL_ID
    assert registrar.list_registered() == [USER_TOOL_ID]
    definition = registrar.tool_registry().get(USER_TOOL_ID)
    assert definition is not None
    assert definition.namespace == "user"
    assert definition.capability == USER_TOOL_ID
    assert definition.action == "run"
    assert definition.permission.level == "dangerous"
    assert definition.permission.confirm == "first_time"
    assert definition.permission.audit is True
    assert definition.memory_policy_key == USER_TOOL_ID
    assert definition.side_effects == ("write_memory",)
    assert capability_registry.has(USER_TOOL_ID, "run")


def test_register_requires_both_gates():
    """AC：注册需双闸；Flag 全 off 时注册拒绝。"""
    for envs in (
        {"tool_system_enabled": False, "tool_user_defined_enabled": False},
        {"tool_system_enabled": False, "tool_user_defined_enabled": True},
        {"tool_system_enabled": True, "tool_user_defined_enabled": False},
    ):
        registrar = _registrar(settings=ext_settings(**envs))
        report = registrar.validate(user_declaration())
        assert report.passed is False
        assert report.errors == [user_defined.GATE_DISABLED_REASON]
        with pytest.raises(user_defined.UserToolRejected):
            registrar.register(user_declaration())
        assert registrar.list_registered() == []
        assert registrar.tool_registry().list() == []


def test_register_without_tool_registry_is_rejected():
    """总闸 on 但工具注册表不可用（单例未构建）→ 注册拒绝且不留痕。"""
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = user_defined.UserToolRegistrar(
        None, settings=ext_settings(), capability_registry=capability_registry
    )
    assert registrar.tool_registry() is None
    with pytest.raises(user_defined.UserToolRejected) as error:
        registrar.register(user_declaration())
    assert error.value.errors == [user_defined.GATE_DISABLED_REASON]
    assert capability_registry.has(USER_TOOL_ID) is False


def test_declaration_cannot_weaken_permission_or_side_effects():
    """强制纪律：声明不得携带 permission/level（等级恒 dangerous，不可降级）。"""
    registrar = _registrar()
    for key, value in (("permission", {"level": "normal"}), ("level", "safe")):
        declaration = {**user_declaration(), key: value}
        report = registrar.validate(declaration)
        assert report.passed is False
        assert any("未允许字段" in error for error in report.errors)


def test_e11_derived_side_effects_override_declared_read_only():
    """E11：声明只读但步骤含写动作 → 推导覆盖声明，按写类处理。"""
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    declaration = user_declaration(side_effects=["read"])

    registrar.register(declaration)

    definition = registrar.tool_registry().get(USER_TOOL_ID)
    assert definition.side_effects == ("write_memory",)
    assert definition.is_read_only() is False
    view = registrar.view(USER_TOOL_ID)
    assert view["side_effects"] == ["write_memory"]
    assert view["declared_side_effects"] == ["read"]
    assert view["side_effects_derived"] is True
    assert view["level"] == "dangerous"
    assert view["memory_deposit"] is False


def test_read_only_user_tool_derives_read_only():
    capability_registry = _full_registry(ScriptedCapability("search", {"query": ["query"]}))
    registrar = _registrar(capability_registry=capability_registry)
    declaration = user_declaration(
        steps=[
            {
                "capability": "search",
                "action": "query",
                "params_map": {"query": "{params.query}"},
            }
        ],
        input_schema={"parameters": [{"name": "query", "required": True}]},
        side_effects=["read", "irreversible"],
    )
    registrar.register(declaration)
    assert registrar.tool_registry().get(USER_TOOL_ID).side_effects == ("read",)
    assert registrar.tool_registry().get(USER_TOOL_ID).is_irreversible() is False


def test_e12_unknown_capability_is_rejected():
    """E12：引用不存在的 capability → 校验拒绝、不注册、不留痕。"""
    registrar = _registrar()  # 空能力注册表：所有步骤都解析不到
    report = registrar.validate(user_declaration())
    assert report.passed is False
    assert any("不存在的 capability" in error for error in report.errors)
    with pytest.raises(user_defined.UserToolRejected):
        registrar.register(user_declaration())
    assert registrar.tool_registry().get(USER_TOOL_ID) is None
    assert registrar.capability_registry().has(USER_TOOL_ID) is False


@pytest.mark.parametrize(
    "steps",
    [
        [{"capability": "http", "action": "get", "params_map": {"url": "{params.url}"}}],
        [{"capability": "fs", "action": "read_file", "params_map": {"path": "/etc/passwd"}}],
        [{"capability": "memory", "action": "save", "code": "print(1)"}],
        [{"capability": "memory", "action": "save"}] * 4,
        [{"capability": "memory", "action": "read"}],
    ],
)
def test_e10_dsl_negative_cases_are_all_rejected(steps):
    """E10：HTTP 直连 / 文件访问 / 任意代码 / 超 3 步 / 越白名单 → 全拒、不留痕。"""
    registrar = _registrar()
    declaration = user_declaration(steps=steps)
    report = registrar.validate(declaration)
    assert report.passed is False
    assert report.errors
    with pytest.raises(user_defined.UserToolRejected):
        registrar.register(declaration)
    assert registrar.list_registered() == []
    assert registrar.tool_registry().list() == []


def test_placeholder_must_be_declared_in_input_schema():
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    declaration = user_declaration(input_schema={"parameters": [{"name": "other"}]})
    report = registrar.validate(declaration)
    assert report.passed is False
    assert any("未在 input_schema 声明" in error for error in report.errors)


def test_input_schema_is_derived_when_absent():
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    declaration = user_declaration()
    declaration.pop("input_schema")
    registrar.register(declaration)
    parameters = registrar.tool_registry().get(USER_TOOL_ID).input_schema.parameters
    assert [(parameter.name, parameter.required) for parameter in parameters] == [
        ("content", True)
    ]


def test_name_and_description_budgets():
    registrar = _registrar()
    assert registrar.validate(user_declaration(name="名" * 21)).passed is False
    assert registrar.validate(user_declaration(description="描" * 121)).passed is False


def test_tool_id_must_use_user_prefix():
    registrar = _registrar()
    for tool_id in ("builtin.mood.append", "mood", "user.Bad-Name"):
        assert registrar.validate(user_declaration(tool_id=tool_id)).passed is False


def test_duplicate_registration_is_rejected():
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    registrar.register(user_declaration())
    with pytest.raises(user_defined.UserToolRejected):
        registrar.register(user_declaration())
    assert registrar.list_registered() == [USER_TOOL_ID]


def test_rejection_leaves_no_trace_even_when_registry_write_fails():
    """失败即拒绝且不留痕：能力注册成功而工具注册失败时回滚能力。"""
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    tool_registry = registrar.tool_registry()
    assert tool_registry is not None
    original = tool_registry.register

    def _boom(*args, **kwargs):
        raise ValueError("注册表拒绝")

    tool_registry.register = _boom
    with pytest.raises(user_defined.UserToolRejected):
        registrar.register(user_declaration())
    tool_registry.register = original

    assert registrar.list_registered() == []
    assert capability_registry.has(USER_TOOL_ID) is False


def test_capability_name_collision_is_rejected():
    capability_registry = _full_registry(
        ScriptedCapability("memory", {"save": ["fact"]}),
        ScriptedCapability(USER_TOOL_ID, {"run": []}),
    )
    registrar = _registrar(capability_registry=capability_registry)
    with pytest.raises(user_defined.UserToolRejected) as error:
        registrar.register(user_declaration())
    assert "能力名已被占用" in str(error.value)
    assert registrar.list_registered() == []


def test_e13_registration_is_process_memory_only(tmp_path):
    """E13：注册是运行期内存态，重启（新注册表 + 新注册面）即丢失，需重新注册。"""
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    registrar.register(user_declaration())
    assert registrar.list_registered() == [USER_TOOL_ID]

    restarted = _registrar()
    assert restarted.list_registered() == []
    assert restarted.tool_registry().get(USER_TOOL_ID) is None


def test_e14_unregistered_tool_is_unavailable_and_idempotent():
    capability_registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=capability_registry)
    registrar.register(user_declaration())

    registrar.unregister(USER_TOOL_ID)

    assert registrar.list_registered() == []
    assert registrar.tool_registry().get(USER_TOOL_ID) is None
    assert capability_registry.has(USER_TOOL_ID) is False
    registrar.unregister(USER_TOOL_ID)
    registrar.unregister("user.never.registered")
    assert registrar.view(USER_TOOL_ID) is None


def test_composite_execution_runs_steps_in_order_and_aggregates():
    memory = ScriptedCapability("memory", {"save": ["fact"]})
    registry = _full_registry(memory)
    registrar = _registrar(capability_registry=registry)
    registrar.register(user_declaration())

    capability = registry.get(USER_TOOL_ID)
    result = asyncio.run(
        capability.execute("run", {"content": "今天很好"}, _execution_context())
    )

    assert result.status == "succeeded"
    assert memory.calls == [("save", {"fact": "今天很好"})]
    assert result.payload["memory_id"] == "mem-1"
    assert result.payload["step_count"] == 1
    assert result.payload["failure_kind"] is None


def test_composite_short_circuits_on_first_failure():
    failing = ScriptedCapability(
        "memory",
        {"save": ["fact"]},
        CapabilityResult(status="failed", payload={"failure_kind": "transient"}, error="boom"),
    )
    registry = _full_registry(failing)
    registrar = _registrar(capability_registry=registry)
    declaration = user_declaration(
        steps=[
            {"capability": "memory", "action": "save", "params_map": {"fact": "{params.content}"}},
            {"capability": "memory", "action": "save", "params_map": {"fact": "second"}},
        ]
    )
    registrar.register(declaration)

    result = asyncio.run(
        registry.get(USER_TOOL_ID).execute("run", {"content": "x"}, _execution_context())
    )

    assert result.status == "failed"
    assert result.payload["failure_kind"] == "transient"
    assert result.payload["retryable"] is True
    assert result.payload["failed_step"] == 0
    assert len(failing.calls) == 1, "第一步失败即短路"


def test_composite_reports_timeout_status():
    failing = ScriptedCapability(
        "memory",
        {"save": ["fact"]},
        CapabilityResult(status="timeout", payload={"failure_kind": "timeout"}, error="slow"),
    )
    registry = _full_registry(failing)
    registrar = _registrar(capability_registry=registry)
    registrar.register(user_declaration())
    result = asyncio.run(
        registry.get(USER_TOOL_ID).execute("run", {"content": "x"}, _execution_context())
    )
    assert result.status == "timeout"
    assert result.payload["failure_kind"] == "timeout"


def test_composite_is_unavailable_when_gate_off():
    registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    capability = user_defined.UserToolCapability(
        USER_TOOL_ID,
        "记录心情",
        ({"capability": "memory", "action": "save"},),
        (),
        settings=ext_settings(tool_user_defined_enabled=False),
        capability_registry=registry,
    )
    result = asyncio.run(capability.execute("run", {}, _execution_context()))
    assert result.status == "unavailable"
    assert result.payload["failure_kind"] == "unavailable"


def test_composite_unknown_action_is_permanent():
    registry = _full_registry(ScriptedCapability("memory", {"save": ["fact"]}))
    registrar = _registrar(capability_registry=registry)
    registrar.register(user_declaration())
    result = asyncio.run(
        registry.get(USER_TOOL_ID).execute("ghost", {}, _execution_context())
    )
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "permanent"


def test_allowed_actions_are_shared_with_dsl():
    assert user_defined.USER_NAMESPACE == "user"
    assert user_defined.USER_TOOL_ACTION == "run"
    assert ("memory", "save") in ALLOWED_ACTIONS


def _execution_context():
    from app.services.action.registry import ExecutionContext

    return ExecutionContext(
        user_id="u-tool011", now=None, settings=ext_settings(), dedupe_key="dk"
    )
