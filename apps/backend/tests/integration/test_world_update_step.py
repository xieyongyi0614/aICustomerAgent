"""V8-006 post_process 第 8 步：世界迁移落库 + 降级契约。"""

from app.application import post_process, world_engine
from app.application.post_process import PostProcessContext
from app.repositories import world_repository


def _ctx(user_id="default-user", message="给我拿个西瓜"):
    return PostProcessContext(
        session_id="s-world",
        user_id=user_id,
        user_input=message,
        ai_reply="好呀，稍等哦。",
        state=None,
        analysis=None,
    )


async def test_run_world_update_applies_transitions(db_session_factory, monkeypatch):
    world_engine.ensure_world("default-user")
    world_engine.create_object(
        "default-user", name="西瓜", category="food", location_id="home.kitchen.fridge", aliases=["瓜"]
    )

    async def _explode():
        raise RuntimeError("不应被调用")

    await post_process.run_world_update(_ctx())

    world = world_engine.get_world("default-user")
    assert world.current_location == "home.living_room"
    obj = world_engine.find_object_by_name("default-user", "西瓜")
    assert obj.location_id == "home.living_room"
    refreshed = world_repository.get_world("default-user")
    assert refreshed.notes, "解释备注应写入世界行"


async def test_run_world_update_swallows_engine_crash(db_session_factory, monkeypatch):
    world_engine.ensure_world("default-user")

    def _explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(world_engine, "run_turn_update", _explode)
    await post_process.run_world_update(_ctx(message="随便聊聊"))


def test_step_registry_includes_world_update():
    assert post_process.STEP_HANDLERS[-1].__name__ == "run_world_update"
