"""API-002 tool_step 独立通道契约测试。"""

from __future__ import annotations

import pytest

from app.application.agent_runtime import contracts
from app.services.tool.step_events import (
    CHAT_EVENT_TOOL_STEP,
    CollectingToolStepSink,
    ToolStepEvent,
    bind_tool_step_sink,
    emit_todo_plan,
    emit_tool_step,
    plan_for,
    reset_tool_step_sink,
)

pytestmark = pytest.mark.unit


def test_ndjson_type_derived_from_contract_constant():
    assert contracts.EVENT_TOOL_STEP == "ToolStepRecorded"
    assert CHAT_EVENT_TOOL_STEP == "tool_step"


def test_ledger_record_plan_has_four_steps():
    plan = plan_for("builtin.ledger.record")
    assert len(plan) == 4
    assert plan[0]["step_id"] == "ledger.extract_amount"
    assert plan[-1]["target"] == "已同步到「生活 · 记账」"


def test_sink_is_turn_local_and_drains():
    sink = CollectingToolStepSink()
    token = bind_tool_step_sink(sink)
    try:
        emit_todo_plan("builtin.ledger.record")
        emit_tool_step(
            step_id="ledger.extract_amount",
            tool_id="builtin.ledger.record",
            label="提取金额",
            status="running",
        )
        events = sink.drain()
        assert len(events) == 5
        assert all(isinstance(e, ToolStepEvent) for e in events)
        assert events[0].status == "todo"
        assert events[-1].status == "running"
        assert sink.drain() == []
    finally:
        reset_tool_step_sink(token)


def test_no_sink_is_noop():
    emit_tool_step(step_id="x", tool_id="y", label="z", status="done")


def test_ndjson_payload_shape():
    event = ToolStepEvent(
        step_id="ledger.persist",
        tool_id="builtin.ledger.record",
        label="保存账单",
        status="done",
        target="已同步到「生活 · 记账」",
    )
    payload = event.to_ndjson_dict()
    assert payload["type"] == "tool_step"
    assert set(payload) == {
        "type",
        "step_id",
        "tool_id",
        "label",
        "status",
        "detail",
        "target",
    }
    assert "params" not in payload
    assert "loop_run_id" not in payload


def test_loop_steps_not_touched():
    src = open(
        "app/services/tool/step_events.py", encoding="utf-8"
    ).read()
    assert "loop_runs" not in src
