"""MEV-009 记忆链接关系扩展与 1-hop 扩展召回。

契约：`docs/version/v6.0.0/tasks/MEV-009.md` §4.1 与 §7。
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, Index, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core import timeutil
from app.core.constants import LAYER_FOR_TYPE
from app.core.db import Memory as MemoryRow, MemoryCandidateRow, MemoryLinkRow
from app.core.settings import get_settings
from app.core.settings.memory import MemorySettings
from app.repositories import memory_repository
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import retriever
from app.services.memory import types as memory_types
from tests.support import schema_pins
from tests.support.frozen_surface import file_digest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    BACKEND_ROOT / "migrations" / "versions" / "0010_memory_layer_and_enums.py"
)

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)

LEGACY_RELATIONS = ("supersedes", "merges", "contradicts")
NEW_RELATIONS = ("caused_by", "before", "related")
EXPECTED_RELATIONS = LEGACY_RELATIONS + NEW_RELATIONS

PRESERVED_FUNCTION_DIGESTS = {
    "_link_exists": "c4474cfeddf5f1f8",
    "_create_link": "586206133be33100",
    "on_promoted": "2d94031d413eee03",
}

SCORING_FUNCTION_DIGESTS = {
    "_recency": "b44950f139577ace",
    "_structured_score": "0fbe8b0ac3a297b8",
    "_affinity_score": "70f5dfb1d4f00d76",
    "_filter_reasons": "4c543692219eb3af",
}

PRESERVED_FILE_DIGESTS = {
    "app/services/memory/ingest.py": (
        "75f240fe908d8b91a2af7e9060f5f5f76ecdd209740155d77cb8f9926b044949"
    ),
    "app/services/memory/evaluator.py": (
        "f33da2b3323773d2d04a5169d3b204164c64dc1e3c2276f17ce613eae2829286"
    ),
    "app/services/memory/episodic.py": (
        "5dac7df90c46e5806cbeae24bd1580e6da0fd6618bc05581910f1369e02f8c81"
    ),
    "app/services/memory/semantic.py": (
        "28e10bfae6f2685b09693bd65312a218d7104022819b76eac4ec658994b34a26"
    ),
    "app/services/memory/refs.py": (
        "487b848b6b4c6a31838135070359e4fd0a70842d42b8aaa724c06e86c93726a6"
    ),
    "app/services/memory/offline_metrics.py": (
        "f8f0bcb52e91ad495bc2b2d6ee9f46cce0cfc59ae3804dd3560ea582948d1b90"
    ),
    "app/services/memory/product_view.py": (
        "81245df26dffa4ca41106a99cbb55380c82fac1e302e49aa53c6e645af9a8f3d"
    ),
    "app/services/memory/commands.py": (
        "8782fc4eb40d9160cd6f30ce10c03297df5419e234d57770d651c5a0cd3f2cef"
    ),
    "app/services/memory/embeddings.py": (
        "922d9127b5612cdf34e983d7c1f0341a9726c52b4e3e0c6c708f3a619bd6f03e"
    ),
    "app/services/memory/sources.py": (
        "ea5fb93d976e94340ae643f7b5224dda4347b8f1969db6ee50e09b5087525d57"
    ),
}


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0010", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def _memory_row(
    memory_id: str,
    *,
    user_id: str = "u1",
    character_id: str = "asuna",
    memory_type: str = "user_fact",
    content: str | None = None,
    importance: float = 0.5,
    salience: float = 0.5,
    status: str = "active",
    visibility: str | None = None,
    created_at: datetime | None = None,
    superseded_by: str | None = None,
) -> MemoryRow:
    created = created_at or NOW
    return MemoryRow(
        id=memory_id,
        user_id=user_id,
        content=content or f"{memory_id} 内容",
        type=memory_type,
        layer=LAYER_FOR_TYPE[memory_type],
        importance=importance,
        character_id=character_id,
        confidence=0.9,
        source="user_stated",
        status=status,
        superseded_by=superseded_by,
        visibility=visibility,
        salience=salience,
        embedding=None,
        created_at=created,
        updated_at=created,
    )


def _link_row(
    link_id: str,
    memory_id: str,
    related_memory_id: str,
    relation: str,
    created_at: datetime | None = None,
) -> MemoryLinkRow:
    return MemoryLinkRow(
        id=link_id,
        memory_id=memory_id,
        related_memory_id=related_memory_id,
        relation=relation,
        created_at=created_at or NOW,
    )


@pytest.fixture
def seeded_db(db_session_factory, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(retriever.timeutil, "now", lambda: NOW)
    monkeypatch.setattr(settings, "memory_rerank_mode", "off")
    monkeypatch.setattr(settings, "memory_query_rewrite_mode", "off")
    monkeypatch.setattr(settings, "memory_layer_quota", "")
    monkeypatch.setattr(settings, "memory_graph_expand_mode", "off")
    monkeypatch.setattr(settings, "memory_graph_expand_seeds", 3)
    monkeypatch.setattr(settings, "memory_graph_expand_decay", 0.7)
    monkeypatch.setattr(settings, "memory_candidate_pool_limit", 2)
    monkeypatch.setattr(retriever.memory_embeddings, "embed_query", lambda text: None)

    def _seed(memories=(), links=(), candidates=()):
        with db_session_factory() as session:
            session.add_all(list(memories))
            session.add_all(list(links))
            session.add_all(list(candidates))
            session.commit()

    return _seed


@pytest.fixture
def reinforce_spy(monkeypatch):
    spy = _ReinforceSpy()
    monkeypatch.setattr(memory_lifecycle, "record_reinforce", spy)
    return spy


def _seed_expand_scene(seed, *, neighbor_kwargs=None):
    neighbor_kwargs = neighbor_kwargs or {}
    seed(
        memories=[
            _memory_row("d1", created_at=NOW - timedelta(minutes=1)),
            _memory_row("d2", created_at=NOW - timedelta(minutes=2)),
            _memory_row(
                "n1",
                content="关联但未直接命中的记忆",
                created_at=NOW - timedelta(days=30),
                **neighbor_kwargs,
            ),
        ],
        links=[_link_row("l1", "d1", "n1", "caused_by")],
    )


class TestRelationVocabulary:
    def test_relation_constants_are_frozen(self):
        assert memory_types.MEMORY_LINK_RELATIONS == EXPECTED_RELATIONS
        assert memory_types.MEMORY_LINK_RELATIONS_LEGACY == LEGACY_RELATIONS
        assert memory_types.MEMORY_LINK_RELATIONS[:3] == LEGACY_RELATIONS

    def test_check_constraint_matches_migration_definition(self):
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in MemoryLinkRow.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }
        migration = _migration_module()
        assert migration.RELATIONS == EXPECTED_RELATIONS
        assert checks["ck_memory_links_relation"] == migration._relation_clause()


class TestLinkValues:
    def test_new_relation_values_are_accepted(self, db_session_factory):
        with db_session_factory() as session:
            session.add_all(
                [
                    _link_row(f"l-{relation}", "m1", "m2", relation)
                    for relation in NEW_RELATIONS
                ]
            )
            session.commit()
            assert session.query(MemoryLinkRow).count() == 3

    def test_unknown_relation_value_is_rejected(self, db_session_factory):
        with db_session_factory() as session:
            session.add(_link_row("l-bad", "m1", "m2", "likes"))
            with pytest.raises(IntegrityError):
                session.commit()


class TestRepositoryLinks:
    def test_list_links_returns_ordered_tuples(self, db_session_factory):
        with db_session_factory() as session:
            session.add_all(
                [
                    _link_row("l2", "a", "c", "before"),
                    _link_row("l1", "a", "b", "caused_by"),
                    _link_row("l3", "x", "y", "supersedes"),
                ]
            )
            session.commit()

        assert memory_repository.list_links(["a"]) == [
            ("a", "b", "caused_by"),
            ("a", "c", "before"),
        ]

    def test_list_links_filters_relations_and_handles_empty_ids(self):
        assert memory_repository.list_links([]) == []


class TestExpand:
    def test_expand_off_is_bytewise_identical_to_baseline(
        self, seeded_db, reinforce_spy
    ):
        _seed_expand_scene(seeded_db)
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        assert [item.memory.id for item in result.items] == ["d1", "d2"]
        assert reinforce_spy.ids == ["d1", "d2"]
        assert "expand_mode" not in trace.step(retriever.STEP_NAME)

    def test_expand_is_skipped_when_no_links(
        self, seeded_db, monkeypatch, reinforce_spy
    ):
        seeded_db(
            memories=[
                _memory_row("d1", created_at=NOW - timedelta(minutes=1)),
                _memory_row("d2", created_at=NOW - timedelta(minutes=2)),
            ]
        )
        baseline = retriever.retrieve("u1", "查询", top_k=5)
        baseline_items = [(item.memory.id, item.score) for item in baseline.items]

        settings = get_settings()
        monkeypatch.setattr(settings, "memory_graph_expand_mode", "one_hop")
        reinforce_spy.ids.clear()
        result = retriever.retrieve("u1", "查询", top_k=5)

        assert [(item.memory.id, item.score) for item in result.items] == baseline_items

    def test_expand_appends_neighbors_after_direct_hits(
        self, seeded_db, monkeypatch
    ):
        _seed_expand_scene(seeded_db)
        monkeypatch.setattr(get_settings(), "memory_graph_expand_mode", "one_hop")

        result = retriever.retrieve("u1", "查询", top_k=5)

        assert [item.memory.id for item in result.items] == ["d1", "d2", "n1"]
        direct_scores = [item.score for item in result.items[:2]]
        assert result.items[2].score < min(direct_scores)

    def test_expand_applies_decay_to_neighbor_score(
        self, seeded_db, monkeypatch
    ):
        _seed_expand_scene(seeded_db)
        settings = get_settings()
        monkeypatch.setattr(settings, "memory_graph_expand_mode", "one_hop")

        result = retriever.retrieve("u1", "查询", top_k=5)

        neighbor = next(item for item in result.items if item.memory.id == "n1")
        memory = memory_repository.get_memory("n1")
        facts = retriever._row_facts(["n1"])
        baseline = retriever._score_all(
            [memory],
            facts,
            None,
            set(),
            NOW,
            temporal=False,
        )[0]
        assert neighbor.score == pytest.approx(
            baseline.score * settings.memory_graph_expand_decay, abs=1e-9
        )
        assert neighbor.semantic == baseline.semantic
        assert neighbor.structured == baseline.structured
        assert neighbor.affinity == baseline.affinity

    def test_expand_dedupes_existing_and_filtered_neighbors(
        self, seeded_db, monkeypatch
    ):
        seeded_db(
            memories=[
                _memory_row("d1", created_at=NOW - timedelta(minutes=1)),
                _memory_row("d2", created_at=NOW - timedelta(minutes=2)),
                _memory_row(
                    "n-rejected",
                    content="被拒主题的记忆",
                    created_at=NOW - timedelta(days=1),
                ),
                _memory_row(
                    "n-hypothetical",
                    visibility="hypothetical",
                    created_at=NOW - timedelta(days=2),
                ),
                _memory_row(
                    "n-forgotten",
                    status="forgotten",
                    created_at=NOW - timedelta(days=3),
                ),
            ],
            links=[
                _link_row("l-direct", "d1", "d2", "related"),
                _link_row("l-rejected", "d1", "n-rejected", "related"),
                _link_row("l-hypothetical", "d1", "n-hypothetical", "related"),
                _link_row("l-forgotten", "d1", "n-forgotten", "related"),
            ],
            candidates=[
                MemoryCandidateRow(
                    id="c-rejected",
                    user_id="u1",
                    character_id="asuna",
                    content="被拒主题的记忆",
                    proposed_type="user_fact",
                    source="user_stated",
                    status="rejected",
                    created_at=NOW,
                )
            ],
        )
        monkeypatch.setattr(get_settings(), "memory_candidate_pool_limit", 200)
        monkeypatch.setattr(get_settings(), "memory_graph_expand_mode", "one_hop")
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        ids = [item.memory.id for item in result.items]
        assert ids.count("d2") == 1
        assert "n-rejected" not in ids
        assert "n-hypothetical" not in ids
        assert "n-forgotten" not in ids
        assert trace.step(retriever.STEP_NAME)["expanded_count"] == 0

    def test_expand_does_not_reinforce_neighbors(
        self, seeded_db, monkeypatch, reinforce_spy
    ):
        _seed_expand_scene(seeded_db)
        monkeypatch.setattr(get_settings(), "memory_graph_expand_mode", "one_hop")

        retriever.retrieve("u1", "查询", top_k=5)

        assert reinforce_spy.ids == ["d1", "d2"]

    def test_expand_marks_reason_with_hop_relation(
        self, seeded_db, monkeypatch
    ):
        _seed_expand_scene(seeded_db)
        monkeypatch.setattr(get_settings(), "memory_graph_expand_mode", "one_hop")
        trace = _TraceSpy()

        result = retriever.retrieve("u1", "查询", top_k=5, trace=trace)

        neighbor = next(item for item in result.items if item.memory.id == "n1")
        assert neighbor.reason == "hop:caused_by"
        step = trace.step(retriever.STEP_NAME)
        assert step["expand_mode"] == "one_hop"
        assert step["expanded_count"] == 1

    def test_expand_is_deterministic(self, seeded_db, monkeypatch, reinforce_spy):
        _seed_expand_scene(seeded_db)
        monkeypatch.setattr(get_settings(), "memory_graph_expand_mode", "one_hop")

        sequences = []
        for _ in range(3):
            reinforce_spy.ids.clear()
            result = retriever.retrieve("u1", "查询", top_k=5)
            sequences.append([item.memory.id for item in result.items])

        assert sequences[0] == sequences[1] == sequences[2]

    def test_expand_failure_degrades_and_does_not_raise(
        self, seeded_db, monkeypatch, caplog
    ):
        _seed_expand_scene(seeded_db)
        baseline = retriever.retrieve("u1", "查询", top_k=5)
        baseline_items = [(item.memory.id, item.score) for item in baseline.items]
        settings = get_settings()
        monkeypatch.setattr(settings, "memory_graph_expand_mode", "one_hop")

        def _boom(*args, **kwargs):
            raise RuntimeError("links unavailable")

        monkeypatch.setattr(memory_repository, "list_links", _boom)
        with caplog.at_level("WARNING"):
            result = retriever.retrieve("u1", "查询", top_k=5)

        assert [(item.memory.id, item.score) for item in result.items] == baseline_items
        assert any("1-hop" in record.message for record in caplog.records)

    def test_expand_decay_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            MemorySettings(memory_graph_expand_decay=1.2)
        with pytest.raises(ValidationError):
            MemorySettings(memory_graph_expand_decay=0.0)

    def test_invalid_expand_mode_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("MEMORY_GRAPH_EXPAND_MODE", "two_hop")
        assert MemorySettings().memory_graph_expand_mode == "off"

    def test_expand_settings_defaults(self):
        settings = MemorySettings()
        assert settings.memory_graph_expand_mode == "off"
        assert settings.memory_graph_expand_seeds == 3
        assert settings.memory_graph_expand_decay == 0.7


@pytest.mark.xdist_group("migration")
class TestMigrationRoundTrip:
    @pytest.fixture(scope="class")
    @staticmethod
    def sqlite_round_trip(tmp_path_factory):
        url = f"sqlite:///{(tmp_path_factory.mktemp('mev009') / 'memory.db').as_posix()}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield cfg, url
        engine = create_engine(url)
        engine.dispose()

    def test_upgrade_downgrade_upgrade_roundtrip(self, sqlite_round_trip):
        cfg, url = sqlite_round_trip
        now = timeutil.now().isoformat(sep=" ")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO memory_links"
                    " (id, memory_id, related_memory_id, relation, created_at)"
                    " VALUES ('old', 'm1', 'm2', 'supersedes', :now),"
                    " ('new', 'm1', 'm3', 'caused_by', :now)"
                ),
                {"now": now},
            )

        command.downgrade(cfg, "0009")
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, relation FROM memory_links ORDER BY id")
            ).all()
        assert rows == [("old", "supersedes")]

        command.upgrade(cfg, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO memory_links"
                    " (id, memory_id, related_memory_id, relation, created_at)"
                    " VALUES ('new-again', 'm1', 'm3', 'before', :now)"
                ),
                {"now": now},
            )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM memory_links")
            ).scalar_one() == 2
        engine.dispose()


class TestPreserve:
    def test_lifecycle_link_writers_unchanged(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(memory_lifecycle, name)) == digest, name

    def test_link_table_columns_and_index_unchanged(self):
        table = MemoryLinkRow.__table__
        assert [column.name for column in table.columns] == [
            "id",
            "memory_id",
            "related_memory_id",
            "relation",
            "created_at",
        ]
        assert table.c.id.primary_key
        assert all(not column.nullable for column in table.columns)
        indexes = {
            index.name: [column.name for column in index.columns]
            for index in table.indexes
            if isinstance(index, Index)
        }
        assert indexes["idx_memory_links_memory"] == ["memory_id"]

    def test_scoring_functions_unchanged(self):
        for name, digest in SCORING_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(retriever, name)) == digest, name

    def test_other_memory_modules_untouched(self):
        for relative, digest in PRESERVED_FILE_DIGESTS.items():
            assert file_digest(relative) == digest, relative

    def test_pins_updated_and_table_count_unchanged(self):
        assert schema_pins.MIGRATION_HEAD == "0010"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0009"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == "2088c55108ab39a1"
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == schema_pins.schema_columns_digest()

    def test_all_repo_pin_tests_green(self):
        assert schema_pins.MIGRATION_HEAD == "0010"
        stale = []
        current = Path(__file__).resolve()
        for path in (BACKEND_ROOT / "tests").rglob("*.py"):
            if path.resolve() == current:
                continue
            source = path.read_text(encoding="utf-8")
            if 'MIGRATION_HEAD == "0009"' in source:
                stale.append(path)
            if 'MIGRATION_HEAD_PARENT == "0008"' in source:
                stale.append(path)
        assert not stale


def test_migration_module_metadata():
    migration = _migration_module()
    assert migration.revision == "0010"
    assert migration.down_revision == "0009"
    assert migration.NEW_RELATIONS == NEW_RELATIONS
    assert migration.LEGACY_RELATIONS == LEGACY_RELATIONS
