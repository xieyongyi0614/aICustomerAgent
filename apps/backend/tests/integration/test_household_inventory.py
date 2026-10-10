"""Household Inventory 验收测试（Tests 1~8）：查询 / 位置 / 消耗规则 / 持久化 / 事实来源。

默认家庭库存种子已移除（2026-10-10）：世界建档为空，物品只在被显式录入时创建。
故本文件用 `_seed_items()` **显式录入** 6 件物品，再验证围绕物品的被动链路。
每个用例由 autouse `_offline_repos` 提供全新内存 SQLite，测试彼此隔离。
"""

from app.application import world_engine
from app.models.world import ConsumeError, ObjectStatus
from app.repositories import world_repository
from app.services.world.context_selector import render_world_section

ITEMS = (
    ("鸡蛋", "food", "home.kitchen.fridge", 6, "piece"),
    ("牛奶", "drink", "home.kitchen.fridge", 1, "piece"),
    ("可乐", "drink", "home.kitchen.fridge", 2, "piece"),
    ("面条", "food", "home.kitchen.cabinet", 2, "piece"),
    ("大米", "food", "home.kitchen.cabinet", 2, "kg"),
    ("面包", "food", "home.kitchen.cabinet", 1, "piece"),
)


def _seed_items(user_id: str = "default-user") -> None:
    for name, category, location_id, quantity, unit in ITEMS:
        world_engine.create_object(
            user_id,
            name=name,
            category=category,
            location_id=location_id,
            quantity=quantity,
            unit=unit,
            consumable=True,
        )


def _by_name(user_id: str, name: str):
    return world_engine.find_object_by_name(user_id, name)


# Test 1：查询家里有什么
def test_query_home_inventory(db_session_factory):
    _seed_items()
    by_name = {
        obj.name: obj.quantity
        for obj in world_engine.get_objects_by_location("default-user", "home")
    }
    assert by_name == {
        "鸡蛋": 6,
        "牛奶": 1,
        "可乐": 2,
        "面条": 2,
        "大米": 2,
        "面包": 1,
    }
    assert _by_name("default-user", "大米").unit == "kg"


# Test 2：查询位置
def test_query_fridge_only(db_session_factory):
    _seed_items()
    fridge = {
        obj.name: obj.quantity
        for obj in world_engine.get_objects_by_location(
            "default-user", "home.kitchen.fridge"
        )
    }
    assert fridge == {"鸡蛋": 6, "牛奶": 1, "可乐": 2}


def test_query_cabinet_only(db_session_factory):
    _seed_items()
    cabinet = {
        obj.name: obj.quantity
        for obj in world_engine.get_objects_by_location(
            "default-user", "home.kitchen.cabinet"
        )
    }
    assert cabinet == {"面条": 2, "大米": 2, "面包": 1}


# Test 3：消耗成功并落库
def test_consume_success_persisted(db_session_factory):
    _seed_items()
    result = world_engine.consume_object("default-user", "鸡蛋", 1)
    assert result.ok is True
    assert result.previous_quantity == 6
    assert result.object.quantity == 5
    assert _by_name("default-user", "鸡蛋").quantity == 5


# Test 4：消耗完 → quantity=0, state=empty，且不能继续消耗
def test_consume_to_empty(db_session_factory):
    _seed_items()
    for _ in range(6):
        assert world_engine.consume_object("default-user", "鸡蛋", 1).ok is True
    egg = _by_name("default-user", "鸡蛋")
    assert egg.quantity == 0
    assert egg.state == "empty"
    assert egg.status is ObjectStatus.ACTIVE

    blocked = world_engine.consume_object("default-user", "鸡蛋", 1)
    assert blocked.ok is False
    assert blocked.error is ConsumeError.INSUFFICIENT_QUANTITY


# Test 5：超量消耗必须失败且不部分扣除
def test_consume_insufficient_no_partial(db_session_factory):
    _seed_items()
    result = world_engine.consume_object("default-user", "大米", 3)
    assert result.ok is False
    assert result.error is ConsumeError.INSUFFICIENT_QUANTITY
    assert _by_name("default-user", "大米").quantity == 2


# Test 6：不可消耗物品拒绝
def test_consume_not_consumable(db_session_factory):
    _seed_items()
    world_engine.create_object(
        "default-user",
        name="冰箱",
        category="misc",
        location_id="home.kitchen",
        quantity=1,
        consumable=False,
    )
    result = world_engine.consume_object("default-user", "冰箱", 1)
    assert result.ok is False
    assert result.error is ConsumeError.NOT_CONSUMABLE
    assert _by_name("default-user", "冰箱").quantity == 1


# Test 7：持久化——重新加载 World 后仍为消耗后数量
def test_consume_persists_across_reload(db_session_factory):
    _seed_items()
    world_engine.consume_object("default-user", "鸡蛋", 1)
    state = world_engine.get_full_state("default-user")
    egg = next(item for item in state["entities"] if item["name"] == "鸡蛋")
    assert egg["quantity"] == 5


# Test 8：LLM 不得创造事实——World Context 必须以清单为事实来源
def test_world_context_shows_zero_as_fact(db_session_factory):
    _seed_items()
    world_engine.consume_object("default-user", "面条", 2)
    context = world_engine.build_context("default-user")
    assert context is not None
    text = render_world_section(context)
    assert "面条 × 0" in text
    assert "面条 × 2" not in text


def test_consume_invalid_quantity(db_session_factory):
    _seed_items()
    assert (
        world_engine.consume_object("default-user", "鸡蛋", 0).error
        is ConsumeError.INVALID_QUANTITY
    )
    assert (
        world_engine.consume_object("default-user", "鸡蛋", -1).error
        is ConsumeError.INVALID_QUANTITY
    )


def test_consume_object_not_found(db_session_factory):
    _seed_items()
    result = world_engine.consume_object("default-user", "不存在的物品", 1)
    assert result.ok is False
    assert result.error is ConsumeError.OBJECT_NOT_FOUND


def test_available_consumables_excludes_empty_and_nonconsumable(db_session_factory):
    _seed_items()
    world_engine.consume_object("default-user", "可乐", 2)
    available = {
        obj.name for obj in world_engine.get_available_consumables("default-user")
    }
    assert "可乐" not in available
    assert "鸡蛋" in available
    assert "大米" in available


# 新行为（2026-10-10）：世界建档为空，物品只在被显式录入时创建
def test_ensure_world_starts_empty(db_session_factory):
    world = world_engine.ensure_world("alice")
    assert world is not None
    assert world_engine.get_objects_by_location("alice", "home") == []
    assert world_engine.get_available_consumables("alice") == []


def test_ensure_world_does_not_backfill(db_session_factory):
    world_repository.ensure_world("erin")
    assert world_engine.get_objects_by_location("erin", "home") == []
    assert world_engine.ensure_world("erin") is not None
    assert world_engine.get_objects_by_location("erin", "home") == []


def test_ensure_world_preserves_recorded_items(db_session_factory):
    world_engine.ensure_world("bob")
    world_engine.create_object(
        "bob",
        name="鸡蛋",
        category="food",
        location_id="home.kitchen.fridge",
        quantity=3,
        consumable=True,
    )
    assert world_engine.ensure_world("bob") is not None
    names = {
        obj.name for obj in world_engine.get_objects_by_location("bob", "home")
    }
    assert names == {"鸡蛋"}
    assert world_engine.find_object_by_name("bob", "鸡蛋").quantity == 3


def test_world_owner_is_user(db_session_factory):
    world_engine.ensure_world("carol")
    assert world_repository.get_owner_fields("carol") == {
        "owner_type": "user",
        "owner_id": "carol",
    }
