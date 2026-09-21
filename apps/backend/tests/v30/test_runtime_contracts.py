"""RT-001 契约冻结与语义测试（纯逻辑：零 DB、零 LLM、零网络）。"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.application.agent_runtime import contracts
from app.core.settings.agent_runtime import AgentRuntimeSettings
from tests.v30.runtime_support import V30_RUNTIME_FIELDS

pytestmark = pytest.mark.unit

CONTRACTS_PATH = Path(contracts.__file__)
FORBIDDEN_IMPORT_PREFIXES = (
    "app.repositories",
    "app.services",
    "app.chains",
    "app.prompts",
    "pydantic",
)

EXPECTED_EVENT_TYPES = {
    "RunOpened",
    "StageCompleted",
    "RunClosed",
    "StateVersionBumped",
    "ObservationRecorded",
    "UserMessageReceived",
    "ActionExecuted",
    "ActionCompleted",
    "MemoryUpdated",
    "RelationshipUpdated",
    "DecisionMade",
}
"""冻结事件集 + RT-008 追加项 `DecisionMade`（Reason 段产出通知锚点）。

追加理由见 `contracts.EVENT_DECISION_MADE`：RT-008 §5.3 要求 Reason 段发出该事件，
而 `RuntimeEvent` 对未知类型 fail-closed。属**契约追加**（同批登记），非私改。
"""


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sample_values():
    now = _now()
    return [
        contracts.RuntimeInput(
            kind="channel_message",
            source="web",
            payload={"text": "hi"},
            received_at=now,
        ),
        contracts.SessionContext(session_id="s1"),
        contracts.RunResult(run_id="r1", status="done"),
        contracts.RuntimeEvent(
            event_type=contracts.EVENT_RUN_OPENED,
            run_id="r1",
            session_id="s1",
            occurred_at=now,
        ),
        contracts.RuntimeFailure(
            kind="decision", stage="reason", run_id="r1", recoverable=True
        ),
    ]


def test_field_freeze_constants_match_dataclasses():
    cases = [
        (contracts.RuntimeInput, contracts.RUNTIME_INPUT_FIELDS),
        (contracts.SessionContext, contracts.SESSION_CONTEXT_FIELDS),
        (contracts.RunResult, contracts.RUN_RESULT_FIELDS),
        (contracts.RuntimeEvent, contracts.RUNTIME_EVENT_FIELDS),
        (contracts.RuntimeFailure, contracts.RUNTIME_FAILURE_FIELDS),
    ]
    for cls, frozen in cases:
        assert tuple(f.name for f in dataclasses.fields(cls)) == frozen


@pytest.mark.parametrize(
    "value", _sample_values(), ids=lambda value: type(value).__name__
)
def test_value_objects_are_immutable(value):
    field_name = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field_name, None)


def test_runtime_input_rejects_bad_kind():
    with pytest.raises(ValueError):
        contracts.RuntimeInput(
            kind="nope", source="web", payload={}, received_at=_now()
        )


def test_runtime_input_requires_tz_aware_received_at():
    with pytest.raises(ValueError):
        contracts.RuntimeInput(
            kind="channel_message",
            source="web",
            payload={},
            received_at=datetime(2026, 9, 21, 12, 0, 0),
        )


def test_runtime_input_payload_must_be_json_safe():
    with pytest.raises(ValueError):
        contracts.RuntimeInput(
            kind="channel_message",
            source="web",
            payload={"bad": object()},
            received_at=_now(),
        )


def test_session_context_requires_non_empty_session_id():
    with pytest.raises(ValueError):
        contracts.SessionContext(session_id="")


def test_terminal_status_for_recoverable_matrix():
    recoverable = contracts.RuntimeFailure(
        kind="execution", stage="act", run_id="r1", recoverable=True
    )
    fatal = contracts.RuntimeFailure(
        kind="decision", stage="reason", run_id="r1", recoverable=False
    )
    assert contracts.terminal_status_for(recoverable) == "degraded"
    assert contracts.terminal_status_for(fatal) == "aborted"
    assert contracts.terminal_status_for(recoverable) in ("done", "aborted", "degraded")


def test_event_types_are_unique_and_complete():
    assert len(set(contracts.EVENT_TYPES)) == len(contracts.EVENT_TYPES)
    assert set(contracts.EVENT_TYPES) == EXPECTED_EVENT_TYPES


def _is_forbidden(name: str) -> bool:
    return any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_contracts_module_has_no_forbidden_imports():
    imported = _imported_modules(CONTRACTS_PATH)
    offenders = [name for name in imported if _is_forbidden(name)]
    assert offenders == []


def test_settings_runtime_fields_are_registered():
    runtime_fields = {
        name for name in AgentRuntimeSettings.model_fields if name.startswith("runtime_")
    }
    assert runtime_fields <= set(V30_RUNTIME_FIELDS)


def test_agent_runtime_protocol_exposes_run():
    assert hasattr(contracts.AgentRuntime, "run")
