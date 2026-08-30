"""V8 世界调试与运维端点（persistence.md §6 / testing.md §5）。

GET 均只读；POST 为显式手动通道（播种实体 / 设定环境 / 迁移位置 / 快照）。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.application import world_engine
from app.core.settings import get_settings

world_router = APIRouter()


class EntityCreate(BaseModel):
    user_id: str | None = None
    name: str
    category: str = "misc"
    location_id: str | None = None
    quantity: float = 1.0
    aliases: list[str] = []
    properties: dict = {}


class EnvironmentUpdate(BaseModel):
    user_id: str | None = None
    weather: str | None = None
    temperature_c: float | None = None
    lighting: str | None = None
    noise: str | None = None
    atmosphere: str | None = None


class LocationUpdate(BaseModel):
    user_id: str | None = None
    location_id: str


class SnapshotCreate(BaseModel):
    user_id: str | None = None
    label: str | None = None


def _user(user_id: str | None) -> str:
    return user_id or get_settings().default_user


@world_router.get("/debug/world")
def get_world_state(user_id: str | None = None):
    state = world_engine.get_full_state(_user(user_id))
    if state is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return state


@world_router.post("/debug/world/entities")
def create_entity(body: EntityCreate):
    obj = world_engine.create_object(
        _user(body.user_id),
        name=body.name,
        category=body.category,
        location_id=body.location_id,
        quantity=body.quantity,
        aliases=body.aliases,
        **body.properties,
    )
    if obj is None:
        raise HTTPException(status_code=409, detail="实体创建失败（上限或参数非法）")
    return obj.model_dump(mode="json")


@world_router.post("/debug/world/environment")
def update_environment(body: EnvironmentUpdate):
    world = world_engine.set_environment(
        _user(body.user_id),
        weather=body.weather,
        temperature_c=body.temperature_c,
        lighting=body.lighting,
        noise=body.noise,
        atmosphere=body.atmosphere,
    )
    if world is None:
        raise HTTPException(status_code=409, detail="环境更新失败")
    return world.environment.model_dump(mode="json")


@world_router.post("/debug/world/location")
def update_location(body: LocationUpdate):
    world = world_engine.set_location(_user(body.user_id), body.location_id)
    if world is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    return {"current_location": world.current_location}


@world_router.post("/debug/world/snapshots")
def create_snapshot(body: SnapshotCreate):
    snapshot = world_engine.snapshot(_user(body.user_id), label=body.label)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="快照失败")
    return snapshot.model_dump(mode="json")


@world_router.get("/debug/world/snapshots")
def list_world_snapshots(user_id: str | None = None):
    from app.repositories import world_repository

    world = world_engine.get_world(_user(user_id))
    if world is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return [
        item.model_dump(mode="json")
        for item in world_repository.list_snapshots(world.world_id)
    ]
