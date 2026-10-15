"""TOOL-012 验收支撑：Flag 矩阵、V2.3.0 基线判据、静态扫描与场景装配。

基线口径（全部只读取自 git，不覆盖工作区）：
- 基线提交 `d67ebe7`（V2.2.0 收尾 + V2.3.0 全部落地，V2.4.0 文档提交 78854d5 的父提交）。
- 迁移文件数、文件 blob sha、ORM 列/约束/索引摘要均由该提交的 `git archive` 检出物算出，
  数值以常量形式冻结在本模块（详见 tests/v24/ACCEPTANCE-CHECKLIST.md 的"基线取证"节）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tests.support.schema_pins import (
    MIGRATION_HEAD,
    MIGRATION_HEAD_PARENT,
    SCHEMA_COLUMNS_DIGEST,
    SCHEMA_TABLE_COUNT,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
REPO_ROOT = BACKEND_ROOT.parents[1]

BASELINE_COMMIT = "d67ebe7"
BASELINE_LABEL = "V2.3.0"

AUX_FLAGS: tuple[str, ...] = (
    "FEISHU_ENABLED",
)
TOOL_PARAM_ENVS: dict[str, str] = {
    "TOOL_DISABLED_IDS": "",
    "TOOL_SURFACE_MAX_TOOLS": "12",
    "TOOL_BREAKER_THRESHOLD": "3",
    "TOOL_BREAKER_COOLDOWN_SECONDS": "300",
    "TOOL_CONFIRM_TIMEOUT_HOURS": "24",
    "TOOL_CONFIRM_TTL_REUSE": "true",
    "TOOL_AUDIT_RETENTION_DAYS": "180",
    "TOOL_EXT_MANIFEST_PATH": "",
    "TOOL_EXT_ALLOWED_HOSTS": "",
}
FEISHU_PLACEHOLDER_ENVS: dict[str, str] = {
    "FEISHU_APP_ID": "cli_tool012_test",
    "FEISHU_APP_SECRET": "tool012_test_secret",
    "FEISHU_VERIFICATION_TOKEN": "tool012_test_token",
}

BUILTIN_TOOL_COUNT = 13
BUILTIN_TOOL_IDS: tuple[str, ...] = (
    "builtin.ledger.query",
    "builtin.ledger.record",
    "builtin.ledger.revise",
    "builtin.memory.save",
    "builtin.notification.send",
    "builtin.reminder.cancel",
    "builtin.reminder.create",
    "builtin.search.query",
    "channel.feishu.send",
    "world.env.query",
    "world.object.create",
    "world.object.move",
    "world.object.use",
)

SQUASHED_MIGRATION_FILE = "0001_squashed_full_schema.py"

INCREMENTAL_MIGRATION_FILES: tuple[str, ...] = (
    "0002_briefing_preferences.py",
    "0003_car_domain.py",
    "0004_channel_identity_bindings.py",
    "0005_id_scheme_split.py",
    "0006_all_domains_utc_timestamps.py",
    "0007_ledger_entry_identity_split.py",
    "0008_ledger_categories_aliases_encoding.py",
    "0009_app_release_artifacts.py",
)

# 旧账同步声明（2026-10-15）：表集在 0002~0009 增量迁移期间合法增长后漏同步本摘要
# （HEAD 即红）；核对现表集 57 张与 `tests/support/schema_pins.py::SCHEMA_TABLE_COUNT`
# 一致后同步。原值 88d74b2e。
SCHEMA_TABLE_SET_DIGEST = "8704b2b571d513ce"
# ID 体系收敛声明（2026-10-03，ADR-16 阶段 D）：feishu 两台账表加雪花 id 主键、业务键转 UNIQUE —— 有意演进。
SCHEMA_COLUMNS_DIGEST_BASELINE = "10134443a5903a3f"
SCHEMA_ADDED_TABLES_VS_BASELINE: tuple[str, ...] = (
    "feishu_dedupe_ledger",
    "feishu_deliveries",
    "users",
    "ledger_accounts",
    "ledger_categories",
    "ledger_entries",
    "life_tasks",
    "briefing_preferences",
    "car_profiles",
    "car_loans",
    "car_service_records",
    "car_mileage_logs",
    "app_releases",
    "app_release_artifacts",
)
SCHEMA_INDEXES_CHANGED_TABLES: tuple[str, ...] = ("development_state",)
SCHEMA_CHECKS_DIGEST_BASELINE = "94ca6c7f046b3638"
SCHEMA_CHECKS_CHANGED_TABLES: tuple[str, ...] = ("insights", "development_changes")
BASELINE_TABLE_DIGESTS: dict[str, tuple[str, str, str]] = {
    "action_records": ("90f5e647f8f1d8a8", "fccaeb1aee8d6cba", "8a7a52790352b2d8"),
    # ID 体系收敛声明（2026-10-03，ADR-16 阶段 D）：conversations 加 session_id 业务键 +
    # 唯一索引（存量回填 = 旧 id，新会话 id 发雪花）；messages.id 自增 Integer → 雪花
    # BigInteger（autoincrement 关闭）—— 有意演进，非 TOOL-012 改脏。原值 ecfdeb39 / 5d424b72。
    "conversations": ("012ca73a3e21bafa", "18f3a52de812d1f3", "619fc3bee13003f0"),
    "conversation_summaries": ("dfb4a7f2e6b6ba3a", "e3b0c44298fc1c14", "e3b0c44298fc1c14"),
    "messages": ("859d319a9c244bfb", "28485ce6aa400d11", "80cc53e497c96a49"),
    "memory_candidates": ("2e5d80cbd4a5c8e5", "41df4f3ee6f0c7bc", "1152da1a25969f8a"),
    "memory_links": ("3d3ded6c6e54c04a", "283ca81681e4286f", "35da9fa6f9d0bbf0"),
    "memories": ("727a9d903fefaf06", "70aeda5a3b94d14f", "f548dcfb8ad1dc1a"),
    "outbox_events": ("d41598a8d9dd0a59", "a3d68da9b90a22f4", "37e2a34025bbdc06"),
    "trigger_registry": ("ab91ce9b9b46c0ce", "2abe4ba951c80f5e", "917152757e46a642"),
    "world_entities": ("911237899993c840", "1981fcf3f0fe94f6", "a0a707e89ac86a7a"),
    "world_events": ("3f80b1d6d02fbcad", "6be5466818ae881a", "eb3f5d93af571ed5"),
    "world_snapshots": ("cd3378bda5c2aa2f", "e3b0c44298fc1c14", "7fa2ed5fc8465330"),
    "worlds": ("afe8b4993121e952", "8f9151510eb82fd1", "dedd4af9dce523ea"),
}
MEMORY_TABLES: tuple[str, ...] = ("memories", "memory_candidates", "memory_links")
EVENT_TABLES: tuple[str, ...] = ("world_events", "outbox_events", "trigger_registry")
SESSION_TABLES: tuple[str, ...] = ("conversations", "conversation_summaries", "messages")
RUN_KIND_PROFILES: tuple[str, ...] = (
    "event_driven",
    "autonomous_tick",
    "foreground_chat",
)
UNTRUSTED_NAMESPACES: tuple[str, ...] = ("ext.api", "user")

_RUN_KIND_LITERAL_PATTERN = re.compile(
    r"""["']([a-z][a-z0-9_]*_(?:tick|driven|chat))["']"""
)
SCHEMA_FROZEN_TABLES: tuple[str, ...] = (
    "worlds",
    "world_entities",
    "world_events",
    "world_snapshots",
    "daily_plans",
    "user_situations",
    "action_records",
    "memories",
    "trigger_registry",
    "channel_identities",
    "conversations",
    "messages",
)

FROZEN_BLOB_SHA_BASELINE: dict[str, str] = {}
"""冻结面 blob sha1 基线（LF 归一，git 对象口径）——**当前为空**。

- `app/application/life_loop.py` 已撤下（P2-4）：P2-1 在它的 `has_due` 调用侧合法新增到期
  口径排除，整文件哈希会把正常演进判成违规；其语义面（维护步序列 / 无第二套确认清理路径）
  改由 `test_tool012_bans.test_ban_no_second_agent_stage_sequence_unchanged` 与
  `test_tool_acceptance.test_g_compat_life_loop_semantics_replacing_blob_freeze` 持有。
- `app/application/agent_runtime/profiles.py` 已撤下（P2-5）：V3.0 RT-006 按 Task Detail
  §6.2 合法扩展 `ProfileSpec`（新增 `optional_stages`，默认空集 = 行为不变）。整文件哈希
  会把该合法扩展判成「第二套 Agent」违规；其语义面（三 Profile 的 run_kind / stages /
  critical / llm_capable 逐元素不变）改由 `V9_PROFILE_SIGNATURES` 持有，比 blob 哈希
  更精确地命名了「什么不许变」。
"""

V9_PROFILE_SIGNATURES: dict[str, dict[str, tuple[str, ...]]] = {
    "foreground_chat": {
        "stages": (
            "perception",
            "context_assembly",
            "turn_decisions",
            "mode_stabilize",
            "scene_resolve",
            "behavior_resolve",
            "action_planning",
            "reply_generation",
            "record_handoff",
        ),
        "llm_capable": ("reply_generation", "turn_decisions"),
        "critical": ("reply_generation",),
    },
    "autonomous_tick": {
        "stages": (
            "perception",
            "state_update",
            "state_snapshot",
            "goal_check",
            "goal_stack",
            "goal_supply",
            "goal_advance",
            "memory_retrieval",
            "reflection_check",
            "decision",
            "world_experience",
        ),
        "llm_capable": ("decision",),
        "critical": ("decision",),
    },
    "event_driven": {
        "stages": ("event_pregate",),
        "llm_capable": (),
        "critical": (),
    },
}


def profile_signature(run_kind: str) -> dict[str, tuple[str, ...]]:
    """Profile 的语义签名（stages / llm_capable / critical），替代整文件 blob 冻结。"""
    from app.application.agent_runtime import profiles

    spec = profiles.get_profile(run_kind)
    return {
        "stages": tuple(spec.stages),
        "llm_capable": tuple(sorted(spec.llm_capable)),
        "critical": tuple(sorted(spec.critical)),
    }

LIFE_LOOP_MAINTENANCE_SEQUENCE: tuple[str, ...] = (
    "world_maintenance",
    "world_simulation",
    "action_retry",
    "action_schedule",
    "outbox_consume",
    "trigger_reconcile",
    "ledger_digest",
    "ledger_alert",
)

POST_PROCESS_STEP_SEQUENCE: tuple[str, ...] = (
    "run_scene_update",
    "run_state_update",
    "run_goal_review",
    "run_summary",
    "run_memory_extract",
    "run_ledger_extraction",
    "run_ledger_confirmation",
    "run_budget_observer",
    "run_evaluation",
    "run_world_update",
    "run_character_action_sync",
    "run_action_planning",
    # 通道收敛声明（2026-09-30，台账 §5.2）：新增收尾评估步（非 tool 域改脏）。
    "run_memory_evaluate",
)

V9_RUN_KINDS: tuple[str, ...] = ("foreground_chat", "autonomous_tick", "event_driven")

V9_STEP_KEYS: frozenset[str] = frozenset(
    {"index", "capability", "action", "params", "status", "result"}
)
V24_STEP_KEYS_ADDED: frozenset[str] = frozenset(
    {"tool_id", "permission", "validation", "duration_ms"}
)

LEGACY_REFLECTION_SYSTEM_PROMPT = """你是角色的反思引擎：从一组已沉淀的记忆证据中形成关于用户的认知（Insight）。

判定原则：
- 结论必须完全由给出的证据支撑，不得超出证据可支撑的范围（不要外推、不要脑补细节）。
- 每条候选结论必须引用支撑它的证据编号（evidence_ids），引用不存在的证据编号视为无效。
- 每条候选结论必须填写 counter_evidence 字段：说明「证据不支持什么」；确无反例时填「无」。
- type 取值：belief（对用户的具体看法）/ preference（稳定偏好）/ pattern（跨时间的重复模式）。
- scope 取值：user（关于用户本人）/ relationship（关于你们的关系）/ world（关于环境世界）。

只依据给出的证据组输出，不要臆造信息。"""

LEGACY_REFLECTION_USER_PROMPT = (
    "证据组（同一主题的时间窗聚合，共 2 条）：\n"
    "[E1] (2026-08-20 user_stated) 用户提到最近工作压力大，常常加班到很晚\n"
    "[E2] (2026-08-22 ai_inferred) 用户连续三天在深夜发消息，说自己睡不着\n\n"
    "请从以上证据形成候选 Insight（最多 3 条），每条包含 statement（陈述句）、"
    "type、scope、evidence_ids（引用 [E编号] 对应的成员 id）、"
    "counter_evidence（证据不支持什么，无反例填「无」）、self_confidence（0~1 自评，"
    "仅作参考，终值由系统按证据强度校准）。"
)

PROMPT_BASELINE_FILES: dict[str, str] = {
    "prompt_v1_default": "prompt_v1_default.txt",
    "prompt_v5_full": "prompt_v5_full.txt",
    "prompt_v6_full": "prompt_v6_full.txt",
    "prompt_v65_full": "prompt_v65_full.txt",
}

PRODUCTION_SCAN_ROOTS: tuple[Path, ...] = (
    APP_ROOT / "services" / "tool",
    APP_ROOT / "models" / "tool.py",
    APP_ROOT / "character" / "asuna" / "tool.py",
)

FORBIDDEN_TOOL_IMPORT_ROOTS: tuple[str, ...] = (
    "app.core.db",
    "sqlalchemy",
    "alembic",
)

FORBIDDEN_MODEL_IMPORT_ROOTS: tuple[str, ...] = (
    "app.repositories",
    "app.services",
    "app.application",
)

SECRET_NAME_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE_KEY)", re.I)

CREDENTIAL_ENV_NAME_PATTERN = re.compile(
    r"(SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY|API_KEY|ACCESS_KEY|APP_TOKEN"
    r"|VERIFICATION_TOKEN)",
    re.I,
)

PLACEHOLDER_SECRET_VALUES: frozenset[str] = frozenset(
    {"", "test", "fake", "stub", "none", "null", "changeme", "xxx", "placeholder"}
)


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    kind: str
    detail: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def render_acceptance_artifacts() -> dict[str, str]:
    """渲染验收用确定性产物（prompt 快照 + 反思 Prompt）。

    输入与 `tests/unit/test_prompt_golden.py`、V2.3.0 基线渲染脚本逐字段一致，
    因此产出的文本可与 V2.3.0 基线逐字节比较。
    """
    from app.character.asuna.behavior_instructions import BEHAVIOR_INSTRUCTIONS
    from app.models.behavior_strategy import (
        ActionBudget,
        BehaviorDirective,
        BehaviorStrategy,
        HabitRule,
    )
    from app.models.character_state import CharacterState
    from app.models.conversation import ChatMessage, ConversationState
    from app.models.emotion import TurnAnalysis
    from app.models.goal import GoalRecord
    from app.models.intention import ValidatedIntention
    from app.models.memory import UserMemory
    from app.models.reflection import EvidenceMember, EvidenceWindow, WindowStats
    from app.models.relationship import RelationshipState
    from app.models.scene import SceneContext, SceneState
    from app.prompts.builder import PromptBuilder
    from app.prompts.goal import GoalContext
    from app.prompts.reflection import build_reflection_messages
    from app.services.goal.service import SelectedGoal

    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
    base_state = ConversationState(
        session_id="golden",
        user_id="golden",
        messages=[
            ChatMessage(role="human", content="你好"),
            ChatMessage(role="ai", content="你好呀"),
            ChatMessage(role="human", content="今天做什么"),
        ],
        summary="此前聊过日常安排",
        memories=[],
        current_input="现在呢",
    )
    full_state = ConversationState(
        session_id="golden",
        user_id="golden",
        messages=[ChatMessage(role="human", content="我回来了")],
        summary="此前聊过日常安排",
        memories=[
            UserMemory(
                id="m1",
                user_id="golden",
                character_id="asuna",
                type="user_preference",
                content="用户喜欢西瓜",
                importance=0.9,
                confidence=0.95,
                source="user_stated",
                created_at=now,
                updated_at=now,
            )
        ],
        current_input="今天好累",
        character_state=CharacterState(
            mood="worried", intensity=0.65, cause="用户看起来疲惫", energy=0.5
        ),
        relationship_state=RelationshipState(
            intimacy=0.6, trust=0.6, familiarity=0.45, tension=0.55, stage="close_friend"
        ),
    )
    analysis = TurnAnalysis(
        user_emotion={"emotion": "tired", "event": "setback"},
        behavior={"behavior": "comfort", "reason": "用户疲惫"},
        emotion_event={
            "type": "worrying_news",
            "magnitude": "normal",
            "confidence": 0.85,
            "cause": "用户连日劳累",
        },
        relationship_event={
            "type": "user_care",
            "magnitude": "normal",
            "confidence": 0.8,
            "cause": "用户主动分享状态",
        },
    )
    scene_ctx = SceneContext(
        state=SceneState(
            session_id="golden",
            turn_id=5,
            location="客厅",
            current_activity="休息",
            current_action="倒水",
        ),
        intent="chat",
        directive=None,
    )
    goal = GoalRecord(
        id="g-1",
        user_id="golden",
        type="user_care",
        description="陪伴用户放松",
        priority=5,
        horizon="current",
        source="policy",
        created_turn=3,
        expires_at_turn=23,
        created_at=now,
        updated_at=now,
    )
    goal_ctx = GoalContext(
        selected_goal=SelectedGoal(
            goal=goal,
            reason="用户表达疲惫，user_care 目标提升",
            suppressed=["g-2"],
            suppressed_description="守护用户的身心状态",
        ),
        intention=ValidatedIntention(
            intention="comfort_user",
            reason="用户表达疲惫，选择安抚",
            goal_id="g-1",
            degraded=False,
        ),
    )
    behavior_ctx = BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="quiet_companion",
            base_strategy="quiet_companion",
            instruction="先安静地陪着，接住情绪；不急着给建议，问一句「想聊聊吗」就好。",
            mood_tone="低而稳的语气，不强行打气",
        ),
        budget=ActionBudget(max_action_desc=0),
        habits=[
            HabitRule(
                id="habit_question_bounded",
                domain="pace",
                priority=3,
                instruction="一次最多问一个问题，问完先等回答",
            )
        ],
        activity="ambient_activity",
        activity_text="倒水",
    )
    degraded = BehaviorDirective(
        strategy=BehaviorStrategy(
            strategy="natural_continuation",
            base_strategy="natural_continuation",
            degraded=True,
        ),
        budget=ActionBudget(),
        fallback_directive=BEHAVIOR_INSTRUCTIONS["comfort"],
    )
    window = EvidenceWindow(
        topic_digest="golden-topic",
        members=[
            EvidenceMember(
                memory_id="mem-1",
                content="用户提到最近工作压力大，常常加班到很晚",
                created_at=datetime(2026, 8, 20, 9, 30, 0),
                source="user_stated",
                source_ref="conv-1",
                salience=0.8,
                weight=0.9,
            ),
            EvidenceMember(
                memory_id="mem-2",
                content="用户连续三天在深夜发消息，说自己睡不着",
                created_at=datetime(2026, 8, 22, 23, 10, 0),
                source="ai_inferred",
                source_ref="conv-2",
                salience=0.6,
                weight=0.7,
            ),
        ],
        stats=WindowStats(
            member_count=2,
            span_hours=62.0,
            distinct_source_refs=2,
            source_type_mix={"user_stated": 1, "ai_inferred": 1},
            coherence=0.55,
        ),
    )
    reflection = build_reflection_messages(window)
    return {
        "prompt_v1_default": _render(PromptBuilder.build("default", base_state)),
        "prompt_v5_full": _render(
            PromptBuilder.build("immersive", full_state, analysis, scene_ctx=scene_ctx)
        ),
        "prompt_v6_full": _render(
            PromptBuilder.build(
                "immersive", full_state, analysis, scene_ctx=scene_ctx, goal_ctx=goal_ctx
            )
        ),
        "prompt_v65_full": _render(
            PromptBuilder.build(
                "default",
                full_state,
                analysis,
                scene_ctx=scene_ctx,
                goal_ctx=goal_ctx,
                behavior_ctx=behavior_ctx,
            )
        ),
        "prompt_v65_degraded": _render(
            PromptBuilder.build(
                "default",
                full_state,
                analysis,
                scene_ctx=scene_ctx,
                goal_ctx=goal_ctx,
                behavior_ctx=degraded,
            )
        ),
        "reflection_system": reflection[0][1],
        "reflection_user": reflection[1][1],
    }


def _render(prompt) -> str:
    return "\n---\n".join(message.content for message in prompt.format_messages())


def baseline_artifacts_path() -> Path:
    """V2.3.0 基线产物路径（仓库外，由 git archive 生成；见 ACCEPTANCE-CHECKLIST.md）。"""
    override = os.environ.get("TOOL012_BASELINE_ARTIFACTS")
    if override:
        return Path(override)
    return REPO_ROOT.parent / "tool012-baseline" / "artifacts_v230.json"


def load_baseline_artifacts() -> dict[str, str] | None:
    """读取仓库外 V2.3.0 基线产物；兼容早期的 `reflection_messages` 合并键形态。"""
    path = baseline_artifacts_path()
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("artifacts", payload)
    artifacts = {key: str(value) for key, value in raw.items()}
    if "reflection_messages" in artifacts and "reflection_system" not in artifacts:
        merged = artifacts.pop("reflection_messages")
        system_part, _, user_part = merged.partition("\x00")
        artifacts["reflection_system"] = system_part.split("\x01", 1)[-1]
        artifacts["reflection_user"] = user_part.split("\x01", 1)[-1]
    return artifacts


def git_blob_sha(relative_to_backend: str) -> str:
    """工作区文件按 git 对象口径（LF 归一）计算 blob sha1。"""
    data = (BACKEND_ROOT / relative_to_backend).read_bytes().replace(b"\r\n", b"\n")
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data).hexdigest()


def _reset_settings_cache() -> None:
    from app.core.settings import get_settings

    get_settings.cache_clear()


def reset_runtime_state() -> None:
    """清空工具系统全部进程内单例（Flag 矩阵组间隔离）。"""
    from app.services.action import registry as capability_registry_module
    from app.services.tool import channel_tools, ext_api, user_defined
    from app.services.tool import registry as tool_registry

    tool_registry._registry = None
    capability_registry_module._registry = None
    channel_tools.reset_channel_adapters()
    ext_api.reset_external_api_state()
    user_defined.reset_user_tool_registrar()
    _reset_settings_cache()


def apply_flag_env(monkeypatch, envs: dict[str, Any] | None = None) -> None:
    """隔离基线：辅助闸置 off + 工具参数与飞书占位固定，再套用给定 env。

    V2.4.0 工具总闸与九个子闸已随该版本转正删除，不再需要显式置 off；
    `envs` 中若仍带这些已删键，写入即被静默忽略（无副作用）。
    """
    values: dict[str, Any] = {}
    for flag in AUX_FLAGS:
        values[flag] = "false"
    values.update(TOOL_PARAM_ENVS)
    values.update(FEISHU_PLACEHOLDER_ENVS)
    for key, value in (envs or {}).items():
        values[key] = "true" if value is True else "false" if value is False else str(value)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    reset_runtime_state()


ALWAYS_ON_GROUP = "always_on"


def group_env(group: str = ALWAYS_ON_GROUP) -> dict[str, Any]:
    """唯一配置下的环境增量（保留签名以兼容既有调用形态）。"""
    return dict(FLAG_MATRIX[group])


FLAG_MATRIX: dict[str, dict[str, Any]] = {
    ALWAYS_ON_GROUP: {},
}
"""开关体系已删除：原本的总闸/子闸组合收敛为唯一配置。"""

EXPECTED_FINGERPRINTS: dict[str, dict[str, Any]] = {
    ALWAYS_ON_GROUP: {
        "registry_size": BUILTIN_TOOL_COUNT,
        "permission_layer": True,
        "channel_tools": False,
        "external_api": True,
        "user_defined": True,
        "tool_feed": True,
        "tool_insights_ready": True,
    },
}


def capability_fingerprint(settings) -> dict[str, Any]:
    """Flag 组合的可判定指纹：注册表规模 + 六条闸门判据。"""
    from app.services.reflection import tool_feed
    from app.services.tool import channel_tools, ext_api, permission, registry, user_defined

    registry_instance = registry.get_tool_registry()
    return {
        "registry_size": len(registry_instance.list()),
        "permission_layer": True,
        "channel_tools": channel_tools.channel_tools_enabled(settings),
        "external_api": True,
        "user_defined": True,
        "tool_feed": True,
        "tool_insights_ready": True,
    }


def builtin_registry():
    """构建内置声明全集（10 个 ToolDefinition），不依赖 Flag。"""
    from app.services.tool import builtin
    from app.services.tool.registry import ToolRegistry

    registry = ToolRegistry()
    builtin.register_all(registry)
    return registry


def tool_settings(**overrides: Any):
    """V2.4.0 工具域 settings 替身（开关体系已删除，只剩治理参数）。"""
    from types import SimpleNamespace

    values: dict[str, Any] = {
        "feishu_enabled": False,
        "tool_disabled_ids": "",
        "tool_surface_max_tools": 12,
        "tool_breaker_threshold": 3,
        "tool_breaker_cooldown_seconds": 300,
        "tool_confirm_timeout_hours": 24,
        "tool_confirm_ttl_reuse": True,
        "tool_ext_allowed_hosts": "",
        "tool_ext_manifest_path": "",
        "action_execution_timeout_seconds": 10,
    }
    values.update(overrides)
    settings = SimpleNamespace(**values)
    settings.disabled_tool_ids = lambda: frozenset(
        part.strip()
        for part in str(values["tool_disabled_ids"]).split(",")
        if part.strip()
    )
    settings.allowed_ext_hosts = lambda: frozenset(
        part.strip()
        for part in str(values["tool_ext_allowed_hosts"]).split(",")
        if part.strip()
    )
    return settings


def action_intent(action_type: str, params: dict[str, Any], *, confidence: str = "confident"):
    from app.models.action import ActionIntent, make_dedupe_key

    return ActionIntent(
        action_type=action_type,
        confidence=confidence,
        params=params,
        dedupe_key=make_dedupe_key(action_type, params),
    )


def iter_production_files(roots: Iterable[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    for root in PRODUCTION_SCAN_ROOTS if roots is None else roots:
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts
        )
    return files


def _display(path: Path) -> str:
    try:
        return path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _import_roots(module: ast.Module) -> list[tuple[int, str]]:
    roots: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            roots.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append((node.lineno, node.module))
    return roots


def scan_import_boundaries(
    paths: Iterable[Path], forbidden_roots: Iterable[str]
) -> list[Violation]:
    """依赖方向扫描：禁止生产模块 import 给定根（AST，非正则）。"""
    forbidden = tuple(forbidden_roots)
    violations: list[Violation] = []
    for path in paths:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, root in _import_roots(module):
            if any(root == item or root.startswith(f"{item}.") for item in forbidden):
                violations.append(
                    Violation(_display(path), lineno, "forbidden_import", root)
                )
    return violations


def scan_models_dependency_direction() -> list[Violation]:
    paths = sorted((APP_ROOT / "models").glob("*.py"))
    return scan_import_boundaries(paths, FORBIDDEN_MODEL_IMPORT_ROOTS)


def scan_tool_tree_dependency_direction() -> list[Violation]:
    return scan_import_boundaries(iter_production_files(), FORBIDDEN_TOOL_IMPORT_ROOTS)


IDENTIFIER_LIKE = re.compile(r"^[a-z][a-z0-9_]*$")


def scan_credential_hardcode() -> list[Violation]:
    """凭据零硬编码扫描：常量名含 SECRET/TOKEN/… 且值非占位符/非标识符即违规。

    值域常量（如 `REASON_CREDENTIAL_MISSING = "credential_missing"`）是标识符形态的
    枚举值，不是凭据；只在值不像标识符时才判违规（与 TOOL-011 安全扫描同口径）。
    """
    violations: list[Violation] = []
    for path in iter_production_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in module.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            if value is None or not isinstance(value, ast.Constant):
                continue
            if not isinstance(value.value, str):
                continue
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if not SECRET_NAME_PATTERN.search(target.id):
                    continue
                text = value.value.strip()
                if text.lower() in PLACEHOLDER_SECRET_VALUES:
                    continue
                if IDENTIFIER_LIKE.fullmatch(text):
                    continue
                violations.append(
                    Violation(
                        _display(path),
                        node.lineno,
                        "hardcoded_credential",
                        f"{target.id} = <{len(text)} 字符字面量>",
                    )
                )
    return violations


def scan_arbitrary_code_execution() -> list[Violation]:
    """无第二套运行时的代码面禁令：工具树不得出现 eval/exec/import 动态执行。"""
    forbidden_calls = {"eval", "exec", "compile", "__import__"}
    forbidden_attrs = {"import_module", "system", "popen", "spawn", "check_output"}
    violations: list[Violation] = []
    for path in iter_production_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in forbidden_calls:
                violations.append(
                    Violation(_display(path), node.lineno, "dynamic_execution", func.id)
                )
            elif (
                isinstance(func, ast.Attribute) and func.attr in forbidden_attrs
            ):
                violations.append(
                    Violation(
                        _display(path), node.lineno, "dynamic_execution", func.attr
                    )
                )
    return violations


def scan_second_runtime_surfaces() -> list[Violation]:
    """无第二套 Agent 运行时的声明面扫描：工具树不得定义新的 Run Profile / 阶段序列。"""
    violations: list[Violation] = []
    banned_names = {
        "RUN_PROFILES",
        "STEP_SEQUENCE",
        "PROFILE_REGISTRY",
        "PHASE_SEQUENCE",
        "STAGE_SEQUENCE",
    }
    for path in iter_production_files():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in module.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in banned_names:
                        violations.append(
                            Violation(
                                _display(path), node.lineno, "second_runtime", target.id
                            )
                        )
    return violations


def scan_run_kind_literals() -> list[str]:
    """工具树内出现的 Run Profile 字面量（用于"无新 Profile"断言）。"""
    found: set[str] = set()
    for path in iter_production_files():
        source = path.read_text(encoding="utf-8")
        found.update(_RUN_KIND_LITERAL_PATTERN.findall(source))
    return sorted(found)


def scan_new_tables() -> list[Violation]:
    """无新表扫描：生产代码里出现的 `__tablename__` 必须已在 V2.3.0 基线集合内。"""
    from app.core.db import Base

    baseline_tables = set(Base.metadata.tables)
    violations: list[Violation] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "__tablename__"
                    for target in item.targets
                ):
                    continue
                value = item.value
                name = value.value if isinstance(value, ast.Constant) else None
                if isinstance(name, str) and name not in baseline_tables:
                    violations.append(
                        Violation(
                            _display(path),
                            item.lineno,
                            "unregistered_table",
                            f"{node.name}.__tablename__ = {name}",
                        )
                    )
    return violations


def _digest_lines(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()[:16]


def table_column_digest(table) -> str:
    return _digest_lines(
        "{}:{}:{}:{}".format(column.name, str(column.type), column.nullable, bool(column.primary_key))
        for column in table.columns
    )


def table_checks_digest(table) -> str:
    return _digest_lines(
        "{}:{}".format(constraint.name or "", str(constraint.sqltext).replace("\n", " "))
        for constraint in table.constraints
        if type(constraint).__name__ == "CheckConstraint"
    )


def table_indexes_digest(table) -> str:
    return _digest_lines(
        "{}:{}:{}".format(
            index.name, ",".join(column.name for column in index.columns), bool(index.unique)
        )
        for index in table.indexes
    )


def table_set_digest() -> str:
    from app.core.db import Base

    return _digest_lines(sorted(Base.metadata.tables))


def schema_columns_digest(exclude_tables: tuple[str, ...] = ()) -> str:
    """全库列摘要；`exclude_tables` 用于**排除已登记的基线后新增表**。

    这样「基线未漂移」仍可被证明：`schema_columns_digest()` == `SCHEMA_COLUMNS_DIGEST`
    且 `schema_columns_digest(SCHEMA_ADDED_TABLES_VS_BASELINE)` ==
    `SCHEMA_COLUMNS_DIGEST_BASELINE`。直接改基线摘要常量会让断言变成谎，故不采用。

    **例外（2026-10-03，ADR-16）**：`SCHEMA_COLUMNS_DIGEST_BASELINE` 由
    `45eef10a675e4794` 更新为 `3631831cc3c8c1d5`。这是**唯一一次**对基线表列定义的
    有意演进——迁移 `0004` 把基线表 `channel_identities.session_id` 放开为可空
    （该表成为全通道统一凭据绑定表后，邮箱绑定行无会话概念，NOT NULL 是原飞书专用
    设计的残留）。此处更新是**登记该演进**，不是用它掩盖未登记漂移：新增表仍走
    `SCHEMA_ADDED_TABLES_VS_BASELINE`，其余基线表列定义仍受本摘要保护。
    """
    from app.core.db import Base

    return _digest_lines(
        "{}:{}".format(name, table_column_digest(table))
        for name, table in Base.metadata.tables.items()
        if name not in exclude_tables
    )


def table_digests(name: str) -> tuple[str, str, str]:
    from app.core.db import Base

    table = Base.metadata.tables[name]
    return (
        table_column_digest(table),
        table_checks_digest(table),
        table_indexes_digest(table),
    )


def live_loop_maintenance_names(source: str) -> tuple[str, ...]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "_record_maintenance_run":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            calls.append((node.lineno, str(node.args[0].value)))
    return tuple(name for _lineno, name in sorted(calls))


class ExternalCallProbe:
    """外部调用打桩：统计出站网络 / 通道适配器 / LLM 的触达次数。

    回环地址不计入外部调用：Windows 的 `asyncio.run` 经 `socket.socketpair()`
    回退实现会向 127.0.0.1 发起一次自连接，那不是出站调用（TOOL-012 E4 同款口径）。
    """

    LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", ""})

    def __init__(self) -> None:
        self.network = 0
        self.channel = 0
        self.llm = 0

    @property
    def total(self) -> int:
        return self.network + self.channel + self.llm

    def install(self, monkeypatch) -> "ExternalCallProbe":
        import socket

        from app.channels.base import OutboundMessage, SendResult
        from app.services.tool import channel_tools

        probe = self

        def _connect(original):
            def _wrapped(self_socket, address, *args, **kwargs):
                host = address[0] if isinstance(address, tuple) and address else address
                if str(host) not in probe.LOOPBACK_HOSTS:
                    probe.network += 1
                return original(self_socket, address, *args, **kwargs)

            return _wrapped

        monkeypatch.setattr(
            socket.socket, "connect", _connect(socket.socket.connect)
        )

        class _RecordingAdapter:
            async def send(self, message: OutboundMessage) -> SendResult:
                probe.channel += 1
                raise AssertionError("越权路径触达了通道适配器")

        channel_tools.register_channel_adapter("feishu", _RecordingAdapter())
        return self


def empty_tool_context(**overrides: Any):
    from app.services.tool.context import ToolContext

    values: dict[str, Any] = {
        "user_id": "u-tool012",
        "now": _now(),
        "settings": tool_settings(),
        "world": {},
        "inventory": [],
        "situations": [],
        "scene": {},
        "relationship": {},
        "authorized_recipients": [],
    }
    values.update(overrides)
    return ToolContext(**values)
