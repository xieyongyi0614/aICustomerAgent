from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.db import SceneStateRow
from app.models.scene import PendingAction, SceneState
from app.repositories import scene_state_repository


def test_get_scene_state_returns_default_when_missing(db_session_factory):
    state = scene_state_repository.get_scene_state("no-such-session")
    assert isinstance(state, SceneState)
    assert state.session_id == "no-such-session"
    assert state.turn_id == 0
    assert state.location is None
    assert state.pending_action is None


def test_upsert_and_get_round_trip(db_session_factory):
    state = SceneState(
        session_id="s-1",
        turn_id=3,
        location="客厅",
        current_activity="休息",
        current_action="切西瓜",
        pending_action=PendingAction(action="把西瓜拿给用户", created_at_turn=2),
    )
    saved = scene_state_repository.upsert_scene_state("s-1", state)
    assert saved.location == "客厅"

    loaded = scene_state_repository.get_scene_state("s-1")
    assert loaded.turn_id == 3
    assert loaded.location == "客厅"
    assert loaded.current_activity == "休息"
    assert loaded.current_action == "切西瓜"
    assert loaded.pending_action is not None
    assert loaded.pending_action.action == "把西瓜拿给用户"
    assert loaded.pending_action.status == "pending"
    assert loaded.pending_action.created_at_turn == 2


def test_upsert_updates_existing_row_in_place(db_session_factory):
    scene_state_repository.upsert_scene_state(
        "s-1",
        SceneState(session_id="s-1", turn_id=1, location="客厅"),
    )
    scene_state_repository.upsert_scene_state(
        "s-1",
        SceneState(session_id="s-1", turn_id=5, location="厨房"),
    )
    with db_session_factory() as session:
        rows = session.query(SceneStateRow).filter_by(session_id="s-1").all()
        assert len(rows) == 1
        assert rows[0].turn_id == 5
        assert rows[0].location == "厨房"
    loaded = scene_state_repository.get_scene_state("s-1")
    assert loaded.location == "厨房"


def test_scene_mood_is_not_persisted(db_session_factory):
    scene_state_repository.upsert_scene_state(
        "s-1", SceneState(session_id="s-1", location="客厅", scene_mood="relaxed")
    )
    with db_session_factory() as session:
        row = session.get(SceneStateRow, "s-1")
        assert not hasattr(row, "scene_mood")
    loaded = scene_state_repository.get_scene_state("s-1")
    assert loaded.scene_mood is None


def test_scene_state_migration_matches_orm_metadata(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "scene_state" in tables

    actual = {c["name"] for c in inspector.get_columns("scene_state")}
    expected = {c.name for c in SceneStateRow.__table__.columns}
    assert actual == expected
    engine.dispose()
