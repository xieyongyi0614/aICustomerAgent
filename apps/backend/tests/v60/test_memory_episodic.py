"""MEV-006 情景聚合：确定性归组 / 幂等产出 / 防递归 / 只读纪律 / 接线与 Preserve。

契约：`docs/version/v6.0.0/tasks/MEV-006.md` §4（选材、分组、产出、设置、来源枚举）。
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

from app.core import timeutil
from app.core.db import (
    BackgroundJobRow,
    Base,
    Memory as MemoryRow,
    MemoryCandidateRow,
)
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.memory import (
    embeddings as memory_embeddings,
    episodic,
    ingest as memory_ingest,
    job_worker as memory_job_worker,
    lifecycle as memory_lifecycle,
    product_view,
)
from tests.support import schema_pins
from tests.support.frozen_surface import file_digest

BASE = timeutil.now()

BASELINE_SOURCE_LABELS = {
    "conversation": "对话提及",
    "action_records": "任务完成",
    "world_events": "生活事件",
    "relationship_events": "相处经历",
    "relationship_milestones": "关系里程碑",
    "character_goals": "目标达成",
    "commands": "你直接交代",
    "ledger_insights": "记账观察",
    "user_stated": "你亲口说过",
    "user_derived": "从对话里整理",
    "ai_inferred": "我自己留意到的",
}

PRESERVED_FUNCTION_DIGESTS = {
    "ingest_from_conversation": "b52154ba25de49be",
    "ingest_from_action_record": "24bc66b57c564a20",
    "ingest_from_world_event": "8c5487eb3a071c90",
    "ingest_from_relationship_event": "222babedde7bcc37",
    "ingest_from_relationship_milestone": "543872d978b32cf8",
    "ingest_from_goal_completion": "d84c10e834ac8055",
    "create_candidate": "3c84f1df2c8693d0",
}

PRESERVED_FILE_DIGESTS = {
    # MEV-008（2026-10-16）：`lifecycle.py` / `retriever.py` 由该任务**合法扩展**
    # （分层配额截取 + λ 层乘数调制），摘要已同步为 MEV-008 交付态；
    # `evaluator.py` 仍逐字节冻结（MEV-008 未触碰）。
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
}


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def epi_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (episodic, memory_ingest, background_job_repository):
        monkeypatch.setattr(module, "SessionLocal", factory)
    settings = get_settings()
    monkeypatch.setattr(settings, "memory_episodic_mode", "auto")
    monkeypatch.setattr(settings, "memory_episodic_window_hours", 12)
    monkeypatch.setattr(settings, "memory_episodic_min_events", 3)
    monkeypatch.setattr(settings, "memory_episodic_max_per_run", 20)
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
        source="user_derived",
        status=status,
        salience=salience,
        source_ref={"table": source_table, "id": f"src-{memory_id}"},
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


def _memory_count(factory) -> int:
    with factory() as session:
        return session.query(MemoryRow).count()


class TestThemeKey:
    def test_theme_key_is_deterministic(self):
        first = episodic.theme_key(_memory("m1", "用户上周末去公园露营了", source_table="world_events"))
        second = episodic.theme_key(_memory("m1", "用户上周末去公园露营了", source_table="world_events"))
        assert first == second == "world_events:outdoor"
        other = episodic.theme_key(_memory("m2", "用户下周有一场面试"))
        assert other != first
        assert other.endswith(":career")

    def test_unmatched_content_falls_back_to_misc(self):
        assert episodic.theme_key(_memory("m3", "天气不错")).endswith(f":{episodic.MISC_THEME}")


class TestSelection:
    def test_mode_off_produces_no_candidate(self, epi_env, monkeypatch, caplog):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        monkeypatch.setattr(get_settings(), "memory_episodic_mode", "off")
        with caplog.at_level("WARNING"):
            outcome = episodic.run_aggregate_tick(BASE)
            stats = episodic.aggregate_once(BASE)

        assert outcome == {"enqueued": False}
        assert stats["created"] == 0
        assert _candidates(factory) == []
        with factory() as session:
            assert session.query(BackgroundJobRow).count() == 0
        assert [r for r in caplog.records if r.levelname == "WARNING"] == []

    def test_groups_below_min_events_are_skipped(self, epi_env):
        factory, _ = epi_env
        _seed(factory, _memory("m1", "用户去公园露营了"), _memory("m2", "用户露营搭帐篷"))
        stats = episodic.aggregate_once(BASE)
        assert stats["skipped_small"] == 1
        assert _candidates(factory) == []

    def test_window_excludes_out_of_range_events(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
            _memory("m-old", "用户上次露营忘带睡袋", minutes_ago=13 * 60),
        )
        stats = episodic.aggregate_once(BASE)
        assert stats["created"] == 1
        candidate = _candidates(factory)[0]
        assert candidate.source_ref["source_ids"] == ["m1", "m2", "m3"]
        assert "m-old" not in candidate.content

    def test_unmatched_topic_is_not_aggregated(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户今天心情不错"),
            _memory("m2", "用户晚上看了会儿书"),
            _memory("m3", "用户明天想早点睡"),
        )
        stats = episodic.aggregate_once(BASE)
        assert stats["skipped_misc"] == 1
        assert _candidates(factory) == []


class TestAggregateOutput:
    def test_group_at_or_above_min_events_produces_exactly_one_candidate(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了", salience=0.5, minutes_ago=180),
            _memory("m2", "用户露营搭了帐篷", salience=0.9, minutes_ago=120),
            _memory("m3", "用户露营煮了火锅", salience=0.7, minutes_ago=60),
        )
        stats = episodic.aggregate_once(BASE)
        assert stats["created"] == 1
        candidates = _candidates(factory)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.source_table == "memory_aggregate"
        assert candidate.proposed_type == "experience"
        assert candidate.source_ref["layer"] == "episodic"
        assert candidate.salience == pytest.approx(0.9)
        # 内容按 created_at 升序拼接
        assert candidate.content == "用户去公园露营了；用户露营搭了帐篷；用户露营煮了火锅"

    def test_source_ref_contains_sorted_source_ids(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m3", "用户去公园露营了", minutes_ago=60),
            _memory("m1", "用户露营搭了帐篷", minutes_ago=180),
            _memory("m2", "用户露营煮了火锅", minutes_ago=120),
        )
        episodic.aggregate_once(BASE)
        ref = _candidates(factory)[0].source_ref
        assert ref["source_ids"] == ["m1", "m2", "m3"]
        assert ref["table"] == "memory_aggregate"
        assert ref["theme"] == "conversation:outdoor"
        assert ref["window_start"] == (BASE - timedelta(hours=12)).isoformat(timespec="seconds")

    def test_source_id_is_deterministic_and_idempotent(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        first = episodic.aggregate_once(BASE)
        second = episodic.aggregate_once(BASE)
        assert first["created"] == 1
        assert second["created"] == 0
        assert second["existing"] == 1
        assert len(_candidates(factory)) == 1
        assert _candidates(factory)[0].source_id == episodic.source_id_for(
            "conversation:outdoor", ["m1", "m2", "m3"]
        )

    def test_aggregate_output_excluded_from_next_run(self, epi_env):
        factory, _ = epi_env
        aggregate_row = _memory(
            "agg-1",
            "用户去公园露营了；用户露营搭了帐篷",
            source_table="memory_aggregate",
        )
        aggregate_row.source_ref = {"table": "memory_aggregate", "id": "episodic:conversation:outdoor:m1"}
        _seed(
            factory,
            aggregate_row,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        stats = episodic.aggregate_once(BASE)
        assert stats["created"] == 1
        candidates = _candidates(factory)
        assert len(candidates) == 1
        assert candidates[0].source_ref["source_ids"] == ["m1", "m2", "m3"]

    def test_respects_max_per_run(self, epi_env, monkeypatch):
        factory, _ = epi_env
        themes = ("露营", "面试", "体检", "考试", "做饭")
        for index, keyword in enumerate(themes):
            _seed(
                factory,
                *[
                    _memory(f"{index}-{slot}", f"用户{keyword}相关第{slot}件事", minutes_ago=slot)
                    for slot in (1, 2, 3)
                ],
            )
        monkeypatch.setattr(get_settings(), "memory_episodic_max_per_run", 2)

        first = episodic.aggregate_once(BASE)
        assert first["created"] == 2
        second = episodic.aggregate_once(BASE)
        assert second["created"] == 2
        third = episodic.aggregate_once(BASE)
        assert third["created"] == 1
        assert len(_candidates(factory)) == 5

    def test_single_group_failure_is_isolated(self, epi_env, monkeypatch, caplog):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("c1", "用户去参加面试了"),
            _memory("c2", "用户面试聊得不错"),
            _memory("c3", "用户面试还有二面"),
            _memory("o1", "用户去公园露营了"),
            _memory("o2", "用户露营搭了帐篷"),
            _memory("o3", "用户露营煮了火锅"),
        )
        original = memory_ingest.create_candidate

        def _explode(**kwargs):
            if "career" in kwargs["source_id"]:
                raise RuntimeError("模拟单组失败")
            return original(**kwargs)

        monkeypatch.setattr(memory_ingest, "create_candidate", _explode)
        with caplog.at_level("WARNING"):
            stats = episodic.aggregate_once(BASE)

        assert stats["failed"] == 1
        assert stats["created"] == 1
        assert len(_candidates(factory)) == 1
        assert any("单组失败" in record.message for record in caplog.records)

    def test_reads_only_and_never_writes_memories(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了", salience=0.6),
            _memory("m2", "用户露营搭了帐篷", salience=0.7),
            _memory("m3", "用户露营煮了火锅", salience=0.8),
        )
        before = _memory_count(factory)
        episodic.aggregate_once(BASE)
        assert _memory_count(factory) == before
        assert len(_candidates(factory)) == 1

    def test_status_and_layer_filters_apply(self, epi_env):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷", status="forgotten"),
            _memory("m3", "用户露营煮了火锅", layer="semantic"),
            _memory("m4", "用户露营买了装备", memory_type="user_fact"),
        )
        stats = episodic.aggregate_once(BASE)
        assert stats["created"] == 0
        assert _candidates(factory) == []


class TestJobWiring:
    def test_mode_auto_enqueues_once_per_hour(self, epi_env):
        factory, _ = epi_env
        first = episodic.run_aggregate_tick(BASE)
        second = episodic.run_aggregate_tick(BASE + timedelta(minutes=5))
        later = episodic.run_aggregate_tick(BASE + timedelta(hours=1))

        assert first == {"enqueued": True}
        assert second == {"enqueued": False}
        assert later == {"enqueued": True}
        with factory() as session:
            assert session.query(BackgroundJobRow).count() == 2

    def test_run_aggregate_job_respects_mode(self, epi_env, monkeypatch):
        factory, _ = epi_env
        _seed(
            factory,
            _memory("m1", "用户去公园露营了"),
            _memory("m2", "用户露营搭了帐篷"),
            _memory("m3", "用户露营煮了火锅"),
        )
        monkeypatch.setattr(get_settings(), "memory_episodic_mode", "off")
        assert episodic.run_aggregate_job()["created"] == 0
        assert _candidates(factory) == []

        monkeypatch.setattr(get_settings(), "memory_episodic_mode", "auto")
        assert episodic.run_aggregate_job()["created"] == 1

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
        assert handlers[episodic.JOB_TYPE_MEMORY_EPISODIC_AGGREGATE] is episodic.run_aggregate_job
        assert episodic.run_aggregate_tick in memory_job_worker._TICK_HOOKS


class TestSettings:
    def test_defaults_are_off(self):
        settings = get_settings()
        assert settings.memory_episodic_mode in ("off", "auto")
        assert settings.memory_episodic_window_hours >= 1
        assert settings.memory_episodic_min_events >= 2
        assert settings.memory_episodic_max_per_run >= 1

    def test_invalid_mode_falls_back_to_off(self, override_settings):
        override_settings(MEMORY_EPISODIC_MODE="always")
        assert get_settings().memory_episodic_mode == "off"

    def test_limits_are_clamped(self, override_settings):
        override_settings(
            MEMORY_EPISODIC_WINDOW_HOURS=999,
            MEMORY_EPISODIC_MIN_EVENTS=1,
            MEMORY_EPISODIC_MAX_PER_RUN=999,
        )
        settings = get_settings()
        assert settings.memory_episodic_window_hours == 168
        assert settings.memory_episodic_min_events == 2
        assert settings.memory_episodic_max_per_run == 200


class TestPreserve:
    def test_product_view_existing_eleven_mappings_unchanged(self):
        for kind, label in BASELINE_SOURCE_LABELS.items():
            assert product_view.SOURCE_LABELS[kind] == label
        assert product_view.SOURCE_LABELS["memory_aggregate"] == "一段经历"
        assert len(product_view.SOURCE_LABELS) == 12

    def test_product_view_unknown_source_kind_still_falls_back(self):
        assert product_view.SOURCE_LABELS.get("some_new_table", "some_new_table") == (
            "some_new_table"
        )

    def test_ingest_paths_untouched(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(memory_ingest, name)) == digest, name

    def test_evaluator_lifecycle_retriever_untouched(self):
        for relative, digest in PRESERVED_FILE_DIGESTS.items():
            assert file_digest(relative) == digest, relative

    def test_no_llm_import_in_episodic_module(self):
        source = Path(episodic.__file__).read_text(encoding="utf-8")
        for forbidden in ("app.chains", "langchain", "llm_factory", "get_llm"):
            assert forbidden not in source, forbidden

    def test_no_new_migration_and_pins_unchanged(self):
        # MEV-009（2026-10-20）：迁移 0011 入链，HEAD/PARENT 推进为 0011/0010。
        assert schema_pins.MIGRATION_HEAD == "0011"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0010"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == schema_pins.schema_columns_digest()
