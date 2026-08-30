"""V8 Context Builder Test（tests/v8 版本级）：切片正确进入渲染。"""

from app.application import world_engine
from app.services.world.context_selector import render_world_section


def test_context_reflects_world_after_updates(db_session_factory):
    world_engine.ensure_world("default-user")
    world_engine.create_object("default-user", name="西瓜", category="food", location_id="home.living_room")
    world_engine.run_turn_update("default-user", "外面下雨了记得关窗")

    context = world_engine.build_context("default-user")
    assert context is not None
    assert context.location.current_name == "客厅"
    assert context.environment.weather == "rain"
    text = render_world_section(context)
    assert "【当前世界】" in text
    assert "西瓜" in text
    assert "下雨" in text or "下着雨" in text


def test_context_budget_respected(db_session_factory):
    world_engine.ensure_world("default-user")
    for index in range(5):
        world_engine.create_object(
            "default-user", name=f"物品{index}", category="misc", location_id="home.living_room"
        )
    context = world_engine.build_context("default-user")
    text = render_world_section(context, budget=150)
    assert len(text) <= 150
