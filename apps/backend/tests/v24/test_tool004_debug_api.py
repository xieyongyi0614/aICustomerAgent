"""TOOL-004 §4.2/§6.2：管理面 6 端点的门控、投影与执行台账（E9~E12）。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.application import action_engine
from app.main import app
from app.models.action import ActionIntent
from app.repositories import action_repository
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import ToolSurfaceResolver
from tests.v24.tool004_support import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
    notification_send_parameters,
    registry_with,
    surface_context,
    tool_definition,
)

TOOL_ID = "builtin.reminder.create"
CHANNEL_ID = "channel.feishu.send"
EXEC_USER = "u-tool-exec"
BASE = "/api/v1"


def _url(path: str) -> str:
    return f"{BASE}{path}"


async def _get(path: str, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(_url(path), params=params)


async def _post(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(_url(path))


@pytest.fixture
def tools_on(v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True, V24_TOOL_SURFACE_ENABLED=True)


@pytest.fixture
def tools_master_only(v24_tool_env):
    v24_tool_env(V24_TOOL_SYSTEM_ENABLED=True, V24_TOOL_SURFACE_ENABLED=False)


def _seed_record(user_id: str = EXEC_USER) -> str:
    record = action_engine.new_record(
        ActionIntent(
            action_type="create_reminder",
            confidence="confident",
            params={"content": "开会", "due_at": "2026-09-15T08:00:00"},
        ),
        user_id,
        session_id=None,
    )
    record.status = "succeeded"
    record.steps = [
        {
            "index": 0,
            "capability": "reminder",
            "action": "create",
            "params": {"content": "开会"},
            "status": "succeeded",
            "result": {
                "status": "succeeded",
                "effects": [{"kind": "world", "ref": "we-1", "detail": "", "reversible": True}],
                "observations": {},
            },
            "tool_id": TOOL_ID,
            "permission": {
                "level": "normal",
                "decision": "allow",
                "reason": "permission_layer_off",
                "confirmed": False,
            },
            "validation": None,
            "duration_ms": 12,
        },
        {
            "index": 1,
            "capability": "memory",
            "action": "save",
            "params": {},
            "status": "succeeded",
            "result": {"status": "succeeded"},
        },
    ]
    action_repository.save_record(record)
    return record.id


def _custom_channel_registry() -> ToolRegistry:
    return registry_with(
        tool_definition(TOOL_ID, priority=10),
        tool_definition(
            CHANNEL_ID,
            namespace="channel",
            capability="notification",
            action="send",
            tags=("channel", "feishu"),
            side_effects=("send_external",),
            priority=20,
            parameters=notification_send_parameters(),
        ),
    )


# --- 总闸 off 门控 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_read_endpoints_report_disabled_when_master_flag_off():
    for path, params in (
        ("/debug/tools", {}),
        (f"/debug/tools/{TOOL_ID}", {}),
        ("/debug/tools/surface", {}),
        ("/debug/tools/executions", {"user_id": EXEC_USER}),
    ):
        response = await _get(path, **params)
        assert response.status_code == 200, path
        body = response.json()
        assert body["enabled"] is False, path


@pytest.mark.asyncio
async def test_write_endpoints_are_forbidden_when_master_flag_off():
    for suffix in ("disable", "enable"):
        response = await _post(f"/debug/tools/{TOOL_ID}/{suffix}")
        assert response.status_code == 403
        assert "v24_tool_system_enabled" in response.json()["detail"]


# --- 工具清单 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_list_exposes_declaration_status_and_health(tools_on):
    payload = (await _get("/debug/tools")).json()
    assert payload["enabled"] is True
    rows = {row["tool_id"]: row for row in payload["tools"]}
    assert len(rows) == 10
    assert rows[TOOL_ID]["namespace"] == "builtin"
    assert rows[TOOL_ID]["side_effects"] == ["write_world"]
    assert rows[TOOL_ID]["status"] == "enabled"
    assert rows[TOOL_ID]["health"]["consecutive_failures"] == 0
    assert rows[CHANNEL_ID]["status"] == "disabled"
    assert payload["runtime_disabled"] == []


# --- 单工具详情（E9） ------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_detail_returns_schema_permission_and_executions(tools_on):
    record_id = _seed_record()
    payload = (
        await _get(f"/debug/tools/{TOOL_ID}", user_id=EXEC_USER)
    ).json()
    assert payload["enabled"] is True
    assert payload["tool_id"] == TOOL_ID
    assert payload["definition"]["id"] == TOOL_ID
    assert payload["definition"]["input_schema"]["strict"] is True
    assert payload["permission"]["level"] == "normal"
    assert len(payload["recent_executions"]) == 1
    assert payload["recent_executions"][0]["record_id"] == record_id
    assert payload["recent_executions"][0]["tool_id"] == TOOL_ID


@pytest.mark.asyncio
async def test_e9_unregistered_tool_detail_is_404(tools_on):
    response = await _get("/debug/tools/builtin.ghost.tool")
    assert response.status_code == 404
    assert response.json()["detail"] == "工具未注册"


# --- 工具面投影（E11） -----------------------------------------------------


@pytest.mark.asyncio
async def test_surface_endpoint_defaults_run_kind_and_lists_reasons(tools_on):
    payload = (await _get("/debug/tools/surface")).json()
    assert payload["enabled"] is True
    assert payload["run_kind"] == RUN_KIND_FOREGROUND_CHAT
    assert payload["run_kind_defaulted"] is True
    assert CHANNEL_ID not in payload["tool_ids"]
    # TOOL-010｜通道工具声明态 disabled + 检索工具可用性降级裁剪 → 实际进面 8 个。
    assert len(payload["tool_ids"]) == 8
    assert {item["tool_id"] for item in payload["excluded"]} == {
        CHANNEL_ID,
        "builtin.search.query",
    }
    assert payload["surface_hash"]


@pytest.mark.asyncio
async def test_e11_surface_endpoint_honours_explicit_run_kind(tools_on, monkeypatch):
    registry = _custom_channel_registry()
    monkeypatch.setattr("app.api.v1.debug.get_tool_registry", lambda: registry)
    payload = (
        await _get("/debug/tools/surface", run_kind=RUN_KIND_AUTONOMOUS_TICK)
    ).json()
    assert payload["run_kind"] == RUN_KIND_AUTONOMOUS_TICK
    assert payload["run_kind_defaulted"] is False
    assert payload["tool_ids"] == [TOOL_ID]
    assert payload["excluded"][0]["tool_id"] == CHANNEL_ID
    assert payload["excluded"][0]["reason"].startswith("run_profile:")


@pytest.mark.asyncio
async def test_surface_endpoint_matches_resolver_projection(tools_on):
    payload = (await _get("/debug/tools/surface", run_kind=RUN_KIND_FOREGROUND_CHAT)).json()
    registry = ToolRegistry()
    register_builtin_tools(registry)
    expected = ToolSurfaceResolver(registry).resolve(
        RUN_KIND_FOREGROUND_CHAT, surface_context(user_id="")
    )
    assert payload["surface_hash"] == expected.surface_hash
    assert payload["tool_ids"] == list(expected.tool_ids)


@pytest.mark.asyncio
async def test_surface_endpoint_requires_surface_sub_flag(tools_master_only):
    response = await _get("/debug/tools/surface")
    assert response.status_code == 403
    assert "v24_tool_surface_enabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_surface_endpoint_reports_disabled_when_master_flag_off():
    response = await _get("/debug/tools/surface", run_kind=RUN_KIND_FOREGROUND_CHAT)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["tool_ids"] == []
    assert body["surface_hash"] is None


# --- 运行期禁用 / 恢复（E10） ---------------------------------------------


@pytest.mark.asyncio
async def test_disable_then_enable_roundtrip(tools_on):
    disabled = (await _post(f"/debug/tools/{TOOL_ID}/disable")).json()
    assert disabled == {
        "enabled": True,
        "tool_id": TOOL_ID,
        "effective_status": "disabled",
        "runtime_disabled": True,
    }
    listing = (await _get("/debug/tools")).json()
    assert listing["runtime_disabled"] == [TOOL_ID]
    assert next(
        row for row in listing["tools"] if row["tool_id"] == TOOL_ID
    )["status"] == "disabled"
    surface = (await _get("/debug/tools/surface")).json()
    assert TOOL_ID not in surface["tool_ids"]

    enabled = (await _post(f"/debug/tools/{TOOL_ID}/enable")).json()
    assert enabled == {
        "enabled": True,
        "tool_id": TOOL_ID,
        "effective_status": "enabled",
        "runtime_disabled": False,
    }
    assert TOOL_ID in (await _get("/debug/tools/surface")).json()["tool_ids"]


@pytest.mark.asyncio
async def test_e10_disable_unregistered_tool_is_404_and_writes_nothing(tools_on):
    response = await _post("/debug/tools/builtin.ghost.tool/disable")
    assert response.status_code == 404
    assert response.json()["detail"] == "工具未注册"
    assert (await _get("/debug/tools")).json()["runtime_disabled"] == []


@pytest.mark.asyncio
async def test_e10_enable_unregistered_tool_is_404(tools_on):
    assert (await _post("/debug/tools/builtin.ghost.tool/enable")).status_code == 404


# --- 执行台账（E12） ------------------------------------------------------


@pytest.mark.asyncio
async def test_e12_executions_for_unknown_user_is_empty_list(tools_on, db_session_factory):
    payload = (await _get("/debug/tools/executions", user_id="nobody")).json()
    assert payload["enabled"] is True
    assert payload["user_id"] == "nobody"
    assert payload["executions"] == []


@pytest.mark.asyncio
async def test_executions_project_only_tool_steps(tools_on, db_session_factory):
    record_id = _seed_record()
    payload = (await _get("/debug/tools/executions", user_id=EXEC_USER)).json()
    assert payload["user_id"] == EXEC_USER
    assert len(payload["executions"]) == 1
    row = payload["executions"][0]
    assert row == {
        "record_id": record_id,
        "tool_id": TOOL_ID,
        "status": "succeeded",
        "permission": {
            "level": "normal",
            "decision": "allow",
            "reason": "permission_layer_off",
            "confirmed": False,
        },
        "duration_ms": 12,
        "effects": [{"kind": "world", "ref": "we-1", "detail": "", "reversible": True}],
    }


@pytest.mark.asyncio
async def test_executions_filter_by_tool_id_in_detail_view(tools_on, db_session_factory):
    _seed_record()
    payload = (
        await _get(f"/debug/tools/{TOOL_ID}", user_id=EXEC_USER)
    ).json()
    assert [row["tool_id"] for row in payload["recent_executions"]] == [TOOL_ID]
    other = (
        await _get("/debug/tools/builtin.memory.save", user_id=EXEC_USER)
    ).json()
    assert other["recent_executions"] == []


@pytest.mark.asyncio
async def test_executions_are_empty_when_ledger_has_no_tool_steps(tools_on, db_session_factory):
    record = action_engine.new_record(
        ActionIntent(
            action_type="create_reminder",
            confidence="confident",
            params={"content": "开会"},
        ),
        "u-v9-path",
        session_id=None,
    )
    record.steps = [
        {
            "index": 0,
            "capability": "reminder",
            "action": "create",
            "params": {},
            "status": "succeeded",
            "result": {"status": "succeeded"},
        }
    ]
    action_repository.save_record(record)
    payload = (await _get("/debug/tools/executions", user_id="u-v9-path")).json()
    assert payload["executions"] == []


def test_surface_endpoint_shares_resolver_semantics():
    registry = _custom_channel_registry()
    projected = ToolSurfaceResolver(registry).resolve(
        RUN_KIND_AUTONOMOUS_TICK, ToolContext(user_id="", run_kind=RUN_KIND_AUTONOMOUS_TICK)
    )
    assert projected.tool_ids == (TOOL_ID,)
