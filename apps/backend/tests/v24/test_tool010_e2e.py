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
    "ledger",
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
    "app/channels/feishu/delivery.py": "b82457b2f04ac0a6cbad31ca3121bfd48fa1f5607a7dfe7473c4c9679140b390",
    "app/services/action/capabilities/reminder.py": "d6cd1bc27a698b107a02e534c7bb3e1afe48d1cb1f887f8e21e39d4b84ebd954",
    "app/services/action/capabilities/memory.py": "b8ceddddc47c1c857e35cbbe5c266de45cffe28bb5aa74903793ad6dbf7284a2",
    "app/services/action/capabilities/world_action.py": "345912ee8452d4d03c572e5e734f3b5900223be15a80524c1a6386bbffd40048",
    "app/services/action/capabilities/environment_query.py": "d83e44ad9ba4341c42c8027915ab395bc9a7fe1bfd03f01e59e6884a252ce41d",
    "app/character/asuna/action.py": "2da514d98fedbcc72257949e524684666899e3f20e71934218df118e3599f8f5",
    "app/services/action/planner.py": "41288337f0fc712dd64db0d52d90f7f13abbc0dd934fba6bb78c1d6398bedc99",
    "app/services/decision_pipeline.py": "0c6713304f4b80ddab4f3b132be82ac49429a6d8ef8eaec4866f1a1461b9d612",
    "app/application/chat_pipeline.py": "f4320415d8337b6ef5d1908beae1163e8881600923316616bf7d6afbb47d7423",
    "app/application/post_process.py": "3f154e7616c90053df8747358d142544a4b2ad78f9a9001ddb5be4280f72e127",
    "app/application/action_engine.py": "8dec1c865a9e58546e6096e1f61ff13be5e6a168859e6ab8181cd85c68dc4df8",
    "app/prompts/builder.py": "d3ee8bf448dd98c87afa6623361beeedd1cbe20ceb5abd22ed4d919202c9531c",
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
        "feishu_enabled": True,
        "tool_confirm_timeout_hours": 24,
        "tool_confirm_ttl_reuse": True,
        "tool_ext_allowed_hosts": "",
        "tool_breaker_threshold": 3,
        "tool_breaker_cooldown_seconds": 300,
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

    surface = ToolSurfaceResolver(
        registry, _settings(tool_surface_max_tools=20)
    ).resolve(
        "foreground_chat",
        surface_context(settings=_settings(tool_surface_max_tools=20)),
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


