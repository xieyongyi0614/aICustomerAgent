"""API-017 「养车」分类种子：树完整性 / 全局唯一 / 既有用户补齐 / 别名解析。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.character.asuna.ledger_categories import SEED_CATEGORY_TREE
from app.repositories import ledger_repository
from app.services.ledger import category as category_service
from app.services.ledger import service as ledger_service

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 30, 12, 0, 0)

CAR_PARENT = "养车"
CAR_CHILDREN = ("充电", "加油费", "停车费", "过路", "保养", "洗车")
TRANSPORT_CHILDREN = ("公交地铁", "打车", "加油", "停车")
CAR_NODES = (CAR_PARENT, *CAR_CHILDREN)
LEGACY_TREE = tuple(
    node for node in SEED_CATEGORY_TREE if node["name"] not in CAR_NODES
)


def _by_name(user_id: str) -> dict:
    return {row.name: row for row in ledger_repository.list_categories(user_id)}


def test_seed_tree_has_car_parent_and_six_children(db_session_factory):
    ledger_service.ensure_user_bootstrap("car-seed-fresh", now=NOW)
    rows = _by_name("car-seed-fresh")
    parent = rows[CAR_PARENT]
    assert parent.parent_id is None
    assert parent.kind == "expense"
    for name in CAR_CHILDREN:
        child = rows[name]
        assert child.parent_id == parent.id
        assert child.kind == "expense"


def test_seed_tree_category_names_are_globally_unique(db_session_factory):
    ledger_service.ensure_user_bootstrap("car-seed-unique", now=NOW)
    names = [row.name for row in ledger_repository.list_categories("car-seed-unique")]
    assert len(names) == len(set(names))


def test_car_children_do_not_collide_with_transport_children(db_session_factory):
    ledger_service.ensure_user_bootstrap("car-seed-nocollide", now=NOW)
    rows = _by_name("car-seed-nocollide")
    transport = {rows[name].id for name in TRANSPORT_CHILDREN}
    car = {rows[name].id for name in CAR_CHILDREN}
    assert transport.isdisjoint(car)
    assert not ({rows[name].name for name in TRANSPORT_CHILDREN} & set(CAR_CHILDREN))


def test_existing_user_gets_car_subtree_on_next_bootstrap(db_session_factory):
    user_id = "car-seed-existing"
    ledger_repository.ensure_seed_categories(user_id, seed_tree=LEGACY_TREE, now=NOW)
    before = _by_name(user_id)
    legacy_ids = {name: before[name].id for name in TRANSPORT_CHILDREN}
    assert CAR_PARENT not in before

    report = ledger_service.ensure_user_bootstrap(user_id, now=NOW)
    after = _by_name(user_id)
    assert report.categories_created == 7
    for name in CAR_NODES:
        assert name in after
    for name, category_id in legacy_ids.items():
        assert after[name].id == category_id


def test_car_aliases_normalize_to_car_children(db_session_factory):
    user_id = "car-seed-alias"
    ledger_service.ensure_user_bootstrap(user_id, now=NOW)
    cases = {
        "充电": "充电",
        "快充": "充电",
        "换电": "充电",
        "高速费": "过路",
        "ETC": "过路",
        "小保养": "保养",
        "4S店": "保养",
        "月卡": "停车费",
        "洗车费": "洗车",
        "加油费": "加油费",
        "养车": "养车",
    }
    for hint, expected in cases.items():
        assert category_service.normalize(user_id, hint, now=NOW).category_name == expected


def test_unshadowed_legacy_aliases_keep_precedence(db_session_factory):
    user_id = "car-seed-legacy"
    ledger_service.ensure_user_bootstrap(user_id, now=NOW)
    legacy_cases = {
        "加油": "加油",
        "油费": "加油",
        "汽油": "加油",
        "充电桩": "加油",
        "停车": "停车",
        "过路费": "交通",
    }
    for hint, expected in legacy_cases.items():
        assert category_service.normalize(user_id, hint, now=NOW).category_name == expected


def test_car_names_take_precedence_over_legacy_aliases(db_session_factory):
    user_id = "car-seed-shadow"
    ledger_service.ensure_user_bootstrap(user_id, now=NOW)
    shadowed_cases = {
        "停车费": "停车费",
        "加油费": "加油费",
        "洗车": "洗车",
    }
    for hint, expected in shadowed_cases.items():
        assert category_service.normalize(user_id, hint, now=NOW).category_name == expected


def test_seed_aliases_are_marked_is_seed(db_session_factory):
    ledger_service.ensure_user_bootstrap("car-seed-flag", now=NOW)
    for name in CAR_NODES:
        assert _by_name("car-seed-flag")[name].is_seed is True


def test_seed_tree_is_additive_over_legacy_nodes(db_session_factory):
    legacy_names = {node["name"] for node in LEGACY_TREE}
    ledger_service.ensure_user_bootstrap("car-seed-additive", now=NOW)
    rows = _by_name("car-seed-additive")
    assert legacy_names <= set(rows)
    assert len(rows) == len(LEGACY_TREE) + len(CAR_NODES)
