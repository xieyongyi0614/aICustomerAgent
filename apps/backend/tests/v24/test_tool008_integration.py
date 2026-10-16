"""TOOL-008 §6.2/§6.3：投递路径泛化、政策零豁免、幂等、两通道独立与冻结面。

Flag off 路径与 V9 逐字节一致（动作记忆边界表 `action_type` 键）；
Flag on 走 `memory_policy_key` 泛化路径，候选仍必经 R1~R8。
通道收敛第 3 批（台账 §5.2）：投递终点为 v2 候选（`action_records` + record.id），
不再直写 memories；断言目标相应从 memories 前移到 candidates。
"""

import logging
from datetime import datetime
from pathlib import Path

import pytest

from app.core import timeutil
from app.application import action_engine, world_engine
from app.core.db import Base
from app.models.action import ActionResult
from app.models.memory import MemoryCandidate, MemoryType
from app.repositories import memory_repository
from app.services.memory import ingest as memory_ingest
from app.engines import memory_policy
from app.services.action import memory_bridge
from app.services.tool import memory_policy as tool_memory_policy
from app.services.world import memory_bridge as world_memory_bridge
from tests.v24.tool008_support import (
    USER,
    candidate_count,
    candidate_rows,
    candidate_contents,
    memory_count,
    record,
    tool_definition,
)
from tests.support.frozen_surface import assert_frozen, file_digest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

CANCEL_PARAMS = {"target": "开会"}
REMINDER_PARAMS = {"content": "开会", "due_at": "2026-09-20T08:00:00"}
OBJECT_PARAMS = {"object": "牛奶"}

FROZEN_SOURCES: dict[str, str] = {
    # memory 域清理（2026-09-29）：文件由 services/memory_policy.py 归位至
    # services/memory/policy.py，内容逐字节未变（摘要不变），仅键路径更新。
    # services 归位批次 4（2026-09-30）：再由 services/memory/policy.py 归位至
    # engines/memory_policy.py，内容仍逐字节未变（摘要不变），仅键路径更新。
    "app/engines/memory_policy.py": "416f27a9699834fc9e10cf0e6bd90841894cc5685705e3ec6aa9f54ab39603d5",
    # 雪花 ID 声明（2026-10-03，ADR-16 C3）：记忆 id 生成由 `str(uuid4())` 改为雪花
    # —— 非 TOOL-008 改脏。原值 9d65bc16。
    # memory 域时间口径迁移（2026-10-05，0006）：`timeutil.now()` 改走
    # `timeutil.now()`（aware UTC），列改 UtcDateTime —— 非 TOOL-008 改脏。
    # 原值 eb001f3e。
    # 分层写入声明（2026-10-16，MEV-005）：`create_memory` / `create_memory_and_supersede`
    # 落库时按 `core.constants.LAYER_FOR_TYPE` 显式赋值 `layer`（迁移撤默认后漏设即失败）
    # —— 非 TOOL-008 改脏。原值 d959dabc。
    "app/repositories/memory_repository.py": "1c85603c4859a561f96b0c9391928c3f9ed368771e1ae2cc5b4b1b5c279e8a0b",
    # memory 域清理声明（2026-09-29）：`MemoryStatus` 补 `decayed` / `forgotten` 两态
    # （原缺致 `memory_repository._to_memory` 读这两态抛 ValidationError，按 id 读非
    # active 记忆的路径会 500）；`EvaluationVerdict` 从已删除的 `models/memory.py`
    # 归位到本文件 —— 非 TOOL-008 改脏。
    # 词表收窄声明（2026-10-16，MEV-015）：`MemoryType` 收窄为 7 规范值，候选类型域拆出
    # `CandidateMemoryType`（入站容忍遗留名）—— 非 TOOL-008 改脏。原值 3d9419eb。
    "app/models/memory.py": "09d0ce66fb6a255afb45b73351c3facd68b33cf6446b2c527808ebb0fca831cc",
    # memory 域通道收敛声明（2026-09-30，台账 §5.2）：`materialize_event_memory` 直写分支
    # 改为经 memory.ingest.create_candidate 投 v2 候选（评估转正），边界表构造不变 —— 非 TOOL-008 改脏。
    # 时间口径统一（2026-10-05，0006~0008）：`timeutil.now()` → `timeutil.now()`（aware UTC）
    # —— 非 TOOL-008 改脏。原值 952f4bfc。
    # 词表收窄声明（2026-10-16，MEV-015）：`EVENT_MEMORY_TYPES` 与兜底值由遗留名
    # `important_event` 改规范类型 `experience` —— 非 TOOL-008 改脏。原值 cd32a6a1。
    "app/services/world/memory_bridge.py": "0fadddca644b8c75f975e0fd0e83dee80b63f091a19149384533e9326143caea",
    # 记账词表补齐声明（2026-10-02，记账链路修复）：LEDGER_RECORD_TRIGGERS 增补
    # `花费 / 付款 / 买 / 充值 / 交了 / 缴了` —— 非 TOOL-008 改脏。原值 2da514d9。
    "app/character/asuna/action.py": "0269c402790461de1923aa55c58195f05f68b3bb675be2eac5353f7bc50698e0",
}
"""零 diff 冻结摘要：政策闸 / 记忆仓储 / 记忆模型 / 世界记忆桥 / V9 行动模板资产。"""

# 分层列声明（2026-10-16，MEV-005）：`memories` 在 `type` 之后新增 `layer`（合并迁移 `0010`）
# —— 列序即 ORM 声明序，其余 22 列与列序不变。
MEMORIES_COLUMNS: tuple[str, ...] = (
    "id", "user_id", "content", "type", "layer", "importance", "character_id", "confidence",
    "source", "status", "superseded_by", "last_accessed_at", "expires_at", "created_at",
    "updated_at", "embedding", "salience", "last_reinforced_at", "last_decayed_at",
    "forgotten_at", "merge_chain", "source_ref", "visibility",
)

MEMORY_CANDIDATES_COLUMNS: tuple[str, ...] = (
    "id", "user_id", "character_id", "content", "proposed_type", "source", "source_ref",
    "source_table", "source_id", "salience", "status", "reason", "visibility", "created_at",
)

MEMORY_TYPE_DOMAIN: tuple[str, ...] = (
    # 词表收窄声明（2026-10-16，MEV-015）：`important_event` / `relationship_event` 退役，
    # 存储词表 9 → 7 值（原元祖含这两项，位于 `user_fact` 之后）。
    "user_preference",
    "user_fact",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
)

from tests.support.schema_pins import (
    MIGRATION_HEAD,
    SCHEMA_TABLE_COUNT,
)

MIGRATION_COUNT = int(MIGRATION_HEAD)

TABLE_COUNT = SCHEMA_TABLE_COUNT

MEMORY_BRIDGE_LOGGER = "app.services.action.memory_bridge"


@pytest.fixture
def tool_memory_on(v24_tool_env, override_settings):
    """工具记忆子闸 + 行动通道双开（V2.4.0 总闸下的最小开启面）。"""
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_MEMORY_ENABLED=True)
    override_settings()
    yield


def _tool_record(tool_id: str, params: dict, **kwargs):
    return record(tool_id, params=params, **kwargs)


# --- §6.1 分流：普通结果零写入 / 重要结果落库 ---------------------------------


def test_read_only_tool_writes_zero_memories(db_session_factory, tool_memory_on):
    """普通结果（world.env.query）零记忆写入：世界事实的 SoT 是世界。"""
    assert (
        memory_bridge.deliver(
            _tool_record("world.env.query", {"dimension": "weather"}), USER
        )
        is None
    )
    assert memory_count(USER) == 0


def test_declined_world_mutation_writes_zero_memories(db_session_factory, tool_memory_on):
    assert (
        memory_bridge.deliver(
            _tool_record("world.object.move", {"object": "牛奶", "location": "冰箱"}), USER
        )
        is None
    )
    assert memory_bridge.deliver(_tool_record("world.object.use", OBJECT_PARAMS), USER) is None
    assert memory_count(USER) == 0


def test_important_result_invests_candidate_with_template_content(
    db_session_factory, tool_memory_on, override_settings
):
    """重要结果进候选并经 R1~R8 后投递，内容与模板一致；记忆由 v2 评估转正。"""
    override_settings(memory_importance_threshold=0.5)
    payload = memory_bridge.deliver(_tool_record("builtin.reminder.cancel", CANCEL_PARAMS), USER)
    assert payload is not None
    assert payload["content"] == "用户不想再被提醒：开会"
    rows = candidate_rows(USER)
    assert [row.content for row in rows] == ["用户不想再被提醒：开会"]
    assert rows[0].proposed_type == "experience"
    assert rows[0].salience == 0.5
    assert rows[0].source == "user_derived"
    assert rows[0].character_id == "asuna"
    assert memory_count(USER) == 0


def test_world_object_create_invests_as_user_preference(
    db_session_factory, tool_memory_on, override_settings
):
    override_settings(memory_importance_threshold=0.5)
    payload = memory_bridge.deliver(_tool_record("world.object.create", OBJECT_PARAMS), USER)
    assert payload is not None
    assert payload["content"] == "用户请我准备：牛奶"
    rows = [row for row in candidate_rows(USER) if row.id == payload["candidate_id"]]
    assert len(rows) == 1
    assert rows[0].proposed_type == "user_preference"
    assert rows[0].salience == 0.5


def test_reminder_create_candidate_passes_policy_and_lands(
    db_session_factory, tool_memory_on
):
    """P1-3：`builtin.reminder.create` 候选（0.7 / important_event）经 R1~R8 通过并落库。

    文案去掉未消解人称代词后，该工具的记忆通道不再恒定零产出（默认 0.6 阈值即可放行）。
    """
    rec = _tool_record("builtin.reminder.create", REMINDER_PARAMS)
    definition = tool_definition("builtin.reminder.create")
    candidates = tool_memory_policy.get_tool_memory_policy().to_candidates(rec, definition)
    assert [candidate.content for candidate in candidates] == ["用户请我提醒：开会"]
    assert candidates[0].importance == 0.7
    assert memory_policy.apply_policy(candidates).saved == candidates

    payload = memory_bridge.deliver(rec, USER)

    assert payload is not None
    assert payload["content"] == "用户请我提醒：开会"
    assert candidate_count(USER) == 1
    rows = candidate_rows(USER)
    assert rows[0].proposed_type == "experience"
    assert rows[0].salience == 0.7
    assert rows[0].source == "user_derived"


def test_candidate_with_unresolved_reference_is_rejected_by_r8(
    db_session_factory, tool_memory_on, caplog
):
    """R8 零豁免实测：候选内容含未消解指代（此处来自用户原文）→ 零落库。"""
    rec = _tool_record(
        "builtin.reminder.create", {"content": "它", "due_at": "2026-09-20T08:00:00"}
    )
    with caplog.at_level(logging.INFO, logger=MEMORY_BRIDGE_LOGGER):
        assert memory_bridge.deliver(rec, USER) is None
    assert "R8" in caplog.text
    assert candidate_count(USER) == 0


def test_one_off_content_is_rejected_by_r4(db_session_factory, tool_memory_on, caplog):
    rec = _tool_record(
        "builtin.reminder.create", {"content": "今天开会", "due_at": "2026-09-20T08:00:00"}
    )
    with caplog.at_level(logging.INFO, logger=MEMORY_BRIDGE_LOGGER):
        assert memory_bridge.deliver(rec, USER) is None
    assert "R4" in caplog.text
    assert candidate_count(USER) == 0


def test_unresolved_reference_is_rejected_by_r8(
    db_session_factory, tool_memory_on, override_settings, caplog
):
    override_settings(memory_importance_threshold=0.5)
    rec = _tool_record("world.object.create", {"object": "它"})
    with caplog.at_level(logging.INFO, logger=MEMORY_BRIDGE_LOGGER):
        assert memory_bridge.deliver(rec, USER) is None
    assert "R8" in caplog.text
    assert candidate_count(USER) == 0


# --- §6.2 政策零豁免、幂等与路由 ----------------------------------------------


def test_policy_gate_is_always_invoked(db_session_factory, tool_memory_on, monkeypatch):
    seen: list[list[MemoryCandidate]] = []
    original = memory_policy.apply_policy

    def _spy(candidates, active_contents=None):
        seen.append(list(candidates))
        return original(candidates, active_contents)

    monkeypatch.setattr(memory_policy, "apply_policy", _spy)
    memory_bridge.deliver(_tool_record("builtin.reminder.create", REMINDER_PARAMS), USER)
    assert len(seen) == 1
    assert [candidate.content for candidate in seen[0]] == ["用户请我提醒：开会"]


def test_policy_rejection_is_discarded_and_logged(
    db_session_factory, tool_memory_on, caplog
):
    """E7：R1~R8 拒绝 → 丢弃并记日志；工具执行状态不变。

    负例改由用户原文带未消解指代触发（P1-3 后模板本身已不含 R8 触发词）。
    """
    rec = _tool_record(
        "builtin.reminder.create", {"content": "那个", "due_at": "2026-09-20T08:00:00"}
    )
    with caplog.at_level(logging.INFO, logger=MEMORY_BRIDGE_LOGGER):
        payload = memory_bridge.deliver(rec, USER)
    assert payload is None
    assert candidate_count(USER) == 0
    assert rec.status == "succeeded"
    assert "已丢弃" in caplog.text
    assert "R8" in caplog.text


def test_delivery_is_idempotent_via_memory_effect(db_session_factory, tool_memory_on, override_settings):
    override_settings(memory_importance_threshold=0.5)
    rec = _tool_record("builtin.reminder.cancel", CANCEL_PARAMS)
    first = memory_bridge.deliver(rec, USER)
    assert first is not None
    rec.result = {
        "status": "succeeded",
        "effects": [{"kind": "memory", "ref": first["candidate_id"], "detail": "已记住"}],
    }
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 1


def test_integrate_result_registers_memory_effect_for_idempotency(
    db_session_factory, tool_memory_on, override_settings
):
    override_settings(memory_importance_threshold=0.5)
    rec = _tool_record("builtin.reminder.cancel", CANCEL_PARAMS)
    action_engine.integrate_result(rec, ActionResult(status="succeeded", effects=[]))
    assert candidate_count(USER) == 1
    assert [effect["kind"] for effect in rec.result["effects"]] == ["memory"]
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 1


def test_integrate_result_flag_on_uses_generalized_path(
    db_session_factory, tool_memory_on, monkeypatch
):
    calls: list[tuple] = []
    original = memory_bridge.deliver

    def _spy(record_, user_id, character_id="asuna"):
        calls.append((record_.id, user_id, character_id))
        return original(record_, user_id, character_id)

    monkeypatch.setattr(memory_bridge, "deliver", _spy)
    # legacy 直写路径已物理删除（memory 域清理），静态守卫防复活
    assert not hasattr(memory_bridge, "deliver_action_memory")
    rec = _tool_record("builtin.reminder.cancel", CANCEL_PARAMS)
    action_engine.integrate_result(rec, ActionResult(status="succeeded", effects=[]))
    assert calls == [(rec.id, USER, "asuna")]


def test_delivery_failure_does_not_rollback_tool_execution(
    db_session_factory, tool_memory_on, override_settings, monkeypatch
):
    override_settings(memory_importance_threshold=0.5)

    def _boom(*args, **kwargs):
        raise RuntimeError("候选投递通道不可用")

    monkeypatch.setattr(memory_ingest, "create_candidate", _boom)
    rec = _tool_record("builtin.reminder.cancel", CANCEL_PARAMS)
    action_engine.integrate_result(rec, ActionResult(status="succeeded", effects=[]))
    assert rec.status == "succeeded"
    assert rec.result["status"] == "succeeded"
    assert candidate_count(USER) == 0
    assert memory_count(USER) == 0


def test_tool_channel_and_world_channel_are_independent(
    db_session_factory, tool_memory_on, override_settings
):
    """两条通道各走各的幂等标记：`memory_materialized` 与 `effects.kind == "memory"`。

    通道收敛第 3 批：两通道终点均为 v2 候选，且世界通道与 v2 补扫经
    `(world_events, event.id)` 候选键收敛为同一行。
    """
    override_settings(memory_importance_threshold=0.5)
    event = world_engine.create_event(
        USER, "meeting", "项目评审", "high", datetime(2026, 9, 20, 9, 0, 0), "user_mention"
    )
    assert event is not None
    assert world_memory_bridge.materialize_event_memory(event, USER) is True
    assert world_memory_bridge.materialize_event_memory(event, USER) is False
    assert candidate_count(USER) == 1
    world_contents = candidate_contents(USER)

    rec = _tool_record("builtin.reminder.cancel", CANCEL_PARAMS)
    payload = memory_bridge.deliver(rec, USER)
    assert payload is not None
    assert candidate_count(USER) == 2
    assert sorted(candidate_contents(USER)) == sorted([*world_contents, payload["content"]])

    rec.result = {
        "status": "succeeded",
        "effects": [{"kind": "memory", "ref": payload["candidate_id"], "detail": "已记住"}],
    }
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 2

    second = world_engine.create_event(
        USER, "trip", "出差", "high", datetime(2026, 9, 25, 9, 0, 0), "user_mention"
    )
    assert second is not None
    assert world_memory_bridge.materialize_event_memory(second, USER) is True
    assert candidate_count(USER) == 3


# --- §6.3 边界用例 ------------------------------------------------------------


def test_unknown_tool_id_deposits_nothing(db_session_factory, tool_memory_on):
    """E1：边界表无该 tool_id 行 → deposit=False，不沉淀、不报错。"""
    rec = _tool_record("builtin.unknown.tool", {"content": "开会"})
    decision = tool_memory_policy.get_tool_memory_policy().classify(rec, None)
    assert decision.deposit is False
    assert decision.reason == tool_memory_policy.REASON_NO_POLICY_ROW
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 0


def test_missing_template_param_deposits_nothing(db_session_factory, tool_memory_on):
    """E2：渲染缺参 → 空串 → 跳过沉淀（不写半成品内容）。"""
    assert memory_bridge.deliver(_tool_record("builtin.reminder.create", {}), USER) is None
    assert candidate_count(USER) == 0


def test_failed_with_gate_reason_deposits_nothing(db_session_factory, tool_memory_on):
    """E3：未执行（denied / invalid / unavailable / pending_confirmation）零沉淀。"""
    for status, gate_reason in (
        ("failed", "permission_denied"),
        ("cancelled", "invalid_params"),
        ("cancelled", "capability_unavailable"),
        ("planned", "pending_confirmation"),
    ):
        rec = _tool_record(
            "builtin.reminder.cancel", CANCEL_PARAMS, status=status, gate_reason=gate_reason
        )
        assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 0


def test_timeout_deposits_unfinished_semantics(db_session_factory, tool_memory_on):
    """E4：timeout 属真失败，沉淀带未完成语义。"""
    rec = _tool_record(
        "builtin.reminder.cancel", CANCEL_PARAMS, status="failed", failure_kind="timeout"
    )
    payload = memory_bridge.deliver(rec, USER)
    assert payload is not None
    assert payload["content"] == "上次没能帮用户完成：用户不想再被提醒：开会"
    rows = [row for row in candidate_rows(USER) if row.id == payload["candidate_id"]]
    assert len(rows) == 1
    assert rows[0].proposed_type == "experience"
    assert rows[0].salience >= 0.6


def test_memory_save_tool_never_double_delivers(db_session_factory, tool_memory_on):
    """E5：`builtin.memory.save` 直通，投递返回 None（避免二次投递）。"""
    rec = _tool_record("builtin.memory.save", {"fact": "我喜欢抹茶"})
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 0


def test_retry_delivers_only_at_terminal_state(
    db_session_factory, tool_memory_on, override_settings
):
    """E6：先 failed 后 succeeded 的同一 action 只在终态投递一次。"""
    override_settings(memory_importance_threshold=0.5)
    rec = _tool_record(
        "builtin.reminder.cancel", CANCEL_PARAMS, status="executing", attempt=2
    )
    action_engine.integrate_result(rec, ActionResult(status="failed", effects=[]))
    assert candidate_count(USER) == 0

    rec.status = "succeeded"
    action_engine.integrate_result(rec, ActionResult(status="succeeded", effects=[]))
    assert candidate_count(USER) == 1

    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 1


def test_untrusted_namespace_tool_deposits_nothing(db_session_factory, tool_memory_on):
    """E10：`ext.api.*` 硬纪律优先（配置不可违背）→ 仍不沉淀。"""
    rec = _tool_record("ext.api.weather.current", {"dimension": "weather"})
    assert memory_bridge.deliver(rec, USER) is None
    assert candidate_count(USER) == 0


def test_pending_confirmation_then_confirmed_deposits(
    db_session_factory, tool_memory_on, override_settings
):
    """E12：确认未完成不沉淀；确认后成功轮次才沉淀。"""
    override_settings(memory_importance_threshold=0.5)
    rec = _tool_record(
        "builtin.reminder.cancel",
        CANCEL_PARAMS,
        status="planned",
        gate_reason="pending_confirmation",
    )
    assert memory_bridge.deliver(rec, USER) is None
    rec.status = "succeeded"
    rec.gate_reason = None
    assert memory_bridge.deliver(rec, USER) is not None
    assert candidate_count(USER) == 1


def test_extraction_and_tool_delivery_are_parallel(
    db_session_factory, tool_memory_on, override_settings
):
    """E13：同轮内工具沉淀与对话抽取各自独立经 R1~R8，互不影响。"""
    override_settings(memory_importance_threshold=0.5)
    rejected = MemoryCandidate(
        action="save",
        type="user_fact",
        content="用户喜欢抹茶",
        importance=0.9,
        confidence=0.9,
        source="ai_inferred",
    )
    assert memory_policy.apply_policy([rejected]).saved == []

    payload = memory_bridge.deliver(_tool_record("builtin.reminder.cancel", CANCEL_PARAMS), USER)
    assert payload is not None
    assert candidate_count(USER) == 1

    accepted = MemoryCandidate(
        action="save",
        type="user_fact",
        content="用户喜欢抹茶",
        importance=0.9,
        confidence=0.9,
        source="user_stated",
    )
    report = memory_policy.apply_policy([accepted])
    assert [candidate.content for candidate in report.saved] == ["用户喜欢抹茶"]
    memory_repository.create_memory(
        USER,
        "asuna",
        content=accepted.content or "",
        memory_type=accepted.type,
        importance=accepted.importance,
        confidence=accepted.confidence,
        source=accepted.source,
    )
    assert memory_count(USER) == 1


# --- 冻结面：零迁移 / 零表改动 / 零 diff --------------------------------------


@pytest.mark.parametrize("relative,digest", sorted(FROZEN_SOURCES.items()))
def test_frozen_sources_have_zero_diff(relative, digest):
    """零 diff 冻结：比对前做**行尾归一（LF）**，CRLF 检出不应造成假失败（P2-4）。

    实际/期望摘要均在失败信息中呈现（T-24），便于区分「本次改坏」与「常量旧账」。
    """
    assert_frozen(relative, expected=digest, actual=file_digest(relative))


def test_memory_tables_unchanged():
    assert tuple(column.name for column in Base.metadata.tables["memories"].columns) == MEMORIES_COLUMNS
    assert (
        tuple(column.name for column in Base.metadata.tables["memory_candidates"].columns)
        == MEMORY_CANDIDATES_COLUMNS
    )


def test_memory_type_domain_unchanged():
    assert tuple(MemoryType.__args__) == MEMORY_TYPE_DOMAIN


def test_no_new_tables_in_metadata():
    """本任务交付时零新建表；后续版本新增的表由 v24 的 MIGRATION_ADDED_VS_BASELINE 登记。"""
    assert len(Base.metadata.tables) == TABLE_COUNT


def test_no_new_migrations():
    versions = sorted((BACKEND_ROOT / "migrations" / "versions").glob("*.py"))
    assert len(versions) == MIGRATION_COUNT


def test_memory_bridge_has_no_own_policy_table():
    """边界表唯一权威在 `services/tool/memory_policy.py`：桥只做泛化查询与投递。"""
    source = (BACKEND_ROOT / "app/services/action/memory_bridge.py").read_text(encoding="utf-8")
    assert "ACTION_MEMORY_TEMPLATES" in source
    assert "TOOL_MEMORY_TEMPLATES" not in source
    assert "BOUNDARY_TABLE" not in source
    assert "builtin.reminder.create" not in source
    assert "world.object.create" not in source
