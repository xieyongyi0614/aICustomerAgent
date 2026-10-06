"""PLAN-010 单测共享构造：计划证据事实 / 计划域台账 / 监听器探针。

只做构造与探测，不做断言（与 `plan004_support.py` ~ `plan009_support.py` 同款纪律）。四条纪律：

1. **证据事实按 §4.2.1 三窗表构造**：成功率（`goal_plans` 步终态 × 目标类型）/ 失败模式
   （`action_records.steps` 的 tool_id × failure_kind）/ 判据可判定性（`sub_goals` 的
   判据类型 × 不可判定占比）——用例只做「事实 → 窗口」对照，不另立判据。
2. **复用既有写面**：目标 / 计划经 `goal_repository` 既有函数落库，台账经
   `action_repository.save_record`；证据 id 一律由 `PLAN_STEP_DEDUPE_KEY_TEMPLATE` 渲染
   （零硬编码形态）。
3. **探针不改语义**：入队探针 / LLM 探针 / 注册表快照只记录与透传，判定逻辑一行未改。
4. **静态扫描复用**：扫描器与 PLAN-001 ~ PLAN-009 同源（`tests/v25/_plan_scan.py`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.models.action import ActionRecord
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE
from app.models.reflection import EVIDENCE_CHANNEL_PLAN
from app.repositories import action_repository, goal_repository
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import triggers

from . import _plan_scan as scan

NOW = timeutil.ensure_aware(datetime(2026, 9, 16, 12, 0, 0))
USER = "plan10-user"
OTHER_USER = "plan10-other-user"
CHARACTER = "asuna"

TOOL_WEATHER = "world.env.query"
TOOL_REMINDER = "builtin.reminder.create"

GOAL_DOMAINS = ("personal", "relationship", "world")

STRUCTURE_STEP_HOURS = 30.0
ACTION_STEP_HOURS = 30.0


class StubTrace:
    """`trace.record(name, duration, status, **extra)` 的最小记录器（与 TOOL-009 同款）。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, name, duration_ms, status="ok", **extra) -> None:
        self.steps.append({"name": name, "status": status, **extra})

    @property
    def names(self) -> list[str]:
        return [step["name"] for step in self.steps]


class EnqueueProbe:
    """唯一动作探针：记录 `enqueue_planning` 的调用参数与返回值（不改语义）。"""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.result = result

    def __call__(self, user_id, goal_id, trigger):
        self.calls.append((user_id, goal_id, trigger))
        return self.result


class LLMProbe:
    """LLM 面探针：任何构建调用都会记数（零 LLM 断言的可判定形式）。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("证据不足时不得触达 LLM 面")


def install_llm_probe(monkeypatch) -> LLMProbe:
    """把反思与规划的 LLM 链条构建换成探针（调用即失败）。"""
    from app.services.goal import planning as goal_planning
    from app.services.reflection import reflector

    probe = LLMProbe()
    monkeypatch.setattr(reflector, "build_structured_chain", probe)
    monkeypatch.setattr(goal_planning, "build_structured_chain", probe)
    return probe


def evidence_id(goal_id: str, version: int, index: int) -> str:
    return PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
        goal_id=goal_id, version=version, index=index
    )


def structure_step(
    index: int,
    *,
    status: str = "pending",
    criteria_type: str = "action_succeeded",
    attempt_count: int = 0,
    observed_at: datetime | None = None,
    tool_id: str = TOOL_REMINDER,
    capability: str = "create_reminder",
    on_failure: str = "skip",
) -> SubGoalSpec:
    """计划步骤（`sub_goals` 投影的输入）：`last_observed_at` 即「观测时效」事实。"""
    return SubGoalSpec.model_validate(
        {
            "index": index,
            "description": f"步骤{index}",
            "capability": capability,
            "params": {"content": "该休息了"},
            "criteria": {"type": criteria_type, "capability": capability},
            "tool_id": tool_id,
            "status": status,
            "attempt_count": attempt_count,
            "last_observed_at": observed_at,
            "on_failure": on_failure,
        }
    )


def seed_goal(
    *,
    user_id: str = USER,
    domain: str = "personal",
    layer: str = "long_term",
    description: str = "计划效能目标",
):
    """活跃层级目标（既有写面 `create_hierarchical_goal`，零改动）。"""
    return goal_repository.create_hierarchical_goal(
        user_id, layer, domain, description, 3
    )


def seed_plan(
    goal_id: str,
    specs: list[SubGoalSpec],
    *,
    version: int = 1,
    status: str = "active",
    at: datetime | None = None,
) -> GoalPlanRecord:
    moment = at or NOW
    return goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=list(specs),
            created_at=moment,
            updated_at=moment,
        )
    )


def seed_success_rate_series(
    *,
    user_id: str = USER,
    domain: str = "personal",
    done: int = 1,
    failed: int = 3,
    description: str = "面试准备计划",
):
    """窗口一场景：一份「4 步做不完」的计划（done + failed 步各若干，跨 24h 以上）。"""
    goal = seed_goal(user_id=user_id, domain=domain, description=description)
    specs = []
    index = 1
    for _ in range(done):
        specs.append(
            structure_step(
                index,
                status="done",
                observed_at=NOW - timedelta(hours=STRUCTURE_STEP_HOURS * index),
            )
        )
        index += 1
    for _ in range(failed):
        specs.append(
            structure_step(
                index,
                status="failed",
                attempt_count=2,
                observed_at=NOW - timedelta(hours=STRUCTURE_STEP_HOURS * index),
            )
        )
        index += 1
    plan = seed_plan(goal.id, specs)
    return goal, plan


def seed_criteria_series(
    *,
    user_id: str = USER,
    domain: str = "personal",
    undecided: int = 3,
    decided: int = 1,
    criteria_type: str = "field_equals",
    description: str = "判据太虚的计划",
):
    """窗口三场景：多步 `criteria_result=None`（`in_progress` + 零计数 + 已观测）。"""
    goal = seed_goal(user_id=user_id, domain=domain, description=description)
    specs = []
    index = 1
    for _ in range(undecided):
        specs.append(
            structure_step(
                index,
                status="in_progress",
                criteria_type=criteria_type,
                observed_at=NOW - timedelta(hours=STRUCTURE_STEP_HOURS * index),
            )
        )
        index += 1
    for _ in range(decided):
        specs.append(
            structure_step(
                index,
                status="done",
                criteria_type=criteria_type,
                observed_at=NOW - timedelta(hours=STRUCTURE_STEP_HOURS * index),
            )
        )
        index += 1
    plan = seed_plan(goal.id, specs)
    return goal, plan


def action_record(
    goal_id: str,
    *,
    version: int = 1,
    index: int = 1,
    record_id: str = "plan10-action",
    user_id: str = USER,
    tool_id: str = TOOL_WEATHER,
    capability: str = "query_environment",
    status: str = "failed",
    failure_kind: str | None = "timeout",
    at: datetime | None = None,
    dedupe_key: str | None = None,
) -> ActionRecord:
    """计划域台账行（`steps[0].result` 携带既有 ToolResult 契约）。"""
    moment = at or NOW
    result: dict = {"status": status, "effects": [], "observations": {}}
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return ActionRecord(
        id=record_id,
        user_id=user_id,
        character_id=CHARACTER,
        goal_id=goal_id,
        action_type=capability,
        status="succeeded" if status == "succeeded" else "failed",
        dedupe_key=(
            evidence_id(goal_id, version, index) if dedupe_key is None else dedupe_key
        ),
        params={},
        steps=[
            {
                "index": index,
                "capability": capability,
                "status": "succeeded" if status == "succeeded" else "failed",
                "tool_id": tool_id,
                "params": {},
                "result": result,
            }
        ],
        result=None,
        attempt=1,
        created_at=moment,
        updated_at=moment,
        executed_at=moment,
    )


def seed_action_series(
    *,
    goal_id: str,
    tool_id: str = TOOL_WEATHER,
    count: int = 3,
    failure_kind: str | None = "timeout",
    status: str = "failed",
    user_id: str = USER,
    step_hours: float = ACTION_STEP_HOURS,
    record_prefix: str = "plan10-act",
) -> list[ActionRecord]:
    """等间隔铺 `count` 条同类计划步骤执行（默认跨 24h 以上，满足跨度门槛）。"""
    records = []
    for position in range(count):
        at = NOW - timedelta(hours=step_hours * (count - position))
        records.append(
            action_repository.save_record(
                action_record(
                    goal_id,
                    index=position + 1,
                    record_id=f"{record_prefix}-{position}",
                    user_id=user_id,
                    tool_id=tool_id,
                    status=status,
                    failure_kind=failure_kind,
                    at=at,
                )
            )
        )
    return records


def plan_fact(**overrides) -> reflection_evidence.PlanStepFact:
    """`PlanStepFact` 构造器（注入式事实用例用；缺省即一条已完成的计划步）。"""
    payload = {
        "evidence_id": evidence_id("g-plan10", 1, 1),
        "goal_id": "g-plan10",
        "version": 1,
        "step_index": 1,
        "observed_at": NOW,
        "goal_type": "user_care",
        "plan_status": "active",
        "step_status": "done",
    }
    payload.update(overrides)
    return reflection_evidence.PlanStepFact(**payload)


def fact_series(
    *,
    count: int = 3,
    step_status: str = "done",
    goal_type: str = "user_care",
    tool_id: str | None = None,
    failure_kind: str | None = None,
    criteria_kind: str = "",
    undecided: bool = False,
    step_hours: float = STRUCTURE_STEP_HOURS,
) -> list[reflection_evidence.PlanStepFact]:
    """等间隔铺 `count` 条同类事实（默认跨 24h 以上，满足跨度门槛）。"""
    return [
        plan_fact(
            evidence_id=evidence_id("g-plan10", 1, position + 1),
            step_index=position + 1,
            observed_at=NOW - timedelta(hours=step_hours * (count - position)),
            step_status=step_status,
            goal_type=goal_type,
            tool_id=tool_id,
            failure_kind=failure_kind,
            criteria_kind=criteria_kind,
            undecided=undecided,
        )
        for position in range(count)
    ]


def insight_item(
    insight_id: str = "ins:plan10-1",
    *,
    insight_type: str = "capability_note",
    confidence: float = 0.75,
    scope: str = "user",
    statement: str = "这类计划 4 步做不完，实际两步就够",
) -> dict:
    """`notify_insight_created_listeners` 的 created 项（既有 reflector 的落库投影形态）。"""
    return {
        "insight_id": insight_id,
        "type": insight_type,
        "scope": scope,
        "confidence": confidence,
        "statement": statement,
    }


def listener_with_probe(*, settings=None, probe: EnqueueProbe | None = None):
    """带入队探针的监听器实例（`settings_provider` 可注入以固定门控）。"""
    from app.services.planning import revision_listener as listener_mod

    resolved_probe = probe or EnqueueProbe()
    listener = listener_mod.PlanningRevisionListener(
        enqueue=resolved_probe,
        settings_provider=(lambda: settings) if settings is not None else None,
    )
    return listener, resolved_probe


def registry_snapshot() -> str:
    """工具注册表只读快照（G-REFLECT 隔离断言的对照面：健康度 + 声明面逐字节）。"""
    import dataclasses
    import json

    from app.services.tool.registry import get_tool_registry

    registry = get_tool_registry()
    if registry is None:
        return ""
    health = {
        tool_id: record.model_dump(mode="json")
        for tool_id, record in registry.health().items()
    }
    describe = [dataclasses.asdict(item) for item in registry.describe()]
    return json.dumps(
        {"health": health, "describe": describe},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def runs(session_factory) -> list:
    from app.core.db import ReflectionRunRow

    with session_factory() as session:
        rows = session.query(ReflectionRunRow).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def insights(session_factory, *, user_id: str = USER) -> list:
    from app.core.db import InsightRow

    with session_factory() as session:
        rows = (
            session.query(InsightRow).filter(InsightRow.user_id == user_id).all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


def planning_jobs(session_factory) -> list:
    from app.services.goal import planning as goal_planning

    jobs = []
    with session_factory() as session:
        from app.core.db import BackgroundJobRow

        rows = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == goal_planning.JOB_TYPE_PLANNING)
            .all()
        )
        for row in rows:
            session.expunge(row)
            jobs.append(row)
    return jobs


def repo_root():
    return scan.REPO_ROOT


def module_path(name: str):
    return scan.PLANNING_PACKAGE_DIR / name


def code_text(path) -> str:
    return scan.code_text(path)


def plan_reflection_env(override_settings):
    """计划反思通道的基线环境（通道已随开关体系删除转常开，只钉世界与观测面）。"""
    override_settings()


@pytest.fixture
def plan_reflection_on(override_settings):
    """计划反思通道开启（证据通道 + 监听器）+ 触发态复位。"""
    from app.services.planning import revision_listener as listener_mod
    from app.services.reflection import lifecycle as reflection_lifecycle

    plan_reflection_env(override_settings)
    triggers.reset_trigger_state()
    reflection_lifecycle.reset_insight_created_listeners()
    listener_mod.reset_revision_state()
    yield
    triggers.reset_trigger_state()
    reflection_lifecycle.reset_insight_created_listeners()
    listener_mod.reset_revision_state()


@pytest.fixture
def listener(plan_reflection_on):
    """默认监听器（子闸已开）+ 探针。"""
    listener_mod = _listener_module()
    probe = EnqueueProbe()
    return listener_mod.PlanningRevisionListener(enqueue=probe), probe


def _listener_module():
    from app.services.planning import revision_listener as listener_mod

    return listener_mod


@dataclass(frozen=True)
class ListenerCase:
    """监听器用例的三门槛输入（负例与正例共用同一载体）。"""

    insight_type: str = "capability_note"
    confidence: float = 0.75
    scope: str = "user"


CHANNEL_PLAN = EVIDENCE_CHANNEL_PLAN

PLAN_SECTION_SYMBOLS = frozenset(
    {
        "PLAN_EVIDENCE_STEP_NAME",
        "PLAN_STEP_SOURCE",
        "PLAN_EVIDENCE_NAMESPACE",
        "PLAN_STEP_EVIDENCE_PREFIX",
        "GROUP_KIND_PLAN",
        "GROUP_KIND_STEP",
        "GROUP_KIND_CRITERIA",
        "PLAN_WINDOW_SUCCESS_RATE",
        "PLAN_WINDOW_STEP_FAILURE",
        "PLAN_WINDOW_CRITERIA_DECIDABILITY",
        "PLAN_WINDOW_KINDS",
        "PLAN_WINDOW_PRIORITY",
        "PLAN_WINDOW_ALLOWED_INSIGHTS",
        "PLAN_WINDOW_FAILURE_DRIVEN_KINDS",
        "STEP_STATUS_DONE",
        "STEP_STATUS_FAILED",
        "PLAN_STEP_STATUS_WORDS",
        "PLAN_WINDOW_LABELS",
        "PLAN_WINDOW_METRICS",
        "_UNKNOWN_GROUP_KEY",
        "plan_evidence_id",
        "plan_evidence_id_of",
        "plan_thresholds",
        "PlanStepFact",
        "PlanEvidencePackage",
        "aggregate_evidence_windows",
        "aggregate_plan_success_rate",
        "aggregate_step_failure_modes",
        "aggregate_criteria_decidability",
        "aggregate_plan_windows",
        "aggregate_plan_evidence",
        "build_plan_evidence_windows",
        "_plan_kind_priority",
        "_resolve_plan_facts",
        "_plan_facts",
        "_plan_structure_facts",
        "_plan_action_facts",
        "_criteria_kind",
        "_step_undecided",
        "_accumulate_plan_step_group",
        "_plan_window_members",
        "_plan_fact_in_group",
        "_plan_fact_content",
        "_build_plan_window",
        "_plan_trace",
    }
)


def plan_section_source(repo_root) -> str:
    """PLAN-010 计划通道的源码段（按符号 AST 抽取，evidence.py 拆包后语义等价物）。"""
    import ast as _ast

    pkg = repo_root / "app" / "services" / "reflection" / "evidence"
    parts = []
    for path in sorted(pkg.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = _ast.parse(source)
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.ClassDef)):
                name = node.name
            elif isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
                name = node.target.id
            elif isinstance(node, _ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, _ast.Name)]
                name = targets[0] if targets else None
            else:
                continue
            if name in PLAN_SECTION_SYMBOLS:
                parts.append(_ast.get_source_segment(source, node) or "")
    return chr(10).join(parts)
