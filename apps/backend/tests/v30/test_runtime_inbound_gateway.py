"""RT-013 Inbound Gateway 测试：归一 / 会话挂接 / 开关 / 契约零改动。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.application.agent_runtime import inbound as gateway
from app.application.agent_runtime.contracts import RuntimeInput, SessionContext
from app.channels.base import InboundMessage
from app.services.identity import channel as channel_identity_service

INBOUND_PATH = Path(gateway.__file__)
FORBIDDEN_IMPORTS = (
    "app.channels.feishu",
    "app.repositories",
    "app.chains",
    "app.prompts",
    "app.application.chat_pipeline",
)

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
EXTERNAL_USER_ID = "ou_rt013"


def _inbound(**overrides):
    kwargs = {
        "channel": gateway.CHANNEL_FEISHU,
        "external_user_id": EXTERNAL_USER_ID,
        "text": "在吗",
        "received_at": NOW,
        "external_thread_id": "th-1",
        "reply_ref": "om_1",
        "metadata": {"mid": "m1"},
    }
    kwargs.update(overrides)
    return InboundMessage(**kwargs)


class TestNormalize:
    pytestmark = pytest.mark.unit

    def test_normalize_builds_runtime_input(self):
        item = gateway.normalize(
            gateway.CHANNEL_WEB,
            text="你好",
            received_at=NOW,
            external_user_id="u-web",
            thread_id="th-web",
        )

        assert isinstance(item, RuntimeInput)
        assert item.kind == "channel_message"
        assert item.source == gateway.CHANNEL_WEB
        assert dict(item.payload) == {"text": "你好"}
        assert item.thread_id == "th-web"
        assert item.channel_identity is not None
        assert item.channel_identity.channel == gateway.CHANNEL_WEB

    def test_normalize_inbound_maps_inbound_message(self):
        item = gateway.normalize_inbound(_inbound())

        assert item.kind == "channel_message"
        assert item.source == gateway.CHANNEL_FEISHU
        assert item.thread_id == "th-1"
        assert dict(item.payload) == {"mid": "m1", "text": "在吗"}
        assert item.channel_identity is not None
        assert item.channel_identity.external_user_id == EXTERNAL_USER_ID

    def test_normalize_inbound_text_wins_over_metadata(self):
        item = gateway.normalize_inbound(_inbound(metadata={"text": "被覆盖"}))

        assert item.payload["text"] == "在吗"

    def test_normalize_without_identity_leaves_identity_empty(self):
        item = gateway.normalize(
            gateway.CHANNEL_WEB, text="x", received_at=NOW
        )

        assert item.channel_identity is None
        assert item.thread_id is None

    def test_normalize_requires_tz_aware_received_at(self):
        with pytest.raises(ValueError):
            gateway.normalize(
                gateway.CHANNEL_WEB,
                text="x",
                received_at=datetime(2026, 9, 21, 12, 0, 0),
            )

    def test_unknown_channel_fails_closed(self):
        with pytest.raises(ValueError):
            gateway.normalize("discord", text="x", received_at=NOW)

        with pytest.raises(ValueError):
            gateway.resolve_session("discord", "u-1")

    def test_channel_registry_has_no_discord(self):
        assert gateway.CHANNEL_SOURCES == {
            gateway.CHANNEL_WEB: "rest",
            gateway.CHANNEL_FEISHU: "webhook",
        }
        assert "discord" not in gateway.KNOWN_CHANNELS


class TestSession:
    pytestmark = pytest.mark.unit

    def test_resolve_session_matches_existing_derivation(self):
        context = gateway.resolve_session(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID, thread_id="th-1", now=NOW
        )

        assert isinstance(context, SessionContext)
        assert context.session_id == channel_identity_service.build_session_id(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID
        )
        assert context.channel == gateway.CHANNEL_FEISHU
        assert context.external_user_id == EXTERNAL_USER_ID
        assert context.thread_id == "th-1"

    def test_thread_id_does_not_affect_session_id(self):
        with_thread = gateway.resolve_session(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID, thread_id="th-1", now=NOW
        )
        without_thread = gateway.resolve_session(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID, now=NOW
        )

        assert with_thread.session_id == without_thread.session_id
        assert without_thread.thread_id is None

    def test_web_session_uses_same_derivation(self):
        context = gateway.resolve_session(
            gateway.CHANNEL_WEB, "u-web", now=NOW
        )

        assert context.session_id == "web:u-web"


class TestSwitch:
    pytestmark = pytest.mark.unit

    def test_gateway_disabled_by_default(self):
        assert gateway.enabled_channels() == frozenset()
        assert gateway.is_enabled(gateway.CHANNEL_FEISHU) is False
        assert gateway.is_enabled(gateway.CHANNEL_WEB) is False

    def test_enabled_channels_parses_csv(self, override_settings):
        override_settings(runtime_inbound_gateway_channels=" feishu , web ,, ")

        assert gateway.enabled_channels() == frozenset({"feishu", "web"})
        assert gateway.is_enabled("feishu") is True

    def test_enabled_channels_ignores_unknown_entries(self, override_settings):
        override_settings(runtime_inbound_gateway_channels="discord")

        assert gateway.enabled_channels() == frozenset({"discord"})
        assert gateway.is_enabled("feishu") is False


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_core_layer_does_not_import_feishu(self):
        tree = ast.parse(INBOUND_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offenders = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            )
        ]
        assert offenders == []

    def test_gateway_does_not_touch_execution_entry(self):
        """AST 标识符扫描（docstring 里提到 `stream_chat` 属**说明**，不是调用）。"""
        tree = ast.parse(INBOUND_PATH.read_text(encoding="utf-8"))
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                used.add(node.arg)

        assert "stream_chat" not in used
        assert "AgentLoop" not in used
        assert "run_chat_pipeline" not in used


class TestAdapterProjection:
    pytestmark = pytest.mark.integration

    def test_adapter_outcome_unchanged_when_disabled(self):
        from app.channels.feishu import adapter

        outcome = adapter._outcome(
            _inbound(),
            session_id="feishu:" + EXTERNAL_USER_ID,
            user_id="feishu:" + EXTERNAL_USER_ID,
            outbound_text="在的",
            error_kind=None,
        )

        assert outcome.runtime_input is None
        assert outcome.session_context is None
        assert outcome.session_id == "feishu:" + EXTERNAL_USER_ID

    def test_adapter_outcome_carries_projection_when_enabled(self, override_settings):
        from app.channels.feishu import adapter

        override_settings(runtime_inbound_gateway_channels="feishu")
        session_id = "feishu:" + EXTERNAL_USER_ID

        outcome = adapter._outcome(
            _inbound(),
            session_id=session_id,
            user_id=session_id,
            outbound_text="在的",
            error_kind=None,
        )

        assert isinstance(outcome.runtime_input, RuntimeInput)
        assert isinstance(outcome.session_context, SessionContext)
        assert outcome.runtime_input.source == gateway.CHANNEL_FEISHU
        assert outcome.session_context.session_id == session_id
        assert outcome.session_context.thread_id == "th-1"

    def test_feishu_equivalent_before_and_after_enable(self, override_settings):
        """纳管前后：`session_id` / `user_id` / 管线入参逐字段一致（网关是附加面）。"""
        from app.channels.feishu import adapter

        inbound = _inbound()
        session_id = channel_identity_service.build_session_id(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID
        )

        override_settings(runtime_inbound_gateway_channels="")
        before = adapter._outcome(
            inbound,
            session_id=session_id,
            user_id=session_id,
            outbound_text="在的",
            error_kind=None,
        )
        override_settings(runtime_inbound_gateway_channels="feishu")
        after = adapter._outcome(
            inbound,
            session_id=session_id,
            user_id=session_id,
            outbound_text="在的",
            error_kind=None,
        )

        assert before.session_id == after.session_id == session_id
        assert before.user_id == after.user_id
        assert before.outbound_text == after.outbound_text
        assert before.thread_ref == after.thread_ref
        assert after.runtime_input.payload["text"] == inbound.text

    def test_gateway_failure_does_not_break_turn(self, override_settings, monkeypatch):
        from app.channels.feishu import adapter

        override_settings(runtime_inbound_gateway_channels="feishu")

        def _boom(message):
            raise RuntimeError("gateway down")

        monkeypatch.setattr(gateway, "normalize_inbound", _boom)

        outcome = adapter._outcome(
            _inbound(),
            session_id="feishu:" + EXTERNAL_USER_ID,
            user_id="feishu:" + EXTERNAL_USER_ID,
            outbound_text="在的",
            error_kind=None,
        )

        assert outcome.runtime_input is None
        assert outcome.outbound_text == "在的"

    def test_normalize_is_pure_and_resolve_is_readonly(self, db_session_factory):
        from app.core.db import Base

        def _counts():
            with db_session_factory() as session:
                return {
                    table.name: session.query(table).count()
                    for table in Base.metadata.sorted_tables
                }

        before = _counts()

        gateway.normalize_inbound(_inbound())
        gateway.resolve_session(gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID, now=NOW)

        assert _counts() == before

    def test_no_new_rows_from_normalization(self, db_session_factory):
        from app.core.db import Base

        with db_session_factory() as session:
            before = session.query(Base.metadata.tables["channel_identities"]).count()

        gateway.resolve_session(gateway.CHANNEL_FEISHU, "ou_brand_new", now=NOW)

        with db_session_factory() as session:
            after = session.query(Base.metadata.tables["channel_identities"]).count()

        assert after == before


class TestTimeAlignment:
    pytestmark = pytest.mark.unit

    def test_resolve_session_uses_injected_now(self):
        earlier = NOW - timedelta(hours=3)

        context = gateway.resolve_session(
            gateway.CHANNEL_FEISHU, EXTERNAL_USER_ID, now=earlier
        )

        assert context.started_at == earlier
