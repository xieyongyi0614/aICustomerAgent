"""MEV-005 分层列与回填：映射 / 回填幂等 / schema 一致性 / 写入不变量。

契约：`docs/version/v6.0.0/tasks/MEV-005.md` §4.1（迁移与模型契约、层映射、写入路径赋值）。
合并说明：迁移 `0010_memory_layer_and_enums.py` 同时承载词表收窄、事件源收窄与 `memories.layer`
（用户裁决 2026-10-16：同版本未应用迁移不再逐域拆分）。
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import CheckConstraint, Index, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import timeutil
from app.core.constants import DEFAULT_LAYER, LAYER_FOR_TYPE, MEMORY_LAYERS
from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow
from app.core.settings import get_settings
from app.models.memory import MemoryType
from app.repositories import memory_repository
from app.services.memory import evaluator, ingest, lifecycle
from app.services.memory import types as memory_types

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    BACKEND_ROOT / "migrations" / "versions" / "0010_memory_layer_and_enums.py"
)

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def _migration_module() -> ModuleType:
    """按文件路径装载迁移模块（`0010_*` 不是合法模块名，不能按名 import）。"""
    spec = importlib.util.spec_from_file_location("migration_0010", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def layer_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (memory_repository, evaluator, lifecycle, ingest):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    settings = get_settings()
    monkeypatch.setattr(settings, "memory_eval_threshold_high", 0.75)
    monkeypatch.setattr(settings, "memory_eval_threshold_low", 0.35)
    monkeypatch.setattr(settings, "memory_eval_weight_source", 1.0)
    monkeypatch.setattr(settings, "memory_eval_weight_novelty", 0.0)
    monkeypatch.setattr(settings, "memory_eval_weight_affinity", 0.0)
    monkeypatch.setattr(settings, "memory_eval_weight_salience", 0.0)
    evaluator.reset_evaluator_state()
    yield testing_session, engine
    evaluator.reset_evaluator_state()
    Base.metadata.drop_all(engine)
    engine.dispose()


class TestLayerMapping:
    def test_layer_mapping_covers_all_canonical_types(self):
        assert set(LAYER_FOR_TYPE) == set(memory_types.CANONICAL_MEMORY_TYPES)
        assert set(LAYER_FOR_TYPE) == set(MemoryType.__args__)
        assert set(LAYER_FOR_TYPE.values()) <= set(MEMORY_LAYERS)

    def test_frozen_mapping_values(self):
        assert LAYER_FOR_TYPE == {
            "user_preference": "semantic",
            "user_fact": "semantic",
            "experience": "episodic",
            "relationship_fact": "semantic",
            "commitment": "semantic",
            "milestone_event": "episodic",
            "behavior_pattern": "semantic",
        }

    def test_layers_order_and_default_frozen(self):
        assert MEMORY_LAYERS == ("episodic", "semantic")
        assert DEFAULT_LAYER == "semantic"

    def test_legacy_names_resolve_through_normalization(self):
        """遗留名（入站）也应有确定层：important_event → episodic，relationship_event → semantic。"""
        assert memory_types.layer_for_type("important_event") == "episodic"
        assert memory_types.layer_for_type("relationship_event") == "semantic"

    def test_layer_for_type_unknown_warns_and_returns_default(self, caplog):
        with caplog.at_level("WARNING"):
            assert memory_types.layer_for_type("brand_new") == DEFAULT_LAYER
        assert any(
            "unknown memory type for layer" in record.message for record in caplog.records
        )

    def test_layer_for_type_none_returns_default(self):
        assert memory_types.layer_for_type(None) == DEFAULT_LAYER

    def test_types_module_reexports_core_vocabulary(self):
        """层词汇单一真源在 `core/constants.py`，`services/memory/types.py` 仅再导出。"""
        assert memory_types.MEMORY_LAYERS is MEMORY_LAYERS
        assert memory_types.LAYER_FOR_TYPE is LAYER_FOR_TYPE
        assert memory_types.DEFAULT_LAYER == DEFAULT_LAYER


class TestOrmShape:
    def test_layer_column_shape(self):
        column = MemoryRow.__table__.c.layer
        assert str(column.type) == "VARCHAR(16)"
        assert column.nullable is False
        assert column.server_default is None
        assert column.default is not None and column.default.arg == DEFAULT_LAYER

    def test_layer_check_constraint(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in MemoryRow.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert checks["ck_memories_layer"] == "layer IN ('episodic', 'semantic')"

    def test_layer_index_shape(self):
        indexes = {
            index.name: [column.name for column in index.columns]
            for index in MemoryRow.__table__.indexes
            if isinstance(index, Index)
        }
        assert indexes["idx_memories_user_layer_status"] == ["user_id", "layer", "status"]

    def test_existing_columns_unchanged(self):
        type_column = MemoryRow.__table__.c.type
        assert type_column.nullable is False
        assert type_column.server_default is None
        assert len(MemoryRow.__table__.columns) == 23


class TestMigrationFile:
    @staticmethod
    def _source() -> str:
        return MIGRATION_FILE.read_text(encoding="utf-8")

    def test_revision_metadata(self):
        source = self._source()
        assert 'revision: str = "0010"' in source
        assert 'down_revision: Union[str, Sequence[str], None] = "0009"' in source

    def test_declares_all_three_domains(self):
        source = self._source()
        assert "ck_memories_type" in source
        assert "ck_relationship_events_source" in source
        assert "ck_memories_layer" in source
        assert "idx_memories_user_layer_status" in source

    def test_layer_steps_match_model_contract(self):
        source = self._source()
        # 完整布尔式（不得只传值清单：PG 上会 DatatypeMismatch）
        assert 'f"{LAYER_COLUMN} IN {MEMORY_LAYERS}"' in source
        assert _migration_module()._layer_clause() == "layer IN ('episodic', 'semantic')"
        assert "server_default=DEFAULT_LAYER" in source
        assert "server_default=None" in source

    def test_backfill_sql_shape(self):
        migration = _migration_module()
        sql = migration.BACKFILL_LAYERS_SQL
        assert "SET layer = 'episodic'" in sql
        assert "type IN ('experience', 'milestone_event', 'important_event')" in sql
        assert "layer <> 'episodic'" in sql

    def test_pins_follow_the_merged_migration(self):
        from tests.support import schema_pins

        # MEV-009（2026-10-20）：迁移 0011 入链，HEAD/PARENT 推进为 0011/0010。
        assert schema_pins.MIGRATION_HEAD == "0011"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0010"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == schema_pins.schema_columns_digest()


class TestBackfill:
    SEEDS = (
        ("m-pref", "user_preference", "semantic"),
        ("m-fact", "user_fact", "semantic"),
        ("m-exp", "experience", "episodic"),
        ("m-rel", "relationship_fact", "semantic"),
        ("m-commit", "commitment", "semantic"),
        ("m-mile", "milestone_event", "episodic"),
        ("m-habit", "behavior_pattern", "semantic"),
    )

    def _seed_rows(self, engine) -> None:
        with engine.begin() as connection:
            for memory_id, memory_type, _ in self.SEEDS:
                connection.execute(
                    text(
                        "INSERT INTO memories (id, user_id, content, type, layer,"
                        " importance, character_id, confidence, source, status,"
                        " created_at, updated_at) VALUES (:id, 'u1', '内容', :type,"
                        " 'semantic', 0.5, 'asuna', 0.9, 'user_stated', 'active',"
                        " :now, :now)"
                    ),
                    {"id": memory_id, "type": memory_type, "now": timeutil.now()},
                )

    @staticmethod
    def _layers(engine) -> dict:
        with engine.begin() as connection:
            return dict(
                connection.execute(
                    text("SELECT id, layer FROM memories ORDER BY id")
                ).all()
            )

    def test_backfill_is_idempotent(self, layer_db):
        _, engine = layer_db
        migration = _migration_module()
        self._seed_rows(engine)
        with engine.begin() as connection:
            connection.execute(text(migration.BACKFILL_LAYERS_SQL))
        first = self._layers(engine)
        with engine.begin() as connection:
            connection.execute(text(migration.BACKFILL_LAYERS_SQL))
        second = self._layers(engine)

        assert first == second
        assert first == {memory_id: layer for memory_id, _, layer in self.SEEDS}

    def test_backfill_leaves_canonical_rows_untouched(self, layer_db):
        """归一后库里不存在遗留类型；回填只把 episodic 类型改为 episodic。"""
        _, engine = layer_db
        migration = _migration_module()
        self._seed_rows(engine)
        with engine.begin() as connection:
            connection.execute(text(migration.BACKFILL_LAYERS_SQL))
        layers = self._layers(engine)
        for memory_id, memory_type, expected in self.SEEDS:
            assert layers[memory_id] == expected, memory_type
            assert layers[memory_id] == memory_types.layer_for_type(memory_type)

    def test_check_rejects_unknown_layer(self, layer_db):
        session_factory, _ = layer_db
        with pytest.raises(IntegrityError):
            with session_factory() as session:
                session.add(
                    MemoryRow(
                        id="m-bad",
                        user_id="u1",
                        content="内容",
                        type="user_fact",
                        layer="brand_new",
                        importance=0.5,
                        status="active",
                        created_at=timeutil.now(),
                        updated_at=timeutil.now(),
                    )
                )
                session.commit()


class TestWritePaths:
    def test_repository_create_memory_assigns_layer_for_all_types(self, layer_db):
        for memory_type in memory_types.CANONICAL_MEMORY_TYPES:
            memory = memory_repository.create_memory(
                "u-layer", "asuna", f"内容-{memory_type}", memory_type, 0.6
            )
            assert memory.type == memory_type
            with memory_repository.SessionLocal() as session:
                stored = session.get(MemoryRow, memory.id)
                assert stored.layer == memory_types.layer_for_type(memory_type)

    def test_repository_supersede_path_assigns_layer(self, layer_db):
        old = memory_repository.create_memory("u-sup", "asuna", "旧内容", "experience", 0.6)
        new = memory_repository.create_memory_and_supersede(
            "u-sup", "asuna", "新内容", "experience", 0.6, 0.9, superseded_id=old.id
        )
        with memory_repository.SessionLocal() as session:
            assert session.get(MemoryRow, new.id).layer == "episodic"

    def test_create_candidate_keeps_explicit_layer_only(self, layer_db):
        implicit = ingest.create_candidate(
            user_id="u1",
            character_id="asuna",
            source_table="conversation",
            source_id="c-implicit",
            content="用户喜欢海边",
            proposed_type="user_preference",
            source_kind="user_stated",
            salience_init=0.8,
        )
        assert "layer" not in (implicit.source_ref or {})

        explicit = ingest.create_candidate(
            user_id="u1",
            character_id="asuna",
            source_table="conversation",
            source_id="c-explicit",
            content="用户上周去看了海",
            proposed_type="experience",
            source_kind="user_stated",
            salience_init=0.8,
            layer="episodic",
        )
        assert explicit.source_ref["layer"] == "episodic"

        unknown = ingest.create_candidate(
            user_id="u1",
            character_id="asuna",
            source_table="conversation",
            source_id="c-unknown",
            content="用户最近换了工作",
            proposed_type="user_fact",
            source_kind="user_stated",
            salience_init=0.8,
            layer="brand_new",
        )
        assert "layer" not in (unknown.source_ref or {})

    def test_promotion_derives_layer_from_final_type(self, layer_db):
        session_factory, _ = layer_db
        episodic_id = _promote("experience", "c1", "用户上周参加了面试")
        semantic_id = _promote("user_fact", "c2", "用户在深圳工作")
        with session_factory() as session:
            assert session.get(MemoryRow, episodic_id).layer == "episodic"
            assert session.get(MemoryRow, semantic_id).layer == "semantic"

    def test_promotion_honours_consistent_explicit_layer(self, layer_db):
        session_factory, _ = layer_db
        memory_id = _promote("milestone_event", "c3", "用户和角色第一次看烟火", layer="episodic")
        with session_factory() as session:
            assert session.get(MemoryRow, memory_id).layer == "episodic"

    def test_promotion_ignores_conflicting_explicit_layer(self, layer_db, caplog):
        session_factory, _ = layer_db
        with caplog.at_level("WARNING"):
            memory_id = _promote(
                "experience", "c4", "用户前阵子去看了演唱会", layer="semantic"
            )
        with session_factory() as session:
            assert session.get(MemoryRow, memory_id).layer == "episodic"
        assert any("候选层与类型映射不一致" in record.message for record in caplog.records)

    def test_layer_of_helper_is_pure(self):
        row = MemoryCandidateRow(
            id="c-pure",
            user_id="u1",
            character_id="asuna",
            content="内容",
            proposed_type="milestone_event",
            source="user_stated",
            source_ref={},
            source_table="conversation",
            source_id="s-pure",
            salience=0.8,
            status="pending",
            visibility="private",
            created_at=timeutil.now(),
        )
        assert evaluator._layer_of(row, "milestone_event") == "episodic"
        row.source_ref = {"layer": "episodic"}
        assert evaluator._layer_of(row, "milestone_event") == "episodic"


def _promote(memory_type: str, source_id: str, content: str, layer=None) -> str:
    """走公开链路：create_candidate → evaluate_candidate（规则高分直接转正）→ memory_id。"""
    candidate = ingest.create_candidate(
        user_id="u1",
        character_id="asuna",
        source_table="conversation",
        source_id=source_id,
        content=content,
        proposed_type=memory_type,
        source_kind="user_stated",
        salience_init=0.9,
        source_ref_extra={"importance": 0.9, "confidence": 0.9},
        layer=layer,
    )
    decision = asyncio.run(evaluator.evaluate_candidate(candidate, []))
    assert decision.action == "approve"
    return decision.memory_id
