"""用户显式录入物品（2026-10-10）：确定性前置闸 + 抽取归一 + 步骤内建档。

默认家庭库存种子已移除，物品只在用户显式要求记录时创建；本文件覆盖这条新路径。
"""

import asyncio

from app.application import post_process, world_engine
from app.chains.object_intake_chain import extract_objects, has_record_intent
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.world import ObjectIntake, ObjectIntakeItem


def _ctx(user_id: str, user_input: str, session_id: str = "s-intake"):
    return post_process.PostProcessContext(
        session_id=session_id,
        user_id=user_id,
        user_input=user_input,
        ai_reply="好的。",
        state=ConversationState(
            session_id=session_id,
            user_id=user_id,
            messages=[],
            summary=None,
            memories=[],
            current_input=user_input,
        ),
        analysis=TurnAnalysis(),
        current_turn=1,
    )


def _patch_world_side(monkeypatch) -> None:
    monkeypatch.setattr(world_engine, "run_turn_update", lambda *a, **k: None)
    from app.services.world import user_situation

    monkeypatch.setattr(user_situation, "detect_from_message", lambda *a, **k: None)


def _stub_extract(monkeypatch, items, calls) -> None:
    def _extract(message, *, llm=None):
        calls.append(message)
        return ObjectIntake(is_record_intent=True, items=tuple(items))

    monkeypatch.setattr("app.chains.object_intake_chain.extract_objects", _extract)


def test_record_intent_gate():
    assert has_record_intent("记一下我买了鸡蛋")
    assert has_record_intent("冰箱里还有两盒牛奶")
    assert has_record_intent("家里添了个新沙发")
    assert has_record_intent("帮我记一下，囤了点大米")
    assert not has_record_intent("冰箱里有什么")
    assert not has_record_intent("冰箱里还有几个鸡蛋")
    assert not has_record_intent("家里有没有牛奶")
    assert not has_record_intent("今天天气不错")
    assert not has_record_intent("我饿了")


def test_extract_objects_normalizes(monkeypatch):
    class _Chain:
        def invoke(self, _payload):
            return ObjectIntake(
                is_record_intent=True,
                confidence=0.8,
                items=(
                    ObjectIntakeItem(name=" 鸡蛋 ", category="食材", quantity=0, unit="个"),
                    ObjectIntakeItem(name="   ", category="food", quantity=2, unit="盒"),
                ),
            )

    monkeypatch.setattr(
        "app.chains.object_intake_chain.build_object_intake_chain",
        lambda llm=None: _Chain(),
    )
    result = extract_objects("记一下我买了鸡蛋")
    assert result.is_record_intent is True
    assert len(result.items) == 1
    assert result.items[0].name == "鸡蛋"
    assert result.items[0].category == "misc"
    assert result.items[0].quantity == 1.0


def test_extract_objects_empty_when_not_intent(monkeypatch):
    class _Chain:
        def invoke(self, _payload):
            return ObjectIntake(is_record_intent=False)

    monkeypatch.setattr(
        "app.chains.object_intake_chain.build_object_intake_chain",
        lambda llm=None: _Chain(),
    )
    result = extract_objects("冰箱里有什么")
    assert result.is_record_intent is False
    assert result.items == ()


def test_world_update_creates_item_on_record_intent(monkeypatch, db_session_factory):
    _patch_world_side(monkeypatch)
    calls: list[str] = []
    _stub_extract(
        monkeypatch,
        [ObjectIntakeItem(name="鸡蛋", category="food", quantity=2, unit="个")],
        calls,
    )
    asyncio.run(
        post_process.run_world_update(_ctx("intake-u1", "记一下我买了两个鸡蛋"))
    )
    egg = world_engine.find_object_by_name("intake-u1", "鸡蛋")
    assert egg is not None
    assert egg.quantity == 2.0
    assert egg.unit == "个"
    assert calls == ["记一下我买了两个鸡蛋"]


def test_world_update_gated_without_intent(monkeypatch, db_session_factory):
    _patch_world_side(monkeypatch)
    calls: list[str] = []
    _stub_extract(monkeypatch, [], calls)
    asyncio.run(post_process.run_world_update(_ctx("intake-u2", "今天天气不错")))
    assert calls == []
    assert world_engine.get_objects_by_location("intake-u2", "home") == []


def test_world_update_skips_existing_name(monkeypatch, db_session_factory):
    _patch_world_side(monkeypatch)
    calls: list[str] = []
    _stub_extract(
        monkeypatch,
        [ObjectIntakeItem(name="牛奶", category="drink", quantity=1, unit="盒")],
        calls,
    )
    asyncio.run(post_process.run_world_update(_ctx("intake-u3", "记一下我买了牛奶")))
    asyncio.run(post_process.run_world_update(_ctx("intake-u3", "记一下我买了牛奶")))
    milk = [
        obj
        for obj in world_engine.get_objects_by_location("intake-u3", "home")
        if obj.name == "牛奶"
    ]
    assert len(milk) == 1
    assert milk[0].quantity == 1.0


# ---- 价格 / 购买时间 / 日均金额（2026-10-10） -------------------------------


def test_usage_cost_days_and_daily():
    from datetime import datetime, timezone

    from app.models.world import usage_cost

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    cost = usage_cost(1200, "2026-09-10", now=now)
    assert cost == {
        "days_used": 30,
        "daily_cost_minor": 40,
        "price_minor": 1200,
        "purchased_at": "2026-09-10",
    }
    same_day = usage_cost(1200, "2026-10-10", now=now)
    assert same_day["days_used"] == 1
    assert same_day["daily_cost_minor"] == 1200


def test_usage_cost_none_when_missing_or_invalid():
    from app.models.world import usage_cost

    assert usage_cost(None, "2026-09-10") is None
    assert usage_cost(1200, None) is None
    assert usage_cost(0, "2026-09-10") is None
    assert usage_cost(-1, "2026-09-10") is None
    assert usage_cost(1200, "不是日期") is None


def test_extract_objects_normalizes_price_and_purchase_date(monkeypatch):
    from datetime import datetime, timezone

    class _Chain:
        def invoke(self, _payload):
            return ObjectIntake(
                is_record_intent=True,
                confidence=0.9,
                items=(
                    ObjectIntakeItem(
                        name="锅",
                        category="tool",
                        quantity=1,
                        unit="个",
                        price_yuan=128.5,
                        purchased_at_hint="昨天",
                    ),
                ),
            )

    monkeypatch.setattr(
        "app.chains.object_intake_chain.build_object_intake_chain",
        lambda llm=None: _Chain(),
    )
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    item = extract_objects("记一下我昨天买了个锅 128.5", now=now).items[0]
    assert item.price_minor == 12850
    assert item.purchased_at == "2026-10-09"


def test_extract_objects_price_without_date_defaults_today(monkeypatch):
    from datetime import datetime, timezone

    class _Chain:
        def invoke(self, _payload):
            return ObjectIntake(
                is_record_intent=True,
                items=(
                    ObjectIntakeItem(name="鸡蛋", category="food", price_yuan=12),
                ),
            )

    monkeypatch.setattr(
        "app.chains.object_intake_chain.build_object_intake_chain",
        lambda llm=None: _Chain(),
    )
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    item = extract_objects("记一下我买了鸡蛋 12 块", now=now).items[0]
    assert item.price_minor == 1200
    assert item.purchased_at == "2026-10-10"


def test_extract_objects_unresolvable_date_is_not_fabricated(monkeypatch):
    class _Chain:
        def invoke(self, _payload):
            return ObjectIntake(
                is_record_intent=True,
                items=(
                    ObjectIntakeItem(
                        name="沙发", category="furniture", price_yuan=3000,
                        purchased_at_hint="很久以前",
                    ),
                ),
            )

    monkeypatch.setattr(
        "app.chains.object_intake_chain.build_object_intake_chain",
        lambda llm=None: _Chain(),
    )
    item = extract_objects("记一下我很久以前买的沙发 3000").items[0]
    assert item.price_minor == 300000
    assert item.purchased_at is None


def test_recorded_price_persists_and_renders_daily_cost(monkeypatch, db_session_factory):
    from datetime import datetime, timezone

    from app.services.world.context_selector import render_world_section

    _patch_world_side(monkeypatch)
    calls: list[str] = []
    _stub_extract(
        monkeypatch,
        [
            ObjectIntakeItem(
                name="锅", category="tool", quantity=1, unit="个",
                price_minor=12000, purchased_at="2026-09-10",
            )
        ],
        calls,
    )
    asyncio.run(post_process.run_world_update(_ctx("intake-u4", "记一下我买了锅 120")))

    pot = world_engine.find_object_by_name("intake-u4", "锅")
    assert pot is not None
    assert pot.properties["price_minor"] == 12000
    assert pot.properties["purchased_at"] == "2026-09-10"

    context = world_engine.build_context("intake-u4")
    assert context is not None
    text = render_world_section(
        context, now=datetime(2026, 10, 10, tzinfo=timezone.utc)
    )
    assert "¥120.00" in text
    assert "已用 30 天" in text
    assert "日均 ¥4.00" in text

