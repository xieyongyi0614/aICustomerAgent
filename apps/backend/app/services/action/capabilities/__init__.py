"""V9 内置能力注册（capability-system.md §4 MVP 清单）。

V2.4.0 TOOL-010：通道工具能力 `channel_feishu` 在**通道可用时**追加注册
（`channel_tools_enabled()` = 总闸 + 通道子闸 + `feishu_enabled`）。
默认配置下注册表仍是 V9 的六个能力——`tests/unit` 与 `tests/v9` 对
`get_capability_registry().describe()` 的断言逐字节不变；
通道开关打开时 `channel.feishu.send` 才有可执行实现体（否则该工具是
声明态 `disabled`，不进工具面，见 `tool/builtin.py`）。
"""

from app.services.action.registry import CapabilityRegistry
from app.services.tool.channel_tools import channel_tools_enabled, get_channel_capability


def register_builtin(registry: CapabilityRegistry) -> None:
    from app.services.action.capabilities.environment_query import EnvironmentQueryCapability
    from app.services.action.capabilities.memory import MemoryCapability
    from app.services.action.capabilities.notification import NotificationCapability
    from app.services.action.capabilities.reminder import ReminderCapability
    from app.services.action.capabilities.search import SearchCapability
    from app.services.action.capabilities.world_action import WorldActionCapability

    registry.register(ReminderCapability())
    registry.register(MemoryCapability())
    registry.register(WorldActionCapability())
    registry.register(EnvironmentQueryCapability())
    registry.register(SearchCapability())
    registry.register(NotificationCapability())
    if channel_tools_enabled():
        registry.register(get_channel_capability())
