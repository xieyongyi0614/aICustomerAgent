from __future__ import annotations

import ast
from pathlib import Path

from app.services.life import ownership
from app.services.life.ownership import (
    OWNER_CHARACTER,
    OWNER_USER,
    AccessDecision,
    OwnerRef,
    assert_access,
    resolve_owner,
    scope_filter,
)

BACKEND = Path(__file__).resolve().parents[2]
OWNERSHIP_PATH = BACKEND / "app" / "services" / "life" / "ownership.py"


def test_resolve_owner_null_is_legacy_character():
    owner = resolve_owner(
        {"owner_type": None, "owner_id": None},
        character_id="asuna",
        user_id="u1",
    )
    assert owner == OwnerRef("character", "asuna", True)


def test_resolve_owner_user_container():
    owner = resolve_owner(
        {"owner_type": "user", "owner_id": "u1"},
        character_id="asuna",
        user_id="u1",
    )
    assert owner == OwnerRef("user", "u1", False)


def test_resolve_owner_unknown_type_degrades():
    owner = resolve_owner(
        {"owner_type": "org", "owner_id": "x"},
        character_id="asuna",
        user_id="u1",
    )
    assert owner.owner_type == OWNER_CHARACTER
    assert owner.owner_id == "asuna"
    assert owner.is_legacy is True


def test_assert_access_same_user_allowed():
    owner = OwnerRef(OWNER_USER, "u1", False)
    decision = assert_access(owner, user_id="u1", character_id="asuna", mode="read")
    assert decision == AccessDecision(True, "same_owner")


def test_assert_access_cross_user_denied():
    owner = OwnerRef(OWNER_USER, "u1", False)
    decision = assert_access(owner, user_id="u2", character_id="asuna", mode="read")
    assert decision == AccessDecision(False, "cross_user_denied")


def test_assert_access_character_world_readonly():
    owner = OwnerRef(OWNER_CHARACTER, "asuna", True)
    read = assert_access(owner, user_id="u1", character_id="asuna", mode="read")
    write = assert_access(owner, user_id="u1", character_id="asuna", mode="write")
    assert read == AccessDecision(True, "character_world_readonly")
    assert write == AccessDecision(False, "character_world_readonly")


def test_assert_access_never_raises():
    cases = (
        OwnerRef("", "", True),
        OwnerRef("?", "?", False),
        OwnerRef(OWNER_USER, "", False),
    )
    for owner in cases:
        for mode in ("read", "write"):
            decision = assert_access(
                owner, user_id="", character_id="", mode=mode
            )
            assert isinstance(decision, AccessDecision)


def test_ownership_module_is_pure():
    source = OWNERSHIP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "app.repositories",
        "app.chains",
        "app.prompts",
        "app.api",
        "app.channels",
        "sqlalchemy",
        "datetime",
    ):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imported
        )
    assert "SessionLocal" not in source
    assert "datetime.now" not in source
    assert "random" not in source


def test_scope_filter_shape():
    owner = OwnerRef(OWNER_USER, "u1", False)
    assert scope_filter(owner) == {"owner_type": "user", "owner_id": "u1"}
    assert set(scope_filter(owner).keys()) == {"owner_type", "owner_id"}
