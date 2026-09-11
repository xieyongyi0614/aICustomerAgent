"""库存 grounding 验收测试（对应 Acceptance Test 1~6 行为约束）。"""

from app.models.world import InventoryItem
from app.services.grounding.inventory_guard import (
    check_inventory_grounding,
    rewrite_grounded,
)
from app.services.world.context_selector import (
    build_world_context,
    render_world_section,
)
from app.models.world import (
    TimeContext,
    World,
    WorldEnvironment,
    WorldTimeMode,
)
from datetime import datetime


def _inv(name: str, qty: float, unit: str = "piece", location: str = "home.kitchen.fridge"):
    return InventoryItem(
        name=name,
        quantity=qty,
        unit=unit,
        location_id=location,
        state="whole",
        consumable=True,
    )


HOUSEHOLD = [
    _inv("鸡蛋", 6),
    _inv("牛奶", 1),
    _inv("可乐", 2),
    _inv("面条", 2, location="home.kitchen.cabinet"),
    _inv("大米", 2, "kg", location="home.kitchen.cabinet"),
    _inv("面包", 1, location="home.kitchen.cabinet"),
]


class TestAcceptance1EggQty:
    def test_wrong_qty_rewritten(self):
        report = check_inventory_grounding("鸡蛋还有四个。", HOUSEHOLD)
        assert report.has_conflict
        assert any(c.kind == "QTY_MISMATCH" and c.name == "鸡蛋" for c in report.conflicts)
        assert report.corrected_text is not None
        assert "6" in report.corrected_text
        assert "四个" not in report.corrected_text

    def test_correct_qty_pass(self):
        report = check_inventory_grounding("鸡蛋还有6个。", HOUSEHOLD)
        assert not report.has_conflict


class TestAcceptance2NoApple:
    def test_bare_apples(self):
        report = check_inventory_grounding("还有两个苹果。", HOUSEHOLD)
        assert any(c.kind == "NOT_IN_INVENTORY" and c.name == "苹果" for c in report.conflicts)
        assert report.corrected_text is not None
        assert "还有两个苹果" not in report.corrected_text
        assert "没有苹果" in report.corrected_text or "没有现成" in report.corrected_text

    def test_existence_apple(self):
        report = check_inventory_grounding("冰箱里有苹果。", HOUSEHOLD)
        assert any(c.name == "苹果" for c in report.conflicts)


class TestAcceptance3MilkQty:
    def test_half_box_rejected(self):
        report = check_inventory_grounding("还有半盒牛奶。", HOUSEHOLD)
        assert any(c.kind == "QTY_MISMATCH" and c.name == "牛奶" for c in report.conflicts)
        assert report.corrected_text is not None
        assert "半" not in report.corrected_text


class TestAcceptance4NoSoup:
    def test_pot_soup(self):
        report = check_inventory_grounding("锅里还温着汤。", HOUSEHOLD)
        assert any(c.kind == "NOT_IN_INVENTORY" and c.name == "汤" for c in report.conflicts)
        assert report.corrected_text is not None
        assert "温着汤" not in report.corrected_text

    def test_pot_has_soup(self):
        report = check_inventory_grounding("锅里有番茄汤。", HOUSEHOLD)
        assert any(c.kind == "NOT_IN_INVENTORY" for c in report.conflicts)


class TestAcceptance5Consistency:
    def test_same_world_same_truth(self):
        texts = [
            "鸡蛋呢？鸡蛋还有6个。",
            "鸡蛋还有6个，放心。",
            "鸡蛋没了吗？没有，还有6个。",
        ]
        for text in texts:
            report = check_inventory_grounding(text, HOUSEHOLD)
            if report.has_conflict:
                assert report.corrected_text is not None
                assert "6" in report.corrected_text


class TestAcceptance6AfterConsume:
    def test_after_consume_qty_is_four(self):
        remaining = [_inv("鸡蛋", 4)]
        report = check_inventory_grounding("鸡蛋还有4个。", remaining)
        assert not report.has_conflict
        wrong = check_inventory_grounding("鸡蛋还有6个。", remaining)
        assert wrong.has_conflict
        assert wrong.corrected_text is not None
        assert "4" in wrong.corrected_text


class TestWorldSectionBoundary:
    def test_render_states_absent_means_missing(self):
        world = World(
            world_id="home:u",
            user_id="u",
            current_location="home.kitchen",
            environment=WorldEnvironment(),
        )
        time_ctx = TimeContext(
            now=datetime(2026, 9, 10, 16, 0),
            weekday="周四",
            part_of_day="dusk",
            time_mode=WorldTimeMode.REAL_SYNC,
        )
        from app.models.world import WorldObject

        objects = [
            WorldObject(
                id="o1",
                world_id="home:u",
                name="鸡蛋",
                category="food",
                location_id="home.kitchen.fridge",
                state="whole",
                quantity=6,
                unit="piece",
                consumable=True,
            )
        ]
        ctx = build_world_context(world, objects, [], time_ctx)
        text = render_world_section(ctx)
        assert text is not None
        assert "鸡蛋 × 6" in text
        assert "未列出的物品视为不存在" in text


class TestDialogueSamples:
    def test_leftover_and_milk(self):
        reply = "冰箱里还有剩饭和半盒牛奶。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert report.has_conflict
        assert report.corrected_text is not None

    def test_cabbage_eggs(self):
        reply = "还剩半颗卷心菜和两个鸡蛋。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert report.corrected_text is not None
        assert "卷心菜" not in report.corrected_text
        assert "鸡蛋" in report.corrected_text


class TestRequestedQuantityCap:
    def test_take_exceeds_request_rewritten_to_requested(self):
        reply = "从冰箱拿出鸡蛋6个，马上煎好给你。"
        report = check_inventory_grounding(
            reply, HOUSEHOLD, requested={"鸡蛋": 2.0}
        )
        assert report.has_conflict
        assert any(c.kind == "TAKE_EXCEEDS_REQUEST" for c in report.conflicts)
        assert report.corrected_text is not None
        assert "拿出鸡蛋2个" in report.corrected_text
        assert "6个" not in report.corrected_text

    def test_take_first_position_rewritten(self):
        reply = "拿出6个鸡蛋，马上就好。"
        report = check_inventory_grounding(
            reply, HOUSEHOLD, requested={"鸡蛋": 1.0}
        )
        assert report.has_conflict
        assert "拿出1个鸡蛋" in report.corrected_text

    def test_take_within_request_passes(self):
        reply = "拿出鸡蛋2个，马上就好。"
        report = check_inventory_grounding(
            reply, HOUSEHOLD, requested={"鸡蛋": 2.0}
        )
        assert not report.has_conflict

    def test_take_no_request_no_cap(self):
        reply = "拿出鸡蛋6个，马上就好。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert not report.has_conflict
        assert report.corrected_text is None


class TestOmittedSubjectLeftover:
    CONTEXT_EGG = "冰箱里还有几个蛋啊"

    def test_leftover_matches_planned_after_takeaway_kept(self):
        reply = "刚才拿了两个出来煎给你了，冰箱里应该还剩四个。"
        report = check_inventory_grounding(
            reply,
            [_inv("鸡蛋", 6)],
            context_text=self.CONTEXT_EGG,
        )
        assert not report.has_conflict
        assert report.corrected_text is None

    def test_leftover_without_takeaway_rewritten_to_stock(self):
        reply = "冰箱里应该还剩四个。"
        report = check_inventory_grounding(
            reply,
            [_inv("鸡蛋", 6)],
            context_text=self.CONTEXT_EGG,
        )
        assert report.has_conflict
        assert any(c.kind == "LEFTOVER_MISMATCH" for c in report.conflicts)
        assert report.corrected_text == "冰箱里应该还剩6个。"

    def test_leftover_ambiguous_context_not_guessed(self):
        reply = "冰箱里应该还剩四个。"
        report = check_inventory_grounding(
            reply,
            [_inv("面条", 2), _inv("面包", 1), _inv("鸡蛋", 6)],
            context_text="面条和面包怎么分",
        )
        assert not report.has_conflict
        assert report.corrected_text is None

    def test_leftover_no_context_not_guessed(self):
        reply = "冰箱里应该还剩四个。"
        report = check_inventory_grounding(reply, [_inv("鸡蛋", 6)])
        assert not report.has_conflict
