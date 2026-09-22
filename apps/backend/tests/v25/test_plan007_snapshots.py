"""PLAN-007 Step 7：四项「零改动」的序列快照对照 + 零迁移断言。

覆盖 Task Detail §9.2 I1 / I2 / I3 / I6 / I11 / I12 与 §10.3「增量接线可举证」。

| 快照 | 对象 | 本任务的改动 |
|---|---|---|
| ① | `autonomy_engine._process_user` 语句序列（`tick` 的二十步载体） | **零改动**（形状逐条相等） |
| ② | `autonomy_policy.evaluate` 调制链与八步理由顺序 | 只追加**一环** `_apply_plan_adjustments` |
| ③ | `autonomy_engine._produce_autonomy_action` 形态 | **零改动** |
| ④ | `decision_pipeline` 函数清单 / 六维权重 / 候选优先级表 | **零改动** |

形状快照的取法：对函数体顶层语句取「语句头」（赋值目标 / `if` / `try` / 调用名），
顺序与数量都进快照——任何重排、插入或删除都会使本模块失败（不是断言空安全网）。
"""

import ast
from pathlib import Path
import re

from app.core.settings import get_settings
from app.core.settings.plan import PlanSettings
from app.models.observability import DecisionKind
from app.application import autonomy_engine
from app.repositories import goal_repository
from app.services import autonomy_policy, decision_pipeline

from . import _plan_scan as scan
from . import plan007_support as support
from .test_plan001_scope_markers import (
    PLAN_002_SETTINGS_FLAGS,
    PLAN_002_SETTINGS_PARAMS,
)

ENGINE_PATH = Path(autonomy_engine.__file__)
POLICY_PATH = Path(autonomy_policy.__file__)
PIPELINE_PATH = Path(decision_pipeline.__file__)

TICK_STATEMENT_SHAPE = (
    "assign:conversation",
    "if",
    "assign:messages",
    "assign:tail",
    "assign:(_, attempts)",
    "assign:due_action",
    "if",
    "if",
    "assign:started",
    "assign:trace",
    "assign:snapshot",
    "assign:verdict",
    "call:record",
    "call:info",
    "if",
    "assign:produced_action",
    "if",
    "assign:capabilities",
    "assign:(intention_override, pipeline_audit)",
    "assign:action",
    "assign:enqueued",
    "call:_record_decision",
    "if",
    "assign:active",
    "if",
    "assign:observability_token",
    "try",
    "if",
    "call:on_turn_finished",
    "return",
)
"""`_process_user` 的语句形状（本任务唯一改动的收集点在其被调用的 `_snapshot_for` 内）。"""

SNAPSHOT_FOR_STATEMENT_SHAPE = (
    "assign:(character, relationship)",
    "assign:scene_state",
    "assign:goals",
    "assign:late_night_start",
    "assign:late_night_end",
    "assign:late_night",
    "assign:selected",
    "assign:(last_proactive_at, attempts)",
    "try",
    "AnnAssign",
    "try",
    "assign:action_facts",
    "assign:plan_facts",
    "return",
)
"""`_snapshot_for`：`plan_facts` 装配行**恰位于既有行动事实收集之后**（同源、同一处）。"""

PRODUCE_ACTION_STATEMENT_SHAPE = (
    "Expr",
    "assign:settings",
    "if",
    "assign:action_type",
    "if",
    "if",
    "assign:intent",
    "assign:record",
    "return",
)
"""`_produce_autonomy_action`：形态零改动（不新建自治执行器）。"""

POLICY_FUNCTION_INVENTORY = (
    "_activity_busy",
    "_apply_action_adjustments",
    "_apply_plan_adjustments",
    "_apply_relationship_rules",
    "_apply_tool_adjustments",
    "_apply_tool_insight_adjustments",
    "_apply_world_adjustments",
    "_cooldown_passed",
    "_intention_action_type",
    "_parse_hhmm",
    "_reconciliation_already_used",
    "_verdict",
    "effective_interval_minutes",
    "evaluate",
    "in_quiet_hours",
    "trigger_priority",
)
"""策略层函数清单：相对 V2.4.0 **恰多两个**（调制函数 + 意图 → 动作身份查询）。"""

ENGINE_FUNCTION_INVENTORY = (
    "_advance_moment",
    "_autonomy_action_today",
    "_autonomy_binding",
    "_autonomy_tool_context",
    "_blocked_steps",
    "_build_action",
    "_collect_action_facts",
    "_collect_plan_facts",
    "_decision_record",
    "_is_advance_for",
    "_last_advanced_at",
    "_latest_active_plan",
    "_params_for_autonomy_action",
    "_pipeline_intention",
    "_plan_schedule_context",
    "_process_user",
    "_produce_autonomy_action",
    "_recent_tool_failures",
    "_record_decision",
    "_record_tool_surface_degrade",
    "_resolve_tick_capabilities",
    "_session_tail",
    "_snapshot_for",
    "collect_tool_facts",
    "collect_tool_insights",
    "reset_episode",
    "reset_tool_surface_degrade_count",
    "resolve_autonomy_surface",
    "tick",
    "tool_surface_degrade_count",
)

PIPELINE_FUNCTION_INVENTORY = (
    "_apply_tool_insight",
    "_cost",
    "_gate_budget_type",
    "_gate_capability",
    "_goal_type_of",
    "_intention_for",
    "_interest",
    "_persona_gate",
    "_relationship_fit",
    "_relationship_gate",
    "_state_fit",
    "_timing",
    "assign_priorities",
    "collect_candidates",
    "legacy_capability_of",
    "resolve_goal_type_from_tool_id",
    "run_pipeline",
    "run_risk_gates",
    "score_candidates",
    "select",
    "to_audit",
)
"""决策管线函数清单（**零改动**：本任务不新增、不删除、不重命名任何函数）。"""

GATE_REASON_LITERALS = (
    "用户正在对话",
    "静音时段",
    "冷却中",
    "本集期已达上限",
    "上一条主动还未处理",
    "关系尚浅，不主动打扰",
    "角色状态不宜",
    "无主动动机",
)
"""八步裁决的短路理由（源序即裁决序，逐条冻结）。"""

TRIGGER_PRIORITY_SNAPSHOT = {
    "scheduled_followup": "P0",
    "action_due": "P1",
    "conversation_inactivity": "P3",
}

MIGRATION_HEAD = "0052"


def _statement_heads(path: Path, function: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            return tuple(_head(statement) for statement in node.body)
    raise AssertionError(f"未找到函数 {function}")


def _head(statement) -> str:
    if isinstance(statement, ast.Assign):
        target = statement.targets[0]
        name = target.id if isinstance(target, ast.Name) else ast.unparse(target)
        return f"assign:{name}"
    if isinstance(statement, (ast.If, ast.Try, ast.Return, ast.For)):
        return type(statement).__name__.lower()
    if isinstance(statement, (ast.AsyncWith, ast.With)):
        return "with"
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Await):
        return f"await:{_call_name(statement.value.value)}"
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        return f"call:{_call_name(statement.value)}"
    return type(statement).__name__


def _call_name(node) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "?")
    return "?"


def _function_source(path: Path, function: str) -> str:
    """函数体源码切片（静态「零写面」断言的作用域）。"""
    source = path.read_text(encoding="utf-8")
    return source.split(f"def {function}", 1)[1].split("\ndef ", 1)[0]


def _function_inventory(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(
        sorted(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    )


class TestTickSequenceIsUnchanged:
    """I1 / §4.4：`tick` 序列二十步零改动（形状快照对照零差异）。"""

    def test_the_tick_body_is_unchanged(self):
        assert (
            _statement_heads(ENGINE_PATH, "_process_user")
            == TICK_STATEMENT_SHAPE
        )

    def test_the_packet_is_assembled_in_the_existing_collection_site(self):
        assert (
            _statement_heads(ENGINE_PATH, "_snapshot_for")
            == SNAPSHOT_FOR_STATEMENT_SHAPE
        )
        shape = SNAPSHOT_FOR_STATEMENT_SHAPE
        assert shape.index("assign:plan_facts") == shape.index("assign:action_facts") + 1

    def test_the_tick_signature_is_unchanged(self):
        import inspect

        assert str(inspect.signature(autonomy_engine.tick)) == (
            "(user_ids: list[str] | None = None, llm=None,"
            " now: datetime.datetime | None = None) -> list[str]"
        )
        assert inspect.iscoroutinefunction(autonomy_engine.tick)

    def test_the_tick_delegates_every_user_to_process_user(self):
        text = scan.code_text(ENGINE_PATH)
        assert "_process_user" in text
        assert text.count("_process_user") == 2, "唯一调用点 + 定义处"


class TestPolicySequenceIsExtendedByExactlyOneRing:
    """I2 / D10：八步顺序不变，调制链只追加一环。"""

    def test_the_modulation_chain_gained_exactly_one_ring(self):
        heads = _statement_heads(POLICY_PATH, "evaluate")
        assert heads[:16] == (
            "assign:config",
            "assign:now",
            "FunctionDef",
            "if",
            "if",
            "assign:priority",
            "assign:cooldown_passed",
            "if",
            "if",
            "if",
            "if",
            "if",
            "if",
            "assign:reason",
            "if",
            "assign:verdict",
        )
        assert heads.count("assign:verdict") == 6, "1 次初始裁决 + 5 个调制环"
        assert heads[-1] == "return"

    def test_the_eight_gate_reasons_keep_their_source_order(self):
        source = POLICY_PATH.read_text(encoding="utf-8")
        observed = sorted(
            GATE_REASON_LITERALS, key=lambda reason: source.index(f'"{reason}"')
        )
        assert tuple(observed) == GATE_REASON_LITERALS

    def test_trigger_priority_math_is_unchanged(self):
        assert autonomy_policy.TRIGGER_PRIORITY == TRIGGER_PRIORITY_SNAPSHOT
        assert autonomy_policy.HIGH_PRIORITY_OVERRIDE == frozenset({"P0", "P1"})
        assert autonomy_policy.SLEEPY_MOODS == frozenset({"tired"})
        assert autonomy_policy.STAGE_RANK == {
            "stranger": 0,
            "friend": 1,
            "close_friend": 2,
            "partner": 3,
        }
        assert autonomy_policy._PROACTIVE_GOAL_TYPES == frozenset(
            {"user_care", "relationship"}
        )

    def test_the_function_inventory_gained_exactly_two_names(self):
        assert _function_inventory(POLICY_PATH) == POLICY_FUNCTION_INVENTORY
        baseline = set(POLICY_FUNCTION_INVENTORY) - {
            "_apply_plan_adjustments",
            "_intention_action_type",
        }
        assert len(POLICY_FUNCTION_INVENTORY) == len(baseline) + 2
        assert "plan_facts" in scan.code_text(POLICY_PATH)
        assert "PolicySnapshot" in scan.code_text(POLICY_PATH)


class TestProduceActionShapeIsUnchanged:
    """I6：`_produce_autonomy_action` 形态未变（不新建自治执行器）。"""

    def test_the_body_shape_is_unchanged(self):
        assert (
            _statement_heads(ENGINE_PATH, "_produce_autonomy_action")
            == PRODUCE_ACTION_STATEMENT_SHAPE
        )

    def test_it_still_delegates_to_the_single_orchestrator(self):
        tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_produce_autonomy_action"
            ):
                awaited = sorted(
                    _call_name(inner.value)
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Await)
                )
                assert awaited == ["run_action_planning"]
                return
        raise AssertionError("未找到 _produce_autonomy_action")

    def test_it_still_uses_the_existing_dedupe_template(self):
        source = ENGINE_PATH.read_text(encoding="utf-8")
        assert 'dedupe_key=f"autonomy:{action_type}:{now.date().isoformat()}"' in source

    def test_the_engine_inventory_gained_exactly_the_assembly_helpers(self):
        assert _function_inventory(ENGINE_PATH) == ENGINE_FUNCTION_INVENTORY
        added = {
            "_collect_plan_facts",
            "_latest_active_plan",
            "_plan_schedule_context",
            "_blocked_steps",
            "_last_advanced_at",
            "_is_advance_for",
            "_advance_moment",
        }
        assert len(ENGINE_FUNCTION_INVENTORY) == 30
        assert added <= set(ENGINE_FUNCTION_INVENTORY)


class TestPipelineSnapshotsAreUnchanged:
    """I3：`decision_pipeline` 六维权重、候选优先级表与函数清单零差异。"""

    def test_the_function_inventory_is_unchanged(self):
        assert _function_inventory(PIPELINE_PATH) == PIPELINE_FUNCTION_INVENTORY

    def test_dimension_weights_are_unchanged(self):
        assert decision_pipeline._DIMENSION_WEIGHTS == {
            "goal_alignment": 0.35,
            "state_fit": 0.15,
            "relationship_fit": 0.15,
            "timing": 0.15,
            "interest": 0.10,
            "cost": 0.10,
        }

    def test_the_source_priority_table_is_unchanged(self):
        assert decision_pipeline._SOURCE_PRIORITY == {
            "user_directive": 0,
            "commitment_delivery": 1,
            "autonomy_trigger": 2,
            "goal_compile": 2,
            "turn_intention": 2,
            "capability": 3,
            "world_affordance": 3,
            "chat_response": 0,
            "silence": 4,
        }

    def test_the_gate_names_are_unchanged(self):
        assert decision_pipeline._GATE_PERSONA == "persona_precheck"
        assert decision_pipeline._GATE_RELATIONSHIP == "relationship_gate"
        assert decision_pipeline._GATE_ACTION == "action_check"
        assert decision_pipeline._GATE_BUDGET == "budget_cooldown"


class TestSingleAssemblyPoint:
    """U12 / D5：`plan_facts` 装配点唯一（调用点计数 = 1）。"""

    def test_the_collector_is_called_from_exactly_one_place(self):
        text = scan.code_text(ENGINE_PATH)
        assert text.count("_collect_plan_facts(") == 2, "定义处 + 唯一调用点"

    def test_no_other_module_assembles_the_packet(self):
        modules = (
            "app/services/autonomy_policy.py",
            "app/services/decision_pipeline.py",
            "app/application/life_loop.py",
        )
        for relative in modules:
            path = scan.REPO_ROOT / relative
            assert "_collect_plan_facts" not in scan.code_text(path), relative

    def test_the_packet_field_is_written_only_by_the_snapshot_builder(self):
        source = ENGINE_PATH.read_text(encoding="utf-8")
        assert source.count("plan_facts=plan_facts") == 1
        assert len(re.findall(r"plan_facts=", source)) == 1


class TestZeroMigration:
    """I12 / §7：迁移链头 `0046`、`decision_records.kind` 五值、零新表新列。"""

    def test_migration_chain_head_is_still_0052(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD

    def test_decision_kind_value_set_is_unchanged(self):
        assert tuple(kind.value for kind in DecisionKind) == (
            "proactive_autonomy",
            "turn_goal",
            "turn_intention",
            "turn_behavior",
            "goal_lifecycle",
        )

    def test_no_planning_side_table_is_added(self):
        from app.core.db import Base

        plan_tables = tuple(
            sorted(name for name in Base.metadata.tables if "plan" in name)
        )
        assert plan_tables == ("daily_plans", "goal_plans"), "计划域表集未扩"

    def test_no_new_v25_setting_is_introduced(self):
        declared = set(PlanSettings.model_fields)
        assert declared == set(PLAN_002_SETTINGS_FLAGS) | set(PLAN_002_SETTINGS_PARAMS)
        assert len(PLAN_002_SETTINGS_FLAGS) == 2
        assert len(PLAN_002_SETTINGS_PARAMS) == 14
        assert "plan_autonomy_enabled" not in declared


class TestPacketSemantics:
    """I11 语义反转（v25 去门控）：`plan_facts` 采集恒发生；无 active 计划仍为空包，
    对空包的调制是 no-op、审计行不加字段——与「无计划可抑制」的原状一致。"""

    def test_the_packet_stays_empty_without_an_active_plan(self):
        snapshot = support.act_snapshot()
        assert snapshot.plan_facts == {}
        baseline = autonomy_policy.evaluate(
            support.signal(), snapshot, get_settings(), support.NOW
        )
        assert baseline.decision == "act"

    def test_the_modulation_is_a_no_op_for_the_default_snapshot(self):
        snapshot = support.act_snapshot()
        baseline = autonomy_policy.evaluate(
            support.signal(), snapshot, get_settings(), support.NOW
        )
        assert (
            autonomy_policy._apply_plan_adjustments(baseline, snapshot) is baseline
        )

    def test_the_audit_row_gains_no_field_when_the_packet_is_empty(self):
        record = autonomy_engine._decision_record(
            verdict=autonomy_policy.AutonomyVerdict(
                decision="act", reason="触发", trigger=support.signal()
            ),
            signal=support.signal(),
            snapshot=support.act_snapshot(),
            user_id=support.USER,
            session_id=support.SESSION_ID,
        )
        assert "plan_facts" not in record.input_snapshot

    def test_no_write_face_is_added(self):
        """本任务的写入量为零新增：不写任何表，只进内存快照与既有 JSON 列。"""
        collector = _function_source(ENGINE_PATH, "_collect_plan_facts")
        for write_call in (
            "save_record",
            "create_plan",
            "update_plan_progress",
            "set_plan_status",
            "finish_goal",
        ):
            assert write_call not in collector, write_call
