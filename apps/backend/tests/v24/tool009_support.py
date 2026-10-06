"""TOOL-009 单测共享构造：工具执行记录（action_records 投影）、用户消息、Insight 与注册表快照。"""

import dataclasses
import json
from datetime import datetime, timedelta
from typing import Any

from app.core import timeutil
from app.core.db import (
    ActionRecordRow,
    Conversation,
    EvidenceLinkRow,
    InsightRow,
    Message,
)
from app.models.reflection import (
    EVIDENCE_CHANNEL_TOOL,
    EvidenceMember,
    EvidenceWindow,
    InsightDraft,
    ReflectionProposal,
    WindowStats,
)

USER = "u-tool009"
OTHER_USER = "u-tool009-other"
CHARACTER = "asuna"
SESSION = "conv-tool009"

TOOL_WEATHER = "ext.api.weather.current"
TOOL_REMINDER = "builtin.reminder.create"
TOOL_SEARCH = "builtin.search.query"

ACTION_TYPE_BY_TOOL: dict[str, str] = {
    TOOL_WEATHER: "query_environment",
    TOOL_REMINDER: "create_reminder",
    TOOL_SEARCH: "query_search",
}

SESSION_ID = SESSION


class StubTrace:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, name, duration_ms, status="ok", **extra) -> None:
        self.steps.append({"name": name, "status": status, **extra})


class ScriptedLLM:
    """确定性结构化 stub：按调用次序返回 proposal 或抛错（含调用计数）。"""

    def __init__(self, proposals=None, errors=None) -> None:
        self.proposals = list(proposals or [])
        self.errors = list(errors or [])
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        def _resolve(inputs):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            if self.proposals:
                item = self.proposals.pop(0)
                return (
                    item
                    if isinstance(item, ReflectionProposal)
                    else schema.model_validate(item)
                )
            return ReflectionProposal(insights=[])

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(_resolve)

    def __call__(self, *args, **kwargs):
        return self


def tool_step(
    tool_id: str,
    *,
    status: str = "succeeded",
    failure_kind: str | None = None,
    observations: dict | None = None,
    index: int = 0,
) -> dict:
    result: dict[str, Any] = {
        "status": status,
        "effects": [],
        "observations": dict(observations or {}),
    }
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return {
        "index": index,
        "capability": tool_id.split(".")[0],
        "action": "run",
        "params": {},
        "status": "succeeded" if status == "succeeded" else "failed",
        "result": result,
        "tool_id": tool_id,
        "permission": {},
        "validation": None,
        "duration_ms": 1,
    }


def tool_record(
    tool_id: str,
    *,
    record_id: str,
    user_id: str = USER,
    status: str = "succeeded",
    failure_kind: str | None = None,
    action_type: str | None = None,
    source: str = "conversation",
    session_id: str | None = SESSION,
    target_record_id: str | None = None,
    observed_at: datetime | None = None,
    observations: dict | None = None,
) -> ActionRecordRow:
    """`action_records` 行：`steps[].result` 携带 ToolResult 契约（TOOL-003 写入面）。"""
    at = observed_at or timeutil.now()
    return ActionRecordRow(
        id=record_id,
        user_id=user_id,
        character_id=CHARACTER,
        session_id=session_id,
        source=source,
        action_type=action_type or ACTION_TYPE_BY_TOOL.get(tool_id, "create_reminder"),
        intent={},
        target_record_id=target_record_id,
        dedupe_key="",
        params={},
        status=status,
        gate_reason=None,
        steps=[
            tool_step(
                tool_id, status=status, failure_kind=failure_kind, observations=observations
            )
        ],
        result=None,
        attempt=1,
        created_at=at,
        updated_at=at,
        executed_at=at,
    )


def seed_record(session_factory, record: ActionRecordRow) -> ActionRecordRow:
    with session_factory() as session:
        session.add(record)
        session.commit()
    return record


def seed_tool_series(
    session_factory,
    *,
    tool_id: str,
    count: int,
    user_id: str = USER,
    status: str = "failed",
    failure_kind: str | None = "transient",
    action_type: str | None = None,
    source: str = "conversation",
    session_id: str | None = SESSION,
    now: datetime | None = None,
    step_hours: float = 12.0,
    record_prefix: str = "act009",
    target_record_id: str | None = None,
) -> list[ActionRecordRow]:
    """等间隔铺 `count` 条同类工具执行（默认跨 24h 以上，满足时间跨度门槛）。"""
    now = now or timeutil.now()
    records = []
    for index in range(count):
        at = now - timedelta(hours=step_hours * (count - index))
        records.append(
            seed_record(
                session_factory,
                tool_record(
                    tool_id,
                    record_id=f"{record_prefix}-{tool_id}-{index}",
                    user_id=user_id,
                    status=status,
                    failure_kind=failure_kind,
                    action_type=action_type,
                    source=source,
                    session_id=session_id,
                    observed_at=at,
                    target_record_id=target_record_id,
                ),
            )
        )
    return records


def seed_human_message(
    session_factory,
    content: str,
    *,
    created_at: datetime,
    conversation_id: str = SESSION,
) -> None:
    with session_factory() as session:
        if session.get(Conversation, conversation_id) is None:
            session.add(
                Conversation(
                    id=conversation_id,
                    session_id=conversation_id,
                    user_id=USER,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        session.add(
            Message(
                id=ids.new_id(),
                conversation_id=conversation_id,
                role="human",
                content=content,
                is_proactive=False,
                created_at=created_at,
            )
        )
        session.commit()


from app.core import ids
from app.core.db import Conversation as _Conversation  # noqa: E402  (循环规避：仅测试构造用)


def seed_insight(
    session_factory,
    insight_id: str,
    *,
    insight_type: str,
    statement: str = "最近天气接口不稳定",
    confidence: float = 0.8,
    scope: str = "world",
    user_id: str = USER,
    tool_ids: tuple[str, ...] = (TOOL_WEATHER,),
    created_at: datetime | None = None,
) -> str:
    """Insight + 工具证据链（`evidence_links.memory_id` 用 `tool:<tool_id>:...` 命名空间）。"""
    at = created_at or timeutil.now()
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                character_id=CHARACTER,
                statement=statement,
                type=insight_type,
                confidence=confidence,
                scope=scope,
                status="active",
                run_id=None,
                created_at=at,
                updated_at=at,
            )
        )
        for index, tool_id in enumerate(tool_ids):
            session.add(
                EvidenceLinkRow(
                    id=f"evl-{insight_id}-{index}",
                    insight_id=insight_id,
                    memory_id=f"tool:{tool_id}:act-{index}:0",
                    weight=0.5,
                    created_at=at,
                )
            )
        session.commit()
    return insight_id


def tool_capability_proposal(
    *,
    statement: str = "最近天气接口不稳定，先别急着查",
    insight_type: str = "capability_note",
    scope: str = "world",
    evidence_ids: tuple[str, ...] = ("E1", "E2", "E3"),
    counter_evidence: str = "失败集中在同一时段，不足以说明长期不可靠",
) -> ReflectionProposal:
    return ReflectionProposal(
        insights=[
            InsightDraft(
                statement=statement,
                type=insight_type,
                scope=scope,
                evidence_ids=list(evidence_ids),
                counter_evidence=counter_evidence,
                self_confidence=0.8,
            )
        ]
    )


def memory_window(
    *,
    member_count: int = 3,
    coherence: float = 1.0,
    span_hours: float = 48.0,
    topic: str = "用户说最近加班很累",
):
    """既有（记忆）证据窗替身：仅用于聚合对照，不落库。"""
    members = [
        EvidenceMember(
            memory_id=f"mem009-{index}",
            content=f"{topic}（第 {index + 1} 次）",
            created_at=timeutil.ensure_aware(datetime(2026, 9, 1, 9, 0, 0)) + timedelta(hours=index * 12),
            source="user_stated",
            source_ref=f"conv:u:s:mem009-{index}",
            salience=0.8,
            weight=0.7,
        )
        for index in range(member_count)
    ]
    return EvidenceWindow(
        topic_digest=topic,
        members=members,
        stats=WindowStats(
            member_count=member_count,
            span_hours=span_hours,
            distinct_source_refs=member_count,
            coherence=coherence,
        ),
    )


def registry_snapshot(registry) -> str:
    """注册表只读快照（健康度 + 工具面投影），用于隔离断言的逐字节对照。"""
    health = {
        tool_id: record.model_dump(mode="json")
        for tool_id, record in registry.health().items()
    }
    describe = [dataclasses.asdict(item) for item in registry.describe()]
    statuses = {item["tool_id"]: item["status"] for item in describe}
    return json.dumps(
        {"health": health, "describe": describe, "statuses": statuses},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def tool_channel_marker() -> str:
    return EVIDENCE_CHANNEL_TOOL


def tool_evidence_window(
    *,
    window_kind: str = "action_success_rate",
    group_key: str = TOOL_WEATHER,
    member_count: int = 3,
    now: datetime | None = None,
    group_kind: str = "tool_id",
) -> object:
    """手工工具证据窗（触发侧单测用；字段形态与聚合器产出一致）。"""
    from app.character.asuna import evaluation as asuna_evaluation
    from app.models.reflection import (
        TOOL_EVIDENCE_KIND,
        EvidenceMember,
        ToolEvidenceWindow,
        WindowStats,
    )

    at = now or timeutil.ensure_aware(datetime(2026, 9, 14, 12, 0, 0))
    members = [
        EvidenceMember(
            memory_id=f"tool:{group_key}:act-fake-{index}:0",
            content=f"工具 {group_key} 执行失败（第 {index + 1} 次）",
            created_at=at - timedelta(hours=13 * (member_count - index)),
            source="tool_execution",
            source_ref=f"tool:{group_key}:act-fake-{index}:0",
            salience=0.8,
            weight=0.7,
        )
        for index in range(member_count)
    ]
    return ToolEvidenceWindow(
        topic_digest=f"工具效能：{group_key}（{window_kind}）",
        members=members,
        stats=WindowStats(
            member_count=member_count,
            span_hours=13.0 * max(member_count - 1, 0),
            distinct_source_refs=member_count,
            source_type_mix={"tool_execution": member_count},
            coherence=1.0,
        ),
        kind=TOOL_EVIDENCE_KIND,
        window_kind=window_kind,
        group_key=group_key,
        insight_types=asuna_evaluation.allowed_insight_types(window_kind),
    )


def fake_tool_package(windows: list, *, executions: int | None = None) -> object:
    """工具证据包替身（触发侧单测用；`tool_windows` 供 evidence_summary 落库）。"""
    from app.services.reflection.evidence import ToolEvidencePackage

    tool_windows: dict[str, dict] = {}
    for window in windows:
        tool_windows.setdefault(window.window_kind, {})[window.group_key] = {
            "group_kind": "tool_id",
            "group_key": window.group_key,
            "executions": window.stats.member_count,
            "failed": window.stats.member_count,
            "span_hours": window.stats.span_hours,
        }
    return ToolEvidencePackage(
        tool_windows=tool_windows,
        windows=list(windows),
        passing=len(windows),
        executions=executions if executions is not None else sum(
            window.stats.member_count for window in windows
        ),
    )


__all__ = [
    "ACTION_TYPE_BY_TOOL",
    "CHARACTER",
    "OTHER_USER",
    "SESSION",
    "SESSION_ID",
    "ScriptedLLM",
    "StubTrace",
    "TOOL_REMINDER",
    "TOOL_SEARCH",
    "TOOL_WEATHER",
    "USER",
    "fake_tool_package",
    "memory_window",
    "registry_snapshot",
    "seed_human_message",
    "seed_insight",
    "seed_record",
    "seed_tool_series",
    "tool_capability_proposal",
    "tool_channel_marker",
    "tool_evidence_window",
    "tool_record",
    "tool_step",
]
