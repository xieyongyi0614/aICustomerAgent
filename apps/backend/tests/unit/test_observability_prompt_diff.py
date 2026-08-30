from datetime import datetime

from app.models.observability import CallSite, PromptSnapshot
from app.services.observability.prompt_capture import diff_prompt_snapshots


def _snapshot(snapshot_id="s1", call_site=CallSite.ANSWER, model="fake-a", section_budget=None, messages=None):
    return PromptSnapshot(
        id=snapshot_id,
        request_id="req-1",
        call_site=call_site,
        model=model,
        messages=messages or [{"role": "system", "content": "hi"}],
        section_budget=section_budget,
        created_at=datetime.now(),
    )


def test_diff_reports_section_and_model_changes():
    a = _snapshot(
        snapshot_id="snap-a",
        model="glm-4.7",
        section_budget={"memory": 4100, "total": 10630, "budget": 12000},
        messages=[{"role": "system", "content": "x" * 100}],
    )
    b = _snapshot(
        snapshot_id="snap-b",
        model="minimax-m3",
        section_budget={"memory": 5300, "total": 11890, "budget": 12000},
        messages=[{"role": "system", "content": "y" * 300}],
    )
    diff = diff_prompt_snapshots(a, b)
    assert diff["model_changed"] == {"a": "glm-4.7", "b": "minimax-m3"}
    assert diff["total_chars"] == {"a": 100, "b": 300}
    assert diff["section_diff"]["memory"] == {"a": 4100, "b": 5300}
    assert diff["messages_count"] == {"a": 1, "b": 1}
    assert diff["cross_call_site"] is False


def test_diff_identical_snapshots_have_empty_section_diff():
    budget = {"memory": 100, "total": 500, "budget": 12000}
    diff = diff_prompt_snapshots(
        _snapshot(section_budget=budget), _snapshot(snapshot_id="s2", section_budget=dict(budget))
    )
    assert diff["section_diff"] == {}
    assert diff["total_chars"]["a"] == diff["total_chars"]["b"]
