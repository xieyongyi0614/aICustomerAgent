"""MEV-003 Type Affinity Vocabulary and Label Coverage（focused + module）。"""

import ast
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.db import Memory
from app.models.conversation import ChatMessage, ConversationState
from app.models.memory import UserMemory
from app.prompts.builder import (
    INSIGHT_TYPE_LABELS,
    MEMORY_TYPE_LABELS,
    PromptBuilder,
    memory_type_label,
)
from app.services.memory import retriever
from app.services.memory import types as memory_types

BACKEND_ROOT = Path(memory_types.__file__).resolve().parents[3]

BASELINE_AFFINITY_KEYWORDS = {
    "user_preference": ("喜欢", "讨厌", "偏好", "爱", "不爱", "不喜欢"),
    "user_fact": ("在哪", "工作", "住", "养", "做什么", "是谁"),
    "experience": ("面试", "经历", "发生过", "事件", "考试"),
    "relationship_fact": ("我们", "一起", "送过", "看过", "去过"),
}

BASELINE_LEGACY_LABELS = {"important_event": "事件", "relationship_event": "关系事件"}

BASELINE_INSIGHT_LABELS = {"belief": "看法", "preference": "偏好", "pattern": "模式"}

BASELINE_THIRD_PARTY_ROOTS = {
    "app/prompts/builder.py": {"langchain_core"},
    "app/services/memory/types.py": set(),
}

HITTING_QUERIES = {
    "user_preference": "我特别喜欢这个",
    "user_fact": "他老家在哪",
    "experience": "那次面试经历",
    "relationship_fact": "我们一起去过",
    "commitment": "你答应我的承诺",
    "milestone_event": "下个月就是周年纪念了",
    "behavior_pattern": "你总是这样",
}

NO_KEYWORD_QUERY = "今天天气"

PRESERVED_FUNCTION_DIGESTS = {
    "normalize_type": "4917df56b1930afc",
    "storage_type": "f9a67d2989b40ca7",
}


def _memory(memory_id: str, memory_type: str, content: str = "内容") -> UserMemory:
    now = datetime.now(timezone.utc)
    return UserMemory(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        type=memory_type,
        content=content,
        importance=0.8,
        confidence=0.9,
        source="user_stated",
        created_at=now,
        updated_at=now,
    )


def _unknown_type_memory(memory_id: str, memory_type: str, content: str) -> UserMemory:
    """绕过 `UserMemory.type` 的 Literal 校验：模拟库内出现表外类型（旧行/脏数据）。"""
    return UserMemory.model_construct(
        id=memory_id,
        user_id="u1",
        character_id="asuna",
        type=memory_type,
        content=content,
        importance=0.8,
        confidence=0.9,
        source="user_stated",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _state(memories) -> ConversationState:
    return ConversationState(
        session_id="s",
        user_id="u1",
        messages=[ChatMessage(role="human", content="你好")],
        summary=None,
        memories=memories,
        current_input="在吗",
    )


def _memory_section(prompt) -> str:
    rendered = prompt.format_messages()
    return next(m.content for m in rendered if "你记得关于用户的事" in m.content)


def _source_digest(function) -> str:
    import hashlib

    source = inspect.getsource(function).replace("\r\n", "\n")
    normalized = "\n".join(line.rstrip() for line in source.split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _third_party_roots(relative_path: str) -> set[str]:
    tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return {
        root
        for root in roots
        if root != "app" and root not in sys.stdlib_module_names
    }


class TestAffinityVocabulary:
    def test_affinity_keywords_cover_all_canonical_types(self):
        assert set(memory_types.TYPE_AFFINITY_KEYWORDS) == set(memory_types.V2_MEMORY_TYPES)
        assert set(memory_types.V2_MEMORY_TYPES) == set(memory_types.TYPE_AFFINITY_KEYWORDS)

    def test_affinity_keywords_values_are_non_empty_unique_strings(self):
        for memory_type, keywords in memory_types.TYPE_AFFINITY_KEYWORDS.items():
            assert isinstance(keywords, tuple), memory_type
            assert keywords, memory_type
            assert all(isinstance(word, str) and word for word in keywords), memory_type
            assert len(set(keywords)) == len(keywords), memory_type

    def test_affinity_keywords_retain_previous_entries(self):
        for memory_type, previous in BASELINE_AFFINITY_KEYWORDS.items():
            current = memory_types.TYPE_AFFINITY_KEYWORDS[memory_type]
            for word in previous:
                assert word in current, f"{memory_type} 丢失既有词条 {word}"

    @pytest.mark.parametrize("memory_type", list(memory_types.V2_MEMORY_TYPES))
    def test_each_canonical_type_has_at_least_one_hitting_query(self, memory_type):
        detected = retriever._detect_query_types(HITTING_QUERIES[memory_type])
        assert memory_type in detected, f"{memory_type} 无法被任何关键词命中"
        assert detected == {memory_type}, f"{memory_type} 命中集不纯净：{detected}"

    @pytest.mark.parametrize("memory_type", list(memory_types.V2_MEMORY_TYPES))
    def test_affinity_score_positive_for_covered_types(self, memory_type):
        memory = _memory("m1", memory_type)
        hitting = retriever._affinity_score(
            memory, retriever._detect_query_types(HITTING_QUERIES[memory_type])
        )
        neutral = retriever._affinity_score(
            memory, retriever._detect_query_types(NO_KEYWORD_QUERY)
        )
        assert neutral == pytest.approx(0.5)
        assert hitting == pytest.approx(1.0)
        assert hitting > neutral

    def test_no_keyword_query_detects_nothing(self):
        assert retriever._detect_query_types(NO_KEYWORD_QUERY) == set()


class TestTypeLabels:
    def test_type_labels_cover_all_storage_types(self):
        for memory_type in memory_types.STORAGE_MEMORY_TYPES:
            assert memory_type in MEMORY_TYPE_LABELS, memory_type
        assert set(MEMORY_TYPE_LABELS) >= set(memory_types.STORAGE_MEMORY_TYPES)

    def test_type_labels_are_unique_and_non_empty(self):
        labels = list(MEMORY_TYPE_LABELS.values())
        assert len(labels) == len(memory_types.STORAGE_MEMORY_TYPES)
        assert len(set(labels)) == len(labels)
        assert all(label for label in labels)

    def test_legacy_type_labels_unchanged(self):
        for memory_type, label in BASELINE_LEGACY_LABELS.items():
            assert MEMORY_TYPE_LABELS[memory_type] == label

    def test_label_keys_order_follows_type_constants(self):
        keys = list(MEMORY_TYPE_LABELS)
        split = len(memory_types.V2_MEMORY_TYPES)
        assert keys[:split] == list(memory_types.V2_MEMORY_TYPES)
        assert keys[split:] == list(memory_types.LEGACY_MEMORY_TYPES)

    def test_canonical_type_labels_rendered_in_prompt(self, caplog):
        memories = [
            _memory("m1", "commitment", "答应周末一起看电影"),
            _memory("m2", "milestone_event", "第一次一起旅行"),
            _memory("m3", "behavior_pattern", "每天早上跑步"),
        ]
        with caplog.at_level("WARNING"):
            section = _memory_section(PromptBuilder.build("default", _state(memories)))

        assert "- (目标) 答应周末一起看电影" in section
        assert "- (里程碑) 第一次一起旅行" in section
        assert "- (习惯) 每天早上跑步" in section
        assert not [r for r in caplog.records if "unknown memory type" in r.message]

    def test_unknown_type_logs_warning_and_keeps_raw_value(self, caplog):
        memory = _unknown_type_memory("m1", "brand_new", "神秘内容")
        with caplog.at_level("WARNING"):
            section = _memory_section(PromptBuilder.build("default", _state([memory])))

        assert "- (brand_new) 神秘内容" in section
        assert any(
            "unknown memory type for label" in record.message for record in caplog.records
        )

    def test_memory_type_label_helper_falls_back_without_raising(self, caplog):
        assert memory_type_label("relationship_fact") == "关系"
        with caplog.at_level("WARNING"):
            assert memory_type_label("brand_new") == "brand_new"
        assert any(
            "unknown memory type for label" in record.message for record in caplog.records
        )


class TestContracts:
    def test_type_constants_unchanged(self):
        assert memory_types.V2_MEMORY_TYPES == (
            "user_preference",
            "user_fact",
            "experience",
            "relationship_fact",
            "commitment",
            "milestone_event",
            "behavior_pattern",
        )
        assert memory_types.LEGACY_MEMORY_TYPES == ("important_event", "relationship_event")
        assert memory_types.LEGACY_TYPE_ALIASES == {
            "important_event": "experience",
            "relationship_event": "relationship_fact",
        }
        assert memory_types.STORAGE_MEMORY_TYPES == (
            memory_types.V2_MEMORY_TYPES + memory_types.LEGACY_MEMORY_TYPES
        )
        assert memory_types.DEFAULT_MEMORY_TYPE == "user_fact"

    def test_normalize_and_storage_type_unchanged(self):
        for name, digest in PRESERVED_FUNCTION_DIGESTS.items():
            assert _source_digest(getattr(memory_types, name)) == digest, name

    def test_retriever_and_schema_untouched(self):
        assert (
            retriever.memory_types.TYPE_AFFINITY_KEYWORDS
            is memory_types.TYPE_AFFINITY_KEYWORDS
        )
        retriever_source = (
            BACKEND_ROOT / "app" / "services" / "memory" / "retriever.py"
        ).read_text(encoding="utf-8")
        assert "TYPE_AFFINITY_KEYWORDS" in retriever_source
        assert "TYPE_AFFINITY_KEYWORDS = {" not in retriever_source

        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in Memory.__table__.constraints
            if getattr(constraint, "name", None) == "ck_memories_type"
        }
        assert "ck_memories_type" in checks
        for memory_type in memory_types.STORAGE_MEMORY_TYPES:
            assert f"'{memory_type}'" in checks["ck_memories_type"]

    def test_no_new_migration_and_pins_unchanged(self):
        from tests.support import schema_pins

        assert schema_pins.MIGRATION_HEAD == "0009"
        assert schema_pins.MIGRATION_HEAD_PARENT == "0008"
        assert schema_pins.SCHEMA_TABLE_COUNT == 57
        assert schema_pins.SCHEMA_COLUMNS_DIGEST == "f4f1cc5b50ae78ed"

    def test_insight_labels_untouched(self):
        assert INSIGHT_TYPE_LABELS == BASELINE_INSIGHT_LABELS

    def test_no_new_third_party_import(self):
        for relative_path, expected in BASELINE_THIRD_PARTY_ROOTS.items():
            assert _third_party_roots(relative_path) == expected, relative_path
