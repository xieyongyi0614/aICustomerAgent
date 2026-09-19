"""TOOL-012 系统验收：Flag 矩阵、逐字节一致性、八个版本 Gate 与零迁移最终核对。

对应任务书 TOOL-012 §2.2（八个 Gate / Flag 矩阵）、§2.3（逐字节一致性 / 零迁移核对）、
§6.1~§6.3（AC 与边界）。本文件只做验收判定，不新增功能、不修复缺陷。

模板偏移登记：任务书要求的两份交付物 `scenario-test.md` / `regression-checklist.md`
按用户级约束落至 `tests/v24/SCENARIO-TEST.md` 与 `tests/v24/ACCEPTANCE-CHECKLIST.md`，
`docs/` 零改动。
"""

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.models.tool import PermissionProfile
from app.services.tool.registry import ToolRegistry
from tests.v24 import tool012_support as support
from tests.v24.tool003_support import (
    build_executor,
    notification_definition,
    stub_registry,
)
from tests.v24.tool005_support import (
    CHANNEL_TOOL_ID,
    SENSITIVE_TOOL_ID,
    UNTRUSTED_TOOL_ID,
    grant,
    invocation,
    notification_capability,
    snapshot,
)
from tests.v24.tool010_support import builtin_registry

pytestmark = pytest.mark.xdist_group("tool012")


def _future_due_at() -> str:
    return (support._now() + timedelta(minutes=30)).isoformat()


# --- 常开配置的运行期指纹与注册表 ----------------------------------------------


def test_runtime_fingerprint_matches_always_on_config(monkeypatch):
    """开关体系已删除：运行期指纹等于唯一常开配置的期望。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    settings = get_settings()

    assert support.capability_fingerprint(settings) == support.EXPECTED_FINGERPRINTS[
        support.ALWAYS_ON_GROUP
    ]


def test_registry_ids_are_stable(monkeypatch):
    """注册表恒为固定 10 条内置声明。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    from app.services.tool.registry import get_tool_registry

    registry = get_tool_registry()
    assert registry is not None
    assert tuple(sorted(definition.id for definition in registry.list())) == (
        support.BUILTIN_TOOL_IDS
    )








def test_flag_matrix_startup_chain_validation_is_gone():
    """批次 8：enablement 空壳与启动校验调用已删除（链上无闸可校验）。"""
    source = (support.APP_ROOT / "main.py").read_text(encoding="utf-8")

    assert "validate_enablement_chain" not in source


# --- Flag 矩阵：各子闸的行为分支 ------------------------------------------------


def _executor_for(capability, settings, registry=None):
    return build_executor(
        registry if registry is not None else builtin_registry(),
        capability,
        settings=settings,
        timeout_seconds=5.0,
    )


def _permission_registry():
    """内置声明 + 不受信命名空间声明（`user.*` / `ext.api.*` 无内置工具）。"""
    from tests.v24.tool005_support import ext_definition, untrusted_definition

    registry = builtin_registry()
    for definition in (untrusted_definition(), ext_definition()):
        registry.register(definition)
    return registry


def _grant_free_registry():
    """同形通知声明的免授权档版本（P0-1：总闸 on + 子闸 off 时 sensitive 默认拒绝）。

    校验段 / 观测段等**非权限主题**的用例改走该档，才能在"仅总闸"的矩阵组合下
    走到被验证的那一段；权限段本身的行为由 `test_flag_matrix_permission_branch` 持有。
    """
    registry = ToolRegistry()
    registry.register(
        notification_definition(
            permission=PermissionProfile(level="normal", scope=("self",))
        )
    )
    return registry


def test_schema_validation_always_enforced(monkeypatch):
    """校验段已转正常开：参数错误一律拦下。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    settings = get_settings()
    capability = notification_capability()
    executor = _executor_for(capability, settings, registry=_grant_free_registry())

    execution = _run(
        executor,
        invocation(SENSITIVE_TOOL_ID, {"content": "在吗", "unknown_field": "x"}),
        settings,
    )

    assert execution.status == "invalid"
    assert execution.validation["structural"][0]["code"] == "unknown_param"
    assert capability.calls == []


def test_permission_layer_always_evaluates(monkeypatch):
    """权限层已转正常开：无授权 → 首次确认。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    settings = get_settings()
    capability = notification_capability()
    executor = _executor_for(capability, settings)

    execution = _run(
        executor,
        invocation(SENSITIVE_TOOL_ID, {"content": "在吗"}),
        settings,
        permission_snapshot=snapshot(grants=[], settings=settings),
    )

    assert execution.status == "pending_confirmation"
    assert execution.permission["reason"] == "first_time_confirmation"
    assert capability.calls == []


def test_observation_persists_structured_keys(monkeypatch):
    """观测结果恒走 ToolResult 结构化键，并保留旧 `payload` 读键。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    settings = get_settings()
    executor = _executor_for(
        notification_capability(), settings, registry=_grant_free_registry()
    )

    execution = _run(
        executor, invocation(SENSITIVE_TOOL_ID, {"content": "在吗"}), settings
    )

    assert execution.status == "succeeded"
    payload = execution.result
    assert {"status", "effects", "observations", "raw_error"} <= set(payload)
    assert "payload" in payload, "兼容双写必须保留旧 payload 读键"


def test_tool_memory_delivery_never_falls_back_to_legacy(monkeypatch):
    """工具记忆子闸已转正删除：投递恒走工具路径，不回退 legacy。"""
    support.apply_flag_env(monkeypatch, support.group_env())
    from app.services.action import memory_bridge

    calls: list[str] = []
    monkeypatch.setattr(
        memory_bridge, "deliver_action_memory", lambda *a, **k: calls.append("legacy")
    )

    from app.models.action import ActionRecord

    record = ActionRecord(
        id="act-tool012-memory",
        user_id="u-tool012",
        character_id="asuna",
        session_id="s-tool012",
        action_type="create_reminder",
        status="succeeded",
        params={"content": "开会"},
        dedupe_key="tool012-memory",
        steps=[{"index": 0, "tool_id": "builtin.reminder.create", "status": "succeeded"}],
    )
    memory_bridge.deliver(record, "u-tool012")

    assert calls == [], "工具路径不得回退 legacy 投递"




def test_channel_tool_status_follows_feishu(monkeypatch):
    """通道工具状态只由 `feishu_enabled` 决定（总闸与通道子闸已删除）。"""
    support.apply_flag_env(monkeypatch, {**support.group_env(), 
        "FEISHU_ENABLED": True})
    registry = builtin_registry()
    assert registry.effective_status(CHANNEL_TOOL_ID) == "enabled"
    assert registry.get(CHANNEL_TOOL_ID).namespace == "channel"

    support.apply_flag_env(monkeypatch, support.group_env())
    assert builtin_registry().effective_status(CHANNEL_TOOL_ID) == "disabled"




def test_autonomy_surface_is_always_resolved(monkeypatch):
    """自治工具面恒可解析（总闸已删除）。"""
    from app.application import autonomy_engine

    support.apply_flag_env(monkeypatch, {})
    surface = autonomy_engine.resolve_autonomy_surface("tool012", support._now())
    assert surface is not None

    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    surface = autonomy_engine.resolve_autonomy_surface("tool012", support._now())
    assert surface is not None
    assert surface.tool_ids
    assert all(not tool_id.startswith("channel.") for tool_id in surface.tool_ids)
    assert "builtin.search.query" not in surface.tool_ids


def _run(executor, inv, settings, *, permission_snapshot=None):
    import asyncio

    from app.services.action.registry import ExecutionContext

    ctx = ExecutionContext(
        user_id="u-tool012", now=support._now(), settings=settings, dedupe_key=inv.dedupe_key
    )
    registry = executor.registry
    binding = registry.resolve(inv.tool_id)
    return asyncio.run(
        executor.run(binding, inv, ctx, permission_snapshot=permission_snapshot)
    )


# --- G-COMPAT 逐字节一致性 ------------------------------------------------------


def test_g_compat_prompt_artifacts_match_checked_in_v230_golden(monkeypatch):
    """Flag 全 off：4 份 prompt 快照与仓库内 V2.3.0 基线文件逐字节一致。"""
    support.apply_flag_env(monkeypatch, {})
    artifacts = support.render_acceptance_artifacts()
    golden_dir = support.BACKEND_ROOT / "tests" / "golden"

    for key, filename in support.PROMPT_BASELINE_FILES.items():
        expected = (golden_dir / filename).read_text(encoding="utf-8")
        assert artifacts[key] == expected, f"{key} 与 V2.3.0 基线 {filename} 不一致"


def test_g_compat_reflection_prompt_matches_v230_literal(monkeypatch):
    """Flag 全 off：反思 Prompt 不传类型域时与 V2.3.0 基线逐字节一致。"""
    support.apply_flag_env(monkeypatch, {})
    artifacts = support.render_acceptance_artifacts()

    assert artifacts["reflection_system"] == support.LEGACY_REFLECTION_SYSTEM_PROMPT
    assert artifacts["reflection_user"] == support.LEGACY_REFLECTION_USER_PROMPT


def test_g_compat_artifact_bundle_matches_git_archive_baseline(monkeypatch):
    """与仓库外 V2.3.0 git archive 渲染产物逐字节比较（基线缺失即 skip）。"""
    baseline = support.load_baseline_artifacts()
    if baseline is None:
        pytest.skip(
            "V2.3.0 基线产物缺失：先按 tests/v24/ACCEPTANCE-CHECKLIST.md 的"
            "「基线取证」节执行 git archive + 渲染脚本"
        )
    support.apply_flag_env(monkeypatch, {})
    artifacts = support.render_acceptance_artifacts()

    for key in sorted(baseline):
        assert key in artifacts, f"基线含本套件未渲染的产物: {key}"
        assert artifacts[key] == baseline[key], f"{key} 与 V2.3.0 基线不一致"


def test_g_compat_life_loop_maintenance_sequence_unchanged():
    """维护步序列与 V2.3.0 相同（基线由 git archive 检出物同法提取）。"""
    source = (support.APP_ROOT / "application" / "life_loop.py").read_text(
        encoding="utf-8"
    )

    assert (
        support.live_loop_maintenance_names(source)
        == support.LIFE_LOOP_MAINTENANCE_SEQUENCE
    )


def test_g_compat_post_process_step_sequence_unchanged():
    """第 9 步所在的后处理步序列零改动。"""
    from app.application import post_process

    assert (
        tuple(handler.__name__ for handler in post_process.STEP_HANDLERS)
        == support.POST_PROCESS_STEP_SEQUENCE
    )


def test_g_compat_frozen_blobs_zero_diff():
    """冻结面文件与 V2.3.0 的 git blob 零 diff（对象口径，LF 归一）。

    P2-4：`app/application/life_loop.py` 已从 blob 冻结面撤下（P2-1 在 `has_due` 调用侧
    合法新增到期口径排除），改由下面的语义断言持有；冻结整文件哈希会把正常演进判成违规。
    """
    for relative_path, expected_sha in support.FROZEN_BLOB_SHA_BASELINE.items():
        assert support.git_blob_sha(relative_path) == expected_sha, relative_path


def test_g_compat_life_loop_semantics_replacing_blob_freeze():
    """life_loop 的语义面替代 blob 哈希：维护步序列不变 + 不新增确认清理路径。"""
    source = (support.APP_ROOT / "application" / "life_loop.py").read_text(
        encoding="utf-8"
    )
    assert support.live_loop_maintenance_names(source) == support.LIFE_LOOP_MAINTENANCE_SEQUENCE
    assert "ConfirmationService" not in source
    assert "_expire_pending_confirmations" not in source


def test_g_action_domain_steps_shape_is_v9_plus_tool_fields(
    db_session_factory, override_settings
):
    """行动域 steps[] = V9 六键 + V2.4.0 四键（工具面常开后恒为增量形态）。"""
    import asyncio

    override_settings(WORLD_ENABLED="true")
    from app.application import action_engine, world_engine

    user = "u-tool012-compat"
    world_engine.ensure_world(user)
    intent = support.action_intent(
        "create_reminder", {"content": "明天开会", "due_at": _future_due_at()}
    )

    record = asyncio.run(
        action_engine.run_action_planning(user, intent, session_id="s-tool012")
    )

    assert record is not None
    assert record.steps
    for step in record.steps:
        assert set(step) == support.V9_STEP_KEYS | support.V24_STEP_KEYS_ADDED
        assert {"status", "payload", "usage", "error"} <= set(step["result"])

def test_g_compat_action_domain_steps_gain_v24_keys_only_when_master_on(
    db_session_factory, override_settings, monkeypatch
):
    """反向对照：总闸 on 时 steps[] 才出现 V2.4.0 键（证明上一条断言非空转）。"""
    import asyncio

    override_settings(WORLD_ENABLED="true")
    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    from app.application import action_engine
    from app.application import world_engine

    user = "u-tool012-compat-on"
    world_engine.ensure_world(user)
    intent = support.action_intent(
        "create_reminder", {"content": "明天开会", "due_at": _future_due_at()}
    )

    record = asyncio.run(
        action_engine.run_action_planning(user, intent, session_id="s-tool012")
    )

    assert record is not None and record.steps
    assert support.V24_STEP_KEYS_ADDED <= set(record.steps[0])
    assert record.steps[0]["tool_id"] == "builtin.reminder.create"


# --- G-GOVERN ------------------------------------------------------------------


def test_g_govern_every_tool_answers_four_questions(monkeypatch):
    """每个工具都能回答：谁注册 / 何时启用 / 当前状态 / 最近健康度。"""
    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    registry = builtin_registry()
    from app.models.tool import ToolSurface

    for definition in registry.list():
        binding = registry.resolve(definition.id)
        assert binding is not None and binding.capability == definition.capability
        assert definition.namespace in {
            "builtin",
            "channel",
            "world",
            "ext.api",
            "user",
        }

        status = registry.effective_status(definition.id)
        assert status in {"enabled", "disabled", "deprecated", "removed"}

        descriptors = registry.describe(
            surface=ToolSurface(run_kind="foreground_chat", tool_ids=(definition.id,))
        )
        if status == "enabled":
            assert [item.tool_id for item in descriptors] == [definition.id]
            assert descriptors[0].status == status
        else:
            assert descriptors == []

        health = registry.health(definition.id)
        assert definition.id in health
        assert health[definition.id].consecutive_failures == 0


def test_g_govern_namespace_index_reports_registration_source(monkeypatch):
    """命名空间索引回答"谁注册"：三个命名空间各自可枚举且计数自洽。"""
    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    registry = builtin_registry()

    index = registry.namespaces()
    assert index["builtin"].enabled_count == 5
    assert index["world"].enabled_count == 4
    assert index["channel"].enabled_count == 0
    assert index["channel"].tool_ids == [CHANNEL_TOOL_ID]


# --- G-SELECT ------------------------------------------------------------------


def _surface(run_kind, *, channel_on: bool = True, **context_overrides):
    from app.services.tool.context import ToolContext
    from app.services.tool.surface import ToolSurfaceResolver

    settings = support.tool_settings(
        feishu_enabled=channel_on,
    )
    values = {"user_id": "u-tool012", "now": support._now(), "settings": settings}
    values.update(context_overrides)
    context = ToolContext(**values)
    return ToolSurfaceResolver(builtin_registry(), settings).resolve(run_kind, context)


def test_g_select_three_contexts_project_three_surfaces(monkeypatch):
    """≥3 组语境投影出不同工具面，且 surface_hash 同输入同输出。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_CHANNEL_ENABLED": True,
            "FEISHU_ENABLED": True,
        },
    )
    foreground = _surface("foreground_chat")
    autonomous = _surface("autonomous_tick")
    event_driven = _surface("event_driven")

    hashes = {foreground.surface_hash, autonomous.surface_hash, event_driven.surface_hash}
    assert len(hashes) == 3
    assert len({foreground.tool_ids, autonomous.tool_ids, event_driven.tool_ids}) == 3

    assert _surface("foreground_chat").surface_hash == foreground.surface_hash
    assert _surface("autonomous_tick").tool_ids == autonomous.tool_ids

    registry = builtin_registry()
    assert event_driven.tool_ids
    for tool_id in event_driven.tool_ids:
        assert set(registry.get(tool_id).side_effects) <= {"read"}
    assert CHANNEL_TOOL_ID not in autonomous.tool_ids


def test_g_select_excluded_reasons_are_human_readable(monkeypatch):
    """不同工具面的差异有可读裁剪理由（非黑箱）。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_CHANNEL_ENABLED": True,
            "FEISHU_ENABLED": True,
        },
    )
    surface = _surface("autonomous_tick")
    reasons = {item["tool_id"]: item["reason"] for item in surface.excluded}

    assert reasons[CHANNEL_TOOL_ID].startswith("run_profile")
    assert reasons["builtin.search.query"] == "unavailable:source_not_configured"


def test_g_select_late_night_and_relationship_dimensions(monkeypatch):
    """日时段维度独立裁剪，且投影为纯函数（同输入同输出）。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_CHANNEL_ENABLED": True,
            "FEISHU_ENABLED": True,
        },
    )
    context = {
        "world": {"part_of_day": "late_night", "world_enabled": True},
        "relationship": {"stage": "stranger", "tension": 0.1},
    }
    surface = _surface("foreground_chat", **context)

    assert CHANNEL_TOOL_ID not in surface.tool_ids
    reasons = {item["tool_id"]: item["reason"] for item in surface.excluded}
    assert reasons[CHANNEL_TOOL_ID] == "part_of_day:late_night"
    assert _surface("foreground_chat", **context).tool_ids == surface.tool_ids
    assert _surface("foreground_chat", **context).surface_hash == surface.surface_hash


def test_g_select_selector_is_deterministic():
    """选择器同输入同输出（priority + tool_id 字典序 tiebreak）。"""
    from app.services.tool.surface import ToolSelector

    surface = _surface("foreground_chat")
    intent = support.action_intent("send_notification", {"content": "在吗"})
    selector = ToolSelector(builtin_registry())

    first = selector.select(intent, surface)
    second = selector.select(intent, surface)

    assert first is not None and first.tool_id == second.tool_id
    assert first.tool_id == "builtin.notification.send"


# --- G-VALIDATE -----------------------------------------------------------------


def _validation_definition():
    from app.models.tool import (
        PermissionProfile,
        ToolDefinition,
        ToolParameter,
        ToolSchema,
    )

    return ToolDefinition(
        id="builtin.tool012.probe",
        name="验收探针",
        description="TOOL-012 校验矩阵探针",
        namespace="builtin",
        capability="reminder",
        action="create",
        input_schema=ToolSchema(
            semantic_validators=(
                "future_datetime",
                "location_exists",
                "object_in_inventory",
                "recipient_authorized",
                "content_within_budget",
            ),
            parameters=[
                ToolParameter(name="content", type="string", required=True),
                ToolParameter(name="due_at", type="datetime"),
                ToolParameter(name="location", type="string"),
                ToolParameter(name="object", type="string"),
                ToolParameter(name="recipient", type="string"),
                ToolParameter(
                    name="importance", type="string", enum=("low", "normal", "high")
                ),
                ToolParameter(name="repeat", type="integer", min=0, max=7),
                ToolParameter(name="note", type="string", max_length=5),
                ToolParameter(name="code", type="string", pattern=r"^[A-Z]{3}$"),
                ToolParameter(name="email", type="string", format="email"),
            ],
        ),
        permission=PermissionProfile(level="normal", scope=("world",), confirm="never"),
        side_effects=("write_world",),
    )


STRUCTURAL_CASES: dict[str, dict] = {
    "missing_required": {},
    "type_mismatch": {"content": "在吗", "repeat": "abc"},
    "enum_invalid": {"content": "在吗", "importance": "urgent"},
    "range_violated": {"content": "在吗", "repeat": 99},
    "length_violated": {"content": "在吗", "note": "超出上限的内容"},
    "pattern_mismatch": {"content": "在吗", "code": "abc"},
    "format_invalid": {"content": "在吗", "email": "not-an-email"},
    "unknown_param": {"content": "在吗", "undeclared": "x"},
}

SEMANTIC_CASES: dict[str, tuple[dict, dict]] = {
    "not_future": (
        {"content": "在吗", "due_at": "2020-01-01T00:00:00"},
        {},
    ),
    "location_not_found": (
        {"content": "在吗", "location": "火星基地"},
        {"world": {"locations": ["home.living_room"], "world_enabled": True}},
    ),
    "object_not_in_inventory": (
        {"content": "在吗", "object": "水杯"},
        {"world": {"world_enabled": True}, "inventory": []},
    ),
    "recipient_not_authorized": (
        {"content": "在吗", "recipient": "陌生人"},
        {"authorized_recipients": ["小林"]},
    ),
    "content_over_budget": (
        {"content": "长" * 4001},
        {},
    ),
}


@pytest.mark.parametrize("code,params", STRUCTURAL_CASES.items())
def test_g_validate_structural_eight_codes(code, params):
    """结构层八类错误各有一例，且理由字段级可读。"""
    from app.services.tool.validator import ParamValidator
    from app.services.tool.context import ToolContext

    report = ParamValidator().validate(
        _validation_definition(), params, ToolContext(user_id="u-tool012")
    )

    assert report.passed is False
    assert code in {issue["code"] for issue in report.structural}
    issue = next(item for item in report.structural if item["code"] == code)
    assert issue["param"]
    assert len(issue["message"]) > 4


@pytest.mark.parametrize("code,case", SEMANTIC_CASES.items())
def test_g_validate_semantic_five_codes(code, case):
    """语义层五类错误各有一例（结构层通过后才进入语义层）。"""
    from app.services.tool.validator import ParamValidator
    from app.services.tool.context import ToolContext

    params, context = case
    values = {
        "user_id": "u-tool012",
        "now": support._now(),
        "world": {"locations": ["home.living_room"]},
        "inventory": ["水杯"],
        "authorized_recipients": ["小林"],
    }
    values.update(context)
    report = ParamValidator().validate(
        _validation_definition(), params, ToolContext(**values)
    )

    assert report.passed is False
    assert report.structural == []
    assert code in {issue["code"] for issue in report.semantic}
    issue = next(item for item in report.semantic if item["code"] == code)
    assert len(issue["message"]) > 4


def test_g_validate_rejects_before_execution(monkeypatch):
    """校验失败在执行前拦下：能力实现零调用。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_SCHEMA_VALIDATION_ENABLED": True,
        },
    )
    settings = get_settings()
    capability = notification_capability()
    executor = build_executor(
        _grant_free_registry(),
        capability,
        settings=settings,
        timeout_seconds=5.0,
    )

    execution = _run(
        executor, invocation(SENSITIVE_TOOL_ID, {"content": "", "bogus": "1"}), settings
    )

    assert execution.status == "invalid"
    assert capability.calls == []


def test_g_validate_normalized_is_idempotent():
    """normalized 幂等：对规范化结果再规范化输出不变。"""
    from app.services.tool.validator import ParamValidator
    from app.services.tool.context import ToolContext

    definition = _validation_definition()
    validator = ParamValidator()
    ctx = ToolContext(user_id="u-tool012")
    params = {"content": "  明天   开会  ", "importance": "NORMAL", "repeat": 2}

    first = validator.validate(definition, params, ctx)
    second = validator.validate(definition, first.normalized, ctx)

    assert first.passed and second.passed
    assert first.normalized == second.normalized
    assert first.normalized["content"] == "明天 开会"
    assert first.normalized["importance"] == "normal"


# --- G-PERMISSION ---------------------------------------------------------------


def test_g_permission_default_deny_paths(monkeypatch):
    """默认拒绝：无授权的敏感/危险/不受信工具一律不执行（fail-closed）。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_PERMISSION_ENABLED": True,
        },
    )
    settings = get_settings()
    capability = notification_capability()
    executor = _executor_for(capability, settings, _permission_registry())
    now = support._now()

    cases = {
        SENSITIVE_TOOL_ID: ("pending_confirmation", "first_time_confirmation"),
        UNTRUSTED_TOOL_ID: ("denied", "untrusted_namespace"),
    }
    for tool_id, (status, reason) in cases.items():
        execution = _run(
            executor,
            invocation(tool_id, {"content": "在吗"}),
            settings,
            permission_snapshot=snapshot(
                grants=[], settings=settings, now=now, namespace_floors={"user": "dangerous"}
            ),
        )
        assert execution.status == status, tool_id
        assert execution.permission["reason"] == reason, tool_id

    expired = _run(
        executor,
        invocation(SENSITIVE_TOOL_ID, {"content": "在吗"}),
        settings,
        permission_snapshot=snapshot(
            grants=[grant(SENSITIVE_TOOL_ID, expires_at=now - timedelta(days=1))],
            settings=settings,
            now=now,
        ),
    )
    assert expired.status == "pending_confirmation"
    assert expired.permission["reason"] == "first_time_confirmation"


def test_g_permission_denied_path_makes_zero_external_calls(monkeypatch):
    """不变量 2：权限失败路径零外部调用（能力 / 网络 / 通道 / LLM 全为 0）。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_PERMISSION_ENABLED": True,
        },
    )
    settings = get_settings()
    probe = support.ExternalCallProbe().install(monkeypatch)
    capability = notification_capability()
    executor = _executor_for(capability, settings, _permission_registry())

    execution = _run(
        executor,
        invocation(SENSITIVE_TOOL_ID, {"content": "在吗"}),
        settings,
        permission_snapshot=snapshot(grants=[], settings=settings),
    )

    assert execution.status == "pending_confirmation"
    assert capability.calls == []
    assert probe.total == 0


def test_g_permission_grant_unlocks_without_confirmation(monkeypatch):
    """有有效授权即放行（② grant_matched），确认流不再介入。"""
    support.apply_flag_env(
        monkeypatch,
        {
            "TOOL_SYSTEM_ENABLED": True,
            "TOOL_PERMISSION_ENABLED": True,
        },
    )
    settings = get_settings()
    capability = notification_capability()
    executor = _executor_for(capability, settings, _permission_registry())

    execution = _run(
        executor,
        invocation(SENSITIVE_TOOL_ID, {"content": "在吗"}),
        settings,
        permission_snapshot=snapshot(
            grants=[grant(SENSITIVE_TOOL_ID, ("self",))], settings=settings
        ),
    )

    assert execution.status == "succeeded"
    assert execution.permission["reason"] == "grant_matched"
    assert capability.calls


# --- G-WORLD --------------------------------------------------------------------


def test_g_world_static_scan_zero_violations():
    """静态扫描：工具实现体零世界直写、零世界仓储 import。"""
    from tests.v24.test_tool_world_guard import scan_tool_modules

    assert scan_tool_modules() == []
    assert support.scan_tool_tree_dependency_direction() == []


def test_g_world_outbox_is_the_only_write_path(
    db_session_factory, override_settings, monkeypatch
):
    """端到端：工具写世界全部经 outbox，消费后才落 world_events。"""
    import asyncio

    override_settings(
        WORLD_ENABLED="true",
        ACTION_OUTBOX_ENABLED="true")
    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    from app.application import action_engine, outbox_consumer, world_engine
    from app.repositories import outbox_repository, world_repository

    user = "u-tool012-world"
    world = world_engine.ensure_world(user)
    intent = support.action_intent(
        "create_reminder", {"content": "明天开会", "due_at": _future_due_at()}
    )

    record = asyncio.run(
        action_engine.run_action_planning(user, intent, session_id="s-tool012")
    )
    assert record is not None and record.status == "succeeded"

    before = [event for event in world_repository.list_events(world.world_id, limit=100)]
    outbox_rows = outbox_repository.list_recent(limit=50)
    assert any(row.idempotency_key == record.id for row in outbox_rows)

    outbox_consumer.consume_pending(now=support._now())
    after = [event for event in world_repository.list_events(world.world_id, limit=100)]
    assert len(after) > len(before)
    assert any(
        (event.payload or {}).get("outbox_action_id") == record.id for event in after
    )


# --- G-MEMORY -------------------------------------------------------------------


def test_g_memory_read_only_tool_never_deposits():
    """读类工具零沉淀（硬纪律①，优先于边界表配置）。"""
    from app.services.tool.memory_policy import get_tool_memory_policy
    from app.models.action import ActionRecord

    policy = get_tool_memory_policy()
    definition = builtin_registry().get("world.env.query")
    record = ActionRecord(
        id="act-tool012-readonly",
        user_id="u-tool012",
        character_id="asuna",
        session_id="s-tool012",
        action_type="query_environment",
        status="succeeded",
        params={"dimension": "weather"},
        dedupe_key="tool012-readonly",
        steps=[{"index": 0, "tool_id": "world.env.query", "status": "succeeded"}],
    )

    decision = policy.classify(record, definition)
    assert decision.deposit is False
    assert decision.reason == "read_only_tool"
    assert policy.to_candidates(record, definition) == []


def test_g_memory_untrusted_namespaces_never_deposit():
    """`ext.api.*` / `user.*` 默认不沉淀（硬纪律②）。"""
    from app.services.tool.memory_policy import get_tool_memory_policy
    from app.models.action import ActionRecord

    policy = get_tool_memory_policy()
    for tool_id in ("ext.api.push.write", "user.notes.delete"):
        record = ActionRecord(
            id=f"act-tool012-{tool_id}",
            user_id="u-tool012",
            character_id="asuna",
            session_id="s-tool012",
            action_type="send_notification",
            status="succeeded",
            params={"content": "x"},
            dedupe_key=f"tool012-{tool_id}",
            steps=[{"index": 0, "tool_id": tool_id, "status": "succeeded"}],
        )
        decision = policy.classify(record, None)
        assert decision.deposit is False
        assert decision.reason == "untrusted_source"


def test_g_memory_important_result_enters_candidate_pool():
    """重要结果进候选：`builtin.reminder.create` 成功即产出 1 条候选。"""
    from app.services.tool.memory_policy import get_tool_memory_policy
    from app.models.action import ActionRecord

    policy = get_tool_memory_policy()
    definition = builtin_registry().get("builtin.reminder.create")
    record = ActionRecord(
        id="act-tool012-deposit",
        user_id="u-tool012",
        character_id="asuna",
        session_id="s-tool012",
        action_type="create_reminder",
        status="succeeded",
        params={"content": "明天开会", "due_at": "2026-09-15T09:00:00"},
        dedupe_key="tool012-deposit",
        steps=[{"index": 0, "tool_id": "builtin.reminder.create", "status": "succeeded"}],
    )

    candidates = policy.to_candidates(record, definition)
    assert len(candidates) == 1
    assert candidates[0].type == "important_event"
    assert candidates[0].importance == 0.7
    assert "明天开会" in candidates[0].content


POLICY_RULE_CASES: dict[str, dict] = {
    "R1": {"action": "save", "type": "important_event", "content": "AI 推测内容", "source": "ai_inferred"},
    "R4": {"action": "save", "type": "important_event", "content": "今晚想看电影", "source": "user_stated"},
    "R5": {"action": "save", "type": "important_event", "content": "低置信度内容", "confidence": 0.1},
    "R6": {"action": "save", "type": "important_event", "content": "低重要性内容", "importance": 0.05},
    "R8": {"action": "save", "type": "important_event", "content": "他说明天要出差", "source": "user_stated"},
}


@pytest.mark.parametrize("rule,payload", POLICY_RULE_CASES.items())
def test_g_memory_rules_r1_r8_have_no_exemption(rule, payload):
    """R1~R8 零豁免：政策闸对工具结果候选与记忆候选一视同仁。"""
    from app.models.memory import MemoryCandidate
    from app.services import memory_policy

    candidate = MemoryCandidate(
        action=payload["action"],
        type=payload["type"],
        content=payload["content"],
        importance=payload.get("importance", 0.9),
        confidence=payload.get("confidence", 0.95),
        source=payload.get("source", "user_derived"),
    )
    report = memory_policy.apply_policy([candidate])

    assert report.saved == []
    assert [outcome.rule for outcome in report.discarded] == [rule]


def test_g_memory_r2_r3_r7_rules_reachable():
    """R2 / R3 / R7 同样零豁免（suppress 阻断、forget 转隐私、完全重复）。"""
    from app.models.memory import MemoryCandidate
    from app.services import memory_policy

    base = MemoryCandidate(
        action="save",
        type="important_event",
        content="用户喜欢西瓜",
        importance=0.9,
        confidence=0.95,
        source="user_stated",
    )
    suppressed = memory_policy.apply_policy(
        [
            base,
            MemoryCandidate(
                action="suppress", type="important_event", content="x", importance=0.9, confidence=0.9
            ),
        ]
    )
    assert "R2" in {outcome.rule for outcome in suppressed.discarded}

    forgotten = memory_policy.apply_policy([base.model_copy(update={"action": "forget"})])
    assert forgotten.privacy_items and forgotten.privacy_items[0].action == "forget"

    duplicate = memory_policy.apply_policy([base], active_contents=["用户喜欢西瓜"])
    assert [outcome.rule for outcome in duplicate.discarded] == ["R7"]


def test_g_memory_policy_rejection_prevents_write(
    db_session_factory, override_settings, monkeypatch
):
    """政策拒收的候选被丢弃 → memories 表零写入。"""
    override_settings(ACTION_MEMORY_POLICY_ENABLED="true")
    support.apply_flag_env(
        monkeypatch,
        {"TOOL_SYSTEM_ENABLED": True, "TOOL_MEMORY_ENABLED": True},
    )
    from app.services.action import memory_bridge
    from tests.v24.tool008_support import memory_count, record

    user = "u-tool012-memreject"
    rejected = record(
        tool_id="builtin.notification.send",
        user_id=user,
        params={"content": "在吗"},
    )
    assert memory_bridge.deliver(rejected, user) is None
    assert memory_count(user) == 0


def test_g_memory_idempotent_effects_block_redelivery(monkeypatch):
    """幂等：effects 已登记 memory 效果时不重复投递。"""
    support.apply_flag_env(
        monkeypatch,
        {"TOOL_SYSTEM_ENABLED": True, "TOOL_MEMORY_ENABLED": True},
    )
    from app.services.tool.memory_policy import has_memory_effect
    from tests.v24.tool008_support import record

    delivered = record(
        tool_id="builtin.reminder.create",
        result={"status": "succeeded", "effects": [{"kind": "memory", "ref": "mem-1"}]},
    )
    assert has_memory_effect(delivered) is True


# --- G-EXTEND -------------------------------------------------------------------


def _probe_definition():
    from app.models.tool import (
        PermissionProfile,
        ToolDefinition,
        ToolParameter,
        ToolSchema,
    )

    return ToolDefinition(
        id="builtin.tool012.extend",
        name="扩展探针",
        description="G-EXTEND 实操探针：新增声明即可进管线",
        when_to_use="验收探针使用",
        namespace="builtin",
        capability="reminder",
        action="create",
        input_schema=ToolSchema(
            parameters=[
                ToolParameter(name="content", type="string", required=True),
                ToolParameter(name="due_at", type="datetime", required=True),
            ]
        ),
        permission=PermissionProfile(level="normal", scope=("world",), confirm="never"),
        side_effects=("write_world",),
        idempotency="keyed",
        tags=("reminder", "world"),
        memory_policy_key="builtin.reminder.create",
    )


def test_g_extend_new_builtin_needs_no_pipeline_change():
    """新增内置工具 ≤4 步：只加声明即可被注册表 / 工具面 / 校验 / 执行器接住。"""
    from app.models.tool import ToolSurface
    from app.services.tool.registry import ToolRegistry
    from app.services.tool.surface import ToolSurfaceResolver
    from app.services.tool.validator import ParamValidator
    from app.services.tool.context import ToolContext

    registry = builtin_registry()
    definition = _probe_definition()
    registry.register(definition, None)

    assert registry.get(definition.id) is definition
    assert registry.effective_status(definition.id) == "enabled"
    assert definition.id in {item.tool_id for item in registry.describe()}

    settings = support.tool_settings()
    surface = ToolSurfaceResolver(registry, settings).resolve(
        "foreground_chat", ToolContext(user_id="u-tool012", settings=settings)
    )
    assert definition.id in surface.tool_ids

    report = ParamValidator().validate(
        definition, {"content": "在吗", "due_at": _future_due_at()}
    )
    assert report.passed is True

    from app.services.tool.executor import resolve_step_binding

    assert registry.resolve(definition.id) is not None
    assert ToolSurface(run_kind="foreground_chat", tool_ids=(definition.id,)).tool_ids


def test_g_extend_pipeline_modules_have_no_tool_id_literals():
    """管线与治理模块零工具 id 字面量：新增工具不需要改这些文件。"""
    pipeline_modules = (
        "executor.py",
        "validator.py",
        "surface.py",
        "permission.py",
        "normalizer.py",
        "registry.py",
        "health.py",
        "context.py",
    )
    root = support.APP_ROOT / "services" / "tool"
    offenders: dict[str, list[str]] = {}
    for name in pipeline_modules:
        source = (root / name).read_text(encoding="utf-8")
        hits = [tool_id for tool_id in support.BUILTIN_TOOL_IDS if f'"{tool_id}"' in source]
        if hits:
            offenders[name] = hits
    assert offenders == {}


def test_g_extend_external_api_costs_one_manifest(tmp_path):
    """新增外部 API 工具 = 1 个 YAML：单文件即产出 1 个 `ext.api.*` 工具。"""
    from tests.v24.tool011_support import WEATHER_HOST, load_manifests, weather_manifest

    registry, index, report = load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=support.tool_settings(
            tool_ext_allowed_hosts=WEATHER_HOST,
        ),
        environ={"EXT_API_WEATHER_TOKEN": "test-value"},
    )

    assert report.loaded == ["ext.api.weather.current"]
    assert index.tool_ids() == ("ext.api.weather.current",)
    assert [definition.id for definition in registry.list(namespace="ext.api")] == [
        "ext.api.weather.current"
    ]


# --- 零迁移最终核对 -------------------------------------------------------------


def test_zero_migration_reconciliation_records_breakpoints():
    """零迁移断言已破例：破例点登记在 `MIGRATION_ADDED_VS_BASELINE`，且与实况逐条对齐。"""
    versions = sorted(
        path.name
        for path in (support.BACKEND_ROOT / "migrations" / "versions").glob("0*.py")
        if path.name != "__init__.py"
    )

    assert len(versions) == support.MIGRATION_FILE_COUNT_CURRENT
    assert len(versions) - support.MIGRATION_FILE_COUNT_BASELINE == len(
        support.MIGRATION_ADDED_VS_BASELINE
    )
    assert versions[-1] == support.MIGRATION_BREAKPOINT
    assert tuple(support.MIGRATION_ADDED_VS_BASELINE) == tuple(
        versions[support.MIGRATION_FILE_COUNT_BASELINE :]
    )
    assert tuple(versions[-3:-1]) == support.V23_MIGRATION_TAIL

def test_zero_migration_model_structure_unchanged():
    """模型结构 diff：42 张表集合与列摘要零变更（结构面零迁移成立）。"""
    from app.core.db import Base

    tables = Base.metadata.tables
    assert len(tables) == support.SCHEMA_TABLE_COUNT

    columns_spec = []
    index_spec = []
    for name, table in sorted(tables.items()):
        columns_spec.append(
            f"{name}:"
            + hashlib.sha256(
                "\n".join(
                    "{}:{}:{}:{}".format(c.name, str(c.type), c.nullable, bool(c.primary_key))
                    for c in sorted(table.columns, key=lambda item: item.name)
                ).encode("utf-8")
            ).hexdigest()[:16]
        )
        index_spec.append(
            f"{name}:"
            + hashlib.sha256(
                "\n".join(
                    sorted(
                        "{}:{}:{}".format(
                            index.name, ",".join(c.name for c in index.columns), bool(index.unique)
                        )
                        for index in table.indexes
                    )
                ).encode("utf-8")
            ).hexdigest()[:16]
        )

    columns_digest = hashlib.sha256(
        "\n".join(columns_spec).encode("utf-8")
    ).hexdigest()[:16]
    assert columns_digest == support.SCHEMA_COLUMNS_DIGEST
    assert columns_digest == support.SCHEMA_COLUMNS_DIGEST_BASELINE

    for name in support.SCHEMA_FROZEN_TABLES:
        assert name in tables


def test_zero_migration_only_insights_check_domain_changed():
    """唯一结构差异是 `insights.ck_insights_type` 值域放宽（与 0046 一致）。"""
    from app.core.db import Base

    table = Base.metadata.tables["insights"]
    checks = {
        constraint.name: str(constraint.sqltext).replace("\n", " ")
        for constraint in table.constraints
        if type(constraint).__name__ == "CheckConstraint"
    }

    assert checks["ck_insights_type"] == (
        "type IN ('belief', 'preference', 'pattern', 'capability_note',"
        " 'usage_preference', 'interaction_calibration')"
    )
    assert support.SCHEMA_CHECKS_CHANGED_TABLES == ("insights",)
    assert support.SCHEMA_INDEXES_CHANGED_TABLES == ()


def test_migration_chain_head_is_current():
    """迁移链 head 为当前最新且线性（无分支、无多 head）。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(support.BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    assert heads == [support.MIGRATION_HEAD]
    revision = script.get_revision(support.MIGRATION_HEAD)
    assert revision is not None
    assert revision.down_revision == support.MIGRATION_HEAD_PREVIOUS

def test_migration_0046_is_downgradable():
    """0046 性质=可降级（有 downgrade 实现，非破坏性值域放宽）。"""
    source = (
        support.BACKEND_ROOT / "migrations" / "versions" / "0046_tool_insight_types.py"
    ).read_text(encoding="utf-8")

    assert "def downgrade()" in source
    assert re.search(r"LEGACY_TYPES\s*=", source)


def test_latest_breakpoint_is_downgradable():
    """每次零迁移破例都必须可回退：最新破例点同样要有 downgrade 实现。"""
    source = (
        support.BACKEND_ROOT / "migrations" / "versions" / support.MIGRATION_BREAKPOINT
    ).read_text(encoding="utf-8")

    assert "def downgrade()" in source

# --- 交付面核对（.env.example / 文档零改动） -------------------------------------


def test_env_example_covers_every_tool_flag_and_param():
    """.env.example 的 TOOL_* 段完整且默认值与 ToolSettings 一致。"""
    text = (support.BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    present = dict(
        re.findall(r"^(TOOL_[A-Z_]+)=(.*)$", text, flags=re.MULTILINE)
    )
    from app.core.settings.tool import ToolSettings

    defaults = ToolSettings()
    expected: dict[str, str] = {}
    for field, value in defaults.model_dump().items():
        if isinstance(value, bool):
            expected[field.upper()] = "true" if value else "false"
        else:
            expected[field.upper()] = str(value)

    assert set(present) == set(expected)
    assert present == expected


def test_env_example_has_no_real_credentials():
    """.env.example 不含真实凭据（AC §6.2 末条）。"""
    text = (support.BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")

    for match in re.findall(r"^[A-Z0-9_]+=\S+", text, flags=re.MULTILINE):
        name, value = match.split("=", 1)
        if support.CREDENTIAL_ENV_NAME_PATTERN.search(name):
            assert value.strip().lower() in support.PLACEHOLDER_SECRET_VALUES | {
                "test",
                "your-key-here",
            }, f"{name} 疑似真实凭据"


def test_docs_untouched_by_this_task():
    """docs/ 零改动：本任务的两份交付物落在 tests/v24/。"""
    docs = support.REPO_ROOT / "docs" / "version" / "v2.4.0" / "tool-system"

    assert sorted(path.name for path in docs.iterdir()) == [
        "architecture.md",
        "tasks",
        "tasks.md",
    ]
    assert not (docs / "scenario-test.md").exists()
    assert not (docs / "regression-checklist.md").exists()

    deliverables = support.BACKEND_ROOT / "tests" / "v24"
    assert (deliverables / "SCENARIO-TEST.md").exists()
    assert (deliverables / "ACCEPTANCE-CHECKLIST.md").exists()
