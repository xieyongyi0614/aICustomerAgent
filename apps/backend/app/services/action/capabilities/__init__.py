"""V9 内置能力注册（capability-system.md §4 MVP 清单）。"""

from app.services.action.registry import CapabilityRegistry


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
