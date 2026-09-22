from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from app.core.db import WorldRow
from app.repositories import world_repository
from app.services.character_assets import DEFAULT_CHARACTER_ID
from app.services.life.ownership import resolve_owner, assert_access

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _seed_world(
    db_session_factory,
    *,
    world_id: str,
    user_id: str,
    owner_type: str | None,
    owner_id: str | None,
) -> None:
    now = datetime.now()
    with db_session_factory() as session:
        session.add(
            WorldRow(
                id=world_id,
                user_id=user_id,
                name="home",
                time_mode="real_sync",
                current_location="living_room",
                environment={},
                notes=[],
                created_at=now,
                updated_at=now,
                owner_type=owner_type,
                owner_id=owner_id,
            )
        )
        session.commit()


def test_legacy_world_still_loads(db_session_factory):
    _seed_world(
        db_session_factory,
        world_id="home:legacy-user",
        user_id="legacy-user",
        owner_type=None,
        owner_id=None,
    )
    world = world_repository.get_world("legacy-user")
    assert world is not None
    fields = world_repository.get_owner_fields("legacy-user")
    owner = resolve_owner(
        fields, character_id=DEFAULT_CHARACTER_ID, user_id="legacy-user"
    )
    assert owner.owner_type == "character"
    assert owner.is_legacy is True
    decision = assert_access(
        owner,
        user_id="legacy-user",
        character_id=DEFAULT_CHARACTER_ID,
        mode="read",
    )
    assert decision.allowed is True


def test_world_read_failure_degrades_to_empty_context(monkeypatch):
    from app.application import world_engine

    def _boom(user_id: str):
        raise RuntimeError("db down")

    monkeypatch.setattr(world_engine, "ensure_world", _boom)
    assert world_engine.build_context("any-user") is None


def test_user_container_world_created_with_owner(db_session_factory):
    _seed_world(
        db_session_factory,
        world_id="life:u1",
        user_id="u1",
        owner_type="user",
        owner_id="u1",
    )
    rows = world_repository.list_worlds_by_owner("user", "u1")
    assert [row.world_id for row in rows] == ["life:u1"]
    assert world_repository.list_worlds_by_owner("user", "u2") == []
    owner = resolve_owner(
        {"owner_type": "user", "owner_id": "u1"},
        character_id=DEFAULT_CHARACTER_ID,
        user_id="u1",
    )
    assert assert_access(owner, user_id="u1", character_id=DEFAULT_CHARACTER_ID).allowed
    assert not assert_access(
        owner, user_id="u2", character_id=DEFAULT_CHARACTER_ID
    ).allowed


def test_world_repository_owner_filter(db_session_factory):
    _seed_world(
        db_session_factory,
        world_id="home:c1",
        user_id="c-user",
        owner_type="character",
        owner_id="asuna",
    )
    _seed_world(
        db_session_factory,
        world_id="life:u9",
        user_id="u9",
        owner_type="user",
        owner_id="u9",
    )
    character_rows = world_repository.list_worlds_by_owner("character", "asuna")
    user_rows = world_repository.list_worlds_by_owner("user", "u9")
    assert [row.world_id for row in character_rows] == ["home:c1"]
    assert [row.world_id for row in user_rows] == ["life:u9"]


def test_world_domain_modules_untouched():
    result = subprocess.run(
        [
            "git",
            "diff",
            "--stat",
            "--",
            "apps/backend/app/services/world",
            "apps/backend/app/models/world.py",
        ],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""
