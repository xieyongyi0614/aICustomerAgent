"""TOOL-010 §6.1/§6.2：≥9 工具 × 成功/校验失败/权限拒绝 端到端矩阵、四步流程与零 diff。

三类路径都走真实 `ToolExecutor` 五段链路（resolve → permission → validate → invoke →
normalize）：成功路径的实现体对 4 个 V9 能力用打桩（V9 实现语义由 `tests/unit` 与
`tests/v9` 覆盖），对 TOOL-010 的三个能力（`search` / `notification` / `channel_feishu`）
用**真实实现体**——它们的"成功"语义正是本任务的交付物。
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.channels.base import SendResult
from app.models.action import ActionIntent
from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema
from app.services.action.capabilities.notification import NotificationCapability
from app.services.action.capabilities.search import SearchCapability
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import CapabilityRegistry, get_capability_registry
from app.services.tool import channel_tools
from app.services.tool.channel_tools import CHANNEL_SCOPE, ChannelCapability
from app.services.tool.executor import ToolExecutor
from app.services.tool.permission import ToolPermissionGate
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import ToolSurfaceResolver, ToolSelector
from app.models.tool import ToolInvocation
from tests.v24.tool004_support import surface_context
from tests.v24.tool005_support import grant, snapshot
from tests.v24.tool010_support import (
    CAPABILITY_ACTIONS,
    CHANNEL_ENVS,
    CHANNEL_TOOL_ID,
    EXPECTED_OBSERVATIONS,
    INVALID_PARAMS,
    MATRIX_TOOL_IDS,
    NOTIFICATION_TOOL_ID,
    VALID_PARAMS,
    SEARCH_TOOL_ID,
    USER,
    RecordingAdapter,
    ScriptedCapability,
    builtin_registry,
    enable,
    reset_runtime_state,
    tool_context,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

SCRIPTED_CAPABILITIES: tuple[str, ...] = (
    "reminder",
    "memory",
    "world_action",
    "environment_query",
)

MATRIX_OBSERVATIONS: dict[str, dict] = {
    **EXPECTED_OBSERVATIONS,
    SEARCH_TOOL_ID: {"search.result_count": 0, "search.untrusted": True},
}


def _expected_success_status(tool_id: str) -> str:
    """路线 B：检索工具的可判定结果就是 `unavailable`（不是 succeeded）。"""
    return "unavailable" if tool_id == SEARCH_TOOL_ID else "succeeded"


CRLF = b"\r\n"
LF = b"\n"

ZERO_DIFF_HASHES: dict[str, str] = {
    "app/channels/base.py": "f992542b7585468c09f169a16d1f6d4aab36639eb35ae840936b201402359617",
    "app/channels/feishu/outbound.py": "50aa5f198d1793195ba32634e6d25e67fd21f160821957f96c4e5d78b1b800ac",
    "app/channels/feishu/client.py": "5f9fe0dadc8a5fa49a945f611d68600f3dc15d07e65d3d2463384a6f036bff7e",
    "app/channels/feishu/delivery.py": "4b16ad9e5e57694b4f2d8ff57029981a36cfa48efd9475870dfc2766110b493c",
    "app/services/action/capabilities/reminder.py": "df820840262c7d00c229e29cb412ceebf71011e2e72356ded51efbf0accd8062",
    "app/services/action/capabilities/memory.py": "b8ceddddc47c1c857e35cbbe5c266de45cffe28bb5aa74903793ad6dbf7284a2",
    "app/services/action/capabilities/world_action.py": "10c0ef114fdd32b2fc6ad44354127cea19e501be3b15c5fb6c211c44a86c4cb0",
    "app/services/action/capabilities/environment_query.py": "d83e44ad9ba4341c42c8027915ab395bc9a7fe1bfd03f01e59e6884a252ce41d",
    "app/character/asuna/action.py": "86d8080c29b29c2f2a88c6b804ac4b4500b4d8b75d92b8557cf8bb17425b6a8d",
    "app/services/action/planner.py": "3efc790a9cbde441885a1ae789bb0af844d2e12ec75fd35304f1b959240013cd",
    "app/services/decision_pipeline.py": "2ac6b51e501bd127fab008ea985beb5fe5cfa0167485b0ae64daeb00c2daf757",
    "app/application/chat_pipeline.py": "da4ac2ccfb6c7923ac62a683e7a1452297c2d27dc619cf8c37b3ed4d07b34bc7",
    "app/application/post_process.py": "9ad19a529e0ce662ad8ad36602a2de5346a3f1ebc983159a8c8ed8c2108f6e7e",
    "app/application/action_engine.py": "2529395ca3eb97b36ce9b9a520ef0f8449ae760344dd6d1aa7ab55d4f5e92f4c",
    "app/prompts/builder.py": "d1a98f6887735b34c935896b00cf5d94d2bd36e41a8c433620ced649c678c826",
}
"""整文件零 diff 冻结面。

`app/application/autonomy_engine.py` 已从本表撤下（P2-3 合法新增降级计数器与访问器），
改由 `test_autonomy_engine_has_no_channel_tool_coupling` 做语义级断言——冻结整文件哈希会把
正常演进判成违规。
"""


def test_autonomy_engine_has_no_channel_tool_coupling():
    """TOOL-010 的真实关切：新通道工具没有把自治管线改脏（语义替代整文件哈希）。"""
    from app.application import autonomy_engine

    source = (BACKEND_ROOT / "app/application/autonomy_engine.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "channel.feishu",
        "channel_feishu",
        "ChannelCapability",
        "app.channels",
        "OutboundMessage",
    ):
        assert forbidden not in source
    for name in (
        "tick",
        "resolve_autonomy_surface",
        "collect_tool_facts",
        "_resolve_tick_capabilities",
        "_autonomy_binding",
    ):
        assert callable(getattr(autonomy_engine, name))


TOOL_ADDITION_STEPS: tuple[str, ...] = (
    "① 声明：`tool/builtin.py` 加一条 ToolDefinition（schema / permission / side_effects / 记忆键）",
    "② 实现：复用既有 Capability（新增实现体时才写一行）",
    "③ 注册：`register_builtin_tools` 加一行（声明全集逐条注册）",
    "④ 资产：`asuna/tool.py` 加语义文案 / 观察键 / 记忆模板",
)


@pytest.fixture(autouse=True)
def _isolate_singletons(monkeypatch):
    enable(monkeypatch, **CHANNEL_ENVS)
    reset_runtime_state()
    yield
    reset_runtime_state()


def _settings(**overrides):
    values = {
        "v24_tool_system_enabled": True,
        "v24_tool_permission_enabled": True,
        "v24_tool_schema_validation_enabled": True,
        "v24_tool_observation_enabled": True,
        "v24_tool_channel_enabled": True,
        "feishu_enabled": True,
        "v24_tool_confirm_timeout_hours": 24,
        "v24_tool_confirm_ttl_reuse": True,
        "v24_tool_ext_allowed_hosts": "",
        "v24_tool_breaker_threshold": 3,
        "v24_tool_breaker_cooldown_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _capability_registry(adapter: RecordingAdapter) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for name in SCRIPTED_CAPABILITIES:
        registry.register(ScriptedCapability(name, CAPABILITY_ACTIONS[name]))
    registry.register(SearchCapability())
    registry.register(NotificationCapability())
    registry.register(ChannelCapability(adapter=adapter))
    return registry


class _SnapshotlessGate:
    """权限快照不可得（E1）：一切调用保守拒绝——每个工具都有的"权限拒绝"路径。"""

    def __init__(self, settings) -> None:
        self._settings = settings

    def build_snapshot(self, *args, **kwargs):
        return None

    def evaluate(self, definition, invocation, snapshot):
        return ToolPermissionGate(self._settings).evaluate(definition, invocation, snapshot)


def _executor(gate=None, adapter: RecordingAdapter | None = None) -> ToolExecutor:
    settings = _settings()
    real_adapter = adapter if adapter is not None else RecordingAdapter()
    return ToolExecutor(
        builtin_registry(),
        CapabilityExecutor(_capability_registry(real_adapter), 2.0),
        settings=settings,
        permission_gate=gate if gate is not None else ToolPermissionGate(settings),
    )


def _grants():
    return [
        grant(NOTIFICATION_TOOL_ID, ("self",)),
        grant(CHANNEL_TOOL_ID, (CHANNEL_SCOPE,)),
    ]


def _invocation(tool_id: str, params: dict) -> ToolInvocation:
    return ToolInvocation(
        tool_id=tool_id,
        params=dict(params),
        rationale="TOOL-010 矩阵",
        source="conversation",
        intent=ActionIntent(action_type="send_notification", confidence="confident", params={}),
        dedupe_key=f"dk-{tool_id}",
    )


def _ctx(tool_id: str):
    return tool_context(_settings(), dedupe_key=f"dk-{tool_id}")


# --- 成功路径 ---------------------------------------------------------------


@pytest.mark.parametrize("tool_id", MATRIX_TOOL_IDS, ids=lambda value: value)
async def test_matrix_success_path(tool_id):
    registry = builtin_registry()
    adapter = RecordingAdapter(SendResult(ok=True, external_message_id="om-1"))
    executor = _executor(adapter=adapter)
    execution = await executor.run(
        registry.resolve(tool_id),
        _invocation(tool_id, VALID_PARAMS[tool_id]),
        _ctx(tool_id),
        permission_snapshot=snapshot(grants=_grants(), settings=_settings()),
    )
    assert execution.status == _expected_success_status(tool_id), execution.result
    assert execution.tool_id == tool_id
    assert execution.result["observations"] == MATRIX_OBSERVATIONS[tool_id]
    assert execution.permission["decision"] == "allow"


# --- 校验失败路径（invalid） -------------------------------------------------


@pytest.mark.parametrize("tool_id", MATRIX_TOOL_IDS, ids=lambda value: value)
async def test_matrix_invalid_path(tool_id):
    params, expected_code = INVALID_PARAMS[tool_id]
    adapter = RecordingAdapter()
    executor = _executor(adapter=adapter)
    execution = await executor.run(
        builtin_registry().resolve(tool_id),
        _invocation(tool_id, params),
        _ctx(tool_id),
        permission_snapshot=snapshot(grants=_grants(), settings=_settings()),
    )
    assert execution.status == "invalid"
    assert execution.validation is not None
    issues = execution.validation["structural"] + execution.validation["semantic"]
    assert expected_code in {issue["code"] for issue in issues}, issues
    assert execution.result["failure_kind"] == "invalid"
    assert adapter.messages == []


# --- 权限拒绝路径（denied） --------------------------------------------------


@pytest.mark.parametrize("tool_id", MATRIX_TOOL_IDS, ids=lambda value: value)
async def test_matrix_denied_path_when_snapshot_is_unavailable(tool_id):
    adapter = RecordingAdapter()
    executor = _executor(gate=_SnapshotlessGate(_settings()), adapter=adapter)
    execution = await executor.run(
        builtin_registry().resolve(tool_id), _invocation(tool_id, {}), _ctx(tool_id)
    )
    assert execution.status == "denied"
    assert execution.permission["decision"] == "deny"
    assert execution.permission["reason"] == "snapshot_unavailable"
    assert execution.result["failure_kind"] == "denied"
    assert adapter.messages == []


@pytest.mark.parametrize("tool_id", (NOTIFICATION_TOOL_ID, CHANNEL_TOOL_ID))
async def test_matrix_denied_path_for_sensitive_tools_out_of_scope(tool_id):
    adapter = RecordingAdapter()
    executor = _executor(adapter=adapter)
    definition = builtin_registry().get(tool_id)
    execution = await executor.run(
        builtin_registry().resolve(tool_id),
        _invocation(tool_id, {}),
        _ctx(tool_id),
        permission_snapshot=snapshot(
            grants=[grant(tool_id, ("unrelated.scope",))], settings=_settings()
        ),
    )
    assert execution.status == "denied"
    assert execution.permission["reason"] == "out_of_scope"
    assert execution.permission["level"] == "sensitive"
    assert definition.permission.level == "sensitive"
    assert adapter.messages == []


# --- describe / resolve 全量 -------------------------------------------------


def test_every_declared_tool_is_describable_and_resolvable():
    registry = builtin_registry()
    described = {item.tool_id for item in registry.describe()}
    assert described == set(MATRIX_TOOL_IDS)
    assert len(described) >= 9
    for tool_id in MATRIX_TOOL_IDS:
        binding = registry.resolve(tool_id)
        assert binding is not None
        assert binding.tool_id == tool_id
        assert registry.get(tool_id).input_schema.parameters


# --- §6.2 零 diff 断言 ------------------------------------------------------


def _file_digest(relative_path: str) -> str:
    """行尾归一（LF）后的 sha256：抵消 CRLF 检出带来的假失败（P2-4）。"""
    data = (BACKEND_ROOT / relative_path).read_bytes().replace(CRLF, LF)
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("relative_path", sorted(ZERO_DIFF_HASHES), ids=lambda value: value)
def test_zero_diff_frozen_surfaces(relative_path):
    assert _file_digest(relative_path) == ZERO_DIFF_HASHES[relative_path], (
        f"{relative_path} 被 TOOL-010 改动"
    )


def test_existing_channel_split_and_contract_modules_untouched():
    for relative_path in (
        "app/channels/base.py",
        "app/channels/feishu/outbound.py",
        "app/channels/feishu/client.py",
        "app/channels/feishu/delivery.py",
    ):
        assert relative_path in ZERO_DIFF_HASHES


def test_pipelines_are_not_touched_by_the_new_tool():
    """管线整文件零 diff：`autonomy_engine.py` 由语义断言接手（P2-3 的合法演进）。"""
    for relative_path in (
        "app/services/action/planner.py",
        "app/services/decision_pipeline.py",
        "app/application/chat_pipeline.py",
        "app/application/post_process.py",
        "app/application/action_engine.py",
        "app/prompts/builder.py",
    ):
        assert relative_path in ZERO_DIFF_HASHES
    assert "app/application/autonomy_engine.py" not in ZERO_DIFF_HASHES


# --- 四步流程实操（≤ 4 步、不改管线） ----------------------------------------


async def test_four_step_tool_addition_keeps_pipelines_untouched():
    """§6.2：新增工具 = 声明 + 复用实现 + 注册 + 资产（4 步），**不改任何管线**。"""
    from tests.v24.tool002_support import parameter

    assert len(TOOL_ADDITION_STEPS) <= 4

    declaration = ToolDefinition(
        id="world.obj.tidy",
        name="整理物品",
        description="把一件已存在的物品收进目标地点，复用既有世界动作能力。",
        namespace="world",
        capability="world_action",
        action="move",
        input_schema=ToolSchema(
            parameters=[
                parameter("object", required=True, description="物品名称"),
                parameter("location", required=True, description="目标地点"),
            ]
        ),
        permission=PermissionProfile(level="normal", scope=("world",)),
        side_effects=("write_world",),
        idempotency="keyed",
        priority=200,
        tags=("world", "object"),
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    registry.register(declaration)

    assert declaration.id in [item.tool_id for item in registry.describe()]
    assert registry.resolve("world.obj.tidy").action == "move"

    surface = ToolSurfaceResolver(registry, _settings()).resolve(
        "foreground_chat", surface_context(settings=_settings())
    )
    assert "world.obj.tidy" in surface.tool_ids
    assert (
        ToolSelector(registry)
        .select(
            ActionIntent(action_type="move_object", confidence="confident", params={}), surface
        )
        .tool_id
        == "world.object.move"
    )

    adapter = RecordingAdapter()
    executor = ToolExecutor(
        registry,
        CapabilityExecutor(_capability_registry(adapter), 2.0),
        settings=_settings(),
        permission_gate=ToolPermissionGate(_settings()),
    )
    execution = await executor.run(
        registry.resolve("world.obj.tidy"),
        _invocation("world.obj.tidy", {"object": "苹果", "location": "home.kitchen"}),
        _ctx("world.obj.tidy"),
    )
    assert execution.status == "succeeded"
    # 观察键属第④步资产：示例工具未登记资产时 observations 为空（这正是 E15 要抓的漏项），
    # 而执行链路本身无需任何管线改动。
    assert execution.result["observations"] == {}
    assert MATRIX_OBSERVATIONS["world.object.move"] != execution.result["observations"]

    for relative_path in ZERO_DIFF_HASHES:
        assert _file_digest(relative_path) == ZERO_DIFF_HASHES[relative_path]


# --- Flag 全 off：既有路径零变化 -------------------------------------------


def test_flag_off_tool_registry_is_absent(monkeypatch):
    from app.services.tool.registry import get_tool_registry

    enable(monkeypatch, v24_tool_system_enabled=False, v24_tool_channel_enabled=False)
    reset_runtime_state()
    assert get_tool_registry() is None


def test_flag_off_capability_registry_is_six_v9_capabilities(monkeypatch):
    enable(monkeypatch, v24_tool_system_enabled=False, v24_tool_channel_enabled=False)
    reset_runtime_state()
    names = {entry["name"] for entry in get_capability_registry().describe()}
    assert names == {
        "reminder",
        "memory",
        "world_action",
        "environment_query",
        "search",
        "notification",
    }


async def test_flag_off_capabilities_keep_v9_unavailable_shape(monkeypatch):
    enable(monkeypatch, v24_tool_system_enabled=False, v24_tool_channel_enabled=False)
    reset_runtime_state()
    from app.services.action.registry import ExecutionContext

    ctx = ExecutionContext(user_id=USER, record_id="act-tool010")
    search = await SearchCapability().execute("query", {"query": "天气"}, ctx)
    notification = await NotificationCapability().execute("send", {"content": "喝水"}, ctx)
    assert search.status == notification.status == "unavailable"
    assert search.payload == {"failure_kind": "unavailable"}
    assert notification.payload == {"failure_kind": "unavailable"}


def test_channel_adapter_port_unregistered_in_default_deployment(monkeypatch):
    enable(monkeypatch, v24_tool_system_enabled=False, v24_tool_channel_enabled=False)
    reset_runtime_state()
    assert channel_tools.get_channel_adapter() is None
    registry = builtin_registry()
    assert registry.effective_status(CHANNEL_TOOL_ID) == "disabled"
