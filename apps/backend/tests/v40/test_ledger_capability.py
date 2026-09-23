"""PLA-009 账本能力与治理链接入用例。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.models.action import CapabilityResult
from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.action.capabilities.ledger import LedgerCapability
from app.services.action.registry import ExecutionContext, get_capability_registry
from app.services.ledger import ensure_user_bootstrap, record_entry

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "ledger-cap-user"


@pytest.fixture()
def ctx(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    return ExecutionContext(user_id=USER, record_id="act-ledger", now=NOW)


@pytest.fixture()
def account_id(ctx):
    return ledger_repository.list_accounts(USER)[0].id


def _record_params(account_id: str, **overrides) -> dict:
    params = {
        "amount_minor": 2000,
        "direction": "expense",
        "source": "conversation",
        "idempotency_key": "key-record-01",
        "account_id": account_id,
        "occurred_at": NOW.isoformat(),
    }
    params.update(overrides)
    return params


async def test_record_capability_creates_entry(ctx, account_id):
    result = await LedgerCapability().execute("record", _record_params(account_id), ctx)
    assert result.status == "succeeded"
    assert result.payload["entry_id"]
    assert result.payload["created"] is True
    assert ledger_repository.count_entries(USER) == 1


async def test_record_capability_idempotent(ctx, account_id):
    capability = LedgerCapability()
    first = await capability.execute("record", _record_params(account_id), ctx)
    second = await capability.execute("record", _record_params(account_id), ctx)
    assert first.payload["created"] is True
    assert second.payload["created"] is False
    assert second.payload["entry_id"] == first.payload["entry_id"]
    assert ledger_repository.count_entries(USER) == 1


@pytest.mark.parametrize("free_key", ["message", "text", "raw"])
async def test_record_rejects_free_text_payload(ctx, account_id, free_key):
    params = _record_params(account_id)
    params[free_key] = "中午吃了20块快餐"
    result = await LedgerCapability().execute("record", params, ctx)
    assert result.status == "failed"
    assert "拒绝自由文本入参" in (result.error or "")


@pytest.mark.parametrize("amount", ["20", 20.5, True])
async def test_record_rejects_non_integer_amount(ctx, account_id, amount):
    result = await LedgerCapability().execute(
        "record", _record_params(account_id, amount_minor=amount), ctx
    )
    assert result.status == "failed"


@pytest.mark.parametrize("amount", [0, -100])
async def test_record_rejects_non_positive_amount(ctx, account_id, amount):
    result = await LedgerCapability().execute(
        "record", _record_params(account_id, amount_minor=amount), ctx
    )
    assert result.status == "failed"


async def test_record_rejects_invalid_direction(ctx, account_id):
    result = await LedgerCapability().execute(
        "record", _record_params(account_id, direction="spend"), ctx
    )
    assert result.status == "failed"


async def test_record_requires_idempotency_key(ctx, account_id):
    params = _record_params(account_id)
    del params["idempotency_key"]
    result = await LedgerCapability().execute("record", params, ctx)
    assert result.status == "failed"


async def test_query_capability_is_readonly(ctx, account_id):
    capability = LedgerCapability()
    before = ledger_repository.count_entries(USER)
    result = await capability.execute("query", {"period": "month"}, ctx)
    assert result.status == "succeeded"
    assert ledger_repository.count_entries(USER) == before


async def test_revise_capability_creates_reversal(ctx, account_id):
    capability = LedgerCapability()
    created = await capability.execute("record", _record_params(account_id), ctx)
    entry_id = created.payload["entry_id"]
    original = ledger_repository.get_entry(entry_id)
    result = await capability.execute(
        "revise",
        {"entry_id": entry_id, "reason": "记错了", "idempotency_key": "key-revise-01"},
        ctx,
    )
    assert result.status == "succeeded"
    assert result.payload["reversal_of"] == entry_id
    reloaded = ledger_repository.get_entry(entry_id)
    assert (
        reloaded.amount_minor,
        reloaded.direction,
        reloaded.reversal_of,
    ) == (original.amount_minor, original.direction, original.reversal_of)


async def test_capability_never_raises(ctx, account_id, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.ledger.record_entry", boom)
    result = await LedgerCapability().execute("record", _record_params(account_id), ctx)
    assert result.status == "failed"
    assert result.payload["failure_kind"] == "transient"
    assert result.error


def test_capability_has_no_decision_logic():
    source = (BACKEND / "app/services/action/capabilities/ledger.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("decision_pipeline", "autonomy_policy", "autonomy_engine", "goal_repository", "goal_stack"):
        assert forbidden not in source


def test_capability_does_not_call_extraction_chain():
    source = (BACKEND / "app/services/action/capabilities/ledger.py").read_text(
        encoding="utf-8"
    )
    assert "ledger_extraction_chain" not in source
    assert "extract_ledger" not in source


def test_all_capabilities_registered():
    registry = get_capability_registry()
    capability = registry.get("ledger")
    assert capability is not None
    assert set(capability.actions) == {"record", "query", "revise"}
    from app.services.tool.registry import ToolRegistry, register_builtin_tools

    tools = ToolRegistry()
    register_builtin_tools(tools)
    for tool_id in (
        "builtin.ledger.record",
        "builtin.ledger.query",
        "builtin.ledger.revise",
    ):
        definition = tools.get(tool_id)
        assert definition is not None, tool_id
        binding = tools.resolve(tool_id)
        assert binding is not None
        assert binding.capability == "ledger"


async def test_health_circuit_breaker_effective(ctx, account_id):
    from app.core.settings import get_settings
    from app.models.action import ActionStep
    from app.services.action.executor import CapabilityExecutor
    from app.services.tool.health import ToolHealthTracker
    from app.services.tool.registry import ToolRegistry, register_builtin_tools

    class AlwaysFail:
        name = "ledger"
        description = "fail"
        actions = LedgerCapability().actions

        def validate(self, action, params):
            return []

        async def execute(self, action, params, ctx):
            return CapabilityResult(
                status="failed",
                error="boom",
                payload={"failure_kind": "permanent"},
            )

    tools = ToolRegistry()
    register_builtin_tools(tools)
    settings = get_settings()
    tracker = ToolHealthTracker(tools, settings)
    capability = AlwaysFail()

    class _Registry:
        def get(self, name):
            return capability if name == "ledger" else None

    executor = CapabilityExecutor(_Registry(), 1.0)
    step = ActionStep(index=0, capability="ledger", action="record", params={})
    for _ in range(int(settings.tool_breaker_threshold)):
        result = await executor.run(step, ctx)
        assert result.status == "failed"
        tracker.record_outcome(
            "builtin.ledger.record", ok=False, failure_kind="permanent"
        )
    assert tracker.is_tripped("builtin.ledger.record")
    health_record = tracker.snapshot("builtin.ledger.record")["builtin.ledger.record"]
    assert health_record.tripped is True


def test_direct_capability_call_is_absent_in_business_layer():
    offenders = []
    roots = (
        BACKEND / "app/services/ledger",
        BACKEND / "app/api",
        BACKEND / "app/chains",
    )
    needles = (
        "Capability.execute",
        "LedgerCapability(",
        "capabilities.ledger",
    )
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(needle in source for needle in needles):
                offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []


async def test_ledger_query_marks_readonly_in_tool_meta():
    from app.services.tool.registry import ToolRegistry, register_builtin_tools

    tools = ToolRegistry()
    register_builtin_tools(tools)
    assert tools.get("builtin.ledger.query").side_effects == ("read",)
    assert tools.get("builtin.ledger.query").is_read_only() is True
    assert tools.get("builtin.ledger.record").side_effects == ("irreversible",)
    assert tools.get("builtin.ledger.revise").side_effects == ("irreversible",)


async def test_record_goes_through_action_engine(db_session_factory, override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    from app.application import action_engine
    from app.models.action import ActionIntent, ActionPlan, ActionStep
    from app.repositories import action_repository

    intent = ActionIntent(
        action_type="record_ledger_entry",
        confidence="confident",
        params=_record_params(account.id),
        dedupe_key="dk-ledger-engine",
    )
    record = action_engine.new_record(intent, USER, session_id=None)
    plan = ActionPlan(
        intent=intent,
        steps=[
            ActionStep(
                index=0,
                capability="ledger",
                action="record",
                params=_record_params(account.id),
            )
        ],
    )
    ctx = ExecutionContext(
        user_id=USER,
        record_id=record.id,
        now=NOW,
        settings=action_engine.get_settings(),
        dedupe_key=record.dedupe_key,
    )
    result = await action_engine.execute_plan(record, plan, ctx)
    assert result.status == "succeeded"
    saved = action_repository.get_record(record.id)
    assert saved is not None
    assert saved.status == "succeeded"
    assert saved.steps
    step = saved.steps[0]
    assert step.get("tool_id") == "builtin.ledger.record"
    assert "permission" in step
    assert "validation" in step
    assert "duration_ms" in step
