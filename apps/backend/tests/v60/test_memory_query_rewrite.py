"""MEV-002 Query Rewrite and Multi-Query Memory Recall（focused + module）。"""

import inspect
from pathlib import Path

import pytest

from app.chains import memory_query_rewrite_chain as rewrite_chain
from app.core.settings import get_settings
from app.core.settings.memory import MemorySettings
from app.models.memory import UserMemory
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import retriever

BACKEND_ROOT = Path(retriever.__file__).resolve().parents[3]

PRESERVED_FUNCTION_DIGESTS = {
    "_detect_query_types": "f1a9eb1a8292a92e",
    "_recency": "b44950f139577ace",
    "_structured_score": "0fbe8b0ac3a297b8",
    "_affinity_score": "70f5dfb1d4f00d76",
    "_filter_reasons": "4c543692219eb3af",
}

_ORIGINAL_RECALL = retriever._recall
_ORIGINAL_REWRITE = retriever.memory_query_rewrite.rewrite_queries_sync


@pytest.fixture(autouse=True)
def _restore_retriever_seams():
    """用例后显式还原被替换的 retriever 模块级接缝。

    xdist 下 `monkeypatch` 的 undo 偶发失效（本仓库实测，MEV-001 用例同样受影响），
    一旦泄漏会污染同 worker 的其他用例。这里按**模块导入期**捕获的真身无条件还原，
    使本文件不可能向外泄漏。
    """
    yield
    retriever._recall = _ORIGINAL_RECALL
    retriever.memory_query_rewrite.rewrite_queries_sync = _ORIGINAL_REWRITE


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


def _ranked(pairs) -> list:
    return [
        retriever.RankedMemory(memory=_memory(memory_id), score=score)
        for memory_id, score in pairs
    ]


def _item(memory_id: str, **components) -> retriever.RankedMemory:
    return retriever.RankedMemory(memory=_memory(memory_id), **components)


def _source_digest(function) -> str:
    import hashlib

    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class _TraceSpy:
    def __init__(self):
        self.records = []

    def record(self, name, duration_ms, status="ok", error=None, **extra):
        self.records.append(extra | {"name": name})

    def step(self, name):
        return next(record for record in self.records if record["name"] == name)


class _ReinforceSpy:
    def __init__(self):
        self.ids = []

    def __call__(self, memory_id):
        self.ids.append(memory_id)


class _RewriteStub:
    def __init__(self):
        self.calls = []
        self.result = []
        self.error = None

    def __call__(self, user_input, llm=None):
        self.calls.append(user_input)
        if self.error is not None:
            raise self.error
        return list(self.result)


@pytest.fixture
def rewrite_settings(override_settings):
    """经 env + cache_clear 改设置（仓库既有 `override_settings` 模式）。

    不用实例级 monkeypatch：后者在 xdist worker 内会跨用例泄漏（本仓库实测）。
    """

    def _apply(**kwargs):
        kwargs.setdefault("memory_rerank_mode", "off")
        override_settings(**kwargs)
        return get_settings()

    return _apply


@pytest.fixture
def rewrite_stub(monkeypatch):
    stub = _RewriteStub()
    monkeypatch.setattr(retriever.memory_query_rewrite, "rewrite_queries_sync", stub)
    return stub


@pytest.fixture
def recall_stub(monkeypatch):
    """以 query 文本为键注入逐 query 召回结果，隔离真实 DB / 向量 / 打分。

    `_install(...)` 返回本次收到的 `(query_text, query_embedding)` 序列，供向量化入口断言。
    """

    def _install(by_query, mode=retriever.MODE_HYBRID):
        seen: list = []

        def _fake(user_id, character_id, query_text, now, query_embedding=None):
            seen.append((query_text, query_embedding))
            items = list(by_query.get(query_text, []))
            return items, mode, len(items)

        monkeypatch.setattr(retriever, "_recall", _fake)
        return seen

    return _install


@pytest.fixture
def reinforce_spy(monkeypatch):
    spy = _ReinforceSpy()
    monkeypatch.setattr(memory_lifecycle, "record_reinforce", spy)
    return spy


class TestOffMode:
    def test_rewrite_off_is_bytewise_identical_to_baseline(
        self, recall_stub, rewrite_settings, rewrite_stub, reinforce_spy
    ):
        rewrite_settings(memory_query_rewrite_mode="off")
        recall_stub({"查询": _ranked([("m1", 0.9), ("m2", 0.5), ("m3", 0.1)])})
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        assert [item.memory.id for item in result.items] == ["m1", "m2", "m3"]
        assert [item.score for item in result.items] == [0.9, 0.5, 0.1]
        assert result.rewrite_mode == "off"
        assert rewrite_stub.calls == []
        assert reinforce_spy.ids == ["m1", "m2", "m3"]
        step = trace.step(retriever.STEP_NAME)
        assert step["rewrite_mode"] == "off"
        assert step["queries_count"] == 1
        assert step["matched_queries"] == []

    def test_settings_defaults_are_off(self):
        settings = MemorySettings()
        assert settings.memory_query_rewrite_mode == "off"
        assert settings.memory_query_rewrite_max_queries == 2

    def test_invalid_rewrite_mode_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("MEMORY_QUERY_REWRITE_MODE", "fast")
        assert MemorySettings().memory_query_rewrite_mode == "off"

    def test_valid_rewrite_mode_is_accepted(self):
        assert (
            MemorySettings(memory_query_rewrite_mode=" LITE ").memory_query_rewrite_mode
            == "lite"
        )

    def test_settings_clamp_out_of_range_max_queries(self):
        assert MemorySettings(memory_query_rewrite_max_queries=0).memory_query_rewrite_max_queries == 1
        assert MemorySettings(memory_query_rewrite_max_queries=9).memory_query_rewrite_max_queries == 3


class TestRewriteCleaning:
    def test_rewrite_drops_identical_blank_and_overlong_queries(self):
        raw = ["  查询  ", "", "   ", "甲" * 121, "改写A", "改写A", "改写B"]
        cleaned = rewrite_chain._clean_queries(raw, "查询", 2)
        assert cleaned == ["改写A", "改写B"]

    def test_rewrite_keeps_first_occurrence_order_and_truncates(self):
        raw = ["改写B", "改写A", "改写B", "改写C"]
        assert rewrite_chain._clean_queries(raw, "查询", 3) == ["改写B", "改写A", "改写C"]
        assert rewrite_chain._clean_queries(raw, "查询", 1) == ["改写B"]

    def test_normalize_collapses_whitespace_and_folds_case(self):
        assert rewrite_chain._normalize("  Foo\t Bar  ") == "foo bar"

    def test_prompt_version_is_pinned(self):
        from app.prompts import memory_query_rewrite as prompt_module

        assert prompt_module.REWRITE_PROMPT_VERSION == 1
        assert rewrite_chain.QUERY_MAX_CHARS == 120


class TestRewriteChain:
    def test_chain_returns_empty_for_blank_input_without_llm_call(self, fake_llm):
        llm = fake_llm(structured_responses={"QueryRewriteResult": {"queries": ["x"]}})
        assert rewrite_chain.rewrite_queries_sync("   ", llm) == []
        assert llm.seen_messages == []

    def test_chain_cleans_model_output(self, fake_llm, rewrite_settings):
        rewrite_settings(memory_query_rewrite_max_queries=3)
        llm = fake_llm(
            structured_responses={
                "QueryRewriteResult": {
                    "queries": [" 查询 ", "", "甲" * 121, "改写A", "改写A", "改写B", "改写C", "改写D"]
                }
            }
        )
        assert rewrite_chain.rewrite_queries_sync("查询", llm) == ["改写A", "改写B", "改写C"]

    def test_prompt_query_limit_follows_settings(self, fake_llm, rewrite_settings):
        rewrite_settings(memory_query_rewrite_max_queries=3)
        llm = fake_llm(structured_responses={"QueryRewriteResult": {"queries": []}})

        rewrite_chain.rewrite_queries_sync("查询", llm)

        prompt_value = llm.seen_messages[0][0]
        rendered = "\n".join(
            str(message.content) for message in prompt_value.to_messages()
        )
        assert "最多 3 条" in rendered

    def test_chain_returns_empty_on_llm_failure(self, fake_llm, caplog):
        llm = fake_llm(raise_exc=RuntimeError("boom"))
        with caplog.at_level("WARNING"):
            assert rewrite_chain.rewrite_queries_sync("查询", llm) == []
        assert any("记忆查询改写失败" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_chain_async_entry_matches_sync(self, fake_llm):
        llm = fake_llm(structured_responses={"QueryRewriteResult": {"queries": ["改写A"]}})
        assert await rewrite_chain.rewrite_queries("查询", llm) == ["改写A"]

    def test_rewrite_chain_uses_lite_profile(self, monkeypatch):
        calls = []

        def _fake_get_llm(profile_id=None):
            calls.append(profile_id)
            return object()

        monkeypatch.setattr(rewrite_chain, "get_llm", _fake_get_llm)
        rewrite_chain._resolve_llm()
        assert calls == ["lite"]


class TestMultiQueryRecall:
    def test_rewrite_empty_result_falls_back_to_single_query(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = []
        recall_stub({"查询": _ranked([("m1", 0.9)])})
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        assert result.rewrite_mode == "off"
        assert rewrite_stub.calls == ["查询"]
        assert trace.step(retriever.STEP_NAME)["queries_count"] == 1

    def test_rewrite_truncated_at_max_queries(
        self, fake_llm, recall_stub, rewrite_settings, monkeypatch
    ):
        rewrite_settings(memory_query_rewrite_mode="lite", memory_query_rewrite_max_queries=2)
        llm = fake_llm(
            structured_responses={
                "QueryRewriteResult": {"queries": ["r1", "r2", "r3", "r4", "r5"]}
            }
        )
        original = rewrite_chain.rewrite_queries_sync
        monkeypatch.setattr(
            retriever.memory_query_rewrite,
            "rewrite_queries_sync",
            lambda text: original(text, llm),
        )
        recall_stub(
            {
                "查询": _ranked([("m1", 0.9)]),
                "r1": _ranked([("m2", 0.5)]),
                "r2": _ranked([("m3", 0.4)]),
            }
        )
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        assert result.rewrite_mode == "lite"
        assert trace.step(retriever.STEP_NAME)["queries_count"] == 3

    def test_multi_query_embeds_once_by_batch(
        self, recall_stub, rewrite_settings, rewrite_stub, monkeypatch
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写A", "改写B"]
        batches = []
        vectors = {"查询": [0.1], "改写A": [0.2], "改写B": [0.3]}

        def _batch(texts):
            batches.append(list(texts))
            return [vectors[text] for text in texts]

        monkeypatch.setattr(retriever.memory_embeddings, "embed_queries", _batch)
        seen = recall_stub(
            {
                "查询": [_item("m0", structured=0.9)],
                "改写A": [_item("m1", structured=0.8)],
                "改写B": [_item("m2", structured=0.7)],
            }
        )

        retriever.retrieve("u1", "查询", top_k=5)

        assert batches == [["查询", "改写A", "改写B"]]
        assert [embedding for _, embedding in seen] == [[0.1], [0.2], [0.3]]

    def test_single_query_keeps_single_embedding_entry(
        self, recall_stub, rewrite_settings, monkeypatch
    ):
        rewrite_settings(memory_query_rewrite_mode="off")
        singles = []
        monkeypatch.setattr(
            retriever.memory_embeddings,
            "embed_query",
            lambda text: singles.append(text) or [0.4],
        )

        def _unexpected_batch(texts):
            raise AssertionError("单路不应走批量向量化")

        monkeypatch.setattr(
            retriever.memory_embeddings, "embed_queries", _unexpected_batch
        )
        seen = recall_stub({"查询": [_item("m0", structured=0.9)]})

        retriever.retrieve("u1", "查询", top_k=5)

        assert singles == ["查询"]
        assert [embedding for _, embedding in seen] == [[0.4]]

    def test_merge_dedupes_by_memory_id_and_takes_max_components(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {
                "查询": [_item("m1", semantic=0.9, structured=0.2, affinity=0.0)],
                "改写": [
                    _item("m1", semantic=0.1, structured=0.8, affinity=1.0),
                    _item("m2", semantic=0.3, structured=0.3, affinity=0.0),
                ],
            }
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        ids = [item.memory.id for item in result.items]
        assert ids.count("m1") == 1
        merged = next(item for item in result.items if item.memory.id == "m1")
        assert merged.semantic == pytest.approx(0.9)
        assert merged.structured == pytest.approx(0.8)
        assert merged.affinity == pytest.approx(1.0)

    def test_merge_affinity_keeps_no_keyword_fallback(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        """某条 query 无类型关键词时 `affinity` 兜底 0.5 会被 max 保留（D3 的已知推论）。"""
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {
                "查询": [_item("m1", structured=0.5, affinity=0.5)],
                "改写": [_item("m1", structured=0.5, affinity=0.0)],
            }
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert result.items[0].affinity == pytest.approx(0.5)

    def test_merge_takes_max_penalty_conservatively(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {
                "查询": [_item("m2", structured=0.4, penalty=0.0)],
                "改写": [_item("m2", structured=0.4, penalty=0.2)],
            }
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        merged = next(item for item in result.items if item.memory.id == "m2")
        assert merged.penalty == pytest.approx(0.2)

    def test_merge_recomputes_score_with_same_weights(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {
                "查询": [_item("m1", semantic=0.9, structured=0.2, affinity=0.0)],
                "改写": [
                    _item("m1", semantic=0.1, structured=0.8, affinity=1.0),
                    _item("m2", semantic=0.3, structured=0.6, affinity=0.0),
                ],
            }
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        settings = get_settings()
        for item in result.items:
            expected = (
                settings.memory_weight_semantic * item.semantic
                + settings.memory_weight_structured * item.structured
                + settings.memory_weight_affinity * item.affinity
            )
            assert item.score == pytest.approx(expected, abs=1e-9)

    def test_merge_reason_records_matched_query_indexes(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        """命中 query 序号记在 `RankedMemory.matched_queries`（不占用既有 penalty `reason`）。"""
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {
                "查询": [_item("m0", structured=0.9)],
                "改写": [_item("m1", structured=0.8)],
            }
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        by_id = {item.memory.id: item for item in result.items}
        assert by_id["m0"].matched_queries == "q0"
        assert by_id["m1"].matched_queries == "q1"

    def test_multiquery_temporal_boost_when_any_query_has_time_word(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        settings = get_settings()

        rewrite_stub.result = ["改写"]
        recall_stub({"查询": [_item("m1", structured=1.0, affinity=0.5)]})
        plain = retriever.retrieve("u1", "查询", top_k=5)

        rewrite_stub.result = ["昨天的事"]
        recall_stub({"查询": [_item("m1", structured=1.0, affinity=0.5)]})
        boosted = retriever.retrieve("u1", "查询", top_k=5)

        plain_score = plain.items[0].score
        boosted_score = boosted.items[0].score
        assert boosted_score > plain_score
        assert boosted_score - plain_score == pytest.approx(
            settings.memory_temporal_recency_boost, abs=1e-3
        )

    def test_merge_mode_falls_back_to_degraded(
        self, recall_stub, rewrite_settings, rewrite_stub
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        recall_stub(
            {"查询": [_item("m1", structured=0.5)], "改写": [_item("m2", structured=0.4)]},
            mode=retriever.MODE_DEGRADED,
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert result.mode == retriever.MODE_DEGRADED

    def test_filters_and_reinforce_applied_once_after_merge(
        self, recall_stub, rewrite_settings, rewrite_stub, reinforce_spy, monkeypatch
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.result = ["改写"]
        counts = {"rejected": 0, "cooldown": 0}

        def _rejected(user_id, now):
            counts["rejected"] += 1
            return []

        def _cooldown(user_id, now):
            counts["cooldown"] += 1
            return set()

        monkeypatch.setattr(retriever, "_recently_rejected_contents", _rejected)
        monkeypatch.setattr(retriever, "_contradicts_cooldown_ids", _cooldown)
        recall_stub(
            {"查询": [_item("m1", structured=0.9)], "改写": [_item("m2", structured=0.8)]}
        )

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert counts == {"rejected": 1, "cooldown": 1}
        assert reinforce_spy.ids == [item.memory.id for item in result.items]

    def test_rewrite_failure_degrades_and_does_not_raise(
        self, recall_stub, rewrite_settings, rewrite_stub, caplog
    ):
        rewrite_settings(memory_query_rewrite_mode="lite")
        rewrite_stub.error = RuntimeError("llm down")
        recall_stub({"查询": _ranked([("m1", 0.9), ("m2", 0.1)])})
        trace = _TraceSpy()

        with caplog.at_level("WARNING"):
            result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        assert [item.memory.id for item in result.items] == ["m1", "m2"]
        assert result.rewrite_mode == "off"
        assert trace.step(retriever.STEP_NAME)["queries_count"] == 1
        assert any("记忆查询改写失败" in record.message for record in caplog.records)


class TestContracts:
    def test_signature_unchanged_for_existing_callers(self):
        signature = inspect.signature(retriever.retrieve)
        assert list(signature.parameters) == [
            "user_id",
            "query",
            "character_id",
            "top_k",
            "trace",
        ]
        assert signature.parameters["character_id"].default == "asuna"
        assert signature.parameters["top_k"].default is None
        assert signature.parameters["trace"].default is None

        conversation = (
            BACKEND_ROOT / "app" / "services" / "conversation" / "context.py"
        ).read_text(encoding="utf-8")
        assert "memory_retriever.retrieve(user_id, current_input, trace=trace)" in conversation
        planning = (
            BACKEND_ROOT / "app" / "services" / "planning" / "context.py"
        ).read_text(encoding="utf-8")
        assert "ranked = memory_retriever.retrieve(" in planning
        assert "goal.user_id, query=goal.description, top_k=settings.memory_top_k" in planning

    def test_ranked_memories_defaults_keep_backward_compatibility(self):
        result = retriever.RankedMemories(items=[])
        assert result.rewrite_mode == "off"
        assert result.rerank_mode == "off"
        assert result.memories() == []

    def test_scoring_functions_unchanged(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _source_digest(getattr(retriever, name)) == digest, name

    def test_mode_enum_values_unchanged(self):
        assert retriever.MODE_HYBRID == "hybrid"
        assert retriever.MODE_STRUCTURED == "structured"
        assert retriever.MODE_DEGRADED == "degraded"
        assert retriever.REWRITE_MODE_OFF == "off"
        assert retriever.REWRITE_MODE_LITE == "lite"

    def test_no_new_event_type_registered(self):
        from app.application.agent_runtime import contracts
        from tests.v30.test_runtime_contracts import EXPECTED_EVENT_TYPES

        assert set(contracts.EVENT_TYPES) == EXPECTED_EVENT_TYPES

    def test_no_new_migration_and_pins_unchanged(self):
        from tests.support import schema_pins

        # 钉值升级声明（2026-10-16，MEV-015）：词表收窄迁移 `0010` 入链，HEAD/PARENT 随之推进
        # （原 `0009` / `0008`）；本任务（query 改写）自身仍零迁移，表数与列摘要不变。
        assert schema_pins.MIGRATION_HEAD == "0010"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0009"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == "f4f1cc5b50ae78ed"

    def test_services_do_not_import_application(self):
        for relative in (
            "app/chains/memory_query_rewrite_chain.py",
            "app/services/memory/retriever.py",
        ):
            source = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
            assert "app.application" not in source, relative
            assert "app.services.planning" not in source, relative
