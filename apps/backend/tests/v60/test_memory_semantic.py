"""MEV-007 语义抽象：选材/分组/未覆盖判定/白名单 fail-closed/明细护栏/无环/接线与 Preserve。

契约：`docs/version/v6.0.0/tasks/MEV-007.md` §4（链、选材与回路、产出、设置）与 §7。
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chains import memory_semantic_abstract_chain as abstract_chain
from app.core import timeutil
from app.core.db import (
    BackgroundJobRow,
    Base,
    DevelopmentStateRow,
    EvidenceLinkRow,
    InsightRow,
    Memory as MemoryRow,
    MemoryCandidateRow,
    PersonalityStateRow,
)
from app.core.settings import get_settings
from app.prompts import memory_semantic_abstract as abstract_prompt
from app.repositories import background_job_repository
from app.services.memory import (
    embeddings as memory_embeddings,
    episodic,
    evaluator as memory_evaluator,
    ingest as memory_ingest,
    job_worker as memory_job_worker,
    lifecycle as memory_lifecycle,
    semantic,
)
from tests.support import schema_pins
from tests.support.frozen_surface import file_digest

BASE = timeutil.now()

SEMANTIC_ITEM_SCHEMA = "SemanticAbstractResult"

PRESERVED_FUNCTION_DIGESTS = {
    "create_candidate": "3c84f1df2c8693d0",
}

PRESERVED_FILE_DIGESTS = {
    # MEV-008（2026-10-16）：`lifecycle.py` / `retriever.py` 由该任务**合法扩展**
    # （分层配额截取 + λ 层乘数调制），摘要已同步为 MEV-008 交付态；
    # `evaluator.py` / `episodic.py` 仍逐字节冻结（MEV-008 未触碰）。
    "app/services/memory/evaluator.py": (
        "f33da2b3323773d2d04a5169d3b204164c64dc1e3c2276f17ce613eae2829286"
    ),
    # MEV-010（2026-10-20）：`lifecycle.py` 合法新增只写函数 `create_relation_link`，
    # 既有函数与状态机逐字节未变，整文件摘要同步。
    "app/services/memory/lifecycle.py": (
        "f3aece508afa8834bbe718b7e800ff46d09f041fff463f9505c7e5e3d39ab655"
    ),
    # MEV-009（2026-10-20）：`retriever.py` 合法新增 1-hop 扩展，摘要同步。
    "app/services/memory/retriever.py": (
        "8b6aee9633df0f143ce66631b85da2c406d17c572e2645148267c5e38e1ffd19"
    ),
    "app/services/memory/episodic.py": (
        "5dac7df90c46e5806cbeae24bd1580e6da0fd6618bc05581910f1369e02f8c81"
    ),
}

CROSS_DOMAIN_PREFIXES = (
    "services.reflection",
    "services.development",
    "services.relationship",
    "app.application",
)

BENIGN_CONTENTS = (
    "用户喜欢周末去公园露营",
    "用户习惯早起后先喝一杯水",
    "用户每年都会安排一次长途旅行",
    "用户答应过要一起看一次日出",
)


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def sem_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (semantic, memory_ingest, background_job_repository):
        monkeypatch.setattr(module, "SessionLocal", factory)
    settings = get_settings()
    monkeypatch.setattr(settings, "memory_semantic_mode", "auto")
    monkeypatch.setattr(settings, "memory_semantic_min_sources", 3)
    monkeypatch.setattr(settings, "memory_semantic_max_per_run", 5)
    yield factory, engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def _memory(
    memory_id: str,
    content: str,
    *,
    minutes_ago: int = 0,
    salience: float = 0.8,
    user_id: str = "u1",
    character_id: str = "asuna",
    source_table: str = "conversation",
    layer: str = "episodic",
    status: str = "active",
    memory_type: str = "experience",
    source_ids: list[str] | None = None,
) -> MemoryRow:
    created = BASE - timedelta(minutes=minutes_ago)
    source_ref: dict = {"table": source_table, "id": f"src-{memory_id}"}
    if source_ids is not None:
        source_ref["source_ids"] = list(source_ids)
        source_ref["abstract_kind"] = "semantic"
    return MemoryRow(
        id=memory_id,
        user_id=user_id,
        content=content,
        type=memory_type,
        layer=layer,
        importance=0.6,
        character_id=character_id,
        confidence=0.9,
        source="ai_inferred",
        status=status,
        salience=salience,
        source_ref=source_ref,
        created_at=created,
        updated_at=created,
    )


def _seed(factory, *rows: MemoryRow) -> None:
    with factory() as session:
        session.add_all(list(rows))
        session.commit()


def _candidates(factory) -> list:
    with factory() as session:
        rows = session.query(MemoryCandidateRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def _count(factory, model) -> int:
    with factory() as session:
        return session.query(model).count()


def _llm(fake_llm, content: str, proposed_type: str = "user_preference"):
    return fake_llm(
        structured_responses={
            SEMANTIC_ITEM_SCHEMA: {
                "items": [{"content": content, "proposed_type": proposed_type}]
            }
        }
    )


def _outdoor(factory, *ids: str) -> None:
    _seed(
        factory,
        *[
            _memory(memory_id, f"用户去公园露营第{index}次", minutes_ago=index)
            for index, memory_id in enumerate(ids, start=1)
        ],
    )


class TestChainContract:
    def test_chain_rejects_non_single_items(self, fake_llm):
        llm = fake_llm(structured_responses={SEMANTIC_ITEM_SCHEMA: {"items": []}})
        with pytest.raises(ValueError):
            import asyncio

            asyncio.run(
                abstract_chain.abstract_from_episodes(
                    "conversation:outdoor", [("m1", "露营")], llm
                )
            )

    def test_chain_rejects_empty_content(self, fake_llm):
        import asyncio

        llm = _llm(fake_llm, "   ")
        with pytest.raises(ValueError):
            asyncio.run(
                abstract_chain.abstract_from_episodes(
                    "conversation:outdoor", [("m1", "露营")], llm
                )
            )

    def test_chain_rejects_over_max_chars(self, fake_llm):
        import asyncio

        llm = _llm(fake_llm, "很" * (abstract_chain.SEMANTIC_CONTENT_MAX_CHARS + 1))
        with pytest.raises(ValueError):
            asyncio.run(
                abstract_chain.abstract_from_episodes(
                    "conversation:outdoor", [("m1", "露营")], llm
                )
            )

    def test_chain_rejects_out_of_whitelist_type(self, fake_llm):
        import asyncio

        llm = _llm(fake_llm, "用户常去露营", proposed_type="experience")
        with pytest.raises(ValueError):
            asyncio.run(
                abstract_chain.abstract_from_episodes(
                    "conversation:outdoor", [("m1", "露营")], llm
                )
            )

    def test_whitelist_excludes_episodic_types(self):
        assert "experience" not in abstract_chain.SEMANTIC_TYPES
        assert "milestone_event" not in abstract_chain.SEMANTIC_TYPES
        assert set(abstract_chain.SEMANTIC_TYPES) <= set(
            memory_types_canonical()
        )

    def test_prompt_carries_four_disciplines_and_whitelist(self):
        prompt = abstract_prompt.SEMANTIC_ABSTRACT_SYSTEM_PROMPT
        for memory_type in abstract_chain.SEMANTIC_TYPES:
            assert memory_type in prompt
        assert str(abstract_chain.SEMANTIC_CONTENT_MAX_CHARS) in prompt
        assert "不得虚构" in prompt
        assert "账目明细" in prompt
        assert "experience" not in prompt

    def test_abstract_chain_uses_lite_profile(self, monkeypatch, fake_llm):
        seen: dict = {}

        def _fake_get_llm(profile_id=None):
            seen["profile_id"] = profile_id
            return _llm(fake_llm, "用户常去露营")

        monkeypatch.setattr(abstract_chain, "get_llm", _fake_get_llm)
        abstract_chain.build_semantic_abstract_chain()
        assert seen["profile_id"] == "lite"


def memory_types_canonical():
    from app.services.memory import types as memory_types

    return memory_types.CANONICAL_MEMORY_TYPES


class TestSelectionAndOutput:
    def test_mode_off_makes_no_llm_call_and_no_candidate(
        self, sem_env, monkeypatch, caplog, fake_llm
    ):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        monkeypatch.setattr(get_settings(), "memory_semantic_mode", "off")
        llm = _llm(fake_llm, "用户常去露营")

        with caplog.at_level("WARNING"):
            outcome = semantic.run_semantic_tick(BASE)
            stats = semantic.abstract_once(BASE, llm=llm)

        assert outcome == {"enqueued": False}
        assert stats["created"] == 0
        assert llm.seen_messages == []
        assert _candidates(factory) == []
        assert _count(factory, BackgroundJobRow) == 0
        assert [r for r in caplog.records if r.levelname == "WARNING"] == []

    def test_group_below_min_sources_skipped(self, sem_env, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2")
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户常去露营"))
        assert stats["skipped_small"] == 1
        assert stats["created"] == 0
        assert _candidates(factory) == []

    def test_group_at_or_above_min_sources_produces_one_semantic_candidate(
        self, sem_env, fake_llm
    ):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢周末露营"))

        assert stats["created"] == 1
        candidates = _candidates(factory)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.source_table == "memory_aggregate"
        assert candidate.proposed_type in abstract_chain.SEMANTIC_TYPES
        assert candidate.source_ref["layer"] == "semantic"
        assert candidate.source_ref["abstract_kind"] == "semantic"
        assert candidate.source_ref["theme"] == "conversation:outdoor"
        assert candidate.source_ref["source_ids"] == ["m1", "m2", "m3"]
        assert candidate.content == "用户喜欢周末露营"
        # 层与类型不冲突：转正链路（`evaluator._layer_of`）落库层必为 semantic
        assert memory_evaluator._layer_of(candidate, candidate.proposed_type) == (
            "semantic"
        )

    def test_out_of_whitelist_type_is_fail_closed(self, sem_env, fake_llm, caplog):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        llm = _llm(fake_llm, "用户常去露营", proposed_type="experience")

        with caplog.at_level("WARNING"):
            stats = semantic.abstract_once(BASE, llm=llm)

        assert stats["failed"] == 1
        assert stats["created"] == 0
        assert _candidates(factory) == []
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_content_over_max_chars_is_rejected(self, sem_env, fake_llm, caplog):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        llm = _llm(fake_llm, "很" * (abstract_chain.SEMANTIC_CONTENT_MAX_CHARS + 20))

        with caplog.at_level("WARNING"):
            stats = semantic.abstract_once(BASE, llm=llm)

        assert stats["failed"] == 1
        assert _candidates(factory) == []
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_amount_pattern_content_is_discarded_not_masked(
        self, sem_env, fake_llm, caplog
    ):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        llm = _llm(fake_llm, "用户每月餐饮花费约2000元，账单流水稳定")

        with caplog.at_level("WARNING"):
            stats = semantic.abstract_once(BASE, llm=llm)

        assert stats["discarded_detail"] == 1
        assert stats["created"] == 0
        assert _candidates(factory) == []
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_ledger_detail_guardrail_is_deterministic(self):
        for text in (
            "用户每月餐饮花费约2000元",
            "用户信用卡尾号4821",
            "用户绑定账户 6222021234567890",
            "用户喜欢在¥200左右的餐厅吃饭",
        ):
            assert semantic.has_ledger_detail(text) is True, text
        for text in BENIGN_CONTENTS:
            assert semantic.has_ledger_detail(text) is False, text

    def test_salience_init_is_max_of_sources(self, sem_env, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了", salience=0.2, minutes_ago=180),
            _memory("m2", "用户露营搭了帐篷", salience=0.9, minutes_ago=120),
            _memory("m3", "用户露营煮了火锅", salience=0.5, minutes_ago=60),
        )
        semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        assert _candidates(factory)[0].salience == pytest.approx(0.9)

    def test_status_and_layer_filters_apply(self, sem_env, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷", status="forgotten"),
            _memory("m3", "用户露营煮了火锅", layer="semantic"),
            _memory("m4", "用户露营买了装备", memory_type="user_fact"),
        )
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        assert stats["created"] == 0
        assert _candidates(factory) == []


class TestIdempotencyAndLoopback:
    def test_source_id_is_deterministic_and_idempotent(self, sem_env, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        llm = _llm(fake_llm, "用户喜欢露营")

        first = semantic.abstract_once(BASE, llm=llm)
        second = semantic.abstract_once(BASE, llm=llm)

        assert first["created"] == 1
        assert second["created"] == 0
        assert second["existing"] == 1
        candidates = _candidates(factory)
        assert len(candidates) == 1
        assert candidates[0].source_id == semantic.source_id_for(
            "conversation:outdoor", ["m1", "m2", "m3"]
        )

    def test_new_episodes_after_abstraction_trigger_again(self, sem_env, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        llm = _llm(fake_llm, "用户喜欢露营")
        semantic.abstract_once(BASE, llm=llm)

        _seed(factory, _memory("m4", "用户露营看了星星", minutes_ago=0))
        stats = semantic.abstract_once(BASE, llm=llm)

        assert stats["created"] == 1
        assert len(_candidates(factory)) == 2

    def test_already_covered_episodes_alone_do_not_trigger(self, sem_env, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            _memory(
                "s1",
                "用户喜欢露营",
                layer="semantic",
                memory_type="user_preference",
                source_ids=["m1", "m2", "m3"],
            ),
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        assert stats["skipped_small"] == 1
        assert stats["created"] == 0
        assert _candidates(factory) == []

    def test_semantic_output_never_enters_input_set(self, sem_env, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            _memory(
                "s1",
                "用户喜欢露营",
                layer="semantic",
                memory_type="user_preference",
            ),
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))

        assert stats["created"] == 1
        assert _candidates(factory)[0].source_ref["source_ids"] == ["m1", "m2", "m3"]

    def test_semantic_layer_rows_alone_do_not_form_groups(self, sem_env, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            *[
                _memory(
                    f"s{index}",
                    f"用户喜欢露营的第{index}条认识",
                    layer="semantic",
                    memory_type="user_preference",
                )
                for index in (1, 2, 3)
            ],
        )
        stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        assert stats["groups"] == 0
        assert _candidates(factory) == []

    def test_reads_only_and_never_writes_memories(self, sem_env, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        before = _count(factory, MemoryRow)
        semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        assert _count(factory, MemoryRow) == before
        assert len(_candidates(factory)) == 1


class TestBudgetAndIsolation:
    def test_respects_max_per_run(self, sem_env, monkeypatch, fake_llm):
        factory, _ = sem_env
        themes = ("露营", "面试", "体检", "考试", "晚饭", "旅行")
        for index, keyword in enumerate(themes):
            _seed(
                factory,
                *[
                    _memory(
                        f"{index}-{slot}", f"用户{keyword}相关第{slot}件事", minutes_ago=slot
                    )
                    for slot in (1, 2, 3)
                ],
            )
        monkeypatch.setattr(get_settings(), "memory_semantic_max_per_run", 2)
        llm = _llm(fake_llm, "用户有稳定的习惯")

        assert semantic.abstract_once(BASE, llm=llm)["created"] == 2
        assert semantic.abstract_once(BASE, llm=llm)["created"] == 2
        assert semantic.abstract_once(BASE, llm=llm)["created"] == 2
        assert len(_candidates(factory)) == 6

    def test_single_group_failure_is_isolated(self, sem_env, monkeypatch, caplog, fake_llm):
        factory, _ = sem_env
        _seed(
            factory,
            _memory("c1", "用户去参加面试了"),
            _memory("c2", "用户面试聊得不错"),
            _memory("c3", "用户面试还有二面"),
            _memory("o1", "用户去公园露营了"),
            _memory("o2", "用户露营搭了帐篷"),
            _memory("o3", "用户露营煮了火锅"),
        )
        original = semantic.abstract_from_episodes
        llm = _llm(fake_llm, "用户喜欢露营")

        def _explode(theme, episodes, llm=None):
            if "career" in theme:
                raise RuntimeError("模拟单组失败")
            return original(theme, episodes, llm)

        monkeypatch.setattr(semantic, "abstract_from_episodes", _explode)
        with caplog.at_level("WARNING"):
            stats = semantic.abstract_once(BASE, llm=llm)

        assert stats["failed"] == 1
        assert stats["created"] == 1
        assert len(_candidates(factory)) == 1
        assert any("单组失败" in record.message for record in caplog.records)

    def test_selection_failure_does_not_raise(self, sem_env, monkeypatch, caplog, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")

        def _boom():
            raise RuntimeError("模拟选材失败")

        monkeypatch.setattr(semantic, "_select_episodic", _boom)
        with caplog.at_level("WARNING"):
            stats = semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))

        assert stats["created"] == 0
        assert _candidates(factory) == []


class TestJobWiring:
    def test_mode_auto_enqueues_once_per_hour(self, sem_env):
        factory, _ = sem_env
        first = semantic.run_semantic_tick(BASE)
        second = semantic.run_semantic_tick(BASE + timedelta(minutes=5))
        later = semantic.run_semantic_tick(BASE + timedelta(hours=1))

        assert first == {"enqueued": True}
        assert second == {"enqueued": False}
        assert later == {"enqueued": True}
        with factory() as session:
            assert session.query(BackgroundJobRow).count() == 2

    def test_run_semantic_job_respects_mode(self, sem_env, monkeypatch, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        monkeypatch.setattr(get_settings(), "memory_semantic_mode", "off")
        assert semantic.run_semantic_job()["created"] == 0
        assert _candidates(factory) == []

        monkeypatch.setattr(get_settings(), "memory_semantic_mode", "auto")
        monkeypatch.setattr(semantic, "abstract_from_episodes", _sync_abstract())
        assert semantic.run_semantic_job()["created"] == 1

    def test_job_type_registered_without_changing_existing(self):
        handlers = memory_job_worker._JOB_HANDLERS
        assert (
            handlers[memory_job_worker.JOB_TYPE_MEMORY_DECAY]
            is memory_lifecycle.run_decay_cycle
        )
        assert (
            handlers[memory_job_worker.JOB_TYPE_EMBEDDING_BACKFILL]
            is memory_embeddings.backfill_scan
        )
        assert (
            handlers[episodic.JOB_TYPE_MEMORY_EPISODIC_AGGREGATE]
            is episodic.run_aggregate_job
        )
        assert (
            handlers[semantic.JOB_TYPE_MEMORY_SEMANTIC_ABSTRACT]
            is semantic.run_semantic_job
        )
        assert episodic.run_aggregate_tick in memory_job_worker._TICK_HOOKS
        assert semantic.run_semantic_tick in memory_job_worker._TICK_HOOKS


def _sync_abstract():
    """job handler 走真实 `get_llm("lite")`；测试里替换为无网络的假实现。"""
    item = abstract_chain.SemanticAbstractItem(
        content="用户喜欢露营", proposed_type="user_preference"
    )

    async def _abstract(theme, episodes, llm=None):
        return item

    return _abstract


class TestSettings:
    def test_defaults_are_off(self):
        settings = get_settings()
        assert settings.memory_semantic_mode in ("off", "auto")
        assert settings.memory_semantic_min_sources >= 2
        assert settings.memory_semantic_max_per_run >= 1

    def test_invalid_mode_falls_back_to_off(self, override_settings):
        override_settings(MEMORY_SEMANTIC_MODE="always")
        assert get_settings().memory_semantic_mode == "off"

    def test_limits_are_clamped(self, override_settings):
        override_settings(
            MEMORY_SEMANTIC_MIN_SOURCES=1,
            MEMORY_SEMANTIC_MAX_PER_RUN=999,
        )
        settings = get_settings()
        assert settings.memory_semantic_min_sources == 2
        assert settings.memory_semantic_max_per_run == 50


class TestBoundaries:
    def test_no_cross_domain_imports(self):
        for module in (semantic, abstract_chain):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in CROSS_DOMAIN_PREFIXES:
                assert forbidden not in source, (module.__name__, forbidden)

    def test_no_insight_or_development_write(self, sem_env, fake_llm):
        factory, _ = sem_env
        _outdoor(factory, "m1", "m2", "m3")
        semantic.abstract_once(BASE, llm=_llm(fake_llm, "用户喜欢露营"))
        for model in (
            InsightRow,
            EvidenceLinkRow,
            DevelopmentStateRow,
            PersonalityStateRow,
        ):
            assert _count(factory, model) == 0, model

    def test_ingest_create_candidate_untouched(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(memory_ingest, name)) == digest, name

    def test_episodic_module_untouched(self):
        relative = "app/services/memory/episodic.py"
        assert file_digest(relative) == PRESERVED_FILE_DIGESTS[relative]

    def test_evaluator_lifecycle_retriever_untouched(self):
        for relative in (
            "app/services/memory/evaluator.py",
            "app/services/memory/lifecycle.py",
            "app/services/memory/retriever.py",
        ):
            assert file_digest(relative) == PRESERVED_FILE_DIGESTS[relative], relative

    def test_no_new_migration_and_pins_unchanged(self):
        # MEV-009（2026-10-20，2026-10-27 并入 0010）：`memory_links.relation` 值域扩展随
        # 合并迁移入链，HEAD/PARENT 为 0010/0009。
        assert schema_pins.MIGRATION_HEAD == "0010"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0009"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == schema_pins.schema_columns_digest()
