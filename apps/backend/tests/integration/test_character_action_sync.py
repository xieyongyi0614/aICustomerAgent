"""ACTION-005 集成：角色动作 → 事件 → 下一轮上下文最近世界变化闭环。"""

import asyncio

from app.application import world_engine
from app.application.post_process import (
    STEP_HANDLERS,
    PostProcessContext,
    run_character_action_sync,
    run_action_planning,
)
from app.models.conversation import ChatMessage, ConversationState
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
    override_settings(character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u1", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u1", ai_reply="我用了两个测试蛋。", current_turn=1))

    egg = world_engine.find_object_by_name("cas-u1", "测试蛋")
    assert egg is not None
    assert egg.quantity == 4.0
    assert "消耗测试蛋 ×2" in _world_notes("cas-u1")

    context = world_engine.build_context("cas-u1")
    assert context is not None
    assert context.recent_world_changes == ["消耗测试蛋 ×2"]
    text = render_world_section(context)
    assert "最近世界变化：" in text
    assert "  - 消耗测试蛋 ×2" in text
    assert text.index("测试蛋 × 4") < text.index("最近世界变化：")


def test_create_closed_loop(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")
    world_engine.ensure_world("cas-u2")
    _run(_ctx("cas-u2", ai_reply="我做好了一碗面。", current_turn=1))

    made = world_engine.find_object_by_name("cas-u2", "面")
    assert made is not None
    assert made.quantity == 1.0
    context = world_engine.build_context("cas-u2")
    assert context.recent_world_changes == ["做出面"]
    assert "做出面" in render_world_section(context)


def test_gate_off_is_byte_identical(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="false")
    world_engine.create_object(
        "cas-u3", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world_engine.record_character_action_event(
        "cas-u3",
        action_type="CONSUME",
        target_name="测试蛋",
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
    override_settings(character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u4", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world_engine.record_character_action_event(
        "cas-u4",
        action_type="CONSUME",
        target_name="测试蛋",
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
    assert context.recent_world_changes == ["消耗测试蛋 ×2"]


def test_no_applied_actions_keeps_notes_untouched(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u5", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=1.0
    )
    world = world_engine.get_world("cas-u5")
    world.notes = ["测试蛋已从冰箱取出"]
    world_repository.save_world(world)

    _run(_ctx("cas-u5", ai_reply="我用掉三个测试蛋。", current_turn=1))
    assert _world_notes("cas-u5") == ["测试蛋已从冰箱取出"]


def test_interpreter_and_cas_notes_coexist(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u6", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    world = world_engine.get_world("cas-u6")
    world.notes = ["测试蛋已从冰箱取出"]
    world_repository.save_world(world)

    _run(_ctx("cas-u6", ai_reply="我用了两个测试蛋。", current_turn=1))
    notes = _world_notes("cas-u6")
    assert "测试蛋已从冰箱取出" in notes
    assert "消耗测试蛋 ×2" in notes
    assert notes.index("测试蛋已从冰箱取出") < notes.index("消耗测试蛋 ×2")


def test_replay_same_turn_no_duplicate(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")
    world_engine.create_object(
        "cas-u7", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u7", ai_reply="我用了两个测试蛋。", current_turn=3))
    _run(_ctx("cas-u7", ai_reply="我用了两个测试蛋。", current_turn=3))

    egg = world_engine.find_object_by_name("cas-u7", "测试蛋")
    assert egg.quantity == 4.0
    world = world_engine.get_world("cas-u7")
    events = world_repository.list_events(
        world.world_id,
        statuses=["completed"],
        limit=50,
        types=["character_action"],
        order="created_at_desc",
    )
    assert len(events) == 1
    assert _world_notes("cas-u7").count("消耗测试蛋 ×2") == 1


def test_step_handlers_order_relative_to_world_and_planning():
    order = {handler.__name__: index for index, handler in enumerate(STEP_HANDLERS)}
    assert order["run_world_update"] < order["run_character_action_sync"] < order["run_action_planning"]


def test_gate_off_handler_is_noop(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="false")
    world_engine.create_object(
        "cas-u8", name="测试蛋", category="food", location_id="home.kitchen.fridge", quantity=6.0
    )
    _run(_ctx("cas-u8", ai_reply="我用了两个测试蛋。", current_turn=1))
    assert world_engine.find_object_by_name("cas-u8", "测试蛋").quantity == 6.0
    assert _world_notes("cas-u8") == []
    assert world_engine.build_context("cas-u8").recent_world_changes == []


def test_grounding_cap_and_take_consume_chain(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")

    from app.models.world import InventoryItem
    from app.services.grounding.inventory_guard import (
        check_inventory_grounding,
        extract_requested_counts,
    )

    user_id = "cas-take"
    world_engine.ensure_world(user_id)
    raw_reply = "从冰箱拿出鸡蛋6个，熟练地磕进碗里煎好。"
    inventory = [
        InventoryItem(
            name="鸡蛋",
            quantity=6.0,
            unit="piece",
            location_id="home.kitchen.fridge",
            state="whole",
            consumable=True,
        )
    ]

    requested = extract_requested_counts("给我来俩个鸡蛋吧", inventory)
    assert requested == {"鸡蛋": 2.0}

    report = check_inventory_grounding(raw_reply, inventory, requested=requested)
    capped = report.corrected_text or raw_reply
    assert "拿出鸡蛋2个" in capped
    assert "6个" not in capped

    _run(_ctx(user_id, ai_reply=capped, current_turn=1))
    after = world_engine.find_object_by_name(user_id, "鸡蛋")
    assert after.quantity == 4.0
    assert "消耗鸡蛋 ×2" in _world_notes(user_id)


def test_omitted_subject_take_consumes_from_context(db_session_factory, override_settings):
    override_settings(character_action_sync_enabled="true")
    user_id = "cas-omit"
    world_engine.ensure_world(user_id)
    ctx = _ctx(
        user_id,
        ai_reply="刚才拿了两个出来煎给你了，冰箱里应该还剩四个。",
        user_input="冰箱里还有几个蛋啊",
        current_turn=1,
    )
    ctx.state.messages = [
        ChatMessage(role="human", content="冰箱里还有几个蛋啊")
    ]
    _run(ctx)

    egg = world_engine.find_object_by_name(user_id, "鸡蛋")
    assert egg is not None
    assert egg.quantity == 4.0
    assert "消耗鸡蛋 ×2" in _world_notes(user_id)