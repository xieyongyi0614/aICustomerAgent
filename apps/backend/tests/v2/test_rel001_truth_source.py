"""REL-001 关系事实真相源统一测试。

覆盖：里程碑转写通道（类型/salience/source_ref/幂等/insight 溯源位）、
v1 直写旁路已删除（静态守卫）、v1 遗留记忆迁移（dry-run/apply/幂等/校验）、
debug timeline 账本↔记忆互相溯源。
"""

import pathlib
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.db import Memory
from app.core.settings import get_settings
from app.models.relationship import (
    MilestoneRecord,
    RelationshipDelta,
    RelationshipEvent,
)
from app.repositories import (
    memory_repository,
    relationship_event_repository,
    relationship_milestone_repository,
)
from app.services.memory import ingest, migration
from app.services.memory.types import V2_MEMORY_TYPES

BACKEND = pathlib.Path(__file__).resolve().parents[2]


NOW = datetime(2026, 9, 6, 12, 0, 0)


def _milestone(
    key="first_self_disclosure",
    title="第一次袒露心事",
    period="",
    user_id="u-rel1",
    milestone_id=None,
):
    return MilestoneRecord(
        id=milestone_id or f"ms-{key}",
        user_id=user_id,
        milestone_key=key,
        period_key=period,
        title=title,
        created_at=NOW,
    )


class TestMilestoneIngest:
    def test_ingest_creates_milestone_event_candidate(self, _offline_repos):
        row = ingest.ingest_from_relationship_milestone(_milestone())
        assert row is not None
        assert row.proposed_type == "milestone_event"
        assert row.source_table == "relationship_milestones"
        assert row.source_id == "ms-first_self_disclosure"
        assert row.content == "第一次袒露心事"
        assert row.source == "user_derived"
        assert row.source_ref["table"] == "relationship_milestones"
        assert row.source_ref["id"] == "ms-first_self_disclosure"
        assert row.source_ref["milestone_key"] == "first_self_disclosure"
        assert row.source_ref["period_key"] == ""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("first_self_disclosure", ingest.MILESTONE_SALIENCE_MEMORY_WORTHY),
            ("narrative:all_nighter", ingest.MILESTONE_SALIENCE_NARRATIVE),
            ("first_interaction", ingest.MILESTONE_SALIENCE_DEFAULT),
        ],
    )
    def test_salience_mapping(self, _offline_repos, key, expected):
        row = ingest.ingest_from_relationship_milestone(_milestone(key=key))
        assert row.salience == expected

    def test_ingest_idempotent(self, _offline_repos):
        first = ingest.ingest_from_relationship_milestone(_milestone())
        second = ingest.ingest_from_relationship_milestone(
            _milestone(milestone_id="ms-first_self_disclosure")
        )
        assert first.id == second.id

    def test_insight_id_carried_from_meta(self, _offline_repos):
        milestone = SimpleNamespace(
            id="ms-narr-1",
            user_id="u-rel1",
            milestone_key="narrative:all_nighter",
            period_key="",
            title="第一次一起熬夜赶工",
            meta={"source": "insight", "insight_id": "ins-7"},
        )
        row = ingest.ingest_from_relationship_milestone(milestone)
        assert row.source_ref["insight_id"] == "ins-7"

    def test_milestone_event_type_is_canonical(self):
        assert "milestone_event" in V2_MEMORY_TYPES
        assert "relationship_fact" in V2_MEMORY_TYPES


class TestV1BypassGate:
    """v1 直写旁路已随 memory 域清理删除（2026-09-29）：关系记忆不再有 v1 投递通道。"""

    def test_v1_delivery_module_is_removed(self):
        assert not (BACKEND / "app/services/relationship_memory.py").exists()

    def test_state_service_has_no_v1_delivery_reference(self):
        source = (BACKEND / "app/services/conversation/state.py").read_text(encoding="utf-8")
        assert "relationship_memory" not in source


class TestLegacyMigration:
    def _seed_legacy(self, user_id="u-mig", content="我们一起去看过海"):
        return memory_repository.create_memory(
            user_id=user_id,
            character_id="asuna",
            content=content,
            memory_type="relationship_event",
            importance=0.8,
            confidence=0.8,
            source="ai_inferred",
        )

    def test_dry_run_report(self, _offline_repos):
        self._seed_legacy()
        report = migration.collect_report()
        assert report["pending_rows"] == 1
        assert report["per_user"] == {"u-mig": 1}
        assert report["without_source_ref"] == 1
        assert report["replay_source_rows"] == 1
        assert report["target_type"] == "relationship_fact"

    def test_apply_migrates_and_verifies(self, _offline_repos):
        memory = self._seed_legacy()
        report = migration.apply_migration(batch_size=10)
        assert report["mode"] == "apply"
        assert report["migrated"] == 1
        assert report["verification"]["remaining_rows"] == 0
        assert report["verification"]["alias_mapping_ok"] is True
        assert report["verification"]["affinity_normalize_ok"] is True
        row = memory_repository.get_memory(memory.id)
        assert row.type == "relationship_fact"
        assert row.content == "我们一起去看过海"
        assert row.source == "ai_inferred"

    def test_apply_idempotent(self, _offline_repos):
        self._seed_legacy()
        assert migration.apply_migration(batch_size=10)["migrated"] == 1
        assert migration.apply_migration(batch_size=10)["migrated"] == 0


class TestTimelineNarrativeLink:
    def test_event_and_milestone_linked_to_memory(self, _offline_repos):
        from app.api.v1.debug.relationship import get_relationship_timeline

        user_id = "u-link"
        event = relationship_event_repository.create_event(
            RelationshipEvent(
                user_id=user_id,
                session_id="s-1",
                type="intimate_moment",
                magnitude="strong",
                impact=RelationshipDelta(intimacy=0.05),
                confidence=0.9,
                source="conversation",
                cause="深夜长谈",
                created_at=NOW,
            )
        )
        milestone = relationship_milestone_repository.create_milestone(
            user_id=user_id,
            milestone_key="first_self_disclosure",
            title="第一次袒露心事",
            now=NOW,
        )
        now = datetime.now()
        with memory_repository.SessionLocal() as session:
            session.add(
                Memory(
                    id="mem-evt-1",
                    user_id=user_id,
                    content="深夜长谈",
                    type="relationship_fact",
                    importance=0.75,
                    character_id="asuna",
                    confidence=0.9,
                    source="user_derived",
                    status="active",
                    source_ref={
                        "table": "relationship_events",
                        "id": event.id,
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Memory(
                    id="mem-ms-1",
                    user_id=user_id,
                    content="第一次袒露心事",
                    type="milestone_event",
                    importance=0.9,
                    character_id="asuna",
                    confidence=0.9,
                    source="user_derived",
                    status="active",
                    source_ref={
                        "table": "relationship_milestones",
                        "id": milestone.id,
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        report = get_relationship_timeline(user_id)
        items = {item["kind"]: item for item in report["items"]}
        assert items["event"]["narrative_memory_ids"] == ["mem-evt-1"]
        assert items["milestone"]["narrative_memory_ids"] == ["mem-ms-1"]
