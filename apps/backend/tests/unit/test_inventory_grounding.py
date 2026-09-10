"""库存 grounding 守卫单测。"""

from app.models.world import InventoryItem
from app.services.grounding.inventory_guard import (
    check_inventory_grounding,
    extract_inventory_claims,
    rewrite_grounded,
)


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
    _inv("牛奶", 1, "piece"),
    _inv("可乐", 2),
    _inv("面条", 2, location="home.kitchen.cabinet"),
    _inv("大米", 2, "kg", location="home.kitchen.cabinet"),
    _inv("面包", 1, location="home.kitchen.cabinet"),
]


class TestPass:
    def test_clean_reply_pass(self):
        report = check_inventory_grounding("我去看看冰箱。你先坐会儿。", HOUSEHOLD)
        assert report.action == "pass"
        assert not report.has_conflict

    def test_empty_inventory_pass(self):
        report = check_inventory_grounding("还有剩饭和半盒牛奶。", [])
        assert report.action == "pass"


class TestExistenceConflicts:
    def test_fabricated_leftovers(self):
        reply = "冰箱里还有剩饭和半盒牛奶。你先垫垫肚子。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        kinds = {c.kind for c in report.conflicts}
        assert "NOT_IN_INVENTORY" in kinds
        assert any(c.name == "剩饭" for c in report.conflicts)

    def test_cabbage_not_defined(self):
        reply = "除了刚才拿出来的，还剩半颗卷心菜和两个鸡蛋。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert any(c.name == "卷心菜" for c in report.conflicts)

    def test_correct_remain_pass(self):
        reply = "冰箱里还有鸡蛋6个和牛奶1个。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert not report.has_conflict


class TestQuantityConflicts:
    def test_half_milk_mismatch(self):
        reply = "还有半盒牛奶。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert any(c.kind == "QTY_MISMATCH" and c.name == "牛奶" for c in report.conflicts)

    def test_two_eggs_when_six(self):
        reply = "还剩两个鸡蛋。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert any(c.kind == "QTY_MISMATCH" and c.name == "鸡蛋" for c in report.conflicts)


class TestDepletedConflicts:
    def test_eggs_not_gone(self):
        reply = "鸡蛋没了。刚才那枚刚好用完。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert any(c.kind == "DEPLETED_BUT_HAS" and c.name == "鸡蛋" for c in report.conflicts)


class TestRewrite:
    def test_rewrite_fabricated_remain(self):
        reply = "冰箱里还有剩饭和半盒牛奶。"
        text = rewrite_grounded(reply, HOUSEHOLD)
        assert text is not None
        assert "剩饭" not in text
        assert "牛奶" in text

    def test_rewrite_cabbage_and_eggs(self):
        reply = "还剩半颗卷心菜和两个鸡蛋。"
        text = rewrite_grounded(reply, HOUSEHOLD)
        assert text is not None
        assert "卷心菜" not in text
        assert "鸡蛋" in text

    def test_rewrite_depleted(self):
        reply = "鸡蛋没了。"
        text = rewrite_grounded(reply, HOUSEHOLD)
        assert text is not None
        assert "没了" not in text
        assert "鸡蛋" in text

    def test_report_carries_corrected_text(self):
        reply = "冰箱里还有剩饭和半盒牛奶。你先垫垫肚子。"
        report = check_inventory_grounding(reply, HOUSEHOLD)
        assert report.action == "rewritten"
        assert report.corrected_text is not None
        assert "剩饭" not in report.corrected_text


class TestExtractClaims:
    def test_extract_remain_items(self):
        claims = extract_inventory_claims("还剩半颗卷心菜和两个鸡蛋。", HOUSEHOLD)
        names = {c.name for c in claims}
        assert "卷心菜" in names
        assert "鸡蛋" in names

    def test_extract_depleted(self):
        claims = extract_inventory_claims("鸡蛋没了", HOUSEHOLD)
        assert any(c.kind == "depleted" and c.name == "鸡蛋" for c in claims)
