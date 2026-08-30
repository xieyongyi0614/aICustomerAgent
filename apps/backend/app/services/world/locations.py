"""V8 地点装配（location-system.md §2~§4）：层级路径、可用动作、别名解析。

地点是静态设定（角色资产）+ 动态所在位置（worlds.current_location）。
不读写 scene_state——叙事位置与世界事实独立并存。
"""

from app.character.asuna.world import HOME_LOCATIONS, LOCATION_ALIASES
from app.models.world import LocationContext, World


def build_location_context(world: World) -> LocationContext | None:
    definition = HOME_LOCATIONS.get(world.current_location)
    if definition is None:
        return None
    path_ids = []
    cursor = world.current_location
    while cursor is not None:
        path_ids.append(cursor)
        cursor = HOME_LOCATIONS[cursor]["parent_id"]
    path_names = [HOME_LOCATIONS[loc]["name"] for loc in reversed(path_ids)]
    return LocationContext(
        current=world.current_location,
        current_name=definition["name"],
        path=path_names,
        available_actions=list(definition["available_actions"]),
        traits=list(definition["traits"]),
    )


def resolve_location_alias(text: str) -> str | None:
    """从消息文本解析已定义地点；最长别名优先，未命中返回 None（宁缺毋滥）。"""
    for alias in sorted(LOCATION_ALIASES, key=len, reverse=True):
        if alias in text:
            return LOCATION_ALIASES[alias]
    return None


def location_name(location_id: str) -> str | None:
    definition = HOME_LOCATIONS.get(location_id)
    return definition["name"] if definition else None
