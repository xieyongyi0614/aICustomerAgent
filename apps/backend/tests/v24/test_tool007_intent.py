"""TOOL-007 §4.2 / §6.1 / E14：`world.intent.submit` 接口形状冻结、零写入与调试面 not_wired。"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.models.tool import ToolSchema
from app.repositories import (
    action_repository,
    outbox_repository,
    world_repository,
    world_simulation_repository,
)
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.world_intent import (
    INTENT_TYPES,
    NOT_WIRED_NOTE,
    REASON_MAX_CHARS,
    STATUS_NOT_WIRED,
    SUBMIT_UNAVAILABLE,
    WIRED,
    WORLD_INTENT_TOOL_ID,
    WorldIntent,
    WorldIntentSubmitter,
    get_world_intent_submitter,
)

BASE = "/api/v1"
USER = "u-tool007-intent"


def _intent(**overrides) -> WorldIntent:
    payload = {
        "user_id": USER,
        "intent_type": "tidy_room",
        "target": "home.living_room",
        "reason": "房间太乱，想整理一下",
    }
    payload.update(overrides)
    return WorldIntent(**payload)


def _ctx() -> ToolContext:
    return ToolContext(user_id=USER, settings=None)


# --- 接口形状 ----------------------------------------------------------------


def test_world_intent_fields_and_defaults():
    intent = _intent()
    assert intent.user_id == USER
    assert intent.intent_type == "tidy_room"
    assert intent.target == "home.living_room"
    assert intent.created_at is not None
    assert intent.brief() == {
        "intent_type": "tidy_room",
        "target": "home.living_room",
        "reason": "房间太乱，想整理一下",
    }
    assert _intent(target=None).target is None


def test_world_intent_reason_is_bounded():
    assert _intent(reason="长" * REASON_MAX_CHARS).reason == "长" * REASON_MAX_CHARS
    with pytest.raises(ValidationError):
        _intent(reason="长" * (REASON_MAX_CHARS + 1))


def test_intent_types_are_frozen_vocabulary():
    assert INTENT_TYPES == ("tidy_room", "move_location", "start_activity")


def test_status_shape_matches_debug_projection():
    status = get_world_intent_submitter().status()
    assert status == {
        "tool_id": WORLD_INTENT_TOOL_ID,
        "status": STATUS_NOT_WIRED,
        "wired": False,
        "writes": 0,
        "intent_types": list(INTENT_TYPES),
        "note": NOT_WIRED_NOTE,
    }


def test_world_intent_is_not_registered_as_tool():
    """形状冻结、不接线：不占注册表席位（因此不会进工具面、不会被选中执行）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    assert registry.get(WORLD_INTENT_TOOL_ID) is None
    assert WORLD_INTENT_TOOL_ID not in {item.id for item in registry.list()}
    assert ToolSchema().semantic_validators == ()


def test_submitter_reports_not_wired():
    submitter = WorldIntentSubmitter()
    assert submitter.is_wired() is WIRED is False
    assert submitter.status()["status"] == STATUS_NOT_WIRED


# --- E14：占位返回 unavailable 且零写入 --------------------------------------


@pytest.mark.parametrize("intent_type", INTENT_TYPES)
def test_submit_returns_unavailable_placeholder(intent_type):
    submitter = WorldIntentSubmitter()
    assert submitter.submit(_intent(intent_type=intent_type), _ctx()) == SUBMIT_UNAVAILABLE


def test_submit_performs_zero_db_access(db_session_factory, monkeypatch):
    """零写入（E14）：连 SessionLocal 都不碰——任何 DB 访问即失败。"""
    import app.repositories.outbox_repository as outbox_module

    assert world_repository.get_world(USER) is None

    def boom(*args, **kwargs):
        raise AssertionError("world.intent.submit 不得触碰数据库")

    for module in (world_repository, world_simulation_repository, outbox_module, action_repository):
        monkeypatch.setattr(module, "SessionLocal", boom)

    submitter = WorldIntentSubmitter()
    assert submitter.submit(_intent(), _ctx()) == SUBMIT_UNAVAILABLE


def test_submit_writes_no_world_event(db_session_factory):
    submitter = WorldIntentSubmitter()
    for _ in range(3):
        assert submitter.submit(_intent(), _ctx()) == SUBMIT_UNAVAILABLE
    assert world_repository.get_world(USER) is None


# --- E14：调试端点暴露 not_wired --------------------------------------------


def _url(path: str) -> str:
    return f"{BASE}{path}"


async def _get(path: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(_url(path), params=params)


@pytest.mark.asyncio
async def test_e14_debug_tools_exposes_not_wired(v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True)
    payload = (await _get("/debug/tools")).json()
    assert payload["enabled"] is True
    assert payload["world_intent"] == {
        "tool_id": WORLD_INTENT_TOOL_ID,
        "status": STATUS_NOT_WIRED,
        "wired": False,
        "writes": 0,
        "intent_types": list(INTENT_TYPES),
        "note": NOT_WIRED_NOTE,
    }


@pytest.mark.asyncio
async def test_debug_tools_master_flag_off_hides_world_intent(v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=False)
    payload = (await _get("/debug/tools")).json()
    assert payload["enabled"] is False
    assert payload["world_intent"] is None


@pytest.mark.asyncio
async def test_debug_world_intent_status_is_not_a_registered_tool(v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True)
    payload = (await _get("/debug/tools")).json()
    assert WORLD_INTENT_TOOL_ID not in {row["tool_id"] for row in payload["tools"]}
    assert payload["world_intent"]["wired"] is False
