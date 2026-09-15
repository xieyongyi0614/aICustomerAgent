"""V9 内置能力注册（capability-system.md §4 MVP 清单）。

V2.4.0 TOOL-010：通道工具能力 `channel_feishu` 在**通道可用时**追加注册
（`channel_tools_enabled()` = 总闸 + 通道子闸 + `feishu_enabled`）。
默认配置下注册表仍是 V9 的六个能力——`tests/unit` 与 `tests/v9` 对
`get_capability_registry().describe()` 的断言逐字节不变；
通道开关打开时 `channel.feishu.send` 才有可执行实现体（否则该工具是
声明态 `disabled`，不进工具面，见 `tool/builtin.py`）。

V2.4.0 TOOL-011：外部 API 能力 `external_api` 在**外部面双闸开启时**追加注册
（`external_api_enabled()` = 总闸 + `v24_tool_external_api_enabled`），
使声明式清单生成的 `ext.api.*` 工具在统一执行器内可解析到实现体。
用户自定义工具的能力体（能力名 = tool_id）由 `tool/user_defined.py` 在注册时按需登记，
注销走 `CapabilityRegistry.unregister`。

**语义边界（P1-1）：注册表内容 = `register_builtin` 被调用那一刻的 flag 快照，进程内冻结。**
条件注册只读构建时的开关；`get_capability_registry()` 只构建一次（模块级单例），
因此"先构建、后开闸"不会补注册通道 / 外部能力，排障请读
`app.services.action.registry.capability_registry_flags()`（构建期快照，经
`/debug/tools` 的 `capability_flags` 字段暴露）。条件注册本身不改：默认配置下注册表
仍是 V9 的六个能力。
"""

from app.services.action.registry import CapabilityRegistry
from app.services.tool.channel_tools import channel_tools_enabled, get_channel_capability
from app.services.tool.ext_api import external_api_enabled, get_external_api_capability


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
    if external_api_enabled():
        registry.register(get_external_api_capability())
