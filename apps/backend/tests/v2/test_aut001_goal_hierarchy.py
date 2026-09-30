"""AUT-001 Goal 层级与存储扩展测试。

创建守卫（layer/domain/parent 合法性）、层级查询（children/tree/layered）、
goal_plans 存储壳、Sub-Goal 判据白名单校验、旧 goal 行为回归（层级字段
NULL 走 v1 路径）、迁移往返（SQLite up→down→up 结构与数据保留）。
"""

from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.models.goal import (
    GOAL_DESCRIPTION_MAX_LENGTH,
    GoalPlanRecord,
    GoalRecord,
    validate_sub_goals,
)
from app.repositories import goal_repository
from app.services.goal import service as goal_service
from app.character.asuna import PERSISTENT_GOALS

pytestmark = pytest.mark.xdist_group("migration")

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER = "aut-user"
OTHER = "aut-other"


def _v1_record(**overrides) -> GoalRecord:
    base = dict(
        user_id=USER,
        type="user_care",
        description="劝用户早点休息",
        priority=5,
        horizon="current",
        source="policy",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return GoalRecord(**base)


def _sub_goal(**overrides) -> dict:
    base = {
        "index": 1,
        "description": "提醒用户午休",
        "capability": "create_reminder",
        "params": {"content": "午休一下"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    }
    base.update(overrides)
    return base


class TestCreateHierarchicalGoal:
    def test_persists_layered_fields_with_type_mapping(self, db_session_factory):
        record = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "养成规律作息", 4
        )
        assert record.layer == "long_term"
        assert record.domain == "personal"
        assert record.type == "user_care"
        assert record.horizon == "persistent"
        assert record.status == "active"
        assert record.parent_goal_id is None
        assert record.failure_reason is None

    def test_rejects_invalid_layer_and_domain(self, db_session_factory):
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "medium_term", "personal", "非法层", 3
            )
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "long_term", "career", "非法域", 3
            )

    def test_rejects_missing_parent(self, db_session_factory):
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "short_term", "world", "子目标", 3, parent_id="ghost"
            )

    def test_rejects_v1_parent(self, db_session_factory):
        v1 = goal_repository.create_goal(_v1_record())
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "short_term", "world", "子目标", 3, parent_id=v1.id
            )

    def test_long_term_forces_persistent(self, db_session_factory):
        record = goal_repository.create_hierarchical_goal(
            USER, "long_term", "relationship", "长期陪伴", 3, horizon="current"
        )
        assert record.horizon == "persistent"

    def test_short_term_allows_current(self, db_session_factory):
        record = goal_repository.create_hierarchical_goal(
            USER, "short_term", "world", "短期调查", 3, horizon="current"
        )
        assert record.horizon == "current"

    def test_rejects_oversize_description(self, db_session_factory):
        with pytest.raises(ValueError):
            goal_repository.create_hierarchical_goal(
                USER, "long_term", "personal", "x" * (GOAL_DESCRIPTION_MAX_LENGTH + 1), 3
            )


class TestHierarchyQueries:
    def test_children_direct_only(self, db_session_factory):
        root = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "长期目标", 3
        )
        child_one = goal_repository.create_hierarchical_goal(
            USER, "short_term", "personal", "子目标一", 3, parent_id=root.id
        )
        child_two = goal_repository.create_hierarchical_goal(
            USER, "short_term", "personal", "子目标二", 3, parent_id=root.id
        )
        goal_repository.create_hierarchical_goal(
            USER, "short_term", "personal", "别家孩子", 3
        )
        children = goal_repository.list_children(root.id)
        assert {c.id for c in children} == {child_one.id, child_two.id}
        assert all(c.parent_goal_id == root.id for c in children)

    def test_tree_nests_and_isolates_users(self, db_session_factory):
        root = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "树根", 3
        )
        child = goal_repository.create_hierarchical_goal(
            USER, "short_term", "personal", "树枝", 3, parent_id=root.id
        )
        grandchild = goal_repository.create_hierarchical_goal(
            USER, "short_term", "personal", "树叶", 3, parent_id=child.id
        )
        other_root = goal_repository.create_hierarchical_goal(
            OTHER, "long_term", "personal", "别家树根", 3
        )
        tree = goal_repository.list_tree(USER, root.id)
        assert len(tree) == 1
        node = tree[0]
        assert node["goal"].id == root.id
        assert [c["goal"].id for c in node["children"]] == [child.id]
        assert [
            g["goal"].id for g in node["children"][0]["children"]
        ] == [grandchild.id]
        assert goal_repository.list_tree(USER, other_root.id) == []

    def test_layered_active_filters_and_excludes_v1(self, db_session_factory):
        goal_repository.create_goal(_v1_record())
        layered = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "层级目标", 3
        )
        short = goal_repository.create_hierarchical_goal(
            USER, "short_term", "relationship", "短期层级", 3
        )
        assert goal_repository.list_layered_active(USER) == [layered, short]
        assert goal_repository.list_layered_active(USER, layer="long_term") == [layered]
        assert goal_repository.list_layered_active(USER, domain="relationship") == [
            short
        ]
        assert goal_repository.list_layered_active(USER, layer="short_term", domain="personal") == []
        top_level = goal_repository.list_top_level_layered_active(USER)
        assert {g.id for g in top_level} == {layered.id, short.id}


class TestPlanStorage:
    def _plan(self, goal_id: str, version: int, status: str = "draft") -> GoalPlanRecord:
        return GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=[],
            created_at=NOW,
            updated_at=NOW,
        )

    def test_plan_roundtrip(self, db_session_factory):
        goal = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "规划目标", 3
        )
        created = goal_repository.create_plan(self._plan(goal.id, 1))
        assert created.version == 1
        assert created.status == "draft"
        fetched = goal_repository.get_plan(created.id)
        assert fetched is not None and fetched.goal_id == goal.id
        assert goal_repository.count_plans(goal.id) == 1

        plan_v2 = goal_repository.create_plan(self._plan(goal.id, 2, "validated"))
        assert goal_repository.get_latest_plan(goal.id).version == 2
        assert [p.version for p in goal_repository.list_plans(goal.id)] == [2, 1]

        activated = goal_repository.set_plan_status(plan_v2.id, "active")
        assert activated.status == "active"
        rejected = goal_repository.set_plan_rejection(created.id, "capability_unaligned")
        assert rejected.status == "rejected"
        assert rejected.rejection_reason == "capability_unaligned"

    def test_active_plans_join(self, db_session_factory):
        goal = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "联查目标", 3
        )
        draft = goal_repository.create_plan(self._plan(goal.id, 1))
        goal_repository.set_plan_status(draft.id, "active")
        pairs = goal_repository.list_active_plans(USER)
        assert len(pairs) == 1
        assert pairs[0][0].id == goal.id
        assert pairs[0][1].status == "active"

    def test_active_plans_excludes_terminal_goal(self, db_session_factory):
        goal = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "终态目标", 3
        )
        plan = goal_repository.create_plan(self._plan(goal.id, 1))
        goal_repository.set_plan_status(plan.id, "active")
        goal_repository.fail_goal(goal.id, "exec_period_exceeded")
        assert goal_repository.list_active_plans(USER) == []


class TestSubGoalValidation:
    def test_whitelist_passes(self):
        specs = validate_sub_goals(
            [
                _sub_goal(),
                _sub_goal(
                    index=2,
                    criteria={
                        "type": "threshold_reached",
                        "source": "state",
                        "path": "tension",
                        "op": "<=",
                        "value": 0.2,
                    },
                ),
                _sub_goal(
                    index=3,
                    criteria={
                        "type": "all_of",
                        "children": [
                            {"type": "action_succeeded", "capability": "query_environment"},
                            {"type": "field_equals", "source": "world", "path": "weather", "value": "rain"},
                        ],
                    },
                ),
            ]
        )
        assert [s.index for s in specs] == [1, 2, 3]

    def test_rejects_unknown_criterion_type(self):
        with pytest.raises(ValueError):
            validate_sub_goals([_sub_goal(criteria={"type": "user_feels_better"})])

    def test_rejects_free_text_metric_path(self):
        with pytest.raises(ValueError):
            validate_sub_goals(
                [
                    _sub_goal(
                        criteria={
                            "type": "threshold_reached",
                            "source": "state",
                            "path": "用户心情变好",
                            "op": ">=",
                            "value": 1,
                        }
                    )
                ]
            )

    def test_rejects_nested_composite(self):
        with pytest.raises(ValueError):
            validate_sub_goals(
                [
                    _sub_goal(
                        criteria={
                            "type": "all_of",
                            "children": [
                                {"type": "any_of", "children": [{"type": "field_equals", "source": "state", "path": "mood", "value": "calm"}]}
                            ],
                        }
                    )
                ]
            )

    def test_rejects_forward_dependency(self):
        with pytest.raises(ValueError):
            validate_sub_goals([_sub_goal(depends_on=[2]), _sub_goal(index=2)])

    def test_rejects_three_level_nesting(self):
        with pytest.raises(ValueError):
            validate_sub_goals(
                [
                    _sub_goal(),
                    _sub_goal(index=2, parent_index=1),
                    _sub_goal(index=3, parent_index=2),
                ]
            )

    def test_rejects_index_gap(self):
        with pytest.raises(ValueError):
            validate_sub_goals([_sub_goal(), _sub_goal(index=3)])


class TestV1Regression:
    def test_goal_record_defaults_backward_compatible(self):
        record = _v1_record()
        assert record.parent_goal_id is None
        assert record.layer is None
        assert record.domain is None
        assert record.failure_reason is None

    def test_v1_seeds_run_through_v1_path(self, db_session_factory):
        goal_repository.seed_goals(USER, PERSISTENT_GOALS)
        for record in goal_repository.list_active(USER):
            assert record.layer is None
            assert record.domain is None
        active = goal_repository.list_active(USER)
        selected = goal_service.select(
            active,
            tension=0.1,
            user_emotion="calm",
            character_mood="calm",
            character_intensity=0.2,
            scene_pending=False,
            late_night=False,
        )
        assert selected.goal is not None
        assert selected.goal.type == "user_care"
        assert goal_service.list_layered_active(USER) == []

    def test_persistent_layered_goal_immune_to_turn_expiry(self, db_session_factory):
        layered = goal_repository.create_hierarchical_goal(
            USER, "long_term", "personal", "永不过期", 3
        )
        from app.application import life_loop

        assert life_loop._expire_due_goals(USER) == []
        refreshed = goal_repository.get_goal(layered.id)
        assert refreshed.status == "active"


@pytest.fixture(scope="module")
def sqlite_round_trip(tmp_path_factory):
    url = f"sqlite:///{(tmp_path_factory.mktemp('aut001') / 'hierarchy.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield cfg, url


def _seed_round_trip_rows(url):
    now = datetime.now().isoformat(sep=" ")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO character_goals (id, user_id, character_id, type,"
                " description, priority, status, horizon, source, created_turn,"
                " created_at, updated_at)"
                " VALUES ('goal-v1', 'u-rt', 'asuna', 'user_care', 'v1旧目标', 3,"
                " 'active', 'persistent', 'definition', 0, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO character_goals (id, user_id, character_id, type,"
                " description, priority, status, horizon, source, created_turn,"
                " created_at, updated_at, parent_goal_id, layer, domain)"
                " VALUES ('goal-v2', 'u-rt', 'asuna', 'user_care', '层级目标', 3,"
                " 'active', 'persistent', 'policy', 0, :now, :now, NULL,"
                " 'long_term', 'personal')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO goal_plans (id, goal_id, version, status, sub_goals,"
                " created_at, updated_at)"
                " VALUES ('plan-rt', 'goal-v2', 1, 'active', '[]', :now, :now)"
            ),
            {"now": now},
        )
    engine.dispose()


def test_head_structure_and_seed_data(sqlite_round_trip):
    """原 0030/0031 往返用例随迁移链折叠退役；保留 head 态结构与数据写入断言。"""
    _cfg, url = sqlite_round_trip
    _seed_round_trip_rows(url)

    engine = create_engine(url)
    inspector = inspect(engine)
    assert "goal_plans" in inspector.get_table_names()
    goal_columns = {c["name"] for c in inspector.get_columns("character_goals")}
    assert {"parent_goal_id", "layer", "domain", "failure_reason"} <= goal_columns
    plan_columns = {c["name"] for c in inspector.get_columns("goal_plans")}
    assert {"id", "goal_id", "version", "status", "sub_goals"} <= plan_columns
    with engine.connect() as conn:
        v1 = conn.execute(
            text(
                "SELECT layer, domain, failure_reason FROM character_goals"
                " WHERE id = 'goal-v1'"
            )
        ).fetchone()
        plan_count = conn.execute(text("SELECT COUNT(*) FROM goal_plans")).scalar()
    assert v1 == (None, None, None)
    assert plan_count == 1
    engine.dispose()
