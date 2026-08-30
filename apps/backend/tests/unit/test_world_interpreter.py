"""V8-006 解释器确定性矩阵（world-model.md §4：宁缺毋滥）。"""

from datetime import datetime

from app.models.world import World, WorldObject, WorldTimeMode
from app.services.world.interpreter import interpret

NOW = datetime(2026, 9, 1, 10, 0)


def _world(location="home.living_room"):
    return World(world_id="home:default-user", user_id="default-user", current_location=location)


def _object(name="西瓜", location="home.kitchen.fridge", state="whole", aliases=("瓜",)):
    return WorldObject(
        id="watermelon_001",
        world_id="home:default-user",
        name=name,
        aliases=list(aliases),
        category="food",
        location_id=location,
        state=state,
        quantity=1.0,
    )


def test_take_moves_object_to_current_location():
    result = interpret("给我拿个西瓜", _world(), [_object()], [], NOW)
    assert result.moves == [("watermelon_001", "home.living_room")]
    assert any("冰箱" in note for note in result.notes)


def test_take_object_already_here_only_notes():
    result = interpret("给我拿个西瓜", _world(), [_object(location="home.living_room")], [], NOW)
    assert result.moves == []
    assert result.notes


def test_cut_then_eat_state_actions():
    cut = interpret("帮我切一下西瓜", _world(), [_object(location="home.living_room")], [], NOW)
    assert cut.state_actions == [("watermelon_001", "cut")]
    eat = interpret("我吃一块瓜", _world(), [_object(location="home.living_room", state="cut")], [], NOW)
    assert eat.state_actions == [("watermelon_001", "eat")]


def test_put_back_resolves_target_container():
    result = interpret("把西瓜放回冰箱", _world(), [_object(location="home.living_room", state="cut")], [], NOW)
    assert result.moves == [("watermelon_001", "home.kitchen.fridge")]


def test_discard():
    result = interpret("这瓜坏了，扔了吧", _world(), [_object(location="home.living_room", state="cut")], [], NOW)
    assert result.discards == ["watermelon_001"]


def test_buy_creates_known_object():
    result = interpret("我买了个西瓜回来", _world(), [], [], NOW)
    assert result.creations == [{"name": "西瓜", "category": "food", "quantity": 1.0}]


def test_unknown_new_object_is_not_created():
    result = interpret("我买了个克苏鲁回来", _world(), [], [], NOW)
    assert result.creations == []


def test_location_move():
    result = interpret("我们去卧室看电影吧", _world(), [], [], NOW)
    assert result.location_move == "home.bedroom"


def test_event_scheduled_tomorrow_high_importance():
    result = interpret("明天我要面试，好紧张", _world(), [], [], NOW)
    assert len(result.events) == 1
    event = result.events[0]
    assert event["type"] == "interview"
    assert event["importance"] == "high"
    assert event["due_at"] == datetime(2026, 9, 2, 10, 0)


def test_event_completion_and_cancel():
    done = interpret("面试终于结束了", _world(), [], [], NOW)
    assert done.event_completions == ["interview"]
    cancel = interpret("明天的面试取消了", _world(), [], [], NOW)
    assert cancel.event_cancellations == ["interview"]


def test_weather_update_with_negation_guard():
    rain = interpret("外面下雨了记得关窗", _world(), [], [], NOW)
    assert rain.environment_updates == {"weather": "rain"}
    not_rain = interpret("外面没有下雨", _world(), [], [], NOW)
    assert not_rain.environment_updates == {}


def test_plain_chat_produces_zero_changes():
    for message in ("今天心情不错", "你好呀", "在吗", "晚饭吃什么好呢"):
        result = interpret(message, _world(), [_object()], [], NOW)
        assert not result.moves
        assert not result.state_actions
        assert not result.creations
        assert not result.events
        assert result.location_move is None
        assert result.environment_updates == {}
