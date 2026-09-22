from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ledger import ensure_user_bootstrap
from app.services.ledger.category import add_alias, add_category, normalize
from tests.v40.fixtures.ledger_category_samples import LEDGER_CATEGORY_SAMPLES

BACKEND = Path(__file__).resolve().parents[2]
USER = "cat-user"


@pytest.fixture()
def seeded():
    ensure_user_bootstrap(USER)
    return USER


def test_empty_hint_falls_back(seeded):
    result = normalize(seeded, None)
    assert result.reason == "empty_hint"
    assert result.category_name == "其他"


def test_exact_name_match(seeded):
    result = normalize(seeded, "餐饮")
    assert result.reason == "exact"
    assert result.matched_step == 2
    assert result.category_name == "餐饮"


def test_alias_exact_match(seeded):
    result = normalize(seeded, "快餐")
    assert result.reason == "alias"
    assert result.category_name == "餐饮"


def test_rule_normalization_strips_suffix(seeded):
    result = normalize(seeded, "打车费")
    assert result.reason in ("rule", "alias", "substring")
    assert result.category_name == "打车"


def test_substring_long_match_preferred(seeded):
    result = normalize(seeded, "公司楼下快餐")
    assert result.reason == "substring"
    assert result.category_name == "餐饮"


def test_fallback_when_unknown(seeded):
    result = normalize(seeded, "外星人飞船燃料")
    assert result.reason == "fallback"
    assert result.category_name == "其他"


def test_deterministic_same_input(seeded):
    a = normalize(seeded, "黄焖鸡")
    b = normalize(seeded, "黄焖鸡")
    assert a == b


def test_never_creates_category(seeded):
    before = len(__import__("app.repositories.ledger_repository", fromlist=["list_categories"]).list_categories(seeded))
    normalize(seeded, "不存在的类目xyz")
    after = len(__import__("app.repositories.ledger_repository", fromlist=["list_categories"]).list_categories(seeded))
    assert after == before


def test_user_custom_category_preferred(seeded):
    created = add_category(seeded, "我的面馆", "expense", aliases=["楼下那家面馆"])
    result = normalize(seeded, "楼下那家面馆")
    assert result.category_id == created.id
    assert result.category_name == "我的面馆"


def test_add_alias_binds_hint(seeded):
    from app.repositories import ledger_repository

    result = normalize(seeded, "神秘小馆")
    assert result.reason == "fallback"
    categories = {row.name: row for row in ledger_repository.list_categories(seeded)}
    assert add_alias(seeded, categories["餐饮"].id, "神秘小馆") is True
    again = normalize(seeded, "神秘小馆")
    assert again.category_name == "餐饮"
