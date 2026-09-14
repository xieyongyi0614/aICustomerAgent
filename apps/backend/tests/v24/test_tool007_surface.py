"""TOOL-007 §6.1：世界可用性投影规则与语义校验器世界事实供给（E1、E4、E5）。"""

import pytest

from app.models.action import ActionIntent
from app.services.tool.context import ToolContext
from app.services.tool.surface import ToolSurfaceResolver, WORLD_FACTS_REASON, WORLD_REASON
from app.services.tool.validator import ParamValidator
from app.services.tool.world_context import WorldContextBuilder, apply_world_facts
from tests.v24.tool003_support import StubCapability, build_executor
from tests.v24.tool004_support import builtin_registry
from tests.v24.tool007_support import (
    NOW,
    USER,
    seed_all,
    seed_world,
    tool_context,
    world_settings,
)

RUN_KIND = "foreground_chat"

MOVED_TOOL = "world.object.move"
USE_TOOL = "world.object.use"

VALIDATOR = ParamValidator()


@pytest.fixture(autouse=True)
def _world_fixture_isolation(db_session_factory, override_settings):
    override_settings(world_household_autoseed_enabled="false")
    yield


def _facts(**settings_overrides) -> dict:
    settings = world_settings(**settings_overrides)
    return WorldContextBuilder(settings).build(USER, now=NOW, settings=settings)


def _resolved(facts: dict | None, **settings_overrides):
    settings = world_settings(**settings_overrides)
    ctx = apply_world_facts(tool_context(settings=settings), facts) if facts is not None else tool_context(
        settings=settings
    )
    return ToolSurfaceResolver(builtin_registry(), settings).resolve(RUN_KIND, ctx)


def _reasons(surface) -> dict:
    return {item["tool_id"]: item["reason"] for item in surface.excluded}


def _world_tool_ids() -> set[str]:
    return {item.id for item in builtin_registry().list(namespace="world")}


CODE_DISABLED_TOOL = "channel.feishu.send"


def _world_reasons(surface) -> dict:
    """仅世界命名空间的裁剪原因（`channel.feishu.send` 是代码态 disabled，属状态维度）。"""
    return {
        tool_id: reason
        for tool_id, reason in _reasons(surface).items()
        if tool_id.startswith("world.")
    }


# --- §4.4 / E1：世界可用性维度 ------------------------------------------------


def test_e1_world_disabled_facts_cut_world_namespace_with_reason():
    surface = _resolved(_facts(world_enabled=False), world_enabled=False)
    world_ids = _world_tool_ids()
    assert set(_world_reasons(surface)) == world_ids
    assert all(_world_reasons(surface)[tool_id] == WORLD_FACTS_REASON for tool_id in world_ids)
    assert not (world_ids & set(surface.tool_ids))


def test_world_facts_enabled_keeps_world_namespace(db_session_factory):
    seed_all()
    surface = _resolved(_facts())
    assert _world_reasons(surface) == {}


def test_world_disabled_facts_only_affect_world_namespace():
    facts_off = _resolved(_facts(world_enabled=False), world_enabled=False)
    facts_on = _resolved(_facts(), world_enabled=True)
    assert set(_reasons(facts_off)) - set(_reasons(facts_on)) == _world_tool_ids()
    assert _reasons(facts_off)[CODE_DISABLED_TOOL] == "tool_status:disabled"


def test_unassembled_facts_fall_back_to_settings_reason():
    """未装配（TOOL-007 未跑）时保留 TOOL-004 配置态理由，不误用新理由。"""
    surface = _resolved(None, world_enabled=False)
    reasons = _world_reasons(surface)
    assert set(reasons) == _world_tool_ids()
    assert all(reason == WORLD_REASON for reason in reasons.values())


def test_unassembled_facts_with_world_enabled_do_not_trim():
    surface = _resolved(None)
    assert _world_reasons(surface) == {}


def test_world_facts_disabled_but_settings_enabled_still_trims():
    """事实态优先于配置态：装配说世界不可用即裁掉 world.*。"""
    surface = _resolved(_facts(world_enabled=False))
    assert all(
        _world_reasons(surface)[tool_id] == WORLD_FACTS_REASON for tool_id in _world_tool_ids()
    )


def test_surface_hash_reacts_to_world_facts():
    on = _resolved(_facts())
    off = _resolved(_facts(world_enabled=False), world_enabled=False)
    unassembled = _resolved(None)
    assert len({on.surface_hash, off.surface_hash, unassembled.surface_hash}) == 3


# --- E5：location_exists 拿到真实地点词表 ------------------------------------


def _move_params(location: str) -> dict:
    return {"object": "苹果", "location": location}


def _validate(tool_id: str, params: dict, ctx: ToolContext):
    defn = builtin_registry().get(tool_id)
    assert defn is not None
    return VALIDATOR.validate(defn, params, ctx)


def _ctx_with_facts(**settings_overrides) -> ToolContext:
    return apply_world_facts(tool_context(), _facts(**settings_overrides))


def test_e5_location_exists_accepts_registered_location_id(db_session_factory):
    seed_all()
    report = _validate(MOVED_TOOL, _move_params("home.kitchen"), _ctx_with_facts())
    assert report.passed is True
    assert report.semantic == []


def test_e5_location_exists_accepts_registered_location_name(db_session_factory):
    seed_all()
    report = _validate(MOVED_TOOL, _move_params("厨房"), _ctx_with_facts())
    assert report.passed is True


def test_e5_location_exists_rejects_unknown_location(db_session_factory):
    seed_all()
    report = _validate(MOVED_TOOL, _move_params("ghost_place"), _ctx_with_facts())
    assert report.passed is False
    assert [issue["code"] for issue in report.semantic] == ["location_not_found"]
    assert report.semantic[0]["param"] == "location"


def test_e5_unknown_current_location_still_supplies_location_vocabulary(db_session_factory):
    """TOOL-010｜`world.object.move` 按 §2.2 追加 `object_in_inventory` 绑定：本夹具只建世界、
    不建库存，故断言收敛到地点轴（已知地点词表仍生效：home.kitchen 不被判 location_not_found，
    ghost_place 被判）。"""
    seed_world(location="ghost_place")
    ctx = _ctx_with_facts()
    assert ctx.world["location_name"] == "ghost_place"
    known = _validate(MOVED_TOOL, _move_params("home.kitchen"), ctx)
    assert [issue["code"] for issue in known.semantic] == ["object_not_in_inventory"]
    unknown = _validate(MOVED_TOOL, _move_params("ghost_place"), ctx)
    assert [issue["code"] for issue in unknown.semantic] == [
        "object_not_in_inventory",
        "location_not_found",
    ]


def test_location_exists_degrades_when_facts_unassembled():
    report = _validate(MOVED_TOOL, _move_params("ghost_place"), tool_context())
    assert report.passed is True


# --- E4：object_in_inventory --------------------------------------------------


def _use_params(obj: str) -> dict:
    return {"object": obj}


def test_object_in_inventory_accepts_owned_object(db_session_factory):
    seed_all()
    report = _validate(USE_TOOL, _use_params("苹果"), _ctx_with_facts())
    assert report.passed is True


def test_object_in_inventory_rejects_missing_object(db_session_factory):
    seed_all()
    report = _validate(USE_TOOL, _use_params("梨"), _ctx_with_facts())
    assert report.passed is False
    assert [issue["code"] for issue in report.semantic] == ["object_not_in_inventory"]
    assert report.semantic[0]["param"] == "object"


def test_e4_empty_inventory_rejects_any_object(db_session_factory):
    seed_world()
    ctx = _ctx_with_facts()
    assert ctx.inventory == [] and ctx.world_facts_assembled() is True
    for obj in ("苹果", "任何东西"):
        report = _validate(USE_TOOL, _use_params(obj), ctx)
        assert report.passed is False
        assert [issue["code"] for issue in report.semantic] == ["object_not_in_inventory"]


def test_object_in_inventory_degrades_when_facts_unassembled():
    report = _validate(USE_TOOL, _use_params("梨"), tool_context())
    assert report.passed is True


def test_object_in_inventory_degrades_when_world_disabled():
    ctx = _ctx_with_facts(world_enabled=False)
    assert ctx.inventory == []
    assert _validate(USE_TOOL, _use_params("梨"), ctx).passed is True


def test_object_in_inventory_degrades_when_context_missing():
    defn = builtin_registry().get(USE_TOOL)
    assert VALIDATOR.validate(defn, _use_params("梨"), None).passed is True


# --- 执行器端到端：语义校验拦下世界动作（零能力调用） ------------------------


@pytest.mark.asyncio
async def test_executor_blocks_invalid_location_without_calling_capability(db_session_factory):
    seed_all()
    registry = builtin_registry()
    capability = StubCapability(
        name="world_action", action="move", required=["object", "location"]
    )
    executor = build_executor(
        registry,
        capability,
        settings=world_settings(v24_tool_schema_validation_enabled=True),
    )
    binding = registry.resolve(MOVED_TOOL)
    assert binding is not None
    execution = await executor.run(
        binding,
        _invocation(_move_params("ghost_place")),
        _ctx_with_facts(),
    )
    assert execution.status == "invalid"
    assert capability.calls == []
    assert execution.validation["semantic"][0]["code"] == "location_not_found"


@pytest.mark.asyncio
async def test_executor_passes_valid_world_action_with_real_facts(db_session_factory):
    seed_all()
    registry = builtin_registry()
    capability = StubCapability(
        name="world_action", action="move", required=["object", "location"]
    )
    executor = build_executor(
        registry,
        capability,
        settings=world_settings(v24_tool_schema_validation_enabled=True),
    )
    binding = registry.resolve(MOVED_TOOL)
    execution = await executor.run(
        binding,
        _invocation(_move_params("home.kitchen")),
        _ctx_with_facts(),
    )
    assert execution.status == "succeeded"
    assert capability.calls[0]["location"] == "home.kitchen"


def _invocation(params: dict):
    from app.models.tool import ToolInvocation

    return ToolInvocation(
        tool_id=MOVED_TOOL,
        params=params,
        intent=ActionIntent(
            action_type="move_object", confidence="confident", params=params
        ),
    )


# --- 事实与规格的一致性 ------------------------------------------------------


def test_world_facts_carry_all_projection_inputs(db_session_factory):
    seed_all()
    ctx = _ctx_with_facts(v23_scene_expansion_enabled=True)
    assert ctx.world_facts_assembled() is True
    assert ctx.part_of_day() in ("morning", "afternoon", "dusk", "evening", "late_night")
    assert ctx.scene_tone_bias() == "intimate"
    assert ctx.relationship_stage() == "friend"
    assert ctx.world_locations() == tuple(_facts()["world"]["locations"])
