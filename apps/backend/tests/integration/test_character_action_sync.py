"""ACTION-005 集成：角色动作 → 事件 → 下一轮上下文最近世界变化闭环。"""

import asyncio

from app.application import world_engine
from app.application.post_process import (
    STEP_HANDLERS,
    PostProcessContext,
    run_character_action_sync,
    run_action_planning,
)
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.repositories import world_repository
from app.services.world.context_selector import render_world_section


def _ctx(
    user_id: str,
    ai_reply: str = "",
    user_input: str = "",
    session_id: str = "s1",
    current_turn: int = 1,
) -> PostProcessContext:
    return PostProcessContext(
        session_id=session_id,
        user_id=user_id,
        user_input=user_input,
        ai_reply=ai_reply,
        state=ConversationState(
            session_id=session_id,
            user_id=user_id,
            messages=[],
            summary=None,
            memories=[],
            current_input=user_input,
        ),
        analysis=TurnAnalysis(),
        current_turn=current_turn,
    )


def _run(ctx: PostProcessContext) -> None:
    asyncio.run(run_character_action_sync(ctx))


def _world_notes(user_id: str) -> list[str]:
    world = world_engine.get_world(user_id)
    assert world is not None
    return list(world.notes or [])


def test_consume_closed_loop(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u1", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u1", ai_reply="我用了两个鸡蛋。", current_turn=1))

    egg = world_engine.find_object_by_name("cas-u1", "鸡蛋")
    assert egg is not None
    assert egg.quantity == 4.0
    assert "消耗鸡蛋 ×2" in _world_notes("cas-u1")

    context = world_engine.build_context("cas-u1")
    assert context is not None
    assert context.recent_world_changes == ["消耗鸡蛋 ×2"]
    text = render_world_section(context)
    assert "最近世界变化：" in text
    assert "  - 消耗鸡蛋 ×2" in text
    assert text.index("鸡蛋 × 4") < text.index("最近世界变化：")


def test_create_closed_loop(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.ensure_world("cas-u2")
    _run(_ctx("cas-u2", ai_reply="我做好了一碗面。", current_turn=1))

    made = world_engine.find_object_by_name("cas-u2", "面")
    assert made is not None
    assert made.quantity == 1.0
    context = world_engine.build_context("cas-u2")
    assert context.recent_world_changes == ["做出面"]
    assert "做出面" in render_world_section(context)


def test_gate_off_is_byte_identical(db_session_factory):
    world_engine.create_object(
        "cas-u3", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world_engine.record_character_action_event(
        "cas-u3",
        action_type="CONSUME",
        target_name="鸡蛋",
        quantity=2.0,
        object_id=None,
        before={"quantity": 6.0},
        after={"quantity": 4.0},
        location_from=None,
        location_to=None,
        dedupe_key="dk-off",
        session_id="s1",
        turn_id="t1",
    )

    context = world_engine.build_context("cas-u3")
    assert context is not None
    assert context.recent_world_changes == []
    text = render_world_section(context)
    assert "最近世界变化" not in text


def test_gate_on_after_events_renders_tag(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u4", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world_engine.record_character_action_event(
        "cas-u4",
        action_type="CONSUME",
        target_name="鸡蛋",
        quantity=2.0,
        object_id=None,
        before={"quantity": 6.0},
        after={"quantity": 4.0},
        location_from=None,
        location_to=None,
        dedupe_key="dk-on",
        session_id="s1",
        turn_id="t1",
    )
    context = world_engine.build_context("cas-u4")
    assert context.recent_world_changes == ["消耗鸡蛋 ×2"]


def test_no_applied_actions_keeps_notes_untouched(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u5", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=1.0
    )
    world = world_engine.get_world("cas-u5")
    world.notes = ["鸡蛋已从冰箱取出"]
    world_repository.save_world(world)

    _run(_ctx("cas-u5", ai_reply="我用掉三个鸡蛋。", current_turn=1))
    assert _world_notes("cas-u5") == ["鸡蛋已从冰箱取出"]


def test_interpreter_and_cas_notes_coexist(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u6", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world = world_engine.get_world("cas-u6")
    world.notes = ["鸡蛋已从冰箱取出"]
    world_repository.save_world(world)

    _run(_ctx("cas-u6", ai_reply="我用了两个鸡蛋。", current_turn=1))
    notes = _world_notes("cas-u6")
    assert "鸡蛋已从冰箱取出" in notes
    assert "消耗鸡蛋 ×2" in notes
    assert notes.index("鸡蛋已从冰箱取出") < notes.index("消耗鸡蛋 ×2")


def test_replay_same_turn_no_duplicate(db_session_factory, override_settings):
    override_settings(v2_character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u7", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u7", ai_reply="我用了两个鸡蛋。", current_turn=3))
    _run(_ctx("cas-u7", ai_reply="我用了两个鸡蛋。", current_turn=3))

    egg = world_engine.find_object_by_name("cas-u7", "鸡蛋")
    assert egg.quantity == 4.0
    world = world_engine.get_world("cas-u7")
    events = world_repository.list_events(world.world_id, statuses=["completed"], limit=50)
    cas = [e for e in events if e.type == "character_action"]
    assert len(cas) == 1
    assert _world_notes("cas-u7").count("消耗鸡蛋 ×2") == 1


def test_step_handlers_order_relative_to_world_and_planning():
    order = {handler.__name__: index for index, handler in enumerate(STEP_HANDLERS)}
    assert order["run_world_update"] < order["run_character_action_sync"] < order["run_action_planning"]


def test_gate_off_handler_is_noop(db_session_factory):
    world_engine.create_object(
        "cas-u8", name="鸡蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u8", ai_reply="我用了两个鸡蛋。", current_turn=1))
    assert world_engine.find_object_by_name("cas-u8", "鸡蛋").quantity == 6.0
    assert _world_notes("cas-u8") == []
    assert world_engine.build_context("cas-u8").recent_world_changes == []