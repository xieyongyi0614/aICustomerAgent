"""TOOL-010 单测共享构造：通道适配器替身、脚本化能力、环境开关与声明读取。"""

from datetime import datetime

from app.channels.base import ChannelErrorKind, SendResult
from app.core.settings import get_settings
from app.models.action import ActionSchema, CapabilityResult
from app.models.tool import ToolDefinition
from app.services.action import registry as capability_registry_module
from app.services.tool import channel_tools
from app.services.tool import registry as tool_registry
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools

NOW = datetime(2026, 9, 14, 12, 0, 0)

USER = "u-tool010"

EXTERNAL_ID = "ou_asuna"

CHANNEL_TOOL_ID = "channel.feishu.send"

SEARCH_TOOL_ID = "builtin.search.query"

NOTIFICATION_TOOL_ID = "builtin.notification.send"

BUILTIN_TOOL_IDS: tuple[str, ...] = (
    "builtin.memory.save",
    "builtin.notification.send",
    "builtin.reminder.cancel",
    "builtin.reminder.create",
    "builtin.search.query",
    CHANNEL_TOOL_ID,
    "world.env.query",
    "world.object.create",
    "world.object.move",
    "world.object.use",
)

# 通道未绑定时的注册表 enabled 集合（检索工具仍 enabled，只是不进工具面）。
ENABLED_TOOL_IDS: tuple[str, ...] = tuple(
    tool_id for tool_id in BUILTIN_TOOL_IDS if tool_id != CHANNEL_TOOL_ID
)

MATRIX_TOOL_IDS: tuple[str, ...] = BUILTIN_TOOL_IDS

FEISHU_BINDING_ENVS: dict[str, object] = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_test",
    "feishu_app_secret": "test_secret",
    "feishu_verification_token": "test_token",
}

CHANNEL_ENVS: dict[str, object] = {
    **FEISHU_BINDING_ENVS,
}


def enable(monkeypatch, **envs: object) -> None:
    """按 KEY=VALUE 注入环境开关并清理 settings 缓存（与 v24 conftest 同款手法）。"""
    for key, value in envs.items():
        text = str(value).lower() if isinstance(value, bool) else str(value)
        monkeypatch.setenv(key.upper(), text)
    get_settings.cache_clear()


def reset_runtime_state() -> None:
    """四类进程内单例归零：工具注册表、能力注册表、通道适配器、settings 缓存。"""
    tool_registry._registry = None
    capability_registry_module._registry = None
    channel_tools.reset_channel_adapters()
    get_settings.cache_clear()


def builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


class RecordingAdapter:
    """出站适配器替身：记录 OutboundMessage，按脚本返回 SendResult（默认成功）。"""

    def __init__(self, *results: SendResult) -> None:
        self.messages: list[object] = []
        self._results = list(results)

    async def send(self, message):
        self.messages.append(message)
        if self._results:
            return self._results.pop(0)
        return SendResult(ok=True, external_message_id="om-1")

    @property
    def idempotency_keys(self) -> list[str | None]:
        return [getattr(message, "idempotency_key", None) for message in self.messages]

    @property
    def texts(self) -> list[str]:
        return [getattr(message, "text", "") for message in self.messages]


def failure(error: ChannelErrorKind) -> SendResult:
    return SendResult(ok=False, error=error)


class ScriptedCapability:
    """打桩能力实现体：多动作、记录调用、按工具产出可识别的 payload。"""

    def __init__(self, name: str, actions: dict[str, list[str]]) -> None:
        self.name = name
        self.description = "打桩能力"
        self.actions = {
            action: ActionSchema(required=list(required))
            for action, required in actions.items()
        }
        self.calls: list[tuple[str, dict]] = []

    def validate(self, action: str, params: dict) -> list[str]:
        return []

    async def execute(self, action: str, params: dict, ctx) -> CapabilityResult:
        self.calls.append((action, dict(params)))
        return CapabilityResult(
            status="succeeded",
            payload=dict(SUCCESS_PAYLOADS[f"{self.name}.{action}"]),
        )


SUCCESS_PAYLOADS: dict[str, dict] = {
    "reminder.create": {
        "world_event_id": "evt-1",
        "due_at": "2026-09-15T08:00:00",
        "failure_kind": None,
    },
    "reminder.cancel": {"cancelled": 1, "failure_kind": None},
    "memory.save": {"memory_id": "mem-1", "failure_kind": None},
    "world_action.create": {
        "object_id": "obj-1",
        "location_id": "loc-1",
        "failure_kind": None,
    },
    "world_action.move": {
        "object_id": "obj-1",
        "location_id": "loc-1",
        "failure_kind": None,
    },
    "world_action.use": {
        "object_id": "obj-1",
        "location_id": "loc-1",
        "failure_kind": None,
    },
    "environment_query.query": {
        "weather": "sunny",
        "part_of_day": "afternoon",
        "location": "home.kitchen",
        "failure_kind": None,
    },
    "search.query": {"result_count": 0, "failure_kind": None},
    "notification.send": {
        "note_id": "note-1",
        "note_created": True,
        "content": "提醒你喝水",
        "failure_kind": None,
    },
    "channel_feishu.send": {
        "external_sent": True,
        "external_message_id": "om-1",
        "content": "在吗",
        "failure_kind": None,
    },
}

CAPABILITY_ACTIONS: dict[str, dict[str, list[str]]] = {
    "reminder": {"create": ["content", "due_at"], "cancel": ["target"]},
    "memory": {"save": ["fact"]},
    "world_action": {
        "create": ["object"],
        "move": ["object", "location"],
        "use": ["object"],
    },
    "environment_query": {"query": []},
    "search": {"query": ["query"]},
    "notification": {"send": ["content"]},
    "channel_feishu": {"send": ["content", "recipient"]},
}

EXPECTED_OBSERVATIONS: dict[str, dict[str, object]] = {
    "builtin.reminder.create": {
        "world.event_id": "evt-1",
        "time.due_at": "2026-09-15T08:00:00",
    },
    "builtin.reminder.cancel": {"world.cancelled_count": 1},
    "builtin.memory.save": {"memory.id": "mem-1"},
    "world.object.create": {"world.object_id": "obj-1", "world.location_id": "loc-1"},
    "world.object.move": {"world.object_id": "obj-1", "world.location_id": "loc-1"},
    "world.object.use": {"world.object_id": "obj-1", "world.location_id": "loc-1"},
    "world.env.query": {
        "env.weather": "sunny",
        "env.part_of_day": "afternoon",
        "env.location": "home.kitchen",
    },
    "builtin.notification.send": {"note.created": True},
    "channel.feishu.send": {"external.message_id": "om-1"},
    SEARCH_TOOL_ID: {
        "search.result_count": 0,
        "search.untrusted": True,
        "search.results": [],
    },
}

VALID_PARAMS: dict[str, dict] = {
    "builtin.reminder.create": {"content": "开会", "due_at": "2026-09-15T08:00:00"},
    "builtin.reminder.cancel": {"target": "开会"},
    "builtin.memory.save": {"fact": "用户喜欢咖啡", "importance": 0.8},
    "world.object.create": {"object": "牛奶", "category": "food"},
    "world.object.move": {"object": "苹果", "location": "home.kitchen"},
    "world.object.use": {"object": "苹果"},
    "world.env.query": {"dimension": "weather"},
    "builtin.search.query": {"query": "明天天气"},
    "builtin.notification.send": {"content": "记得喝水"},
    CHANNEL_TOOL_ID: {"content": "在吗", "recipient": EXTERNAL_ID},
}

INVALID_PARAMS: dict[str, tuple[dict, str]] = {
    "builtin.reminder.create": (
        {"content": "开会", "due_at": "2020-01-01T00:00:00"},
        "not_future",
    ),
    "builtin.reminder.cancel": ({}, "missing_required"),
    "builtin.memory.save": ({"fact": "用户喜欢咖啡", "importance": 1.5}, "range_violated"),
    "world.object.create": ({"object": "牛奶", "category": "ghost"}, "enum_invalid"),
    "world.object.move": ({"object": "苹果", "location": "ghost_place"}, "location_not_found"),
    "world.object.use": ({"object": "不存在的书"}, "object_not_in_inventory"),
    "world.env.query": ({"dimension": "ghost"}, "enum_invalid"),
    "builtin.search.query": ({"query": "长" * 61}, "length_violated"),
    "builtin.notification.send": ({"content": "长" * 201}, "length_violated"),
    CHANNEL_TOOL_ID: (
        {"content": "在吗", "recipient": "ou_unauthorized"},
        "recipient_not_authorized",
    ),
}


def tool_context(ctx_settings, **overrides) -> ToolContext:
    """世界事实已装配的上下文：地点词表 + 非空库存 + 已授权收件人（TOOL-005/007 供给面）。"""
    payload: dict = {
        "user_id": USER,
        "now": NOW,
        "settings": ctx_settings,
        "world": {"world_enabled": True, "locations": ("home.kitchen", "home.study")},
        "inventory": ["苹果"],
        "authorized_recipients": [EXTERNAL_ID],
        "dedupe_key": "dk-tool010",
    }
    payload.update(overrides)
    return ToolContext(**payload)


def definitions_by_id() -> dict[str, ToolDefinition]:
    return {item.id: item for item in builtin_registry().list()}
