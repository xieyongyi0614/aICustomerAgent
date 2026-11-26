"""V8 世界调试与运维端点（persistence.md §6 / testing.md §5）。

GET 均只读；POST 为显式手动通道（播种实体 / 设定环境 / 迁移位置 / 快照 / 事件）。
V2.3.0 WS-018 追加四个模拟观测端点（三个只读 + 一个调试触发），全部受总闸门控。
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core import timeutil
from app.api.v1.deps import debug_surface_gate
from pydantic import BaseModel

from app.api.v1.auth import require_user
from app.api.v1.schemas import (
    WorldPlanOut,
    WorldSimTickOut,
    WorldSimulationOut,
    WorldSituationsOut,
)
from app.application import world_engine
from app.repositories import world_repository

world_router = APIRouter(
    dependencies=[Depends(debug_surface_gate)], tags=["debug"]
)


class EntityCreate(BaseModel):
    user_id: str | None = None
    name: str
    category: str = "misc"
    location_id: str | None = None
    quantity: float = 1.0
    unit: str = ""
    consumable: bool = False
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


class EventCreate(BaseModel):
    user_id: str | None = None
    type: str
    title: str | None = None
    importance: str = "normal"
    due_at: datetime | None = None


class ConsumeBody(BaseModel):
    user_id: str | None = None
    object_ref: str
    quantity: float


class WorldSimTickBody(BaseModel):
    user_id: str | None = None


def _user(user_id: str | None, caller: str) -> str:
    """调试面身份：显式 user_id 优先，否则用 token 身份（默认用户概念已退役）。"""
    return user_id or caller


@world_router.get("/debug/world")
def get_world_state(
    user_id: str | None = None, caller: str = Depends(require_user)
):
    state = world_engine.get_full_state(_user(user_id, caller))
    if state is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return state


@world_router.post("/debug/world/entities")
def create_entity(body: EntityCreate, caller: str = Depends(require_user)):
    obj = world_engine.create_object(
        _user(body.user_id, caller),
        name=body.name,
        category=body.category,
        location_id=body.location_id,
        quantity=body.quantity,
        unit=body.unit,
        consumable=body.consumable,
        aliases=body.aliases,
        **body.properties,
    )
    if obj is None:
        raise HTTPException(status_code=409, detail="实体创建失败（上限或参数非法）")
    return obj.model_dump(mode="json")


@world_router.post("/debug/world/consume")
def consume(body: ConsumeBody, caller: str = Depends(require_user)):
    result = world_engine.consume_object(
        _user(body.user_id, caller), body.object_ref, body.quantity
    )
    if not result.ok:
        return {
            "ok": False,
            "error": result.error.value if result.error else "ERROR",
        }
    return {"ok": True, "object": result.object.name, "quantity": result.object.quantity}


@world_router.get("/debug/world/locations/{location_id}/objects")
def list_objects_at_location(
    location_id: str, user_id: str | None = None, caller: str = Depends(require_user)
):
    return [
        obj.model_dump(mode="json")
        for obj in world_engine.get_objects_by_location(_user(user_id, caller), location_id)
    ]


@world_router.get("/debug/world/consumables")
def list_consumables(
    user_id: str | None = None, caller: str = Depends(require_user)
):
    return [
        obj.model_dump(mode="json")
        for obj in world_engine.get_available_consumables(_user(user_id, caller))
    ]


@world_router.post("/debug/world/environment")
def update_environment(body: EnvironmentUpdate, caller: str = Depends(require_user)):
    world = world_engine.set_environment(
        _user(body.user_id, caller),
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
def update_location(body: LocationUpdate, caller: str = Depends(require_user)):
    world = world_engine.set_location(_user(body.user_id, caller), body.location_id)
    if world is None:
        raise HTTPException(status_code=404, detail="地点不存在")
    return {"current_location": world.current_location}


@world_router.get("/debug/world/events")
def list_world_events(
    user_id: str | None = None, caller: str = Depends(require_user)
):
    world = world_engine.get_world(_user(user_id, caller))
    if world is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return [
        event.model_dump(mode="json")
        for event in world_repository.list_events(world.world_id, limit=100)
    ]


@world_router.post("/debug/world/events")
def create_world_event(body: EventCreate, caller: str = Depends(require_user)):
    event = world_engine.create_event(
        _user(body.user_id, caller),
        event_type=body.type,
        title=body.title,
        importance=body.importance,
        due_at=body.due_at,
        source="manual",
    )
    if event is None:
        raise HTTPException(status_code=409, detail="事件创建失败（上限或参数非法）")
    return event.model_dump(mode="json")


@world_router.get("/debug/world/snapshots/{snapshot_id}")
def get_world_snapshot(
    snapshot_id: str, user_id: str | None = None, caller: str = Depends(require_user)
):
    world = world_engine.get_world(_user(user_id, caller))
    if world is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    snapshot = world_repository.get_snapshot(world.world_id, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    return snapshot.model_dump(mode="json")


@world_router.post("/debug/world/snapshots/{snapshot_id}/restore")
def restore_world_snapshot(
    snapshot_id: str, user_id: str | None = None, caller: str = Depends(require_user)
):
    world = world_engine.restore_snapshot(_user(user_id, caller), snapshot_id)
    if world is None:
        raise HTTPException(status_code=404, detail="快照不存在或恢复失败")
    return {"current_location": world.current_location, "restored": snapshot_id}


@world_router.post("/debug/world/snapshots")
def create_snapshot(body: SnapshotCreate, caller: str = Depends(require_user)):
    snapshot = world_engine.snapshot(_user(body.user_id, caller), label=body.label)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="快照失败")
    return snapshot.model_dump(mode="json")


@world_router.get("/debug/world/snapshots")
def list_world_snapshots(
    user_id: str | None = None, caller: str = Depends(require_user)
):
    world = world_engine.get_world(_user(user_id, caller))
    if world is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return [
        item.model_dump(mode="json")
        for item in world_repository.list_snapshots(world.world_id)
    ]


@world_router.get("/debug/world/simulation", response_model=WorldSimulationOut)
def get_world_simulation(
    user_id: str | None = None, caller: str = Depends(require_user)
):
    """WS-018：模拟总览（时间上下文 / 简报 / 当前日程块 / 活跃处境 / 近期模拟事件）。"""
    data = world_engine.build_debug_simulation(_user(user_id, caller))
    if data is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return WorldSimulationOut(enabled=True, **data)


@world_router.get("/debug/world/plan", response_model=WorldPlanOut)
def get_world_plan(
    user_id: str | None = None,
    date_str: str | None = Query(default=None, alias="date"),
    caller: str = Depends(require_user),
):
    """WS-018：当日计划（缺省今日）；未生成时返回空列表，不落库。"""
    user = _user(user_id, caller)
    if world_engine.get_world(user) is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    try:
        day = date.fromisoformat(date_str) if date_str else timeutil.local_now().date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date 参数格式应为 YYYY-MM-DD")
    blocks = world_engine.build_debug_plan(user, day)
    return WorldPlanOut(enabled=True, date=day.isoformat(), blocks=blocks)


@world_router.get("/debug/world/situations", response_model=WorldSituationsOut)
def get_world_situations(
    user_id: str | None = None,
    include_expired: bool = False,
    caller: str = Depends(require_user),
):
    """WS-018：用户处境（缺省仅 active；include_expired=True 含 expired/dismissed）。"""
    user = _user(user_id, caller)
    if world_engine.get_world(user) is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return WorldSituationsOut(
        enabled=True,
        situations=world_engine.build_debug_situations(user, include_expired),
    )


@world_router.post("/debug/world/simulation/tick", response_model=WorldSimTickOut)
def trigger_world_simulation_tick(
    body: WorldSimTickBody, caller: str = Depends(require_user)
):
    """WS-018：手动执行一次模拟维护步。"""
    user = _user(body.user_id, caller)
    if world_engine.get_world(user) is None and world_engine.ensure_world(user) is None:
        raise HTTPException(status_code=404, detail="世界不可用")
    return WorldSimTickOut(enabled=True, result=world_engine.run_debug_tick(user))
