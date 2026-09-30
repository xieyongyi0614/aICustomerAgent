import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.channels.base import InboundMessage
from app.channels.feishu.identity import FEISHU_CHANNEL, to_channel_identity
from app.services.identity import channel as service
from app.services.identity.channel import (
    build_internal_user_id,
    build_session_id,
)

IDENTITY_PATH = Path("app/channels/feishu/identity.py")


def test_feishu_channel_constant_frozen():
    assert FEISHU_CHANNEL == "feishu"


def test_build_internal_user_id():
    assert build_internal_user_id("feishu", "ou_x") == "feishu:ou_x"


def test_build_session_id():
    assert build_session_id("feishu", "ou_x") == "feishu:ou_x"


def test_derivation_deterministic():
    first = build_internal_user_id("feishu", "ou_a")
    second = build_internal_user_id("feishu", "ou_a")
    assert first == second
    assert build_session_id("feishu", "ou_a") == build_session_id("feishu", "ou_a")


def test_different_external_ids_never_collide():
    assert build_internal_user_id("feishu", "ou_a") != build_internal_user_id("feishu", "ou_b")
    assert build_internal_user_id("feishu", "ou_a") != build_internal_user_id("web", "ou_a")


def test_session_prefix_isolated_from_web_uuid_sessions():
    derived = build_session_id("feishu", "ou_x")
    web_session = str(uuid.uuid4())
    assert derived.startswith("feishu:")
    assert derived != web_session
    assert ":" in derived and web_session.count("-") == 4


@pytest.mark.parametrize("channel", ["", "   "])
def test_empty_channel_rejected(channel):
    with pytest.raises(ValueError):
        build_internal_user_id(channel, "ou_x")
    with pytest.raises(ValueError):
        build_session_id(channel, "ou_x")


@pytest.mark.parametrize("external_id", ["", "   "])
def test_empty_external_id_rejected(external_id):
    with pytest.raises(ValueError):
        build_internal_user_id("feishu", external_id)
    with pytest.raises(ValueError):
        build_session_id("feishu", external_id)


def test_resolved_identity_is_frozen_value_object():
    identity = service.ResolvedIdentity(
        channel="feishu", external_id="ou_x", internal_user_id="feishu:ou_x",
        session_id="feishu:ou_x", created=True,
    )
    assert identity.created is True
    with pytest.raises(Exception):
        identity.created = False


def _inbound(metadata=None):
    return InboundMessage(
        channel="feishu",
        external_user_id="ou_open",
        text="你好",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata=metadata or {},
    )


def test_to_channel_identity_mapping():
    identity = to_channel_identity(
        _inbound({"tenant_key": "tk_1", "union_id": "un_1"})
    )
    assert identity.channel == "feishu"
    assert identity.external_user_id == "ou_open"
    assert identity.tenant == "tk_1"
    assert identity.display_name is None


def test_to_channel_identity_missing_tenant_key_is_none():
    identity = to_channel_identity(_inbound())
    assert identity.tenant is None


def test_identity_py_pure_no_repository_import():
    tree = ast.parse(IDENTITY_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("app.repositories") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("app.repositories")
            assert not module.startswith("app.core.db")
