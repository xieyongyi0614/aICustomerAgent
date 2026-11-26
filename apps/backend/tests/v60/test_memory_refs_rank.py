"""MEV-004 名次观测量测试：`memory_refs` 四字段派生 / `rank_pre` 规则 / 向后兼容。

契约：`app/services/memory/refs.py`（§MEV-004 §4.1.1 / §4.1.2）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.memory import UserMemory
from app.services.memory.refs import (
    MEMORY_REF_LABEL_MAX,
    build_memory_refs,
    memory_ref_label,
    rank_snapshot,
)
from app.services.memory.retriever import RankedMemory, RankedMemories

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.unit


def _memory(
    mid: str,
    content: str,
    memory_type: str = "user_fact",
    status: str = "active",
) -> UserMemory:
    return UserMemory(
        id=mid,
        user_id="u1",
        character_id="asuna",
        type=memory_type,
        content=content,
        importance=0.8,
        confidence=0.9,
        source="user_stated",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _ranked(items: list[RankedMemory], rerank_mode: str = "off") -> RankedMemories:
    return RankedMemories(items=list(items), mode="structured", rerank_mode=rerank_mode)


def _item(memory: UserMemory, score: float, rerank_score: float | None = None) -> RankedMemory:
    return RankedMemory(memory=memory, score=score, rerank_score=rerank_score)


class TestBackwardCompatibility:
    def test_refs_without_ranked_is_bytewise_identical_to_baseline(self):
        refs = build_memory_refs([_memory("m1", "用户喜欢海边旅行")])
        assert refs == [{"id": "m1", "kind": "user_fact", "label": "用户喜欢海边旅行"}]
        assert set(refs[0]) == {"id", "kind", "label"}

    def test_empty_snapshot_keeps_baseline_shape(self):
        refs = build_memory_refs([_memory("m1", "内容")], [])
        assert set(refs[0]) == {"id", "kind", "label"}

    def test_no_memories_returns_none(self):
        assert build_memory_refs(None) is None
        assert build_memory_refs([]) is None

    def test_label_truncation_unchanged(self):
        assert MEMORY_REF_LABEL_MAX == 12
        assert memory_ref_label("一二三四五六七八九十十一十二十三") == "一二三四五六七八九十十一…"


class TestRankSnapshot:
    def test_snapshot_keys_and_one_based_rank(self):
        ranked = _ranked(
            [
                _item(_memory("m1", "一"), 0.9),
                _item(_memory("m2", "二"), 0.8),
            ]
        )
        snapshot = rank_snapshot(ranked)
        assert [entry["id"] for entry in snapshot] == ["m1", "m2"]
        assert [entry["rank"] for entry in snapshot] == [1, 2]
        assert set(snapshot[0]) == {"id", "score", "rank", "rank_pre", "reranked"}

    def test_rank_pre_equals_rank_when_rerank_off(self):
        ranked = _ranked(
            [
                _item(_memory("m1", "一"), 0.9),
                _item(_memory("m2", "二"), 0.8),
                _item(_memory("m3", "三"), 0.7),
            ],
            rerank_mode="off",
        )
        for entry in rank_snapshot(ranked):
            assert entry["rank_pre"] == entry["rank"]

    def test_rank_pre_recomputed_from_score_when_rerank_lite(self):
        # 最终顺序（重排后）把低分条目提到第一：C(0.5) → A(0.9) → B(0.8)
        ranked = _ranked(
            [
                _item(_memory("mC", "丙"), 0.5, rerank_score=0.9),
                _item(_memory("mA", "甲"), 0.9, rerank_score=0.4),
                _item(_memory("mB", "乙"), 0.8, rerank_score=0.3),
            ],
            rerank_mode="lite",
        )
        by_id = {entry["id"]: entry for entry in rank_snapshot(ranked)}
        assert by_id["mC"]["rank"] == 1 and by_id["mC"]["rank_pre"] == 3
        assert by_id["mA"]["rank"] == 2 and by_id["mA"]["rank_pre"] == 1
        assert by_id["mB"]["rank"] == 3 and by_id["mB"]["rank_pre"] == 2

    def test_rank_pre_tie_break_is_deterministic_by_id(self):
        ranked = _ranked(
            [
                _item(_memory("m-b", "乙"), 0.7, rerank_score=0.9),
                _item(_memory("m-a", "甲"), 0.7, rerank_score=0.8),
            ],
            rerank_mode="lite",
        )
        first = rank_snapshot(ranked)
        second = rank_snapshot(ranked)
        assert first == second
        by_id = {entry["id"]: entry for entry in first}
        assert by_id["m-a"]["rank_pre"] == 1 and by_id["m-b"]["rank_pre"] == 2

    def test_score_is_rounded_to_four_decimals(self):
        ranked = _ranked([_item(_memory("m1", "一"), 0.12345678)])
        assert rank_snapshot(ranked)[0]["score"] == 0.1235

    def test_reranked_flag_reflects_rerank_score_presence(self):
        ranked = _ranked(
            [
                _item(_memory("m1", "一"), 0.9, rerank_score=0.7),
                _item(_memory("m2", "二"), 0.8),
            ],
            rerank_mode="lite",
        )
        by_id = {entry["id"]: entry for entry in rank_snapshot(ranked)}
        assert by_id["m1"]["reranked"] is True
        assert by_id["m2"]["reranked"] is False


class TestRefsWithRank:
    def test_refs_with_ranked_adds_four_derived_fields(self):
        memory = _memory("m1", "用户喜欢海边旅行")
        ranked = _ranked([_item(memory, 0.12345678)])
        refs = build_memory_refs([memory], ranked)
        assert list(refs[0]) == ["id", "kind", "label", "score", "rank", "rank_pre", "reranked"]
        assert refs[0]["score"] == 0.1235
        assert refs[0]["rank"] == 1
        assert refs[0]["rank_pre"] == 1
        assert refs[0]["reranked"] is False

    def test_snapshot_channel_produces_the_same_refs(self):
        """生产链路（context 取快照 → turn_meta 回传）与直传检索结果等价。"""
        memory = _memory("m1", "用户喜欢海边旅行")
        ranked = _ranked([_item(memory, 0.7, rerank_score=0.9)], rerank_mode="lite")
        assert build_memory_refs([memory], ranked) == build_memory_refs(
            [memory], rank_snapshot(ranked)
        )

    def test_memory_not_in_rank_keeps_baseline_fields(self):
        """名次快照缺该 id（如被预算裁剪后仍进了 state）时不编造名次。"""
        memory = _memory("m-extra", "预算外条目")
        ranked = _ranked([_item(_memory("m1", "命中条目"), 0.9)])
        refs = build_memory_refs([memory], ranked)
        assert set(refs[0]) == {"id", "kind", "label"}

    def test_non_active_and_blank_content_excluded(self):
        ranked = _ranked([_item(_memory("m1", "   ", status="superseded"), 0.9)])
        assert build_memory_refs([_memory("m1", "   ", status="superseded")], ranked) is None

    def test_refs_excludes_mechanism_fields(self):
        memory = _memory("m1", "用户喜欢海边旅行")
        ranked = _ranked([_item(memory, 0.9, rerank_score=0.5)], rerank_mode="lite")
        ref = build_memory_refs([memory], ranked)[0]
        for field in ("salience", "confidence", "status", "content", "embedding", "importance"):
            assert field not in ref
