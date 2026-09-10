"""ACTION-003 Action Validation 单测。"""

import pytest

from app.models.character_action import (
    TargetRef,
    TurnRef,
    WorldAction,
    WorldActionReason,
    WorldActionStatus,
)
from app.services.character_action.validator import (
    WorkingView,
    validate_actions,
)


def _action(action_type: str = "CONSUME", name: str = "鸡蛋", quantity: float = 2.0, **kw) -> WorldAction:
    return WorldAction(
        action_type=action_type,
        target=TargetRef(name=name, **{k: v for k, v in kw.items() if k in ("location_id", "object_id")}),
        quantity=quantity,
        turn_ref=TurnRef(session_id="s1", turn_id="t1", ordinal=0),
        dedupe_key=kw.get("dedupe_key", ""),
    )


class _FakeObj:
    def __init__(self, id: str, name: str, quantity: float = 6.0, consumable: bool = True,
                 status: str = "active", location_id: str = "home.kitchen.fridge",
                 aliases: list[str] | None = None):
        self.id = id
        self.name = name
        self.aliases = aliases or []
        self.quantity = quantity
        self.consumable = consumable
        self.status = type("S", (), {"value": status, "__eq__": lambda s, o: s.value == o})()
        self.location_id = location_id


def _world(user_id: str = "u1", world_id: str = "w1", location: str | None = None):
    payload = {"world_id": world_id}
    if location is not None:
        payload["current_location"] = location
    return type("W", (), payload)()


class TestWorkingView:
    def test_find_object(self):
        obj = _FakeObj("e1", "鸡蛋")
        wv = WorkingView([obj], 200)
        assert wv.find_object("鸡蛋") is obj
        assert wv.find_object("不存在") is None

    def test_deduct_quantity(self):
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0)
        wv = WorkingView([obj], 200)
        remaining = wv.deduct_quantity("e1", 2.0)
        assert remaining == 4.0
        assert wv.remaining_quantity["e1"] == 4.0

    def test_register_created(self):
        wv = WorkingView([], 200)
        wv.register_created("syn_1", "面", "food", 1.0)
        assert wv.active_count == 1
        assert len(wv.created_entities) == 1
        found = wv.find_object("面")
        assert found is not None
        assert found.id == "syn_1"
        assert wv.remaining_quantity["syn_1"] == 1.0

    def test_update_location(self):
        obj = _FakeObj("e1", "牛奶", location_id="home.kitchen.fridge")
        wv = WorkingView([obj], 200)
        wv.update_location("e1", "home.kitchen")
        assert wv.location_overrides["e1"] == "home.kitchen"


class TestValidateConsume:
    def test_basic_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0, consumable=True)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CONSUME", "鸡蛋", 2.0)
        results = validate_actions([action], user_id="u1")
        assert len(results) == 1
        assert results[0].status == "validated"
        assert action.status == WorldActionStatus.VALIDATED

    def test_insufficient_quantity(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "鸡蛋", quantity=1.0, consumable=True)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CONSUME", "鸡蛋", 3.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.INSUFFICIENT_QUANTITY
        assert action.status == WorldActionStatus.REJECTED

    def test_object_not_found(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: []})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CONSUME", "番茄汤", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.OBJECT_NOT_FOUND

    def test_not_consumable(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "刀", quantity=1.0, consumable=False)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CONSUME", "刀", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.NOT_CONSUMABLE

    def test_invalid_quantity(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0, consumable=True)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CONSUME", "鸡蛋", None)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.INVALID_QUANTITY


class TestValidateCreate:
    def test_basic_create_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: []})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CREATE", "面", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "validated"

    def test_entity_limit(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 0})())
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: []})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CREATE", "面", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.ENTITY_LIMIT

    def test_create_invalid_location(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: []})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("CREATE", "面", 1.0, location_id="nonexistent.place")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.LOCATION_UNRESOLVED


class TestValidateMove:
    def test_basic_move_pass(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "牛奶", location_id="home.kitchen.fridge")
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("MOVE", "牛奶", quantity=None, location_id="home.kitchen")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "validated"

    def test_move_no_op_same_location(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "牛奶", location_id="home.kitchen")
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("MOVE", "牛奶", quantity=None, location_id="home.kitchen")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.NO_OP

    def test_move_invalid_location(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "牛奶", location_id="home.kitchen.fridge")
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("MOVE", "牛奶", quantity=None, location_id="home.nonexistent")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.LOCATION_UNRESOLVED

    def test_move_object_not_found(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: []})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        action = _action("MOVE", "不存在的东西", quantity=None, location_id="home.kitchen")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.OBJECT_NOT_FOUND


class TestWorkingViewSequential:
    def test_two_consumes_one_pass_one_fail(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "鸡蛋", quantity=1.0, consumable=True)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        a1 = _action("CONSUME", "鸡蛋", 1.0, dedupe_key="k1")
        a2 = _action("CONSUME", "鸡蛋", 1.0, dedupe_key="k2")
        results = validate_actions([a1, a2], user_id="u1")
        assert results[0].status == "validated"
        assert results[1].status == "rejected"
        assert results[1].reason == WorldActionReason.INSUFFICIENT_QUANTITY

    def test_dedupe_rejects_duplicate_key(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0, consumable=True)
        monkeypatch.setattr("app.services.character_action.validator.world_repository", type("R", (), {"list_objects": lambda self, wid: [obj]})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: type("W", (), {"world_id": "w1"})())

        a1 = _action("CONSUME", "鸡蛋", 1.0, dedupe_key="dup_key")
        a2 = _action("CONSUME", "鸡蛋", 1.0, dedupe_key="dup_key")
        results = validate_actions([a1, a2], user_id="u1")
        assert results[0].status == "validated"
        assert results[1].status == "rejected"
        assert results[1].reason == WorldActionReason.DUPLICATE


class TestDisabledWorld:
    def test_all_rejected_when_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": False})())
        action = _action("CONSUME", "鸡蛋", 2.0)
        results = validate_actions([action])
        assert all(r.status == "rejected" for r in results)
        assert all(r.reason == WorldActionReason.DISABLED for r in results)

    def test_world_unavailable(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": 200})())
        monkeypatch.setattr("app.services.character_action.validator.ensure_world", lambda uid: None)

        action = _action("CONSUME", "鸡蛋", 2.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.WORLD_UNAVAILABLE

    def test_zero_candidates(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.validator.get_settings", lambda: type("S", (), {"world_enabled": True})())
        results = validate_actions([])
        assert results == []


def _patch(monkeypatch, objects, location=None, entity_limit=200):
    monkeypatch.setattr(
        "app.services.character_action.validator.get_settings",
        lambda: type("S", (), {"world_enabled": True, "world_active_entities_limit": entity_limit})(),
    )
    monkeypatch.setattr(
        "app.services.character_action.validator.world_repository",
        type("R", (), {"list_objects": lambda self, wid: objects})(),
    )
    monkeypatch.setattr(
        "app.services.character_action.validator.ensure_world",
        lambda uid: _world(location=location),
    )


class TestDuplicateEntity:
    def test_create_existing_name_rejected(self, monkeypatch):
        obj = _FakeObj("e1", "面", quantity=1.0)
        _patch(monkeypatch, [obj])
        action = _action("CREATE", "面", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.DUPLICATE_ENTITY

    def test_create_new_name_passes(self, monkeypatch):
        _patch(monkeypatch, [])
        action = _action("CREATE", "三明治", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "validated"

    def test_same_turn_create_then_consume(self, monkeypatch):
        _patch(monkeypatch, [])
        a1 = _action("CREATE", "面", 1.0, dedupe_key="c1")
        a2 = _action("CONSUME", "面", 1.0, dedupe_key="c2")
        results = validate_actions([a1, a2], user_id="u1")
        assert results[0].status == "validated"
        assert results[1].status == "validated"
        assert a2.target.object_id is not None
        assert a2.target.object_id.startswith("syn_")


class TestLocationUnreachable:
    def test_consume_fridge_from_bedroom(self, monkeypatch):
        obj = _FakeObj("e1", "鸡蛋", location_id="home.kitchen.fridge")
        _patch(monkeypatch, [obj], location="home.bedroom")
        action = _action("CONSUME", "鸡蛋", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.LOCATION_UNREACHABLE

    def test_consume_fridge_from_living_room_allowed(self, monkeypatch):
        obj = _FakeObj("e1", "鸡蛋", location_id="home.kitchen.fridge")
        _patch(monkeypatch, [obj], location="home.living_room")
        action = _action("CONSUME", "鸡蛋", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "validated"


class TestAliasAndAmbiguous:
    def test_alias_resolves(self, monkeypatch):
        obj = _FakeObj("e1", "牛奶", aliases=["乳制品"], location_id="home.kitchen.fridge")
        _patch(monkeypatch, [obj], location="home.living_room")
        action = _action("CONSUME", "乳制品", 1.0)
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "validated"
        assert action.target.object_id == "e1"

    def test_same_name_ambiguous(self, monkeypatch):
        a = _FakeObj("e1", "鸡蛋", location_id="home.kitchen.fridge")
        b = _FakeObj("e2", "鸡蛋", location_id="home.kitchen.cabinet")
        _patch(monkeypatch, [a, b], location="home.kitchen")
        action = _action("MOVE", "鸡蛋", quantity=None, location_id="home.kitchen")
        results = validate_actions([action], user_id="u1")
        assert results[0].status == "rejected"
        assert results[0].reason == WorldActionReason.AMBIGUOUS_TARGET
