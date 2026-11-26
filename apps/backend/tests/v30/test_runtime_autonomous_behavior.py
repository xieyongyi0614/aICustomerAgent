"""RT-017 Autonomous Behavior Triggering：关联标识 / 投递协调 / 事件 / 幂等保留。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import timeutil
from app.application import autonomy_bridge
from app.application.agent_runtime import (
    contracts,
    events as event_bus,
    outbound as outbound_gateway,
    trigger_router,
)
from app.application.agent_runtime.trigger_router import (
    _BACKGROUND_REASON_TO_TRIGGER,
    classify_proactive_trigger,
)
from app.channels.base import ChannelErrorKind, SendResult

BACKEND = Path(__file__).resolve().parents[2]
BRIDGE_PATH = BACKEND / "app" / "application" / "autonomy_bridge.py"

USER = "rt017-user"
DEDUPE = "auto:greet:2026-09-07"


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    outbound_gateway.clear_adapters()
    yield
    event_bus.clear_subscribers()
    outbound_gateway.clear_adapters()


class _Outbound:
    channel = "feishu"

    def __init__(self):
        self.calls: list = []

    async def send(self, user_id, text, dedupe_key):
        self.calls.append((user_id, text, dedupe_key))
        return SendResult(ok=True, external_message_id="ext-1")


class _Trace:
    def __init__(self):
        self.records: list = []

    def record(self, step, duration_ms=0.0, status="ok", **fields):
        self.records.append((step, status, fields))


class TestTriggerClassification:
    pytestmark = pytest.mark.unit

    def test_trigger_classification_matches_legacy_mapping(self):
        for reason, expected in _BACKGROUND_REASON_TO_TRIGGER.items():
            assert classify_proactive_trigger(reason) == expected
        assert classify_proactive_trigger("unknown_reason") == "schedule"

    def test_correlation_id_is_deterministic(self):
        assert autonomy_bridge.proactive_correlation_id(DEDUPE) == f"proactive:{DEDUPE}"
        assert (
            autonomy_bridge.proactive_correlation_id(DEDUPE)
            == autonomy_bridge.proactive_correlation_id(DEDUPE)
        )
        assert autonomy_bridge.proactive_correlation_id(DEDUPE) != (
            autonomy_bridge.proactive_correlation_id("other")
        )


class TestDeliveryCoordination:
    pytestmark = pytest.mark.unit

    async def test_delivery_goes_through_outbound_gateway(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_outbound_gateway_channels="feishu")
        monkeypatch.setattr(outbound_gateway, "is_routable", lambda channel: True)
        gateway_calls: list = []
        fallback_calls: list = []

        async def _gateway(user_id, text, key, *, channel=None, trace=None):
            gateway_calls.append((user_id, text, key, channel))
            return SendResult(ok=True, external_message_id="gw-1")

        async def _fallback(user_id, text, key):
            fallback_calls.append((user_id, text, key))
            return SendResult(ok=True, external_message_id="fb-1")

        monkeypatch.setattr(outbound_gateway, "deliver_proactive", _gateway)
        outbound = _Outbound()
        outbound.send = _fallback

        result = await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )

        assert result.ok is True
        assert len(gateway_calls) == 1
        assert fallback_calls == []

    async def test_delivery_fallback_when_unmanaged(self, monkeypatch, override_settings):
        override_settings(runtime_outbound_gateway_channels="")
        fallback = _Outbound()

        result = await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=fallback
        )

        assert result.ok is True
        assert fallback.calls == [(USER, "hi", DEDUPE)]

    async def test_quiet_hours_blocks_delivery(self, monkeypatch):
        from app.services.autonomy import executor as proactive_executor
        from app.models.autonomy import ProactiveAction
        from datetime import datetime

        monkeypatch.setattr(
            proactive_executor, "in_quiet_hours", lambda *a, **k: True
        )
        delivered: list = []
        monkeypatch.setattr(
            autonomy_bridge,
            "coordinate_delivery",
            lambda *a, **k: delivered.append(1),
        )
        now = timeutil.now()
        action = ProactiveAction(
            id="act-quiet",
            user_id=USER,
            session_id="s1",
            intention="greet",
            reason="due_trigger",
            trigger_type="scheduled_followup",
            dedupe_key=DEDUPE,
            status="candidate",
            created_at=now,
            updated_at=now,
        )
        reason = proactive_executor._recheck_failed_reason(
            action, USER, "s1", timeutil.now()
        )
        assert reason == "quiet_hours"
        assert delivered == []

    async def test_events_emitted_once_each(self, monkeypatch, override_settings):
        override_settings(runtime_event_bus_enabled="true")
        monkeypatch.setattr(outbound_gateway, "is_routable", lambda channel: True)
        captured: list = []
        event_bus.subscribe(
            contracts.EVENT_PROACTIVE_TRIGGERED, lambda e: captured.append(e)
        )
        event_bus.subscribe(
            contracts.EVENT_PROACTIVE_DELIVERED, lambda e: captured.append(e)
        )

        autonomy_bridge.emit_proactive_triggered(DEDUPE, user_id=USER)
        outbound = _Outbound()
        await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )

        kinds = [e.event_type for e in captured]
        assert kinds.count(contracts.EVENT_PROACTIVE_TRIGGERED) == 1
        assert kinds.count(contracts.EVENT_PROACTIVE_DELIVERED) == 1
        assert all(
            e.correlation_id == f"proactive:{DEDUPE}" for e in captured
        )

    async def test_events_off_emits_zero(self, override_settings):
        override_settings(runtime_event_bus_enabled="false")
        captured: list = []
        event_bus.subscribe(
            contracts.EVENT_PROACTIVE_DELIVERED, lambda e: captured.append(e)
        )
        outbound = _Outbound()
        await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )
        assert captured == []

    async def test_state_machine_untouched_by_gateway(self, monkeypatch, override_settings):
        override_settings(runtime_outbound_gateway_channels="feishu")
        monkeypatch.setattr(outbound_gateway, "is_routable", lambda channel: True)

        async def _fail(*a, **k):
            return SendResult(ok=False, error=ChannelErrorKind.UNKNOWN)

        monkeypatch.setattr(outbound_gateway, "deliver_proactive", _fail)
        outbound = _Outbound()
        outbound.send = _fail

        result = await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )
        assert result.ok is False

    def test_bridge_module_has_no_forbidden_imports(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("app.channels.feishu", "app.chains", "app.prompts"):
            assert all(not name.startswith(forbidden) for name in imported)


class TestFullChain:
    pytestmark = pytest.mark.integration

    async def test_full_chain_traces_by_correlation_id(
        self, db_session_factory, monkeypatch, override_settings
    ):
        override_settings(
            runtime_event_bus_enabled="true",
            runtime_outbound_gateway_channels="feishu",
        )
        monkeypatch.setattr(outbound_gateway, "is_routable", lambda channel: True)
        captured: list = []
        event_bus.subscribe(
            contracts.EVENT_PROACTIVE_TRIGGERED, lambda e: captured.append(e)
        )
        event_bus.subscribe(
            contracts.EVENT_PROACTIVE_DELIVERED, lambda e: captured.append(e)
        )
        trace = _Trace()

        async def _gateway(user_id, text, key, *, channel=None, trace=None):
            return SendResult(ok=True, external_message_id="gw-chain")

        monkeypatch.setattr(outbound_gateway, "deliver_proactive", _gateway)
        outbound = _Outbound()
        outbound.send = _gateway

        autonomy_bridge.emit_proactive_triggered(
            DEDUPE, reason="due_trigger", trigger_type="schedule", user_id=USER, trace=trace
        )
        await autonomy_bridge.coordinate_delivery(
            "a-chain",
            dedupe_key=DEDUPE,
            user_id=USER,
            text="hi",
            outbound=outbound,
            trace=trace,
        )

        correlation = f"proactive:{DEDUPE}"
        assert all(e.correlation_id == correlation for e in captured)
        assert [e.event_type for e in captured] == [
            contracts.EVENT_PROACTIVE_TRIGGERED,
            contracts.EVENT_PROACTIVE_DELIVERED,
        ]
        coord = [r for r in trace.records if r[0] == "proactive_coordinate"]
        assert coord and coord[0][2]["correlation_id"] == correlation

    async def test_dedupe_key_prevents_double_delivery(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_outbound_gateway_channels="")
        outbound = _Outbound()
        first = await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )
        second = await autonomy_bridge.coordinate_delivery(
            "a1", dedupe_key=DEDUPE, user_id=USER, text="hi", outbound=outbound
        )
        assert first.ok and second.ok
        assert outbound.calls == [(USER, "hi", DEDUPE), (USER, "hi", DEDUPE)]
        assert (
            autonomy_bridge.proactive_correlation_id(DEDUPE)
            == autonomy_bridge.proactive_correlation_id(DEDUPE)
        )
