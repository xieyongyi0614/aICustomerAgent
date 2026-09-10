"""ACTION-004 World Engine Mutation 单测（引擎映射 + 结果判定）。"""

from app.models.character_action import (
    ActionTransitionEvent,
    TargetRef,
    TurnRef,
    WorldAction,
    WorldActionStatus,
)
from app.services.character_action.mutator import execute_actions


def _action(action_type: str, name: str, quantity: float | None = 1.0, object_id: str | None = None,
            location_id: str | None = None) -> WorldAction:
    return WorldAction(
        action_type=action_type,
        target=TargetRef(
            name=name,
            object_id=object_id,
            location_id=location_id,
        ),
        quantity=quantity,
        turn_ref=TurnRef(session_id="s1", turn_id="t1", ordinal=0),
    )


def _validated(action: WorldAction) -> WorldAction:
    action.transition(ActionTransitionEvent.VALIDATE_PASS)
    return action


def _noop(calls):
    calls["events"] += 1
    return _FakeEvent("no")


class _FakeEvent:
    def __init__(self, event_id: str):
        self.id = event_id
        self.title = ""


class _FakeObj:
    def __init__(self, obj_id: str, name: str, quantity: float = 6.0,
                 state: str = "whole", location_id: str = "home.kitchen.fridge", consumable: bool = True):
        self.id = obj_id
        self.name = name
        self.quantity = quantity
        self.state = state
        self.location_id = location_id
        self.consumable = consumable


class _FakeConsumeResult:
    def __init__(self, ok: bool, obj=None, error=None):
        self.ok = ok
        self.object = obj
        self.error = error


class _FakeWorld:
    current_location = "home.kitchen"


class TestMapping:
    def test_consume_calls_consume_object(self, monkeypatch):
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0)
        calls = {}

        def fake_consume(user_id, ref, quantity):
            calls["ref"] = ref
            calls["quantity"] = quantity
            return _FakeConsumeResult(ok=True, obj=obj)

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: obj)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object", fake_consume)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt1"))

        action = _validated(_action("CONSUME", "鸡蛋", 2.0))
        execute_actions([action], user_id="u1")
        assert calls == {"ref": "鸡蛋", "quantity": 2.0}
        assert action.status == WorldActionStatus.APPLIED

    def test_create_calls_create_object(self, monkeypatch):
        calls = {}

        def fake_create(user_id, name, category, location_id, quantity):
            calls["name"] = name
            calls["category"] = category
            calls["location_id"] = location_id
            calls["quantity"] = quantity
            return _FakeObj("e2", name, quantity=quantity, location_id=location_id)

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.get_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: _FakeObj("e2", name, quantity=1.0))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.create_object", fake_create)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt2"))

        action = _validated(_action("CREATE", "面条", 1.0))
        execute_actions([action], user_id="u1")
        assert calls["name"] == "面条"
        assert calls["quantity"] == 1.0
        assert action.status == WorldActionStatus.APPLIED

    def test_move_calls_move_object(self, monkeypatch):
        calls = {}

        def fake_move(user_id, object_id, location_id):
            calls["object_id"] = object_id
            calls["location_id"] = location_id
            return _FakeObj("e1", "牛奶", location_id=location_id)

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: _FakeObj("e1", "牛奶", location_id="home.living_room"))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.move_object", fake_move)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt3"))

        action = _validated(_action("MOVE", "牛奶", quantity=None, object_id="e1", location_id="home.kitchen"))
        execute_actions([action], user_id="u1")
        assert calls == {"object_id": "e1", "location_id": "home.kitchen"}
        assert action.status == WorldActionStatus.APPLIED


class TestJudgement:
    def test_create_none_failed(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.get_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: None)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.create_object", lambda *args, **kwargs: None)

        action = _validated(_action("CREATE", "面", 1.0))
        results = execute_actions([action], user_id="u1")
        assert results[0].status == "failed"
        assert results[0].engine_fn == "create_object"
        assert action.status == WorldActionStatus.FAILED

    def test_consume_ok_false_failed_with_original_code(self, monkeypatch):
        from app.models.world import ConsumeError

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        obj = _FakeObj("e1", "鸡蛋", quantity=1.0)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: obj)
        monkeypatch.setattr(
            "app.services.character_action.mutator.world_engine.consume_object",
            lambda uid, ref, quantity: _FakeConsumeResult(ok=False, obj=obj, error=ConsumeError.INSUFFICIENT_QUANTITY),
        )
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt"))

        action = _validated(_action("CONSUME", "鸡蛋", 3.0))
        results = execute_actions([action], user_id="u1")
        assert results[0].status == "failed"
        assert results[0].engine_error == ConsumeError.INSUFFICIENT_QUANTITY.value
        assert action.status == WorldActionStatus.FAILED

    def test_engine_exception_failed(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())

        def boom(user_id, ref, quantity):
            raise RuntimeError("engine crashed")

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: _FakeObj("e1", "鸡蛋", quantity=6.0))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object", boom)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt"))

        action = _validated(_action("CONSUME", "鸡蛋", 1.0))
        results = execute_actions([action], user_id="u1")
        assert results[0].status == "failed"
        assert action.status == WorldActionStatus.FAILED

    def test_world_unavailable_all_failed(self, monkeypatch):
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: None)

        a1 = _validated(_action("CONSUME", "鸡蛋", 1.0))
        a2 = _validated(_action("CREATE", "面", 1.0))
        results = execute_actions([a1, a2], user_id="u1")
        assert all(r.status == "failed" for r in results)
        assert all(a.status == WorldActionStatus.FAILED for a in (a1, a2))

    def test_no_user_id_all_failed(self, monkeypatch):
        action = _action("CONSUME", "鸡蛋", 1.0)
        results = execute_actions([action])
        assert results[0].status == "failed"
        assert action.status == WorldActionStatus.CANDIDATE


class TestEvents:
    def test_event_recorded_with_payload_fields(self, monkeypatch):
        captured = {}

        def fake_record(user_id, **kw):
            captured.update(kw)
            return _FakeEvent("evtX")

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: obj)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object", lambda uid, ref, q: _FakeConsumeResult(ok=True, obj=obj))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", fake_record)

        action = _validated(_action("CONSUME", "鸡蛋", 2.0))
        action.dedupe_key = "dk1"
        results = execute_actions([action], user_id="u1")
        assert captured["action_type"] == "CONSUME"
        assert captured["target_name"] == "鸡蛋"
        assert captured["quantity"] == 2.0
        assert captured["object_id"] == "e1"
        assert captured["dedupe_key"] == "dk1"
        assert captured["session_id"] == "s1"
        assert results[0].world_event_id == "evtX"

    def test_failed_action_no_event(self, monkeypatch):
        calls = {"events": 0}

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: None)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object", lambda uid, ref, q: _FakeConsumeResult(ok=False, error=None))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _noop(calls))

        action = _validated(_action("CONSUME", "鸡蛋", 1.0))
        execute_actions([action], user_id="u1")
        assert calls["events"] == 0


class TestOrdering:
    def test_sequential_preserves_order(self, monkeypatch):
        order = []

        def fake_consume(user_id, ref, quantity):
            order.append(f"consume:{ref}")
            return _FakeConsumeResult(ok=True, obj=_FakeObj("e1", ref, quantity=1.0))

        def fake_create(user_id, name, category, location_id, quantity):
            order.append(f"create:{name}")
            return _FakeObj("e_new", name, quantity=quantity)

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.get_world", lambda uid: _FakeWorld())
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: _FakeObj("e1", name, quantity=1.0))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object", fake_consume)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.create_object", fake_create)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt"))

        create = _validated(_action("CREATE", "煎蛋卷", 1.0))
        consume = _validated(_action("CONSUME", "煎蛋卷", 1.0))
        execute_actions([create, consume], user_id="u1")
        assert order == ["create:煎蛋卷", "consume:煎蛋卷"]

    def test_rejected_before_applied_stays_independent(self, monkeypatch):
        calls = {"consumed": 0}

        monkeypatch.setattr("app.services.character_action.mutator.world_engine.ensure_world", lambda uid: _FakeWorld())
        obj = _FakeObj("e1", "鸡蛋", quantity=6.0)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.find_object_by_name", lambda uid, name: obj)
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.consume_object",
                            lambda uid, ref, q: calls.__setitem__("consumed", calls["consumed"] + 1) or _FakeConsumeResult(ok=True, obj=obj))
        monkeypatch.setattr("app.services.character_action.mutator.world_engine.record_character_action_event", lambda uid, **kw: _FakeEvent("evt"))

        bad = _action("CONSUME", "鸡蛋", 1.0)
        bad.transition(ActionTransitionEvent.VALIDATE_REJECT)
        good = _validated(_action("CONSUME", "鸡蛋", 1.0))
        results = execute_actions([bad, good], user_id="u1")
        assert results[0].status == "rejected"
        assert results[1].status == "applied"
        assert calls["consumed"] == 1
