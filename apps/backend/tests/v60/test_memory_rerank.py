import pytest

from app.chains import memory_rerank_chain as rerank_chain
from app.core.settings import get_settings
from app.core.settings.memory import MemorySettings
from app.models.memory import UserMemory
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import retriever


def _memory(memory_id: str, importance: float = 0.5) -> UserMemory:
    from app.core import timeutil

    now = timeutil.now()
    return UserMemory(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        type="user_preference",
        content=f"{memory_id} 内容",
        importance=importance,
        created_at=now,
        updated_at=now,
    )


class _RerankStub:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls: list[list[str]] = []

    def __call__(self, query, candidates, llm=None):
        ids = [memory_id for memory_id, _ in candidates]
        self.calls.append(ids)
        return [
            rerank_chain.MemoryRerankItem(id=memory_id, score=self.scores[memory_id])
            for memory_id in ids
            if memory_id in self.scores
        ]


class _ReinforceSpy:
    def __init__(self):
        self.ids: list[str] = []

    def __call__(self, memory_id):
        self.ids.append(memory_id)


@pytest.fixture
def memory_pool(monkeypatch):
    """以受控分数替换候选池与打分，隔离真实 DB 与向量路径。"""

    def _install(memories, scores: dict[str, float]):
        ranked = [
            retriever.RankedMemory(memory=memory, score=scores[memory.id])
            for memory in memories
        ]
        monkeypatch.setattr(retriever, "_candidate_pool", lambda *a, **k: list(memories))
        monkeypatch.setattr(retriever, "_score_all", lambda *a, **k: list(ranked))
        monkeypatch.setattr(
            retriever.memory_embeddings, "embed_query", lambda text: None
        )
        return ranked

    return _install


@pytest.fixture
def rerank_settings(monkeypatch):
    settings = get_settings()

    def _apply(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(settings, key, value)
        return settings

    return _apply


@pytest.fixture
def reinforce_spy(monkeypatch):
    spy = _ReinforceSpy()
    monkeypatch.setattr(memory_lifecycle, "record_reinforce", spy)
    return spy


class TestOffMode:
    def test_rerank_off_is_bytewise_identical_to_baseline(
        self, memory_pool, rerank_settings, reinforce_spy, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.1, "m2": 0.9})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="off")
        memories = [_memory("m1", 0.5), _memory("m2", 0.5), _memory("m3", 0.5)]
        memory_pool(memories, {"m1": 0.9, "m2": 0.5, "m3": 0.1})

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in result.items] == ["m1", "m2", "m3"]
        assert [item.score for item in result.items] == [0.9, 0.5, 0.1]
        assert all(item.rerank_score is None for item in result.items)
        assert result.rerank_mode == "off"
        assert stub.calls == []
        assert reinforce_spy.ids == ["m1", "m2", "m3"]

    def test_invalid_rerank_mode_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("MEMORY_RERANK_MODE", "turbo")
        assert MemorySettings().memory_rerank_mode == "off"

    def test_settings_defaults_are_off(self):
        settings = MemorySettings()
        assert settings.memory_rerank_mode == "off"
        assert settings.memory_rerank_top_k == 20
        assert settings.memory_rerank_min_candidates == 3

    def test_settings_clamp_out_of_range_limits(self):
        settings = MemorySettings(memory_rerank_top_k=9999, memory_rerank_min_candidates=0)
        assert settings.memory_rerank_top_k == MemorySettings().memory_candidate_pool_limit
        assert settings.memory_rerank_min_candidates == 1


class TestLiteMode:
    def test_rerank_lite_reorders_by_rerank_score(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.2, "m2": 0.4, "m3": 0.95})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memories = [_memory("m1"), _memory("m2"), _memory("m3")]
        memory_pool(memories, {"m1": 0.9, "m2": 0.5, "m3": 0.1})

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in result.items] == ["m3", "m2", "m1"]
        assert result.rerank_mode == "lite"
        assert result.items[0].rerank_score == pytest.approx(0.95)
        assert stub.calls == [["m1", "m2", "m3"]]

    def test_rerank_skips_when_candidates_below_min(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.9})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=3)
        memory_pool([_memory("m1"), _memory("m2")], {"m1": 0.9, "m2": 0.1})

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert stub.calls == []
        assert result.rerank_mode == "off"

    def test_rerank_pool_capped_at_top_k_and_rest_kept_after(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.05, "m2": 0.05})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(
            memory_rerank_mode="lite",
            memory_rerank_top_k=2,
            memory_rerank_min_candidates=1,
        )
        memories = [_memory(f"m{i}") for i in range(1, 6)]
        memory_pool(
            memories,
            {"m1": 1.0, "m2": 0.9, "m3": 0.8, "m4": 0.7, "m5": 0.6},
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert stub.calls == [["m1", "m2"]]
        reranked = [item.memory.id for item in result.items if item.rerank_score is not None]
        rest = [item.memory.id for item in result.items if item.rerank_score is None]
        assert sorted(reranked) == ["m1", "m2"]
        assert rest == ["m3", "m4", "m5"]
        assert [item.memory.id for item in result.items] == [
            *reranked,
            "m3",
            "m4",
            "m5",
        ]

    def test_rerank_discards_unknown_ids_from_model(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        class _GhostStub(_RerankStub):
            def __call__(self, query, candidates, llm=None):
                self.calls.append([memory_id for memory_id, _ in candidates])
                return [
                    rerank_chain.MemoryRerankItem(id="ghost", score=1.0),
                    rerank_chain.MemoryRerankItem(id="m1", score=0.5),
                ]

        stub = _GhostStub({})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool([_memory("m1"), _memory("m2")], {"m1": 0.9, "m2": 0.1})

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in result.items] == ["m1", "m2"]
        assert "ghost" not in [item.memory.id for item in result.items]

    def test_rerank_missing_candidates_fall_back_to_score(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.3})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memories = [_memory(f"m{i}") for i in range(1, 5)]
        memory_pool(memories, {"m1": 0.9, "m2": 0.8, "m3": 0.7, "m4": 0.6})

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert len(result.items) == 4
        assert result.items[0].memory.id == "m1"
        assert [item.memory.id for item in result.items[1:]] == ["m2", "m3", "m4"]
        assert all(item.rerank_score is None for item in result.items[1:])

    def test_rerank_ties_are_deterministic_by_id(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.5, "m2": 0.5})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool([_memory("m2"), _memory("m1")], {"m1": 0.9, "m2": 0.9})

        first = retriever.retrieve("u1", "查询", top_k=5)
        second = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in first.items] == ["m1", "m2"]
        assert [item.memory.id for item in second.items] == ["m1", "m2"]

    def test_rerank_failure_degrades_and_does_not_raise(
        self, memory_pool, rerank_settings, monkeypatch, caplog
    ):
        def _boom(query, candidates, llm=None):
            raise RuntimeError("llm down")

        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", _boom)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool([_memory("m1"), _memory("m2")], {"m1": 0.9, "m2": 0.1})

        with caplog.at_level("WARNING"):
            result = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in result.items] == ["m1", "m2"]
        assert result.rerank_mode == "off"
        assert all(item.rerank_score is None for item in result.items)
        assert any("记忆重排失败" in record.message for record in caplog.records)

    def test_rerank_does_not_change_score_field(
        self, memory_pool, rerank_settings, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.1, "m2": 0.9})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        memories = [_memory("m1"), _memory("m2")]
        scores = {"m1": 0.9, "m2": 0.5}

        rerank_settings(memory_rerank_mode="off")
        memory_pool(memories, scores)
        off_result = retriever.retrieve("u1", "查询", top_k=5)

        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool(memories, scores)
        lite_result = retriever.retrieve("u1", "查询", top_k=5)

        off_scores = {item.memory.id: item.score for item in off_result.items}
        lite_scores = {item.memory.id: item.score for item in lite_result.items}
        assert off_scores == lite_scores

    def test_reinforce_calls_unchanged_by_rerank(
        self, memory_pool, rerank_settings, reinforce_spy, monkeypatch
    ):
        stub = _RerankStub({"m1": 0.1, "m2": 0.9})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        memories = [_memory("m1"), _memory("m2")]
        scores = {"m1": 0.9, "m2": 0.5}

        rerank_settings(memory_rerank_mode="off")
        memory_pool(memories, scores)
        retriever.retrieve("u1", "查询", top_k=5)
        off_ids = list(reinforce_spy.ids)

        reinforce_spy.ids.clear()
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool(memories, scores)
        retriever.retrieve("u1", "查询", top_k=5)

        assert sorted(reinforce_spy.ids) == sorted(off_ids)

    def test_trace_records_rerank_mode(self, memory_pool, rerank_settings, monkeypatch):
        stub = _RerankStub({"m1": 0.9})
        monkeypatch.setattr(rerank_chain, "rerank_memories_sync", stub)
        rerank_settings(memory_rerank_mode="lite", memory_rerank_min_candidates=1)
        memory_pool([_memory("m1")], {"m1": 0.9})

        class _Step:
            def __init__(self, name, extra):
                self.name = name
                self.extra = extra

        class _TraceSpy:
            def __init__(self):
                self.records = []

            def record(self, name, duration_ms, status="ok", error=None, **extra):
                self.records.append(_Step(name, extra))

        trace = _TraceSpy()
        retriever.retrieve("u1", "查询", trace=trace)

        step = next(s for s in trace.records if s.name == retriever.STEP_NAME)
        assert step.extra["rerank_mode"] == "lite"
        assert step.extra["returned"][0]["rerank_score"] == pytest.approx(0.9)


class TestChainContract:
    def test_ranked_memories_defaults_keep_backward_compatibility(self):
        result = retriever.RankedMemories(items=[])
        assert result.rerank_mode == "off"
        assert result.memories() == []

    def test_chain_returns_empty_for_empty_candidates_without_llm_call(self, fake_llm):
        llm = fake_llm(structured_responses={"MemoryRerankResult": {"items": []}})
        assert rerank_chain.rerank_memories_sync("查询", [], llm) == []
        assert llm.seen_messages == []

    def test_chain_discards_unknown_ids(self, fake_llm):
        llm = fake_llm(
            structured_responses={
                "MemoryRerankResult": {
                    "items": [
                        {"id": "ghost", "score": 1.0},
                        {"id": "m1", "score": 0.5},
                    ]
                }
            }
        )
        items = rerank_chain.rerank_memories_sync(
            "查询", [("m1", "内容一")], llm
        )
        assert [item.id for item in items] == ["m1"]

    @pytest.mark.asyncio
    async def test_chain_async_entry_matches_sync(self, fake_llm):
        llm = fake_llm(
            structured_responses={
                "MemoryRerankResult": {"items": [{"id": "m1", "score": 0.7}]}
            }
        )
        items = await rerank_chain.rerank_memories("查询", [("m1", "内容一")], llm)
        assert [item.id for item in items] == ["m1"]

    def test_chain_raises_on_llm_failure(self, fake_llm):
        llm = fake_llm(raise_exc=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            rerank_chain.rerank_memories_sync("查询", [("m1", "内容一")], llm)

    def test_truncate_content_collapses_whitespace_and_caps_length(self):
        long_text = "甲" * (rerank_chain.RERANK_CONTENT_MAX_CHARS + 50)
        truncated = rerank_chain._truncate_content(f"  {long_text}\n第二行  ")
        assert len(truncated) == rerank_chain.RERANK_CONTENT_MAX_CHARS
        assert "\n" not in truncated

    def test_prompt_version_is_pinned(self):
        from app.prompts import memory_rerank as prompt_module

        assert prompt_module.RERANK_PROMPT_VERSION == 1
