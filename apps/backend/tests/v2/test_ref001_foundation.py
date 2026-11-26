"""REF-001：Insight 存储与生命周期。

状态机全路径表驱动（合法迁移/终态拒绝/终态幂等 no-op/reason 必填）；
迁移往返（SQLite up→down→up 结构一致 + 数据保留）；CHECK 约束兜底；
list_active_insights 过滤（status/confidence/scope/排序）。
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core import timeutil
from app.services.reflection import lifecycle

pytestmark = pytest.mark.xdist_group("migration")

REFLECTION_TABLES = {"insights", "reflection_runs", "evidence_links"}


def _seed_insight(
    session_factory,
    insight_id="ins-1",
    user_id="u-1",
    status="active",
    confidence=0.8,
    scope="user",
    with_reason=False,
) -> str:
    from app.core.db import InsightRow
    from datetime import datetime

    now = timeutil.now()
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                character_id="asuna",
                statement="用户最近持续加班，可能处于工作压力中",
                type="pattern",
                confidence=confidence,
                scope=scope,
                status=status,
                invalidated_reason="seed" if with_reason else None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return insight_id


def _row(session_factory, insight_id):
    from app.core.db import InsightRow

    with session_factory() as session:
        row = session.get(InsightRow, insight_id)
        if row is None:
            return None
        session.expunge(row)
        return row


def test_active_invalidate_transitions_and_keeps_row(db_session_factory):
    _seed_insight(db_session_factory)
    assert (
        lifecycle.invalidate_insight("ins-1", "其实我最近不累", "user_clarification") is True
    )
    row = _row(db_session_factory, "ins-1")
    assert row.status == "invalidated"
    assert row.invalidated_reason == "user_clarification:其实我最近不累"
    assert row.invalidated_at is not None


def test_invalidate_requires_reason(db_session_factory):
    _seed_insight(db_session_factory)
    with pytest.raises(ValueError):
        lifecycle.invalidate_insight("ins-1", "  ")
    with pytest.raises(ValueError):
        lifecycle.invalidate_insight("ins-1", "r", source="unknown")
    assert _row(db_session_factory, "ins-1").status == "active"


def test_invalidate_missing_row_returns_false():
    assert lifecycle.invalidate_insight("nope", "r") is False


def test_invalidate_idempotent_noop_keeps_timestamp(db_session_factory):
    _seed_insight(db_session_factory)
    assert lifecycle.invalidate_insight("ins-1", "第一次") is True
    first = _row(db_session_factory, "ins-1").invalidated_at
    assert lifecycle.invalidate_insight("ins-1", "第二次") is True
    row = _row(db_session_factory, "ins-1")
    assert row.invalidated_at == first
    assert row.invalidated_reason == "user_clarification:第一次"


def test_superseded_then_invalidate_rejected(db_session_factory):
    _seed_insight(db_session_factory, "ins-old")
    _seed_insight(db_session_factory, "ins-new", confidence=0.9)
    assert lifecycle.supersede_insight("ins-old", "ins-new") is True
    assert lifecycle.invalidate_insight("ins-old", "r") is False
    assert _row(db_session_factory, "ins-old").status == "superseded"


def test_supersede_requires_new_active_row(db_session_factory):
    _seed_insight(db_session_factory, "ins-a")
    assert lifecycle.supersede_insight("ins-a", "ins-missing") is False
    _seed_insight(
        db_session_factory, "ins-b", status="invalidated", with_reason=True
    )
    assert lifecycle.supersede_insight("ins-a", "ins-b") is False
    assert _row(db_session_factory, "ins-a").status == "active"


def test_supersede_idempotent_guard_keeps_reference(db_session_factory):
    _seed_insight(db_session_factory, "ins-old")
    _seed_insight(db_session_factory, "ins-new")
    assert lifecycle.supersede_insight("ins-old", "ins-new") is True
    assert lifecycle.supersede_insight("ins-old", "ins-new") is False
    row = _row(db_session_factory, "ins-old")
    assert row.status == "superseded"
    assert row.superseded_by == "ins-new"


def test_state_machine_rejects_unknown_paths():
    with pytest.raises(lifecycle.IllegalTransitionError):
        lifecycle.transition("superseded", lifecycle.EVENT_INVALIDATE)
    with pytest.raises(lifecycle.IllegalTransitionError):
        lifecycle.transition("invalidated", lifecycle.EVENT_SUPERSEDE)
    with pytest.raises(lifecycle.IllegalTransitionError):
        lifecycle.transition("active", "reinforce")


def test_list_active_insights_filters_and_orders(db_session_factory):
    _seed_insight(db_session_factory, "i-low", confidence=0.3, scope="user")
    _seed_insight(db_session_factory, "i-rel", confidence=0.7, scope="relationship")
    _seed_insight(db_session_factory, "i-top", confidence=0.9, scope="user")
    _seed_insight(
        db_session_factory, "i-gone", confidence=0.99, status="invalidated", with_reason=True
    )

    actives = lifecycle.list_active_insights("u-1")
    assert [item.id for item in actives] == ["i-top", "i-rel", "i-low"]

    assert [
        item.id for item in lifecycle.list_active_insights("u-1", min_confidence=0.6)
    ] == ["i-top", "i-rel"]
    assert [
        item.id
        for item in lifecycle.list_active_insights("u-1", scopes=["relationship"])
    ] == ["i-rel"]
    assert lifecycle.list_active_insights("u-other") == []


def test_get_insight_roundtrip(db_session_factory):
    _seed_insight(db_session_factory, "ins-get")
    insight = lifecycle.get_insight("ins-get")
    assert insight is not None
    assert insight.type == "pattern"
    assert insight.scope == "user"
    assert insight.status == "active"
    assert lifecycle.get_insight("missing") is None


def test_invalidated_without_reason_violates_check(db_session_factory):
    _seed_insight(db_session_factory, "ins-c", status="invalidated", with_reason=True)
    with pytest.raises(Exception):
        _seed_insight(db_session_factory, "ins-c2", status="invalidated")


@pytest.fixture(scope="module")
def sqlite_round_trip(tmp_path_factory):
    url = f"sqlite:///{(tmp_path_factory.mktemp('ref001') / 'reflection.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield cfg, url


def _seed_round_trip_rows(url):
    from datetime import datetime

    now = timeutil.now().isoformat(sep=" ")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                # `layer` 由迁移 `0010` 加入且**无 server_default**（fail-closed）：裸 SQL 必须显式给值
                "INSERT INTO memories (id, user_id, content, type, layer, importance,"
                " character_id, confidence, source, status, created_at, updated_at)"
                " VALUES ('mem-rt', 'u-rt', 'v1 往返数据', 'user_fact', 'semantic', 0.5, '*',"
                " 0.9, 'ai_inferred', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO insights (id, user_id, statement, type, confidence, scope,"
                " status, created_at, updated_at)"
                " VALUES ('ins-rt', 'u-rt', '往返认知', 'pattern', 0.8, 'user',"
                " 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO reflection_runs (id, user_id, trigger, status, llm_used,"
                " created_at, updated_at)"
                " VALUES ('run-rt', 'u-rt', 'scheduled', 'queued', 0, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO evidence_links (id, insight_id, memory_id, weight, created_at)"
                " VALUES ('el-rt', 'ins-rt', 'mem-rt', 0.5, :now)"
            ),
            {"now": now},
        )
    engine.dispose()


def test_head_structure_and_seed_data(sqlite_round_trip):
    """原 0024 逆放用例随迁移链折叠退役；保留 head 态结构与数据写入断言。"""
    _cfg, url = sqlite_round_trip
    _seed_round_trip_rows(url)

    engine = create_engine(url)
    inspector = inspect(engine)
    assert REFLECTION_TABLES <= set(inspector.get_table_names())
    insight_columns = {c["name"] for c in inspector.get_columns("insights")}
    assert {
        "id", "user_id", "character_id", "statement", "type", "confidence", "scope",
        "status", "run_id", "created_at", "updated_at", "invalidated_at",
        "invalidated_reason", "superseded_by",
    } <= insight_columns
    run_columns = {c["name"] for c in inspector.get_columns("reflection_runs")}
    assert {
        "id", "user_id", "character_id", "trigger", "status", "evidence_summary",
        "outcome", "llm_used", "insight_ids", "error", "created_at", "updated_at",
    } <= run_columns
    link_columns = {c["name"] for c in inspector.get_columns("evidence_links")}
    assert {"id", "insight_id", "memory_id", "weight", "created_at"} <= link_columns
    # 合并迁移 `0010` 在 SQLite 上同样生效：`memories.layer` 存在（列 + 回填 + 撤默认）
    assert "layer" in {c["name"] for c in inspector.get_columns("memories")}

    with engine.connect() as conn:
        memory = conn.execute(
            text("SELECT id, user_id, content, status FROM memories WHERE id = 'mem-rt'")
        ).fetchone()
    assert memory == ("mem-rt", "u-rt", "v1 往返数据", "active")
    engine.dispose()
