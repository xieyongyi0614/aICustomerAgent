"""TOOL-010 §2.3：`search` 路线 B 降级与 `notification` 行动 note 推进（E1、E14）。"""

from pathlib import Path

import pytest

from app.character.asuna.tool import TOOL_FAILURE_TEXT
from app.models.action import CapabilityResult
from app.services.action.capabilities.notification import (
    NOTE_ID_PREFIX,
    NOTIFICATION_CONTENT_MAX_CHARS,
    NotificationCapability,
)
from app.services.action.capabilities.search import (
    REASON_SOURCE_NOT_CONFIGURED,
    SEARCH_QUERY_MAX_CHARS,
    SearchCapability,
)
from app.services.action.registry import ExecutionContext
from app.services.tool.normalizer import ObservationNormalizer, ExecutionMeta
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from tests.v24.tool003_support import tool_settings
from tests.v24.tool010_support import (
    CHANNEL_TOOL_ID,
    NOTIFICATION_TOOL_ID,
    NOW,
    SEARCH_TOOL_ID,
    USER,
    reset_runtime_state,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

V9_UNAVAILABLE_PAYLOAD = {"failure_kind": "unavailable"}


@pytest.fixture(autouse=True)
def _isolate_singletons():
    reset_runtime_state()
    yield
    reset_runtime_state()


def _ctx(enabled: bool) -> ExecutionContext:
    return ExecutionContext(
        user_id=USER,
        record_id="act-tool010",
        now=NOW,
        settings=tool_settings(),
        dedupe_key="dk-tool010",
    )


def _definition(tool_id: str):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    definition = registry.get(tool_id)
    assert definition is not None
    return definition


# --- search：路线 B（保持 unavailable，但不留空壳） ----------------------------


async def test_search_flag_off_is_byte_identical_to_v9():
    result = await SearchCapability().execute("query", {"query": "天气"}, _ctx(False))
    assert result.status == "unavailable"
    assert result.error == "该能力尚未接入"
    assert result.payload == V9_UNAVAILABLE_PAYLOAD


async def test_search_flag_on_reports_decidable_degradation():
    result = await SearchCapability().execute("query", {"query": "天气"}, _ctx(True))
    assert result.status == "unavailable"
    assert result.payload["failure_kind"] == "unavailable"
    assert result.payload["reason_kind"] == REASON_SOURCE_NOT_CONFIGURED
    assert result.payload["retryable"] is False
    assert result.payload["result_count"] == 0
    assert result.payload["untrusted"] is True
    assert result.payload["message"] == TOOL_FAILURE_TEXT[SEARCH_TOOL_ID]


async def test_search_degradation_message_is_character_voiced_and_readable():
    message = TOOL_FAILURE_TEXT[SEARCH_TOOL_ID]
    assert message.endswith(("。", "！", "？"))
    assert "系统" not in message and "接口" not in message
    assert len(message) <= 60


async def test_route_b_has_no_retrieval_source_dependency():
    source = (BACKEND_ROOT / "app/services/action/capabilities/search.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("httpx", "requests", "urllib", "socket", "aiohttp"):
        assert forbidden not in source


def test_search_validate_enforces_declared_query_budget():
    assert SearchCapability().validate("query", {"query": "x"}) == []
    errors = SearchCapability().validate("query", {"query": "长" * (SEARCH_QUERY_MAX_CHARS + 1)})
    assert any(str(SEARCH_QUERY_MAX_CHARS) in error for error in errors)
    assert SearchCapability().validate("ghost", {}) == ["未知动作: ghost"]


async def test_search_unknown_action_fails_with_permanent_kind():
    result = await SearchCapability().execute("ghost", {}, _ctx(True))
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "permanent"


# --- notification：行动 note -------------------------------------------------


async def test_notification_flag_off_is_byte_identical_to_v9():
    result = await NotificationCapability().execute("send", {"content": "喝水"}, _ctx(False))
    assert result.status == "unavailable"
    assert result.error == "该能力尚未接入"
    assert result.payload == V9_UNAVAILABLE_PAYLOAD


async def test_notification_flag_on_produces_action_note():
    result = await NotificationCapability().execute("send", {"content": "记得喝水"}, _ctx(True))
    assert result.status == "succeeded"
    assert result.payload["note_created"] is True
    assert result.payload["note_id"].startswith(f"{NOTE_ID_PREFIX}:")
    assert result.payload["content"] == "记得喝水"
    assert result.payload["delivered_next_turn"] is True
    assert result.payload["created_at"].startswith("2026-09-14T12:00:00")
    assert result.payload["failure_kind"] is None


async def test_notification_note_id_is_deterministic_per_request():
    capability = NotificationCapability()
    first = await capability.execute("send", {"content": "记得喝水"}, _ctx(True))
    second = await capability.execute("send", {"content": "记得喝水"}, _ctx(True))
    other = await capability.execute("send", {"content": "记得吃饭"}, _ctx(True))
    assert first.payload["note_id"] == second.payload["note_id"]
    assert first.payload["note_id"] != other.payload["note_id"]


async def test_notification_empty_content_and_unknown_action_fail_closed():
    empty = await NotificationCapability().execute("send", {"content": "   "}, _ctx(True))
    assert empty.status == "failed"
    assert empty.payload["failure_kind"] == "permanent"
    assert empty.payload["message"] == TOOL_FAILURE_TEXT[NOTIFICATION_TOOL_ID]
    unknown = await NotificationCapability().execute("ghost", {}, _ctx(True))
    assert unknown.status == "failed"
    assert unknown.payload["reason_kind"] == "unknown_action"


def test_notification_validate_enforces_declared_content_budget():
    assert NotificationCapability().validate("send", {"content": "x"}) == []
    errors = NotificationCapability().validate(
        "send", {"content": "长" * (NOTIFICATION_CONTENT_MAX_CHARS + 1)}
    )
    assert any(str(NOTIFICATION_CONTENT_MAX_CHARS) in error for error in errors)


def test_e14_notification_never_sends_external():
    """E14｜note 只落行动素材：实现体零网络、零通道依赖，离线不外发。"""
    source = (BACKEND_ROOT / "app/services/action/capabilities/notification.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "app.channels",
        "OutboundMessage",
        "httpx",
        "requests",
        "urllib",
        "socket",
    ):
        assert forbidden not in source


def test_note_normalizes_to_note_effect_and_observation():
    definition = _definition(NOTIFICATION_TOOL_ID)
    raw = CapabilityResult(
        status="succeeded",
        payload={
            "note_id": "note:abc",
            "note_created": True,
            "content": "记得喝水",
            "failure_kind": None,
        },
    )
    result = ObservationNormalizer().normalize(
        definition,
        raw,
        ExecutionMeta(tool_id=NOTIFICATION_TOOL_ID, duration_ms=1.0),
    )
    assert [(effect.kind, effect.ref) for effect in result.effects] == [("note", "note:abc")]
    assert result.effects[0].detail == "记得喝水"
    assert result.effects[0].reversible is True
    assert result.observations == {"note.created": True}


def test_channel_definition_is_the_only_external_face():
    """外发面唯一：note 与通道工具在 observations 与 effects 上完全可区分。"""
    channel_raw = CapabilityResult(
        status="succeeded",
        payload={
            "external_sent": True,
            "external_message_id": "om-9",
            "content": "在吗",
            "failure_kind": None,
        },
    )
    result = ObservationNormalizer().normalize(
        _definition(CHANNEL_TOOL_ID),
        channel_raw,
        ExecutionMeta(tool_id=CHANNEL_TOOL_ID, duration_ms=1.0),
    )
    assert [(effect.kind, effect.ref, effect.reversible) for effect in result.effects] == [
        ("external", "om-9", False)
    ]
    assert result.observations == {"external.message_id": "om-9"}
