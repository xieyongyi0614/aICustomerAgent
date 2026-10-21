"""MEV-008 分层衰减调制：乘数解析 / `layer=None` 兼容 / 分层衰减差异 / Preserve。

契约：`docs/version/v6.0.0/tasks/MEV-008.md` §4.1.3 与 §7.1 / §7.2。
"""

from __future__ import annotations

import hashlib
import inspect
import math
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import timeutil
from app.core.db import Base, Memory as MemoryRow
from app.core.settings import get_settings
from app.services.memory import lifecycle as memory_lifecycle
from tests.support.frozen_surface import file_digest

PRESERVED_FUNCTION_DIGESTS = {
    "_apply_reinforce": "e08c691fe5e1470b",
    "on_promoted": "2d94031d413eee03",
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
    # MEV-009（2026-10-20）：`types.py` 仅新增链接关系常量再导出，摘要同步。
    "app/services/memory/types.py": (
        "934157620299e6cb1c4323300856bcf5e616f49ec3972b63c5ca24fc4bda866e"
    ),
}

PRESERVED_CALLER_FILES = {
    "app/services/conversation/context.py": (
        "f8da46da9c6218e7891fdc8938edcae88af38ca01e4e97895a57f65fd283b821"
    ),
    "app/prompts/builder.py": (
        "007d66444fe6e0f4759f00706536f755ecdec641954b4af1876d256a060223f0"
    ),
}

PLANNING_TREE_DIGEST = (
    "9c53303235b78fb438c3dd9af41c3ee3a0eb4642718f948abb07eea9ce5ca6e6"
)

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

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

MULTIPLIERS = '{"episodic": 1.5, "semantic": 0.6}'


def _function_digest(function) -> str:
    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _tree_digest(root: str) -> str:
    """目录下全部 `.py` 的「路径:摘要」串联后再 sha256（覆盖整包零 diff）。"""
    parts = []
    for path in sorted((_BACKEND_ROOT / root).rglob("*.py")):
        relative = path.relative_to(_BACKEND_ROOT).as_posix()
        parts.append(f"{relative}:{file_digest(relative)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _row(memory_id: str, *, layer: str, memory_type: str, salience: float, age_days: float):
    created = timeutil.now() - timedelta(days=age_days)
    return MemoryRow(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        content=f"{memory_id} 内容",
        type=memory_type,
        layer=layer,
        importance=0.6,
        confidence=0.9,
        source="ai_inferred",
        status="active",
        salience=salience,
        created_at=created,
        updated_at=created,
    )


@pytest.fixture
def decay_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(memory_lifecycle, "SessionLocal", factory)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def multiplier_settings(monkeypatch):
    settings = get_settings()

    def _apply(raw: str):
        monkeypatch.setattr(settings, "memory_decay_layer_multiplier_json", raw)
        return settings

    return _apply


def _seed(factory, *rows: MemoryRow) -> None:
    with factory() as session:
        session.add_all(list(rows))
        session.commit()


def _salience(factory, memory_id: str) -> float:
    with factory() as session:
        return session.get(MemoryRow, memory_id).salience


def _status(factory, memory_id: str) -> str:
    with factory() as session:
        return session.get(MemoryRow, memory_id).status


class TestMultiplierResolution:
    def test_decay_multiplier_empty_keeps_lambda_unchanged(self, multiplier_settings):
        multiplier_settings("{}")
        for memory_type in get_settings().decay_lambdas():
            assert memory_lifecycle.decay_lambda_for(
                memory_type, "episodic"
            ) == memory_lifecycle.decay_lambda_for(memory_type)
            assert memory_lifecycle.decay_lambda_for(
                memory_type, "semantic"
            ) == memory_lifecycle.decay_lambda_for(memory_type)

    def test_decay_lambda_for_without_layer_is_baseline_identical(
        self, multiplier_settings
    ):
        settings = multiplier_settings(MULTIPLIERS)
        table = settings.decay_lambdas()
        assert table
        for memory_type, expected in table.items():
            assert memory_lifecycle.decay_lambda_for(memory_type) == pytest.approx(
                float(expected)
            )

    def test_decay_lambda_for_unknown_layer_is_baseline(self, multiplier_settings):
        settings = multiplier_settings(MULTIPLIERS)
        table = settings.decay_lambdas()
        assert memory_lifecycle.decay_lambda_for(
            "experience", "legacy_layer"
        ) == pytest.approx(float(table["experience"]))

    def test_decay_multiplier_scales_lambda(self, multiplier_settings):
        settings = multiplier_settings(MULTIPLIERS)
        table = settings.decay_lambdas()
        assert memory_lifecycle.decay_lambda_for(
            "experience", "episodic"
        ) == pytest.approx(float(table["experience"]) * 1.5, abs=1e-9)
        assert memory_lifecycle.decay_lambda_for(
            "user_preference", "semantic"
        ) == pytest.approx(float(table["user_preference"]) * 0.6, abs=1e-9)

    @pytest.mark.parametrize(
        "raw",
        ["not-json", "[]", '"text"', '{"episodic": -1}', '{"episodic": 0}', '{"episodic": 11}'],
    )
    def test_decay_invalid_multiplier_json_degrades_to_one(
        self, multiplier_settings, caplog, raw
    ):
        settings = multiplier_settings(raw)
        baseline = memory_lifecycle.decay_lambda_for("experience")

        with caplog.at_level("WARNING"):
            result = memory_lifecycle.decay_lambda_for("experience", "episodic")

        assert result == pytest.approx(baseline)
        assert settings.memory_decay_layer_multiplier_json == raw
        assert any("乘数" in record.message for record in caplog.records)

    def test_decay_multiplier_non_numeric_value_degrades_to_one(
        self, multiplier_settings, caplog
    ):
        multiplier_settings('{"episodic": "fast"}')
        baseline = memory_lifecycle.decay_lambda_for("experience")
        with caplog.at_level("WARNING"):
            result = memory_lifecycle.decay_lambda_for("experience", "episodic")
        assert result == pytest.approx(baseline)
        assert any("乘数" in record.message for record in caplog.records)


class TestDecayBatch:
    def test_episodic_decays_faster_than_semantic_under_same_delta(
        self, decay_env, multiplier_settings
    ):
        factory = decay_env
        multiplier_settings(MULTIPLIERS)
        _seed(
            factory,
            _row(
                "e1",
                layer="episodic",
                memory_type="experience",
                salience=1.0,
                age_days=10.0,
            ),
            _row(
                "s1",
                layer="semantic",
                memory_type="experience",
                salience=1.0,
                age_days=10.0,
            ),
        )

        memory_lifecycle._decay_batch(timeutil.now())

        assert _salience(factory, "e1") < _salience(factory, "s1")
        assert _salience(factory, "s1") == pytest.approx(math.exp(-0.03 * 0.6 * 10.0), rel=0.02)

    def test_decay_floor_and_transition_unchanged(self, decay_env, multiplier_settings):
        factory = decay_env
        multiplier_settings("{}")
        floor = get_settings().memory_salience_floor
        _seed(
            factory,
            _row(
                "m1",
                layer="episodic",
                memory_type="experience",
                salience=floor * 0.5,
                age_days=400.0,
            ),
        )

        decayed = memory_lifecycle._decay_batch(timeutil.now())

        assert decayed == 1
        assert _status(factory, "m1") == "decayed"
        assert (
            memory_lifecycle.TRANSITIONS[("active", "decay_floor")] == "decayed"
        )

    def test_recent_rows_are_skipped_by_daily_bucket(self, decay_env, multiplier_settings):
        factory = decay_env
        multiplier_settings(MULTIPLIERS)
        _seed(
            factory,
            _row(
                "e1",
                layer="episodic",
                memory_type="experience",
                salience=0.5,
                age_days=0.2,
            ),
        )

        assert memory_lifecycle._decay_batch(timeutil.now()) == 0
        assert _salience(factory, "e1") == pytest.approx(0.5)


class TestPreserve:
    def test_lifecycle_core_invariants_unchanged(self):
        assert memory_lifecycle.TRANSITIONS == EXPECTED_TRANSITIONS
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _function_digest(getattr(memory_lifecycle, name)) == digest, name

    def test_generation_modules_untouched(self):
        for relative, digest in PRESERVED_FILE_DIGESTS.items():
            assert file_digest(relative) == digest, relative

    def test_callers_unchanged(self):
        for relative, digest in PRESERVED_CALLER_FILES.items():
            assert file_digest(relative) == digest, relative
        assert _tree_digest("app/services/planning") == PLANNING_TREE_DIGEST

    def test_lifecycle_has_no_llm_dependency(self):
        for function in (
            memory_lifecycle.decay_lambda_for,
            memory_lifecycle._layer_decay_multiplier,
        ):
            source = inspect.getsource(function)
            assert "get_llm" not in source
            assert "llm_factory" not in source
