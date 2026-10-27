"""MEV-010 记忆关系抽取：链白名单 / 写入幂等 / 候选回落 / job 接线 / 双向读面。

契约：`docs/version/v6.0.0/tasks/MEV-010.md` §4 与 §7。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.chains import memory_link_chain as link_chain
from app.core import timeutil
from app.core.db import BackgroundJobRow, Memory as MemoryRow, MemoryLinkRow
from app.core.settings import get_settings
from app.core.settings.memory import MemorySettings
from app.prompts import memory_link as link_prompt
from app.services.memory import job_worker as memory_job_worker
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import relations, retriever
from tests.support import schema_pins
from tests.support.frozen_surface import file_digest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASE = timeutil.now()
SCHEMA_NAME = "MemoryLinkResult"

PRESERVED_FUNCTION_DIGESTS = {
    "on_promoted": "2d94031d413eee03",
    "_link_exists": "c4474cfeddf5f1f8",
    "_create_link": "586206133be33100",
    "_decay_batch": "4697f803e220cf11",
}

EXPECTED_TRANSITIONS = {
    ("active", "reinforce"): "active",
    ("decayed", "reinforce"): "active",
    ("active", "supersede"): "superseded",
    ("active", "merge"): "superseded",
    ("active", "invalidate"): "invalidated",
    ("active", "decay_floor"): "decayed",
    ("active", "decay_forget"): "forgotten",
    ("decayed", "decay_forget"): "forgotten",
    ("active", "forget"): "forgotten",
    ("decayed", "forget"): "forgotten",
    ("superseded", "forget"): "forgotten",
    ("invalidated", "forget"): "forgotten",
    ("forgotten", "forget"): "forgotten",
}


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _memory(
    memory_id: str,
    content: str,
    *,
    memory_type: str = "user_fact",
    layer: str = "semantic",
    status: str = "active",
    minutes_ago: int = 0,
    user_id: str = "u1",
    character_id: str = "asuna",
) -> MemoryRow:
    created = BASE - timedelta(minutes=minutes_ago)
    return MemoryRow(
        id=memory_id,
        user_id=user_id,
        content=content,
        type=memory_type,
        layer=layer,
        importance=0.6,
        character_id=character_id,
        confidence=0.9,
        source="user_stated",
        status=status,
        salience=0.8,
        embedding=None,
        created_at=created,
        updated_at=created,
    )


def _link(
    memory_id: str,
    related_memory_id: str,
    relation: str,
    *,
    link_id: str | None = None,
) -> MemoryLinkRow:
    return MemoryLinkRow(
        id=link_id or f"l-{memory_id}-{related_memory_id}-{relation}",
        memory_id=memory_id,
        related_memory_id=related_memory_id,
        relation=relation,
        created_at=BASE,
    )


def _seed(factory, *rows, links=()) -> None:
    with factory() as session:
        session.add_all(list(rows))
        session.add_all(list(links))
        session.commit()


def _links(factory) -> list[tuple[str, str, str]]:
    with factory() as session:
        rows = (
            session.query(
                MemoryLinkRow.memory_id,
                MemoryLinkRow.related_memory_id,
                MemoryLinkRow.relation,
            )
            .order_by(
                MemoryLinkRow.memory_id,
                MemoryLinkRow.related_memory_id,
                MemoryLinkRow.relation,
            )
            .all()
        )
        return [(memory_id, related_id, relation) for memory_id, related_id, relation in rows]


def _llm(fake_llm, links: list[dict]):
    return fake_llm(structured_responses={SCHEMA_NAME: {"links": links}})


@pytest.fixture
def rel_env(db_session_factory, monkeypatch):
    settings = get_settings()
    for key, value in {
        "memory_link_extract_mode": "auto",
        "memory_link_candidate_k": 5,
        "memory_link_max_per_run": 20,
        "memory_conflict_threshold": 0.6,
        "memory_candidate_pool_limit": 200,
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(relations.memory_embeddings, "embed_query", lambda text: None)
    return db_session_factory, settings


class TestChainContract:
    def test_extract_links_filters_legacy_and_unknown_ids(self, fake_llm):
        llm = _llm(
            fake_llm,
            [
                {"related_memory_id": "m1", "relation": "caused_by", "confidence": 0.9},
                {"related_memory_id": "m2", "relation": "supersedes", "confidence": 0.8},
                {"related_memory_id": "ghost", "relation": "related", "confidence": 0.7},
            ],
        )

        items, stats = asyncio.run(
            link_chain.extract_links_with_stats(
                "anchor", [("m1", "内容1"), ("m2", "内容2")], llm
            )
        )

        assert [item.related_memory_id for item in items] == ["m1"]
        assert stats["ignored_existing_relations"] == 1
        assert stats["unknown_ids"] == 1

    def test_extract_links_returns_empty_for_no_links(self, fake_llm):
        llm = _llm(fake_llm, [])
        assert (
            asyncio.run(
                link_chain.extract_links("anchor", [("m1", "内容1")], llm)
            )
            == []
        )

    def test_prompt_pins_whitelist_and_direction(self):
        assert link_prompt.MEMORY_LINK_PROMPT_VERSION == 1
        assert link_chain.LINK_EXTRACTABLE_RELATIONS == (
            "caused_by",
            "before",
            "related",
        )
        for token in ("caused_by", "before", "related"):
            assert token in link_prompt.MEMORY_LINK_SYSTEM_PROMPT


class TestRelationWriter:
    def test_write_is_idempotent(self, rel_env):
        factory, _ = rel_env

        assert (
            memory_lifecycle.create_relation_link("a", "b", "caused_by") is True
        )
        assert (
            memory_lifecycle.create_relation_link("a", "b", "caused_by") is False
        )

        assert _links(factory) == [("a", "b", "caused_by")]

    def test_rejects_relation_outside_whitelist_at_write_time(
        self, rel_env, caplog
    ):
        factory, _ = rel_env
        with caplog.at_level("WARNING"):
            created = memory_lifecycle.create_relation_link("a", "b", "likes")

        assert created is False
        assert _links(factory) == []
        assert any("likes" in record.message for record in caplog.records)


class TestExtractService:
    def test_mode_off_makes_no_llm_call_and_no_link(
        self, rel_env, monkeypatch, fake_llm
    ):
        factory, settings = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        monkeypatch.setattr(settings, "memory_link_extract_mode", "off")
        llm = _llm(
            fake_llm,
            [{"related_memory_id": "b", "relation": "related", "confidence": 0.9}],
        )

        stats = relations.run_extract("a", llm=llm)

        assert stats["wrote"] == 0
        assert llm.seen_messages == []
        assert _links(factory) == []
        assert relations.run_extract_tick() == {"enqueued": 0}
        with factory() as session:
            assert session.query(BackgroundJobRow).count() == 0

    def test_no_candidates_skips_without_llm_call(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"))
        llm = _llm(fake_llm, [])

        stats = relations.run_extract("a", llm=llm)

        assert stats["skipped_no_candidates"] == 1
        assert llm.seen_messages == []
        assert _links(factory) == []

    def test_writes_only_extractable_relations(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        llm = _llm(
            fake_llm,
            [{"related_memory_id": "b", "relation": "caused_by", "confidence": 0.9}],
        )

        stats = relations.run_extract("a", llm=llm)

        assert stats["wrote"] == 1
        assert _links(factory) == [("a", "b", "caused_by")]

    def test_ignores_existing_relation_values(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        llm = _llm(
            fake_llm,
            [
                {"related_memory_id": "b", "relation": "supersedes", "confidence": 0.9},
                {"related_memory_id": "b", "relation": "merges", "confidence": 0.8},
                {"related_memory_id": "b", "relation": "contradicts", "confidence": 0.7},
            ],
        )

        stats = relations.run_extract("a", llm=llm)

        assert stats["ignored_existing_relations"] == 3
        assert stats["wrote"] == 0
        assert _links(factory) == []

    def test_discards_ids_outside_candidate_set(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        llm = _llm(
            fake_llm,
            [{"related_memory_id": "ghost", "relation": "related", "confidence": 0.9}],
        )

        stats = relations.run_extract("a", llm=llm)

        assert stats["unknown_ids"] == 1
        assert _links(factory) == []

    def test_empty_result_writes_nothing(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        llm = _llm(fake_llm, [])

        stats = relations.run_extract("a", llm=llm)

        assert stats["extracted"] == 0
        assert _links(factory) == []

    def test_write_is_idempotent_across_extractions(self, rel_env, fake_llm):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))
        llm = _llm(
            fake_llm,
            [{"related_memory_id": "b", "relation": "related", "confidence": 0.9}],
        )

        first = relations.run_extract("a", llm=llm)
        second = relations.run_extract("a", llm=llm)

        assert first["wrote"] == 1
        assert second["wrote"] == 0
        assert _links(factory) == [("a", "b", "related")]

    def test_falls_back_to_same_topic_when_vector_unavailable(
        self, rel_env, fake_llm
    ):
        factory, _ = rel_env
        _seed(
            factory,
            _memory("a", "用户喜欢去公园露营"),
            _memory("b", "用户周末常去公园露营", minutes_ago=1),
        )
        llm = _llm(
            fake_llm,
            [{"related_memory_id": "b", "relation": "related", "confidence": 0.9}],
        )

        stats = relations.run_extract("a", llm=llm)

        assert stats["candidates"] == 1
        assert stats["wrote"] == 1

    def test_single_anchor_failure_is_isolated(self, rel_env, monkeypatch):
        factory, _ = rel_env
        _seed(factory, _memory("a1", "好甲"), _memory("a2", "坏乙", minutes_ago=1))

        async def _fake(anchor_content, candidates, llm=None):
            if "坏" in anchor_content:
                raise RuntimeError("boom")
            return (
                [
                    link_chain.MemoryLinkItem(
                        related_memory_id=candidates[0][0],
                        relation="related",
                        confidence=0.9,
                    )
                ],
                {"ignored_existing_relations": 0, "unknown_ids": 0},
            )

        monkeypatch.setattr(relations, "extract_links_with_stats", _fake)

        stats = relations.extract_once()

        assert stats["anchors"] == 2
        assert stats["failed"] == 1
        assert stats["wrote"] == 1

    def test_respects_max_per_run(self, rel_env, monkeypatch):
        factory, settings = rel_env
        _seed(
            factory,
            _memory("a1", "甲"),
            _memory("a2", "乙", minutes_ago=1),
            _memory("a3", "丙", minutes_ago=2),
        )
        monkeypatch.setattr(settings, "memory_link_max_per_run", 2)

        async def _fake(anchor_content, candidates, llm=None):
            return [], {"ignored_existing_relations": 0, "unknown_ids": 0}

        monkeypatch.setattr(relations, "extract_links_with_stats", _fake)

        stats = relations.extract_once()

        assert stats["anchors"] == 2

    def test_job_idempotency_key_prevents_duplicate_run(self, rel_env):
        factory, _ = rel_env
        _seed(factory, _memory("a", "用户喜欢露营"), _memory("b", "用户计划露营", minutes_ago=1))

        first = relations.run_extract_tick()
        second = relations.run_extract_tick()

        assert first["enqueued"] == 2
        assert second["enqueued"] == 0
        with factory() as session:
            jobs = session.query(BackgroundJobRow).all()
        assert len(jobs) == 2
        assert {job.idempotency_key for job in jobs} == {
            "memory_link:a",
            "memory_link:b",
        }
        assert {tuple(sorted(job.payload.items())) for job in jobs} == {
            (("memory_id", "a"),),
            (("memory_id", "b"),),
        }

    def test_reverse_lookup_matches_both_directions(self, rel_env, monkeypatch):
        factory, settings = rel_env
        _seed(
            factory,
            _memory("d1", "最近去露营", minutes_ago=1),
            _memory("d2", "最近买了睡袋", minutes_ago=2),
            _memory("a1", "计划露营并买了帐篷", minutes_ago=30),
        )
        assert memory_lifecycle.create_relation_link("a1", "d1", "caused_by") is True

        monkeypatch.setattr(settings, "memory_candidate_pool_limit", 2)
        monkeypatch.setattr(settings, "memory_rerank_mode", "off")
        monkeypatch.setattr(settings, "memory_query_rewrite_mode", "off")
        monkeypatch.setattr(settings, "memory_layer_quota", "")
        monkeypatch.setattr(settings, "memory_graph_expand_mode", "one_hop")
        monkeypatch.setattr(settings, "memory_graph_expand_seeds", 3)
        monkeypatch.setattr(settings, "memory_graph_expand_decay", 0.7)
        monkeypatch.setattr(retriever.memory_embeddings, "embed_query", lambda text: None)

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert "a1" in [item.memory.id for item in result.items]

    def test_invalid_mode_falls_back_to_off(self):
        assert (
            MemorySettings(memory_link_extract_mode="always").memory_link_extract_mode
            == "off"
        )

    def test_settings_defaults(self):
        settings = MemorySettings()
        assert settings.memory_link_extract_mode == "off"
        assert settings.memory_link_candidate_k == 5
        assert settings.memory_link_max_per_run == 20

    def test_out_of_range_limits_rejected(self):
        with pytest.raises(ValidationError):
            MemorySettings(memory_link_candidate_k=21)
        with pytest.raises(ValidationError):
            MemorySettings(memory_link_max_per_run=201)


class TestJobWiring:
    def test_job_type_and_tick_hook_registered(self):
        assert (
            memory_job_worker._JOB_HANDLERS[relations.JOB_TYPE_MEMORY_LINK_EXTRACT]
            is relations.run_extract_job
        )
        assert relations.run_extract_tick in memory_job_worker._TICK_HOOKS

    def test_job_worker_dispatches_payload_to_handler(self, db_session_factory):
        with db_session_factory() as session:
            session.add(
                BackgroundJobRow(
                    id="job-payload",
                    job_type="test_payload_mev010",
                    payload={"value": 7},
                    status="running",
                    attempts=0,
                    run_at=BASE,
                    idempotency_key="test_payload_mev010:1",
                    created_at=BASE,
                )
            )
            session.commit()

        seen: list[int] = []
        memory_job_worker.register_job_type(
            "test_payload_mev010", lambda value: seen.append(value)
        )
        try:
            outcome = memory_job_worker._execute_job("job-payload", BASE)
        finally:
            memory_job_worker._JOB_HANDLERS.pop("test_payload_mev010", None)

        assert outcome == "done"
        assert seen == [7]
        with db_session_factory() as session:
            assert session.get(BackgroundJobRow, "job-payload").status == "done"


class TestPreserve:
    def test_lifecycle_existing_functions_unchanged(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(memory_lifecycle, name)) == digest, name
        assert memory_lifecycle.TRANSITIONS == EXPECTED_TRANSITIONS

    def test_conflict_engine_untouched(self):
        assert file_digest("app/engines/memory_conflict.py") == (
            "c64c104a317bd9df352b69184518d13c387ba596e4f0d2a8b0a0b8140ca86244"
        )

    def test_retriever_and_expand_untouched(self):
        assert file_digest("app/services/memory/retriever.py") == (
            "8b6aee9633df0f143ce66631b85da2c406d17c572e2645148267c5e38e1ffd19"
        )

    def test_no_new_migration_and_pins_unchanged(self):
        assert schema_pins.MIGRATION_HEAD == "0010"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0009"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == "2088c55108ab39a1"
        versions = sorted(
            path.name for path in (BACKEND_ROOT / "migrations" / "versions").glob("*.py")
        )
        assert versions[-1].startswith("0010_")
        assert not any(name.startswith("0012_") for name in versions)

    def test_link_chain_uses_lite_profile(self, monkeypatch, fake_llm):
        calls: list[str | None] = []
        model = fake_llm()

        def _get_llm(profile=None):
            calls.append(profile)
            return model

        monkeypatch.setattr(link_chain, "get_llm", _get_llm)
        link_chain.build_memory_link_chain()

        assert calls == ["lite"]

    def test_no_application_import(self):
        for relative in (
            "app/services/memory/relations.py",
            "app/chains/memory_link_chain.py",
            "app/prompts/memory_link.py",
        ):
            source = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
            assert "app.application" not in source
