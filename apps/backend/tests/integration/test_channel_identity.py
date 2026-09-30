
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect

from app.channels.base import RecipientRef
from app.models.relationship import RelationshipState
from app.models.world import WorldObject
from app.repositories import (
    channel_identity_repository,
    conversation_repository,
    memory_repository,
    relationship_repository,
    world_repository,
)
from app.services.identity import channel as service


def _resolve(open_id):
    return service.resolve(
        "feishu", open_id, union_id=f"un_{open_id}", tenant_key="tk_x"
    )


def test_resolve_idempotent(db_session_factory):
    first = _resolve("ou_idem")
    second = _resolve("ou_idem")
    assert first.created is True
    assert second.created is False
    assert first.internal_user_id == second.internal_user_id == "feishu:ou_idem"
    assert first.session_id == second.session_id == "feishu:ou_idem"
    assert channel_identity_repository.find("feishu", "ou_idem") is not None
    assert len(channel_identity_repository.list_by_internal_user("feishu:ou_idem")) == 1


def test_resolve_stores_optional_metadata(db_session_factory):
    service.resolve("feishu", "ou_meta", union_id="un_meta", tenant_key="tk_meta")
    row = channel_identity_repository.find("feishu", "ou_meta")
    assert row.external_union_id == "un_meta"
    assert row.external_tenant_key == "tk_meta"
    assert row.status == "active"


def test_get_or_create_integrity_error_path_recovers(db_session_factory, monkeypatch):
    _resolve("ou_conflict")
    real_find = channel_identity_repository.find
    calls = []

    def _find_then_none(channel, external_id):
        calls.append(1)
        if len(calls) == 1:
            return None
        return real_find(channel, external_id)

    monkeypatch.setattr(channel_identity_repository, "find", _find_then_none)
    row, created = channel_identity_repository.get_or_create(
        "feishu", "ou_conflict", "feishu:ou_conflict", "feishu:ou_conflict"
    )
    assert created is False
    assert row.internal_user_id == "feishu:ou_conflict"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_concurrent_resolve_single_row(db_session_factory):
    import asyncio

    async def _resolve_async():
        return _resolve("ou_race")

    results = await asyncio.gather(*[_resolve_async() for _ in range(8)])
    assert len({r.internal_user_id for r in results}) == 1
    assert results[0].internal_user_id == "feishu:ou_race"
    assert len(channel_identity_repository.list_by_internal_user("feishu:ou_race")) == 1


def test_find_miss_and_hit_detached(db_session_factory):
    assert channel_identity_repository.find("feishu", "ou_missing") is None
    _resolve("ou_detached")
    row = channel_identity_repository.find("feishu", "ou_detached")
    assert row.external_id == "ou_detached"
    assert row.internal_user_id == "feishu:ou_detached"


def test_update_identity(db_session_factory):
    _resolve("ou_update")
    row = channel_identity_repository.update_identity(
        "feishu", "ou_update", display_name="亚丝娜", session_id="feishu:ou_update:s2"
    )
    assert row.display_name == "亚丝娜"
    assert row.session_id == "feishu:ou_update:s2"
    assert row.internal_user_id == "feishu:ou_update"
    assert channel_identity_repository.update_identity("feishu", "ou_none") is None


def test_list_by_internal_user_filters(db_session_factory):
    _resolve("ou_list_a")
    _resolve("ou_list_b")
    rows = channel_identity_repository.list_by_internal_user("feishu:ou_list_a")
    assert [row.external_id for row in rows] == ["ou_list_a"]


def test_resolve_recipient_hit(db_session_factory):
    _resolve("ou_recipient")
    recipient = service.resolve_recipient("feishu:ou_recipient", "feishu")
    assert isinstance(recipient, RecipientRef)
    assert recipient.channel == "feishu"
    assert recipient.external_id == "ou_recipient"
    assert not hasattr(recipient, "open_id")


def test_resolve_recipient_unknown_returns_none(db_session_factory):
    assert service.resolve_recipient("feishu:ou_ghost", "feishu") is None
    assert service.resolve_recipient("", "feishu") is None
    assert service.resolve_recipient("feishu:ou_x", "") is None


def test_resolve_recipient_channel_mismatch_returns_none(db_session_factory):
    _resolve("ou_channel")
    assert service.resolve_recipient("feishu:ou_channel", "web") is None


def test_resolve_recipient_exact_channel_match_among_rows(db_session_factory):
    row, _ = channel_identity_repository.get_or_create(
        "feishu", "ou_multi", "feishu:ou_multi", "feishu:ou_multi"
    )
    channel_identity_repository.get_or_create(
        "web", "ou_multi", "feishu:ou_multi", "feishu:ou_multi"
    )
    recipient = service.resolve_recipient("feishu:ou_multi", "web")
    assert recipient is not None
    assert recipient.channel == "web"
    assert recipient.external_id == "ou_multi"
    assert channel_identity_repository.find("feishu", "ou_multi") is not None


def test_resolve_recipient_deterministic_on_tie(db_session_factory):
    for channel in ("feishu", "web"):
        channel_identity_repository.get_or_create(
            channel, "ou_tie", "feishu:ou_tie", "feishu:ou_tie"
        )
    first = service.resolve_recipient("feishu:ou_tie", "web")
    second = service.resolve_recipient("feishu:ou_tie", "web")
    assert first == second


def test_resolve_recipient_uses_external_id_not_session_prefix(db_session_factory):
    channel_identity_repository.get_or_create(
        "feishu", "ou_real", "feishu:ou_real", "rebound-session-id"
    )
    recipient = service.resolve_recipient("feishu:ou_real", "feishu")
    assert recipient is not None
    assert recipient.external_id == "ou_real"
    assert recipient.external_id != "rebound-session-id"


def test_resolve_recipient_read_only(db_session_factory):
    _resolve("ou_ro")
    before = len(channel_identity_repository.list_by_internal_user("feishu:ou_ro"))
    for _ in range(3):
        service.resolve_recipient("feishu:ou_ro", "feishu")
    after = len(channel_identity_repository.list_by_internal_user("feishu:ou_ro"))
    assert before == after == 1


def _write_minimal_chain(open_id: str) -> None:
    identity = _resolve(open_id)
    conversation_repository.get_or_create_conversation(
        identity.session_id, identity.internal_user_id
    )
    conversation_repository.save_message(
        identity.session_id, "human", f"你好，我是 {open_id}"
    )
    memory_repository.create_memory(
        identity.internal_user_id, "asuna", f"{open_id} 喜欢寿司", "user_preference", 0.8
    )
    world = world_repository.ensure_world(identity.internal_user_id)
    world_repository.save_object(
        WorldObject(
            id=f"obj_{open_id}",
            world_id=world.world_id,
            name="煎锅",
            location_id="kitchen",
            state="idle",
        )
    )
    relationship_repository.upsert_relationship(
        identity.internal_user_id,
        RelationshipState(intimacy=0.9, trust=0.9),
    )


def test_isolation_matrix_between_two_open_ids(db_session_factory):
    _write_minimal_chain("ou_iso_a")
    identity_b = _resolve("ou_iso_b")

    assert conversation_repository.get_latest_for_user("feishu:ou_iso_b") is None
    assert memory_repository.list_by_user("feishu:ou_iso_b") == []
    world_b = world_repository.ensure_world("feishu:ou_iso_b")
    assert world_b.world_id == "home:feishu:ou_iso_b"
    assert world_repository.world_id_for("feishu:ou_iso_a") == "home:feishu:ou_iso_a"
    assert world_b.world_id != world_repository.world_id_for("feishu:ou_iso_a")
    assert world_repository.list_objects("home:feishu:ou_iso_b") == []
    assert len(world_repository.list_objects("home:feishu:ou_iso_a")) == 1
    relationship_b = relationship_repository.get_relationship("feishu:ou_iso_b")
    assert relationship_b.intimacy == pytest.approx(0.3)
    assert relationship_b.intimacy != pytest.approx(0.9)

    identity_a = service.resolve("feishu", "ou_iso_a")
    assert identity_a.internal_user_id != identity_b.internal_user_id
    assert identity_a.session_id != identity_b.session_id


@pytest.fixture(scope="module")
def _pg_url():
    import os

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    pg_url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://asuna:asuna@127.0.0.1:5432/asuna_test"
    )
    server_url = pg_url.rsplit("/", 1)[0] + "/postgres"
    database_name = pg_url.rsplit("/", 1)[1]
    try:
        server = create_engine(server_url, connect_args={"connect_timeout": 2})
        with server.connect() as connection:
            connection.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f'CREATE DATABASE "{database_name}"')
            )
        server.dispose()
    except Exception as exc:
        if "already exists" not in str(exc):
            pytest.skip("PostgreSQL 不可用：docker compose up -d 后重跑")

    engine = create_engine(pg_url, pool_pre_ping=True)
    from app.core.db import Base

    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(alembic_cfg, "head")
    yield alembic_cfg, pg_url


@pytest.mark.xdist_group("migration")
def test_migration_0036_roundtrip_on_postgres(_pg_url):
    """FEISHU-005：channel_identities 表的 PG 最终态断言（原 0035/0036 往返已随折叠退役）。"""
    alembic_cfg, pg_url = _pg_url
    engine = create_engine(pg_url)
    inspector = inspect(engine)
    assert "channel_identities" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("channel_identities")}
    assert columns == {
        "channel",
        "external_id",
        "internal_user_id",
        "session_id",
        "external_union_id",
        "external_tenant_key",
        "display_name",
        "status",
        "created_at",
        "updated_at",
    }
    pk = inspector.get_pk_constraint("channel_identities")
    assert set(pk["constrained_columns"]) == {"channel", "external_id"}
    index_names = {index["name"] for index in inspector.get_indexes("channel_identities")}
    assert "idx_channel_identities_user" in index_names
    engine.dispose()


@pytest.mark.xdist_group("migration")
def test_orm_metadata_matches_migration_columns(_pg_url):
    from sqlalchemy import text as _text

    from app.core.db import Base

    alembic_cfg, pg_url = _pg_url
    del _text
    engine = create_engine(pg_url)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        expected = {column.name for column in table.columns}
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        assert expected == actual, table.name
    engine.dispose()
