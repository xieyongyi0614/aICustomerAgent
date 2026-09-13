"""Profile Registry（AGENT-001 §5.3）：三种 Run Profile 的唯一声明处。

新 Profile 只能在这里声明（阶段序列 / LLM capable / critical / 预算档），
禁止在编排代码里另开阶段序列——「无第二套 Agent Pipeline」的架构落点。
"""

from dataclasses import dataclass

from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
)


@dataclass(frozen=True)
class ProfileSpec:
    run_kind: str
    budget_tier: str
    stages: tuple[str, ...]
    llm_capable: frozenset[str]
    critical: frozenset[str]


_PROFILE_TABLE: dict[str, ProfileSpec] = {
    RUN_KIND_FOREGROUND_CHAT: ProfileSpec(
        run_kind=RUN_KIND_FOREGROUND_CHAT,
        budget_tier="foreground",
        stages=(
            "perception",
            "context_assembly",
            "turn_decisions",
            "mode_stabilize",
            "scene_resolve",
            "behavior_resolve",
            "reply_generation",
            "record_handoff",
        ),
        llm_capable=frozenset({"turn_decisions", "reply_generation"}),
        critical=frozenset({"reply_generation"}),
    ),
    RUN_KIND_AUTONOMOUS_TICK: ProfileSpec(
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        budget_tier="background",
        stages=(
            "perception",
            "state_update",
            "goal_check",
            "goal_supply",
            "goal_advance",
            "memory_retrieval",
            "reflection_check",
            "decision",
            "world_experience",
        ),
        llm_capable=frozenset({"decision"}),
        critical=frozenset({"decision"}),
    ),
    RUN_KIND_EVENT_DRIVEN: ProfileSpec(
        run_kind=RUN_KIND_EVENT_DRIVEN,
        budget_tier="event",
        stages=("event_pregate",),
        llm_capable=frozenset(),
        critical=frozenset(),
    ),
}


def get_profile(run_kind: str) -> ProfileSpec:
    try:
        return _PROFILE_TABLE[run_kind]
    except KeyError as exc:
        raise ValueError(f"未注册的 run_kind：{run_kind}") from exc


def snapshot_profile(run_kind: str) -> dict:
    spec = get_profile(run_kind)
    return {
        "run_kind": spec.run_kind,
        "budget_tier": spec.budget_tier,
        "stages": list(spec.stages),
        "llm_capable": sorted(spec.llm_capable),
        "critical": sorted(spec.critical),
    }
