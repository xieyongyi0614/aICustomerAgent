"""TOOL-011 调试端点（§4.5、§6.2、§6.3 E17）：门控、投影与凭据不可见。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.settings import get_settings
from app.main import app
from app.services.tool import ext_api, user_defined
from tests.v24.tool011_support import (
    USER_TOOL_ID,
    WEATHER_ENV,
    WEATHER_SECRET,
    WEATHER_TOOL_ID,
    assert_no_secret,
    user_declaration,
    weather_manifest,
    write_manifest,
)

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


@pytest.fixture(autouse=True)
def _reset_ext_state():
    ext_api.reset_external_api_state()
    user_defined.reset_user_tool_registrar()
    get_settings.cache_clear()
    yield
    user_defined.reset_user_tool_registrar()
    ext_api.reset_external_api_state()
    get_settings.cache_clear()


def _enable_ext_face(v24_tool_env, tmp_path, **overrides):
    envs = {
        "TOOL_SYSTEM_ENABLED": True,
        "TOOL_EXTERNAL_API_ENABLED": True,
        "TOOL_USER_DEFINED_ENABLED": True,
        "TOOL_EXT_ALLOWED_HOSTS": "api.example.com",
        "TOOL_EXT_MANIFEST_PATH": str(tmp_path),
        WEATHER_ENV: WEATHER_SECRET,
    }
    envs.update(overrides)
    v24_tool_env(**envs)
    return get_settings()


def _run_startup_load():
    settings = get_settings()
    return ext_api.get_manifest_loader().load(settings.tool_ext_manifest_path)


@pytest.mark.asyncio
async def test_manifests_endpoint_reports_load_result(v24_tool_env, tmp_path):
    _enable_ext_face(v24_tool_env, tmp_path)
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    write_manifest(
        tmp_path,
        "broken_rule6.yaml",
        weather_manifest(tool_id="ext.api.weather.today", name="今日天气", permission={"level": "normal"}),
    )
    report = _run_startup_load()
    assert report.loaded == [WEATHER_TOOL_ID]

    response = await _get("/debug/tools/manifests")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["loaded"] == [WEATHER_TOOL_ID]
    assert body["total"] == 2
    assert body["path"] == str(tmp_path)
    assert body["skipped"][0]["rule"] == 6
    assert body["skipped"][0]["file"] == "broken_rule6.yaml"
    assert body["manifests"][0]["auth"]["env"] == WEATHER_ENV
    assert body["manifests"][0]["parameters"] == ["host", "city"]
    assert_no_secret(response.text)


@pytest.mark.asyncio
async def test_e17_external_tools_endpoint_hides_credentials(v24_tool_env, tmp_path):
    """E17：端点返回声明信息，断言响应体无 secret 模式串。"""
    _enable_ext_face(v24_tool_env, tmp_path)
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    _run_startup_load()

    response = await _get("/debug/tools/external")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["allowed_hosts"] == ["api.example.com"]
    assert body["host_whitelist_empty"] is False
    tool = body["tools"][0]
    assert tool["tool_id"] == WEATHER_TOOL_ID
    assert tool["status"] == "enabled"
    assert tool["http"]["method"] == "GET"
    assert tool["response_map"] == {
        "weather.temperature": "$.data.temperature:num",
        "weather.condition": "$.data.condition",
    }
    assert tool["auth"] == {
        "type": "bearer",
        "env": WEATHER_ENV,
        "header": "",
        "configured": True,
    }
    assert_no_secret(response.text)
    assert "api.example.com" in response.text


@pytest.mark.asyncio
async def test_manifests_endpoint_enabled_false_when_tool_system_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=False, TOOL_EXTERNAL_API_ENABLED=False)
    response = await _get("/debug/tools/manifests")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "path": "",
        "loaded": [],
        "skipped": [],
        "total": 0,
        "manifests": [],
    }


@pytest.mark.asyncio
async def test_manifests_endpoint_403_when_external_face_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_EXTERNAL_API_ENABLED=False)
    response = await _get("/debug/tools/manifests")
    assert response.status_code == 403
    assert "tool_external_api_enabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_external_endpoint_403_when_external_face_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_EXTERNAL_API_ENABLED=False)
    response = await _get("/debug/tools/external")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_external_endpoint_enabled_false_when_tool_system_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=False, TOOL_EXTERNAL_API_ENABLED=False)
    response = await _get("/debug/tools/external")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_external_endpoint_shows_empty_whitelist_as_all_disabled(v24_tool_env, tmp_path):
    _enable_ext_face(v24_tool_env, tmp_path, TOOL_EXT_ALLOWED_HOSTS="")
    response = await _get("/debug/tools/external")
    body = response.json()
    assert body["allowed_hosts"] == []
    assert body["host_whitelist_empty"] is True
    assert body["tools"] == []


@pytest.mark.asyncio
async def test_user_defined_endpoint_lists_and_revokes(v24_tool_env, tmp_path):
    _enable_ext_face(v24_tool_env, tmp_path)
    registered = user_defined.get_user_tool_registrar().register(user_declaration())
    assert registered == USER_TOOL_ID

    listed = await _get("/debug/tools/user-defined")
    assert listed.status_code == 200
    body = listed.json()
    assert body["enabled"] is True
    assert body["registered"] == [USER_TOOL_ID]
    tool = body["tools"][0]
    assert tool["level"] == "dangerous"
    assert tool["confirm"] == "first_time"
    assert tool["memory_deposit"] is False
    assert tool["side_effects"] == ["write_memory"]
    assert tool["steps"][0]["capability"] == "memory"
    assert tool["status"] == "enabled"

    unknown = await _post(f"/debug/tools/user-defined/user.ghost.tool/revoke")
    assert unknown.status_code == 404

    revoked = await _post(f"/debug/tools/user-defined/{USER_TOOL_ID}/revoke")
    assert revoked.status_code == 200
    assert revoked.json() == {
        "enabled": True,
        "tool_id": USER_TOOL_ID,
        "revoked": True,
        "registered": [],
    }
    assert user_defined.get_user_tool_registrar().list_registered() == []

    after = await _get("/debug/tools/user-defined")
    assert after.json()["registered"] == []


@pytest.mark.asyncio
async def test_user_defined_endpoint_403_when_flag_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_USER_DEFINED_ENABLED=False)
    assert (await _get("/debug/tools/user-defined")).status_code == 403
    assert (await _post("/debug/tools/user-defined/user.x.y/revoke")).status_code == 403


@pytest.mark.asyncio
async def test_user_defined_endpoint_enabled_false_when_tool_system_off(v24_tool_env):
    v24_tool_env(TOOL_SYSTEM_ENABLED=False, TOOL_USER_DEFINED_ENABLED=False)
    response = await _get("/debug/tools/user-defined")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "registered": [], "tools": []}


@pytest.mark.asyncio
async def test_existing_tool_endpoints_still_resolve_specific_routes(v24_tool_env, tmp_path):
    """新端点不得遮蔽既有 `/debug/tools/{tool_id}` 等具体路由。"""
    _enable_ext_face(v24_tool_env, tmp_path)
    surface = await _get("/debug/tools/surface")
    assert surface.status_code in (200, 403)
    detail = await _get("/debug/tools/ghost.tool.id")
    assert detail.status_code == 404
