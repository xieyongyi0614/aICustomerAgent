"""MEV-008 分层检索配额：解析 / 截取 / 补齐 / 分数不变 / 禁用态一致。

契约：`docs/version/v6.0.0/tasks/MEV-008.md` §4.1.1 / §4.1.2 与 §7.1 / §7.2。
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from app.core import timeutil
from app.core.settings import get_settings
from app.models.memory import UserMemory
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import retriever
from app.services.memory import types as memory_types
from tests.support import schema_pins
from tests.support.frozen_surface import file_digest

EPISODIC_TYPE = "experience"
SEMANTIC_TYPE = "user_preference"

PRESERVED_FUNCTION_DIGESTS = {
    "_recency": "b44950f139577ace",
    "_structured_score": "0fbe8b0ac3a297b8",
    "_affinity_score": "70f5dfb1d4f00d76",
    "_filter_reasons": "4c543692219eb3af",
}


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _memory(memory_id: str, memory_type: str = SEMANTIC_TYPE, importance: float = 0.5):
    now = timeutil.now()
    return UserMemory(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        type=memory_type,
        content=f"{memory_id} 内容",
        importance=importance,
        created_at=now,
        updated_at=now,
    )


def _unknown_layer_memory(memory_id: str):
    """构造层未知的条目：`type` 越出规范词表（`model_construct` 绕过校验）。"""
    now = timeutil.now()
    return UserMemory.model_construct(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        type="legacy_unknown_type",
        content=f"{memory_id} 内容",
        importance=0.5,
        created_at=now,
        updated_at=now,
    )


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
        monkeypatch.setattr(retriever.memory_embeddings, "embed_query", lambda text: None)
        return ranked

    return _install


@pytest.fixture
def quota_settings(monkeypatch):
    settings = get_settings()

    def _apply(**kwargs):
        monkeypatch.setattr(settings, "memory_rerank_mode", "off")
        monkeypatch.setattr(settings, "memory_query_rewrite_mode", "off")
        for key, value in kwargs.items():
            monkeypatch.setattr(settings, key, value)
        return settings

    return _apply


@pytest.fixture
def reinforce_spy(monkeypatch):
    spy = _ReinforceSpy()
    monkeypatch.setattr(memory_lifecycle, "record_reinforce", spy)
    return spy


def _interleaved_pool(count: int):
    """构造 episodic / semantic 交替的候选，返回 (memories, scores)。"""
    memories = []
    scores = {}
    score = 1.0
    for index in range(count):
        episodic_id = f"e{index + 1}"
        semantic_id = f"s{index + 1}"
        memories.append(_memory(episodic_id, EPISODIC_TYPE))
        memories.append(_memory(semantic_id, SEMANTIC_TYPE))
        scores[episodic_id] = round(score, 4)
        scores[semantic_id] = round(score - 0.05, 4)
        score -= 0.1
    return memories, scores


class TestQuotaParsing:
    def test_parse_layer_quota_accepts_valid_pair(self):
        assert retriever.parse_layer_quota("3:5") == (3, 5)
        assert retriever.parse_layer_quota("1:1") == (1, 1)
        assert retriever.parse_layer_quota(" 2 : 7 ") == (2, 7)

    def test_parse_layer_quota_rejects_invalid_and_disables(
        self, memory_pool, quota_settings, caplog
    ):
        invalid = ("3", "a:b", "0:5", "3:-1", "101:1", "1:2:3", "3.5:1")
        with caplog.at_level("WARNING"):
            for raw in invalid:
                assert retriever.parse_layer_quota(raw) is None, raw
        assert any("MEMORY_LAYER_QUOTA" in record.message for record in caplog.records)

        memories, scores = _interleaved_pool(5)
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="a:b")
        result = retriever.retrieve("u1", "查询", top_k=4)
        assert [item.memory.id for item in result.items] == ["e1", "s1", "e2", "s2"]

    def test_empty_quota_is_silent_and_disabled(self, caplog):
        with caplog.at_level("WARNING"):
            assert retriever.parse_layer_quota("") is None
            assert retriever.parse_layer_quota("   ") is None
        assert not any("MEMORY_LAYER_QUOTA" in record.message for record in caplog.records)


class TestQuotaSelection:
    def test_quota_disabled_is_bytewise_identical_to_baseline(
        self, memory_pool, quota_settings, reinforce_spy
    ):
        memories, scores = _interleaved_pool(5)
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="")

        result = retriever.retrieve("u1", "查询", top_k=4)

        assert [item.memory.id for item in result.items] == ["e1", "s1", "e2", "s2"]
        assert [item.score for item in result.items] == [1.0, 0.95, 0.9, 0.85]
        assert reinforce_spy.ids == ["e1", "s1", "e2", "s2"]

    def test_quota_allocation_matches_floor_rule(self, memory_pool, quota_settings):
        memories, scores = _interleaved_pool(5)
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="3:5")

        result = retriever.retrieve("u1", "查询", top_k=8)

        ids = [item.memory.id for item in result.items]
        episodic = [memory_id for memory_id in ids if memory_id.startswith("e")]
        semantic = [memory_id for memory_id in ids if memory_id.startswith("s")]
        assert len(ids) == 8
        assert len(episodic) == 3
        assert len(semantic) == 5
        assert ids == ["e1", "s1", "e2", "s2", "e3", "s3", "s4", "s5"]

    def test_quota_backfills_when_one_layer_is_scarce(self, memory_pool, quota_settings):
        memories = [_memory("e1", EPISODIC_TYPE)] + [
            _memory(f"s{index}", SEMANTIC_TYPE) for index in range(1, 7)
        ]
        scores = {"e1": 1.0}
        for index in range(1, 7):
            scores[f"s{index}"] = round(0.9 - index * 0.05, 4)
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="3:2")

        result = retriever.retrieve("u1", "查询", top_k=5)

        ids = [item.memory.id for item in result.items]
        assert len(ids) == 5
        assert len([memory_id for memory_id in ids if memory_id.startswith("e")]) == 1
        assert ids == ["e1", "s1", "s2", "s3", "s4"]

    def test_quota_does_not_change_scores(self, memory_pool, quota_settings):
        memories, scores = _interleaved_pool(5)

        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="")
        baseline = retriever.retrieve("u1", "查询", top_k=8)

        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="3:5")
        quotaed = retriever.retrieve("u1", "查询", top_k=8)

        baseline_scores = {item.memory.id: item.score for item in baseline.items}
        quota_scores = {item.memory.id: item.score for item in quotaed.items}
        common = set(baseline_scores) & set(quota_scores)
        assert common
        for memory_id in common:
            assert quota_scores[memory_id] == baseline_scores[memory_id]

    def test_quota_preserves_within_layer_order(self, memory_pool, quota_settings):
        memories, scores = _interleaved_pool(5)
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="3:5")

        result = retriever.retrieve("u1", "查询", top_k=8)

        ids = [item.memory.id for item in result.items]
        episodic = [memory_id for memory_id in ids if memory_id.startswith("e")]
        semantic = [memory_id for memory_id in ids if memory_id.startswith("s")]
        assert episodic == sorted(episodic, key=lambda value: int(value[1:]))
        assert semantic == sorted(semantic, key=lambda value: int(value[1:]))
        assert ids.index("e1") < ids.index("s1") < ids.index("e2")

    def test_quota_is_deterministic_across_runs(self, memory_pool, quota_settings):
        memories, scores = _interleaved_pool(5)
        quota_settings(memory_layer_quota="3:5")

        sequences = []
        for _ in range(3):
            memory_pool(memories, scores)
            result = retriever.retrieve("u1", "查询", top_k=8)
            sequences.append([item.memory.id for item in result.items])

        assert sequences[0] == sequences[1] == sequences[2]

    def test_unknown_layer_falls_back_to_default_and_warns_once(
        self, memory_pool, quota_settings, caplog
    ):
        memories = [_unknown_layer_memory(f"m{index}") for index in range(1, 5)]
        scores = {memory.id: round(1.0 - index * 0.1, 4) for index, memory in enumerate(memories)}
        memory_pool(memories, scores)
        quota_settings(memory_layer_quota="1:1")

        with caplog.at_level("WARNING"):
            result = retriever.retrieve("u1", "查询", top_k=4)

        for memory in memories:
            assert retriever._resolve_layer(memory)[0] == memory_types.DEFAULT_LAYER
        aggregated = [
            record for record in caplog.records if "记忆层缺失或未知" in record.message
        ]
        assert len(aggregated) == 1
        assert len(result.items) == 4


class TestPreserve:
    def test_scoring_functions_and_modes_unchanged(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(retriever, name)) == digest, name
        assert (
            retriever.MODE_HYBRID,
            retriever.MODE_STRUCTURED,
            retriever.MODE_DEGRADED,
        ) == ("hybrid", "structured", "degraded")

    def test_no_new_migration_and_pins_unchanged(self):
        assert schema_pins.MIGRATION_HEAD == "0010"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0009"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == schema_pins.schema_columns_digest()

    def test_quota_module_has_no_llm_dependency(self):
        for function in (
            retriever.parse_layer_quota,
            retriever._resolve_layer,
            retriever._quota_select,
        ):
            source = inspect.getsource(function)
            assert "get_llm" not in source
            assert "llm_factory" not in source
