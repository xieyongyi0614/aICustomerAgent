"""DEV-001：Development Aggregate 存储。

状态机全路径（write/arbitrate/retire + 非法转换拒绝 + 终态不复活）；
upsert 仲裁（胜/负/破平/noop）与 changes 审计完整性；strength 越界拒绝；
迁移往返（SQLite up→down→up 结构一致 + v1/P1/P2 数据保留）。
"""

from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.services.development import aggregate

pytestmark = pytest.mark.xdist_group("migration")

DEVELOPMENT_TABLES = {"development_state", "development_changes"}


def _upsert(
    factory,
    key="response_style.length",
    strength=0.8,
    insight_id="ins-1",
    value=None,
    **kwargs,
):
    return aggregate.upsert_modulation(
        "u-1",
        "preference",
        key,
        value if value is not None else {"max_tokens_delta": -150},
        strength,
        insight_id,
        **kwargs,
    )


def test_upsert_creates_active_with_change(db_session_factory):
    outcome = _upsert(db_session_factory)
    assert outcome.outcome == aggregate.OUTCOME_CREATED
    assert outcome.state.status == "active"
    actives = aggregate.list_active_modulations("u-1")
    assert [item.key for item in actives] == ["response_style.length"]
    history = aggregate.get_state_history(actives[0].id)
    assert len(history) == 1
    assert history[0].before is None
    assert history[0].after == {"max_tokens_delta": -150}
    assert history[0].insight_id == "ins-1"
    assert history[0].reason == "compiled"


def test_upsert_lower_strength_loses_and_keeps_trace(db_session_factory):
    _upsert(db_session_factory, strength=0.9, insight_id="ins-win")
    outcome = _upsert(db_session_factory, strength=0.5, insight_id="ins-lose")
    assert outcome.outcome == aggregate.OUTCOME_LOST
    assert outcome.state.status == "superseded"
    actives = aggregate.list_active_modulations("u-1")
    assert len(actives) == 1
    assert actives[0].source_insight_id == "ins-win"
    history = aggregate.get_state_history(outcome.state.id)
    assert history[0].reason == "arbitrated_lost"
    assert history[0].insight_id == "ins-lose"


def test_upsert_higher_strength_replaces_old_row(db_session_factory):
    _upsert(db_session_factory, strength=0.5, insight_id="ins-old", value={"max_tokens_delta": -50})
    outcome = _upsert(
        db_session_factory, strength=0.9, insight_id="ins-new", value={"max_tokens_delta": -150}
    )
    assert outcome.outcome == aggregate.OUTCOME_REPLACED
    actives = aggregate.list_active_modulations("u-1")
    assert len(actives) == 1
    assert actives[0].source_insight_id == "ins-new"
    assert actives[0].value == {"max_tokens_delta": -150}
    history = aggregate.get_state_history(actives[0].id)
    assert history[0].before == {"max_tokens_delta": -50}
    assert history[0].after == {"max_tokens_delta": -150}
    assert history[0].reason == "arbitrated"
    assert history[0].insight_id == "ins-new"


def test_upsert_equal_strength_default_keeps_incumbent(db_session_factory):
    _upsert(db_session_factory, strength=0.8, insight_id="ins-first")
    outcome = _upsert(db_session_factory, strength=0.8, insight_id="ins-second")
    assert outcome.outcome == aggregate.OUTCOME_LOST


def test_upsert_comparator_injection_breaks_tie(db_session_factory):
    _upsert(db_session_factory, strength=0.8, insight_id="ins-first")
    outcome = _upsert(
        db_session_factory,
        strength=0.8,
        insight_id="ins-second",
        comparator=lambda proposal, existing: True,
    )
    assert outcome.outcome == aggregate.OUTCOME_REPLACED


def test_upsert_same_insight_noop(db_session_factory):
    _upsert(db_session_factory, strength=0.8, insight_id="ins-1")
    outcome = _upsert(db_session_factory, strength=0.9, insight_id="ins-1")
    assert outcome.outcome == aggregate.OUTCOME_NOOP
    actives = aggregate.list_active_modulations("u-1")
    assert actives[0].strength == 0.8
    assert len(aggregate.get_state_history(actives[0].id)) == 1


def test_upsert_rejects_strength_out_of_bounds(db_session_factory):
    with pytest.raises(ValueError):
        _upsert(db_session_factory, strength=1.2)
    with pytest.raises(ValueError):
        _upsert(db_session_factory, strength=-0.1)
    assert aggregate.list_active_modulations("u-1") == []


def test_active_uniqueness_same_key_single_row(db_session_factory):
    _upsert(db_session_factory, key="k", insight_id="i1")
    _upsert(db_session_factory, key="k", strength=0.9, insight_id="i2")
    actives = [item for item in aggregate.list_active_modulations("u-1") if item.key == "k"]
    assert len(actives) == 1


def test_retire_withdraws_active_and_records_change(db_session_factory):
    _upsert(db_session_factory)
    state = aggregate.list_active_modulations("u-1")[0]
    assert aggregate.retire_modulation("u-1", "response_style.length", "ins-1") is True
    assert aggregate.list_active_modulations("u-1") == []
    history = aggregate.get_state_history(state.id)
    assert history[-1].before == {"max_tokens_delta": -150}
    assert history[-1].after is None
    assert history[-1].reason == "retired"


def test_retire_without_active_row_noop(db_session_factory):
    assert aggregate.retire_modulation("u-1", "missing", "ins-1") is False


def test_terminal_states_reject_transitions(db_session_factory):
    _upsert(db_session_factory, strength=0.9, insight_id="ins-win")
    _upsert(db_session_factory, strength=0.5, insight_id="ins-lose")
    loser = aggregate.get_state_history("nonexistent")
    assert loser == []
    with pytest.raises(aggregate.IllegalTransitionError):
        aggregate.transition("superseded", aggregate.EVENT_ARBITRATE)
    with pytest.raises(aggregate.IllegalTransitionError):
        aggregate.transition("retired", aggregate.EVENT_ARBITRATE)
    with pytest.raises(aggregate.IllegalTransitionError):
        aggregate.transition("active", "reinforce")


def test_state_rows_isolated_by_user(db_session_factory):
    _upsert(db_session_factory)
    aggregate.upsert_modulation(
        "u-2", "preference", "response_style.length", {"max_tokens_delta": -50}, 0.6, "ins-2"
    )
    assert len(aggregate.list_active_modulations("u-1")) == 1
    assert len(aggregate.list_active_modulations("u-2")) == 1


@pytest.fixture(scope="module")
def sqlite_round_trip(tmp_path_factory):
    url = f"sqlite:///{(tmp_path_factory.mktemp('dev001') / 'development.db').as_posix()}"
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
                "INSERT INTO insights (id, user_id, statement, type, confidence, scope,"
                " status, created_at, updated_at)"
                " VALUES ('ins-rt', 'u-rt', '上游认知', 'preference', 0.8, 'user',"
                " 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO development_state (id, user_id, kind, key, value, strength,"
                " source_insight_id, status, created_at, updated_at)"
                " VALUES ('dev-rt', 'u-rt', 'preference', 'response_style.length',"
                " '{\"max_tokens_delta\": -100}', 0.8, 'ins-rt', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO development_changes (id, development_state_id, before, after,"
                " insight_id, reason, created_at)"
                " VALUES ('devc-rt', 'dev-rt', NULL, '{\"max_tokens_delta\": -100}',"
                " 'ins-rt', 'compiled', :now)"
            ),
            {"now": now},
        )
    engine.dispose()


def test_round_trip_structure_and_data(sqlite_round_trip):
    cfg, url = sqlite_round_trip
    _seed_round_trip_rows(url)

    command.downgrade(cfg, "0025")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert not (DEVELOPMENT_TABLES & set(inspector.get_table_names()))
    with engine.connect() as conn:
        insight = conn.execute(
            text("SELECT id, status FROM insights WHERE id = 'ins-rt'")
        ).fetchone()
    assert insight == ("ins-rt", "active")
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert DEVELOPMENT_TABLES <= set(inspector.get_table_names())
    state_columns = {c["name"] for c in inspector.get_columns("development_state")}
    assert {
        "id", "user_id", "character_id", "kind", "key", "value", "strength",
        "source_insight_id", "status", "created_at", "updated_at",
    } <= state_columns
    change_columns = {c["name"] for c in inspector.get_columns("development_changes")}
    assert {
        "id", "development_state_id", "before", "after", "insight_id", "reason", "created_at"
    } <= change_columns

    with engine.connect() as conn:
        insight = conn.execute(
            text("SELECT id, status FROM insights WHERE id = 'ins-rt'")
        ).fetchone()
        state_count = conn.execute(text("SELECT COUNT(*) FROM development_state")).scalar()
    assert insight == ("ins-rt", "active")
    assert state_count == 0
    engine.dispose()


def test_settings_flag_default_off():
    from app.core.settings import get_settings

    assert get_settings().v2_development_enabled is False
