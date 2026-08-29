from app.services import memory_service
from app.services.memory_policy import PolicyReport
from app.services.trace_collector import TurnTraceSession
from app.repositories import memory_repository as repo
from tests.conftest import FakeLLM


def _extraction(candidates):
    return {"MemoryExtraction": {"candidates": candidates}}


def _save_candidate(content, **overrides):
    payload = {
        "action": "save",
        "type": "user_preference",
        "content": content,
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return payload


def _step(trace, name):
    return next((s for s in trace.steps if s.name == name), None)


async def test_pipeline_records_all_trace_steps(db_session_factory):
    trace = TurnTraceSession()
    llm = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))
    await memory_service.extract_and_save("u1", "我喜欢寿司", "好的", llm=llm, trace=trace)
    assert _step(trace, "memory_extract") is not None
    assert _step(trace, "memory_policy") is not None
    assert _step(trace, "memory_conflict") is not None
    assert all(s.status == "ok" for s in trace.steps)


async def test_extraction_failure_records_error_trace(db_session_factory):
    trace = TurnTraceSession()
    llm = FakeLLM(raise_exc=RuntimeError("llm down"))
    await memory_service.extract_and_save("u1", "x", "y", llm=llm, trace=trace)
    step = _step(trace, "memory_extract")
    assert step is not None
    assert step.status == "error"
    assert step.error == "RuntimeError"
    assert repo.list_by_user("u1") == []


async def test_policy_failure_records_error_trace(db_session_factory, monkeypatch):
    trace = TurnTraceSession()
    llm = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))

    def boom(candidates, active_contents=None):
        raise RuntimeError("policy down")

    monkeypatch.setattr(memory_service, "apply_policy", boom)
    await memory_service.extract_and_save("u1", "x", "y", llm=llm, trace=trace)
    step = _step(trace, "memory_policy")
    assert step is not None
    assert step.status == "error"
    assert repo.list_by_user("u1") == []


async def test_conflict_failure_records_error_trace(db_session_factory, monkeypatch):
    trace = TurnTraceSession()
    llm = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))

    def boom(candidates, active_memories, threshold=None):
        raise RuntimeError("conflict down")

    monkeypatch.setattr(memory_service, "resolve_batch", boom)
    await memory_service.extract_and_save("u1", "x", "y", llm=llm, trace=trace)
    step = _step(trace, "memory_conflict")
    assert step is not None
    assert step.status == "error"
    assert repo.list_by_user("u1") == []


async def test_forget_miss_records_privacy_miss(db_session_factory):
    trace = TurnTraceSession()
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                {
                    "action": "forget",
                    "type": "user_preference",
                    "content": "用户喜欢咖啡",
                    "importance": 0.5,
                    "confidence": 0.95,
                    "source": "user_stated",
                }
            ]
        )
    )
    await memory_service.extract_and_save(
        "u1", "把喜欢咖啡的事忘了吧", "好的", llm=llm, trace=trace
    )
    step = _step(trace, "memory_privacy")
    assert step is not None
    assert step.status == "miss"


async def test_single_write_failure_does_not_block_other_candidates(
    db_session_factory, monkeypatch
):
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                _save_candidate("用户喜欢寿司"),
                _save_candidate("用户在深圳工作", memory_type="user_fact"),
            ]
        )
    )
    original_create = memory_service.repo.create_memory_v4
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("write down")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(memory_service.repo, "create_memory_v4", flaky)
    await memory_service.extract_and_save("u1", "x", "y", llm=llm)
    memories = repo.list_by_user("u1")
    assert len(memories) == 1
    assert memories[0].memory == "用户在深圳工作"


async def test_suppress_round_records_policy_ok_without_writes(db_session_factory):
    trace = TurnTraceSession()
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                _save_candidate("用户在深圳工作", memory_type="user_fact"),
                {
                    "action": "suppress",
                    "type": "user_fact",
                    "content": "用户的收入信息",
                    "importance": 0.9,
                    "confidence": 0.95,
                    "source": "user_stated",
                },
            ]
        )
    )
    await memory_service.extract_and_save("u1", "x", "y", llm=llm, trace=trace)
    assert _step(trace, "memory_policy").status == "ok"
    assert _step(trace, "memory_conflict") is None
    assert repo.list_by_user("u1") == []


def test_policy_report_contract():
    report = PolicyReport()
    assert report.saved == []
    assert report.privacy_items == []
    assert report.discarded == []
