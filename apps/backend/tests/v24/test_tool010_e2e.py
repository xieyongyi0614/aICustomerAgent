"""TOOL-010 §6.1/§6.2：≥9 工具 × 成功/校验失败/权限拒绝 端到端矩阵、四步流程与零 diff。

三类路径都走真实 `ToolExecutor` 五段链路（resolve → permission → validate → invoke →
normalize）：成功路径的实现体对 4 个 V9 能力用打桩（V9 实现语义由 `tests/unit` 与
`tests/v9` 覆盖），对 TOOL-010 的三个能力（`search` / `notification` / `channel_feishu`）
用**真实实现体**——它们的"成功"语义正是本任务的交付物。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import timeutil
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
from tests.support.frozen_surface import assert_frozen, file_digest
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


ZERO_DIFF_HASHES: dict[str, str] = {
    "app/channels/base.py": "f992542b7585468c09f169a16d1f6d4aab36639eb35ae840936b201402359617",
    "app/channels/feishu/outbound.py": "50aa5f198d1793195ba32634e6d25e67fd21f160821957f96c4e5d78b1b800ac",
    "app/channels/feishu/client.py": "5f9fe0dadc8a5fa49a945f611d68600f3dc15d07e65d3d2463384a6f036bff7e",
    # services 归位声明（2026-09-30，批次 3）：`channel_identity_service` → `identity/channel`
    # 导入路径变更 —— 非 TOOL-010 改脏。原值 b82457b2。
    "app/channels/feishu/delivery.py": "21f80983c08175e32542f1106d7fbfedd670a47e7540be9ecd30c097bb4e9749",
    # 开关清理声明（2026-09-28）：world_enabled 主闸删除后，四个能力文件里的恒真死闸
    # （world_gate / world_available 的 getattr 读取）随之移除 —— 非 TOOL-010 改脏。
    # 反向依赖清理声明（2026-09-30）：三个能力文件 `from app.application import world_engine`
    # 改经 `services/world/engine_port` 端口访问 —— 非 TOOL-010 改脏。原值分别
    # aa217128 / 2ad7ae8f / 69eeff31。
    "app/services/action/capabilities/reminder.py": "5ddf80197aff21b0074142f6c0331224abe93047d2097be4cda668d40c860257",
    "app/services/action/capabilities/memory.py": "cfb232780c1510776b7b50e9bfb5b6bb69306c9521039d08cd16b5a8f7746119",  # 前值 912619b5（services 归位批次 4：memory/policy → engines/memory_policy 导入路径变更）；再前值 b8cedddd（memory 域清理）
    "app/services/action/capabilities/world_action.py": "d01ea0b163c1e0beb3fbfb812ba6e25f31dd403a23824f65712813a46ac7be1d",
    "app/services/action/capabilities/environment_query.py": "f48b75e8a105ea907d1c352c348e39813e3a1cbed47919783e3cbd5eb7c603f8",
    # 记账词表补齐声明（2026-10-02，记账链路修复）：LEDGER_RECORD_TRIGGERS 增补
    # `花费 / 付款 / 买 / 充值 / 交了 / 缴了` —— 非 TOOL-010 改脏。原值 2da514d9。
    "app/character/asuna/action.py": "0269c402790461de1923aa55c58195f05f68b3bb675be2eac5353f7bc50698e0",
    # 时间口径声明（2026-10-06）：`GateSnapshot.now` 默认值 `datetime.now` → `timeutil.now`
    # （naive/aware 混算修复）—— 非 TOOL-010 改脏。原值 41288337。
    "app/services/action/planner.py": "95be6179adf985bcceb143550decee9fa04e77724fe0e8add1c1a61b0068fab3",
    # services 归位声明（2026-09-30，批次 1~4）：`llm_budget_gate` → `life/gate`、
    # `state_engine` / `goal_alignment` → `engines/*`、领域包归位导入路径变更；
    # 批次 4 文件由 `services/decision_pipeline.py` 归位至 `engines/decision.py`，
    # 内容逐字节未变（摘要不变），仅键路径更新。原值 0c671330。
    "app/engines/decision.py": "92f5d7b46313d925f0ce62fc2110af0b704a4f3eeab59c47f5480d50b502a6e4",
    # API-003 语义变更声明：turn_meta 追加 memory_refs（键序末尾可选），非 TOOL-010 改脏。
    # 开关清理声明（2026-09-28）：删除 inventory_grounding_enabled / character_action_sync_enabled
    # 并固化常开，grounding 关断改由 inventory_grounding_mode=off 承担 —— 非 TOOL-010 改脏。
    # services 归位声明（2026-09-30，批次 1~4）：`memory_refs` → `memory/refs`、
    # `behavior_engine` / `mode_service` / `state_engine` 等引擎收口、领域包归位、
    # `decision_pipeline` → `engines/decision` 导入路径变更 —— 非 TOOL-010 改脏。
    # 原值 4aec8e65、ea741a87、9054ce0d。
    # 反向依赖清理声明（2026-09-30）：`active_generations` 下沉 `core/runtime_state` 导入路径变更。
    # ID 体系收敛声明（2026-10-03，C3）：`uuid4()` 默认主键改 `ids.new_id_str()`（ADR-16）—— 非 TOOL-010 改脏。
    # memory 域时间口径迁移（2026-10-05，0006/0007）：`timeutil.now()` 改走 `timeutil`
    # （aware UTC），`_select_goal` 深夜判定改 `timeutil.local_now()` —— 非 TOOL-010 改脏。
    # 原值 6571ef69。
    # 入口收敛声明（2026-10-09，T-33）：`agent_service` 兼容壳退役，`stream_chat`
    # （trace 兜底 + observability context set/reset）收编入本文件；生产调用点改直连
    # / 经 `channel_gateway` 转发 —— 非 TOOL-010 改脏。原值 e119d89b。
    # 注释补充声明（2026-10-10）：为前台管线补中文 docstring / 行内注释（零逻辑改动，
    # 逐行仅新增）—— 非 TOOL-010 改脏。原值 d7be7201。
    "app/application/chat_pipeline.py": "7b2ee0e48cae22edc3c1f872678067e66983bd8283705cc123fd226167b9cb5d",
    # memory 域清理声明（2026-09-29）：`memory_service` 死导入移除（该模块生产零调用，
    # 写路径已全量走 memory ingest/evaluate）—— 非 TOOL-010 改脏。
    # memory 域通道收敛声明（2026-09-30，台账 §5.2）：新增 `run_memory_evaluate` 收尾评估步
    # （世界/行动步骤当轮投递的候选当轮转正，保证可见性时序不回退）—— 非 TOOL-010 改脏。
    # V7-010 恢复声明（2026-09-30，台账 §3.3.2）：`_run_memory_ingest_v2` 尾部承接
    # `_register_followups`（会话候选 → scheduled_followup 登记）—— 非 TOOL-010 改脏。
    # 开关固化声明（2026-10-06，批次 2）：`observability_persist_enabled` 总闸删除后
    # `_persist_tool_decision` 守卫收窄 —— 非 TOOL-010 改脏。原值 91e31d92（再前值 bcb7b63c）。
    # 账本单写面声明（2026-10-07）：新增 `_ledger_detected_payload`（待确认承载词表链路
    # 解析）与 `_defer_to_ledger_pending`（同轮同金额已进待确认则确定性链路让位，
    # 修「先入账又被确认一次 → 重复记账」）—— 非 TOOL-010 改脏。原值 83222b5b。
    # 物品录入声明（2026-10-10）：`run_world_update` 步骤内部增强——新增 `_run_object_intake`
    # （用户显式要求记录物品 → LLM 抽取 → 建档）；默认家庭库存种子已移除 —— 非 TOOL-010 改脏。
    # 原值 ac5698b4。
    "app/application/post_process.py": "ea3399d914b66a48a1173b4b9cd5aeb51ee1a36938a67adfcfb4d71f7717cb93",
    # 记账明细/类目声明（2026-10-02，记账链路修复）：新增 `_normalize_ledger_intent`
    # （明细文本 → 类目 id，归一放在引擎侧，能力层仍只收结构化 id）—— 非 TOOL-010 改脏。
    # 记账播种顺序声明（2026-10-07）：新增 `_ensure_ledger_categories`，把账户 / 种子类目
    # 播种提到「明细 → 类目」归一之前（原先播种只发生在执行期能力层，导致用户首笔
    # 对话记账必「未分类」）—— 非 TOOL-010 改脏。原值 fb11fbef。
    "app/application/action_engine.py": "bea2a3101e77ba4f0a5094c618f41c67e7cbb1313c9a6aebfc1b487228496397",
    # services 归位声明（2026-09-30，批次 3）：`relationship_milestone` → `relationship/milestone`
    # 导入路径变更 —— 非 TOOL-010 改脏。原值 d3ee8bf4。
    # 演绎段注入策略位声明（2026-10-02）：新增 `roleplay_prompt_mode`（默认 full）——
    # `off` 时回答链不注入人设/情绪/关系/世界/场景/行为/风格段，`full` 时字节不变。
    # 非 TOOL-010 改脏。原值 2683cf60。
    "app/prompts/builder.py": "ac4476d1d7b4ca49795c3f730253a9c8f14dc4b568eaee79544d40fa22decb51",
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
    """行尾归一（LF）后的 sha256：抵消 CRLF 检出带来的假失败（P2-4）。

    实现已抽到 `tests/support/frozen_surface.py`（T-24：比对前先暴露 actual）。
    """
    return file_digest(relative_path)


@pytest.mark.parametrize("relative_path", sorted(ZERO_DIFF_HASHES), ids=lambda value: value)
def test_zero_diff_frozen_surfaces(relative_path):
    assert_frozen(
        relative_path,
        expected=ZERO_DIFF_HASHES[relative_path],
        actual=_file_digest(relative_path),
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
        "app/engines/decision.py",
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
        assert_frozen(
            relative_path,
            expected=ZERO_DIFF_HASHES[relative_path],
            actual=_file_digest(relative_path),
        )


# --- Flag 全 off：既有路径零变化 -------------------------------------------


